import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SourceConfig(Base):
    __tablename__ = "source_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    podcast_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("podcasts.id"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    config_json: Mapped[dict] = mapped_column(JSONB, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_polled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    podcast = relationship("Podcast", back_populates="source_configs")
