import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Episode(Base):
    __tablename__ = "episodes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    podcast_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("podcasts.id"), nullable=False, index=True)
    guid: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    audio_url: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="new", index=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    model_used: Mapped[str] = mapped_column(Text, nullable=True)
    processing_seconds: Mapped[int] = mapped_column(Integer, nullable=True)
    cost: Mapped[float] = mapped_column(Float, nullable=True)
    abs_item_id: Mapped[str] = mapped_column(Text, nullable=True)
    abs_episode_id: Mapped[str] = mapped_column(Text, nullable=True)
    chapter_index: Mapped[int] = mapped_column(Integer, nullable=True)
    media_type: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    podcast = relationship("Podcast", back_populates="episodes")
    transcript = relationship("Transcript", back_populates="episode", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("podcast_id", "guid", name="uq_episode_guid"),
    )
