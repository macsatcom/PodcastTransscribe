import io
from datetime import datetime
from typing import BinaryIO

import feedparser
import httpx

from app.adapters.base import BaseSourceAdapter, EpisodeMetadata


class RSSSourceAdapter(BaseSourceAdapter):
    async def discover_new(self, url: str) -> list[EpisodeMetadata]:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=30)
            response.raise_for_status()

        feed = feedparser.parse(response.text)
        episodes = []
        for entry in feed.entries:
            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published = datetime(*entry.published_parsed[:6])

            audio_url = None
            if hasattr(entry, "enclosures") and entry.enclosures:
                for enc in entry.enclosures:
                    if enc.get("type", "").startswith("audio/"):
                        audio_url = enc.get("href")
                        break
            if not audio_url and hasattr(entry, "links"):
                for link in entry.links:
                    if link.get("type", "").startswith("audio/"):
                        audio_url = link.get("href")
                        break

            duration = None
            if hasattr(entry, "itunes_duration"):
                duration = self._parse_duration(entry.itunes_duration)

            cover_url = None
            feed_cover = feed.feed.get("image", {})
            if feed_cover:
                cover_url = feed_cover.get("href") or feed_cover.get("url")
            if not cover_url and hasattr(entry, "itunes_image"):
                cover_url = entry.itunes_image.get("href")

            episodes.append(EpisodeMetadata(
                guid=entry.get("id", entry.get("link", "")),
                title=entry.get("title", ""),
                description=entry.get("description", entry.get("summary", "")),
                audio_url=audio_url or "",
                duration_seconds=duration,
                published_at=published,
                cover_url=cover_url,
            ))
        return episodes

    async def fetch_audio(self, audio_url: str) -> BinaryIO:
        if not audio_url:
            raise ValueError("audio_url is empty")

        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; PodcastTransscribe/1.0; +https://github.com/ksn/PodcastTransscribe)",
        }

        for attempt in range(3):
            try:
                async with httpx.AsyncClient(
                    timeout=600, follow_redirects=True, headers=headers
                ) as client:
                    async with client.stream("GET", audio_url) as response:
                        response.raise_for_status()
                        chunks = []
                        async for chunk in response.aiter_bytes():
                            chunks.append(chunk)
                        return io.BytesIO(b"".join(chunks))
            except (httpx.RemoteProtocolError, httpx.ReadTimeout, httpx.ConnectError) as e:
                if attempt == 2:
                    raise
                import asyncio
                await asyncio.sleep(1)

    def _parse_duration(self, duration: str) -> int | None:
        try:
            parts = str(duration).split(":")
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 1:
                return int(parts[0])
        except (ValueError, TypeError):
            return None
        return None
