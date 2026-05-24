import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Podcast(Base):
    __tablename__ = "podcasts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    cover_url: Mapped[str] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(Text, nullable=True)
    auto_process: Mapped[bool] = mapped_column(Boolean, default=True)
    abs_item_id: Mapped[str] = mapped_column(Text, nullable=True)
    media_type: Mapped[str] = mapped_column(Text, nullable=True)
    narrator: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    episodes = relationship("Episode", back_populates="podcast", cascade="all, delete-orphan")
    source_configs = relationship("SourceConfig", back_populates="podcast", cascade="all, delete-orphan")
