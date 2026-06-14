import asyncio
import io
import logging
from datetime import UTC, datetime
from typing import BinaryIO
from urllib.parse import urlparse

import httpx

from app.adapters.base import BaseSourceAdapter, EpisodeMetadata
from app.config import settings

logger = logging.getLogger(__name__)


class ABSSourceAdapter(BaseSourceAdapter):
    def __init__(self, abs_url: str = "", api_key: str = ""):
        self.base_url = (abs_url or settings.abs_url).rstrip("/")
        self.api_key = api_key or settings.abs_api_key
        self._client: httpx.AsyncClient | None = None

    def _resolve_url(self, path: str) -> str:
        parsed = urlparse(path)
        if parsed.hostname:
            path = parsed.path
            if parsed.query:
                path += "?" + parsed.query
        return f"{self.base_url}{path}"

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; TranscribeAndSearch/1.0)",
                "Authorization": f"Bearer {self.api_key}",
            }
            self._client = httpx.AsyncClient(base_url=self.base_url, headers=headers, timeout=30)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "ABSSourceAdapter":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def get_libraries(self) -> list[dict]:
        client = self._get_client()
        response = await client.get("/api/libraries")
        response.raise_for_status()
        data = response.json()
        return data.get("libraries", [])

    async def get_library_items(self, library_id: str, media_type: str | None = None) -> list[dict]:
        client = self._get_client()
        params: dict[str, str] = {"minified": "1"}
        if media_type:
            params["filter"] = media_type
        response = await client.get(f"/api/libraries/{library_id}/items", params=params)
        response.raise_for_status()
        data = response.json()
        return data.get("results", [])

    async def get_item(self, item_id: str, expanded: bool = False) -> dict:
        client = self._get_client()
        params = {}
        if expanded:
            params["expanded"] = "1"
        response = await client.get(f"/api/items/{item_id}", params=params)
        response.raise_for_status()
        return response.json()

    async def get_play_info(self, item_id: str, episode_id: str | None = None) -> dict:
        client = self._get_client()
        if episode_id:
            url = f"/api/items/{item_id}/play/{episode_id}"
        else:
            url = f"/api/items/{item_id}/play"
        body = {
            "deviceInfo": {"clientVersion": "0.0.1"},
            "supportedMimeTypes": [
                "audio/mpeg",
                "audio/mp4",
                "audio/flac",
                "audio/ogg",
            ],
        }
        response = await client.post(url, json=body)
        response.raise_for_status()
        return response.json()

    async def check_new_episodes(self, podcast_item_id: str) -> None:
        client = self._get_client()
        response = await client.get(f"/api/podcasts/{podcast_item_id}/checknew", params={"limit": "0"})
        response.raise_for_status()

    async def discover_new(self, abs_item_id: str) -> list[EpisodeMetadata]:
        item = await self.get_item(abs_item_id)
        media_type = item.get("mediaType", "")

        if media_type == "podcast":
            return await self._discover_podcast_episodes(abs_item_id, item)
        else:
            return await self._discover_book_chapters(abs_item_id, item)

    async def _discover_podcast_episodes(self, abs_item_id: str, item: dict) -> list[EpisodeMetadata]:
        await self.check_new_episodes(abs_item_id)
        item = await self.get_item(abs_item_id, expanded=True)

        media = item.get("media", {})
        episodes = media.get("episodes", [])
        if not episodes:
            return []

        cover_url = f"{self.base_url}/api/items/{abs_item_id}/cover"

        result: list[EpisodeMetadata] = []
        for ep in episodes:
            play_info = None
            for attempt in range(2):
                try:
                    play_info = await self.get_play_info(abs_item_id, ep.get("id"))
                    break
                except httpx.HTTPError:
                    if attempt == 0:
                        await asyncio.sleep(3)
            if play_info is None:
                logger.warning("Skipping episode %s — could not get play info after retries", ep.get("id"))
                continue

            audio_tracks = play_info.get("audioTracks", [])
            if not audio_tracks:
                logger.warning("Skipping episode %s — no audio tracks", ep.get("id"))
                continue

            audio_url = self._resolve_url(audio_tracks[0].get("contentUrl", ""))
            if not audio_url:
                logger.warning("Skipping episode %s — no audio URL", ep.get("id"))
                continue

            published = None
            published_at = ep.get("publishedAt")
            if published_at:
                published = datetime.fromtimestamp(published_at / 1000, tz=UTC)

            result.append(
                EpisodeMetadata(
                    guid=str(ep.get("id", "")),
                    title=ep.get("title", ""),
                    description=ep.get("description"),
                    audio_url=audio_url,
                    duration_seconds=ep.get("duration"),
                    published_at=published,
                    cover_url=cover_url,
                    abs_item_id=abs_item_id,
                    abs_episode_id=ep.get("id"),
                    media_type="podcast",
                )
            )

        return result

    async def _discover_book_chapters(self, abs_item_id: str, item: dict) -> list[EpisodeMetadata]:
        play_info = await self.get_play_info(abs_item_id)
        audio_tracks = play_info.get("audioTracks", [])
        if not audio_tracks:
            raise ValueError("No audio tracks available for this item")

        audio_url = self._resolve_url(audio_tracks[0].get("contentUrl", ""))
        if not audio_url:
            raise ValueError("No content URL in audio track")

        media = item.get("media", {})
        metadata = media.get("metadata", {})
        book_title = metadata.get("title", "Unknown")
        chapters = media.get("chapters", [])

        published = None
        added_at = item.get("addedAt")
        if added_at:
            published = datetime.fromtimestamp(added_at / 1000, tz=UTC)

        cover_url = f"{self.base_url}/api/items/{abs_item_id}/cover"

        if not chapters:
            return [
                EpisodeMetadata(
                    guid=abs_item_id,
                    title=book_title,
                    description=metadata.get("description"),
                    audio_url=audio_url,
                    duration_seconds=play_info.get("duration"),
                    published_at=published,
                    cover_url=cover_url,
                    abs_item_id=abs_item_id,
                    media_type="book",
                )
            ]

        result: list[EpisodeMetadata] = []
        for i, chapter in enumerate(chapters):
            chapter_title = chapter.get("title") or f"Chapter {i + 1}"
            duration = None
            start = chapter.get("startOffset")
            end = chapter.get("endOffset")
            if start is not None and end is not None:
                duration = int(end - start)

            result.append(
                EpisodeMetadata(
                    guid=f"{abs_item_id}_{i}",
                    title=f"{book_title} - {chapter_title}",
                    description=metadata.get("description"),
                    audio_url=audio_url,
                    duration_seconds=duration,
                    published_at=published,
                    cover_url=cover_url,
                    abs_item_id=abs_item_id,
                    chapter_index=i,
                    media_type="book",
                )
            )

        return result

    async def fetch_audio(self, audio_url: str) -> BinaryIO:
        if not audio_url:
            raise ValueError("audio_url is empty")

        parsed = urlparse(audio_url)
        path = parsed.path
        if parsed.query:
            path += "?" + parsed.query
        download_url = self.base_url + path

        logger.info("fetch_audio download_url=%s base_url=%s", download_url, self.base_url)

        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; TranscribeAndSearch/1.0)",
            "Authorization": f"Bearer {self.api_key}",
        }

        for attempt in range(2):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(connect=30, read=600, write=30, pool=30),
                    follow_redirects=True,
                    headers=headers,
                ) as client:
                    async with client.stream("GET", download_url) as response:
                        response.raise_for_status()
                        chunks = []
                        async for chunk in response.aiter_bytes():
                            chunks.append(chunk)
                        return io.BytesIO(b"".join(chunks))
            except (
                httpx.RemoteProtocolError,
                httpx.ReadTimeout,
                httpx.ConnectError,
            ) as e:
                logger.warning("fetch_audio attempt %d failed: %s", attempt + 1, e)
                if attempt == 1:
                    raise
                await asyncio.sleep(2)

    async def get_stream_url(self, item_id: str, episode_id: str | None = None) -> str:
        play_info = await self.get_play_info(item_id, episode_id)
        audio_tracks = play_info.get("audioTracks", [])
        if not audio_tracks:
            raise ValueError("No audio tracks available")
        return audio_tracks[0].get("contentUrl", "")
