"""
models/db_models.py
-------------------
SQLAlchemy ORM models for the database schema.
"""

from datetime import datetime, timezone
from sqlalchemy import (
    String, Integer, Boolean, DateTime, Text, Float,
    ForeignKey, JSON, func
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Instagram identity — populated after OAuth
    instagram_user_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    instagram_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    instagram_avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Token storage — always encrypted at rest
    instagram_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    instagram_token_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    instagram_connected: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    analyses: Mapped[list["Analysis"]] = relationship(
        "Analysis", back_populates="user", cascade="all, delete-orphan"
    )


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Post identity
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    instagram_post_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    instagram_post_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Source: "paste" or "api"
    source: Mapped[str] = mapped_column(String(16), default="paste")

    # Aggregate results
    total_comments: Mapped[int] = mapped_column(Integer, default=0)
    positive_pct: Mapped[float] = mapped_column(Float, default=0.0)
    neutral_pct: Mapped[float] = mapped_column(Float, default=0.0)
    negative_pct: Mapped[float] = mapped_column(Float, default=0.0)
    avg_confidence: Mapped[float] = mapped_column(Float, default=0.0)

    # Full results stored as JSON for the history/replay feature
    full_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="analyses")
