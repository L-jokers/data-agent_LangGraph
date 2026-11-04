import json
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application_session_mysql import ApplicationSessionMySQL


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    status: str
    original_query: str
    current_query: str
    clarification_id: str | None
    turn_id: str
    turn_number: int
    state_version: int
    semantic_model_version: str
    pending_fields: tuple[str, ...]
    terminal_status: str | None
    execution_marker: str | None
    expires_at: datetime


class ApplicationSessionRepository:
    TTL = timedelta(minutes=5)

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _record(model: ApplicationSessionMySQL) -> SessionRecord:
        return SessionRecord(
            session_id=model.session_id,
            status=model.status,
            original_query=model.original_query,
            current_query=model.current_query,
            clarification_id=model.clarification_id,
            turn_id=model.turn_id,
            turn_number=model.turn_number,
            state_version=model.state_version,
            semantic_model_version=model.semantic_model_version,
            pending_fields=tuple(json.loads(model.pending_fields or "[]")),
            terminal_status=model.terminal_status,
            execution_marker=model.execution_marker,
            expires_at=model.expires_at,
        )

    async def create(self, query: str, version_id: str) -> SessionRecord:
        now = self._now()
        model = ApplicationSessionMySQL(
            session_id=str(uuid4()), status="processing", original_query=query,
            current_query=query, turn_id=str(uuid4()), turn_number=1,
            state_version=0, semantic_model_version=version_id,
            expires_at=now + self.TTL, created_at=now, updated_at=now,
        )
        self.session.add(model)
        await self.session.flush()
        await self.session.commit()
        return self._record(model)

    async def get(self, session_id: str) -> SessionRecord | None:
        model = await self.session.get(ApplicationSessionMySQL, session_id)
        return self._record(model) if model else None

    async def claim_clarification(
        self, record: SessionRecord, clarification_id: str, answer: str
    ) -> SessionRecord | None:
        now = self._now()
        result = await self.session.execute(
            update(ApplicationSessionMySQL)
            .where(
                ApplicationSessionMySQL.session_id == record.session_id,
                ApplicationSessionMySQL.clarification_id == clarification_id,
                ApplicationSessionMySQL.state_version == record.state_version,
                ApplicationSessionMySQL.status == "needs_clarification",
                ApplicationSessionMySQL.expires_at > now,
            )
            .values(
                status="processing", current_query=answer, turn_id=str(uuid4()),
                turn_number=record.turn_number + 1,
                state_version=record.state_version + 1, updated_at=now,
            )
        )
        if result.rowcount != 1:
            return None
        await self.session.flush()
        await self.session.commit()
        return await self.get(record.session_id)

    async def update_outcome(
        self, session_id: str, expected_version: int, *, status: str,
        clarification_id: str | None = None, pending_fields: list[str] | None = None,
        terminal_status: str | None = None, execution_marker: str | None = None,
    ) -> SessionRecord | None:
        now = self._now()
        values: dict[str, Any] = {
            "status": status, "clarification_id": clarification_id,
            "pending_fields": json.dumps(pending_fields or [], ensure_ascii=False),
            "terminal_status": terminal_status, "execution_marker": execution_marker,
            "updated_at": now, "state_version": expected_version + 1,
        }
        if status in {"completed", "error", "unsupported", "expired", "execution_unknown"}:
            values["completed_at"] = now
        result = await self.session.execute(
            update(ApplicationSessionMySQL).where(
                ApplicationSessionMySQL.session_id == session_id,
                ApplicationSessionMySQL.state_version == expected_version,
                ApplicationSessionMySQL.status == "processing",
            ).values(**values)
        )
        if result.rowcount != 1:
            return None
        await self.session.flush()
        await self.session.commit()
        return await self.get(session_id)


class InMemoryApplicationSessionRepository:
    """Isolated fake used by API/session tests; production uses MySQL above."""

    TTL = ApplicationSessionRepository.TTL

    def __init__(self):
        self.records: dict[str, SessionRecord] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)

    async def create(self, query: str, version_id: str) -> SessionRecord:
        now = self._now()
        record = SessionRecord(
            session_id=str(uuid4()), status="processing", original_query=query,
            current_query=query, clarification_id=None, turn_id=str(uuid4()),
            turn_number=1, state_version=0, semantic_model_version=version_id,
            pending_fields=(), terminal_status=None, execution_marker=None,
            expires_at=now + self.TTL,
        )
        async with self._lock:
            self.records[record.session_id] = record
        return record

    async def get(self, session_id: str) -> SessionRecord | None:
        return self.records.get(session_id)

    async def claim_clarification(self, record, clarification_id: str, answer: str):
        async with self._lock:
            current = self.records.get(record.session_id)
            if not current or current.clarification_id != clarification_id:
                return None
            if current.status != "needs_clarification" or current.state_version != record.state_version:
                return None
            if current.expires_at <= self._now():
                return None
            updated = SessionRecord(
                **{**current.__dict__, "status": "processing", "current_query": answer,
                   "turn_id": str(uuid4()), "turn_number": current.turn_number + 1,
                   "state_version": current.state_version + 1}
            )
            self.records[current.session_id] = updated
            return updated

    async def update_outcome(self, session_id, expected_version, *, status,
                             clarification_id=None, pending_fields=None,
                             terminal_status=None, execution_marker=None):
        async with self._lock:
            current = self.records.get(session_id)
            if not current or current.status != "processing" or current.state_version != expected_version:
                return None
            completed = {"completed", "error", "unsupported", "expired", "execution_unknown"}
            updated = SessionRecord(
                **{**current.__dict__, "status": status,
                   "clarification_id": clarification_id,
                   "pending_fields": tuple(pending_fields or ()),
                   "terminal_status": terminal_status,
                   "execution_marker": execution_marker,
                   "state_version": expected_version + 1}
            )
            self.records[session_id] = updated
            return updated
