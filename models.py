from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class DailyBlock(Base):
    __tablename__ = "daily_blocks"
    __table_args__ = (
        UniqueConstraint("target_date", "session", name="uq_block_date_session"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    target_date: Mapped[date] = mapped_column(Date, index=True)
    # Human/generated labels are Text so future prompt wording cannot break inserts.
    session: Mapped[str] = mapped_column(Text, index=True)
    level: Mapped[str] = mapped_column(Text)
    topic: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="planned", index=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    block_id: Mapped[int] = mapped_column(Integer, index=True)
    position: Mapped[int] = mapped_column(Integer)
    # Hashes and internal enums remain bounded; generated pedagogical metadata is Text.
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    topic: Mapped[str] = mapped_column(Text, index=True)
    skill: Mapped[str] = mapped_column(Text)
    question_type: Mapped[str] = mapped_column(String(40))
    prompt: Mapped[str] = mapped_column(Text)
    options: Mapped[list[str]] = mapped_column(JSON)
    correct_option_ids: Mapped[list[int]] = mapped_column(JSON)
    explanation: Mapped[str] = mapped_column(Text)
    comparison_axis: Mapped[str] = mapped_column(Text, default="")
    surface_constraints: Mapped[dict] = mapped_column(JSON, default=dict)
    reviewer_score: Mapped[float] = mapped_column(Float, default=100.0)
    reviewer_notes: Mapped[str] = mapped_column(Text, default="")
    telegram_message_id: Mapped[int | None] = mapped_column(Integer)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BotState(Base):
    __tablename__ = "bot_state"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
