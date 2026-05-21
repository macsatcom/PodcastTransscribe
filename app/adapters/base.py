from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import BinaryIO


@dataclass
class EpisodeMetadata:
    guid: str
    title: str
    description: str | None
    audio_url: str
    duration_seconds: int | None
    published_at: datetime | None
    cover_url: str | None


class BaseSourceAdapter(ABC):
    @abstractmethod
    async def discover_new(self, url: str) -> list[EpisodeMetadata]:
        ...

    @abstractmethod
    async def fetch_audio(self, audio_url: str) -> BinaryIO:
        ...
