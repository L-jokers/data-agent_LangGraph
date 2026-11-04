from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ApplicationSessionMySQL(Base):
    __tablename__ = "application_session"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    original_query: Mapped[str] = mapped_column(Text, nullable=False)
    current_query: Mapped[str] = mapped_column(Text, nullable=False)
    clarification_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    turn_id: Mapped[str] = mapped_column(String(64), nullable=False)
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    semantic_model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    pending_fields: Mapped[str | None] = mapped_column(Text, nullable=True)
    query_intent_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    terminal_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    execution_marker: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
