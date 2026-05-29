import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Float, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TopicCluster(Base):
    __tablename__ = "topic_clusters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(3072), nullable=True)
    representative_chunks: Mapped[list[dict]] = mapped_column(JSONB, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="auto")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    episode_assignments = relationship("EpisodeTopic", back_populates="topic", cascade="all, delete-orphan")


class EpisodeTopic(Base):
    __tablename__ = "episode_topics"

    topic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("topic_clusters.id"), primary_key=True)
    episode_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("episodes.id"), primary_key=True)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    topic = relationship("TopicCluster", back_populates="episode_assignments")

    __table_args__ = (UniqueConstraint("topic_id", "episode_id"),)
