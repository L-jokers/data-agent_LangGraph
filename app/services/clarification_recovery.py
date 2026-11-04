from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class PendingClarification:
    session_id: str
    clarification_id: str
    original_query: str
    semantic_version_id: str
    pending_fields: tuple[str, ...]
    state_version: int = 0
    status: str = "needs_clarification"
    expires_at: datetime | None = None


class ClarificationRecoveryError(ValueError):
    pass


class InMemoryClarificationStore:
    """Deterministic fake store for T5 recovery tests; not production persistence."""

    def __init__(self):
        self._records: dict[str, PendingClarification] = {}

    def create(self, original_query: str, semantic_version_id: str, pending_fields: list[str]) -> PendingClarification:
        record = PendingClarification(
            session_id=str(uuid4()),
            clarification_id=str(uuid4()),
            original_query=original_query,
            semantic_version_id=semantic_version_id,
            pending_fields=tuple(pending_fields),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        self._records[record.session_id] = record
        return record

    def get_pending(self, session_id: str, clarification_id: str) -> PendingClarification:
        record = self._records.get(session_id)
        if record is None or record.clarification_id != clarification_id:
            raise ClarificationRecoveryError("澄清会话或clarification_id不匹配")
        if record.status != "needs_clarification":
            raise ClarificationRecoveryError("当前会话不是待澄清状态，不支持上下文追问")
        if record.expires_at is not None and record.expires_at <= datetime.now(timezone.utc):
            raise ClarificationRecoveryError("澄清会话已过期")
        return record

    def consume(self, record: PendingClarification) -> PendingClarification:
        current = self.get_pending(record.session_id, record.clarification_id)
        updated = replace(current, status="resuming", state_version=current.state_version + 1)
        self._records[record.session_id] = updated
        return updated

    def complete(self, session_id: str, clarification_id: str, status: str) -> None:
        record = self._records.get(session_id)
        if record is None or record.clarification_id != clarification_id:
            raise ClarificationRecoveryError("澄清会话或clarification_id不匹配")
        self._records[session_id] = replace(record, status=status, state_version=record.state_version + 1)


def combine_clarification_query(record: PendingClarification, answer: str) -> str:
    answer = answer.strip()
    if not answer:
        raise ClarificationRecoveryError("澄清回答不能为空")
    return f"{record.original_query}\n用户补充的澄清信息：{answer}"


async def resume_clarification(
    store: InMemoryClarificationStore,
    session_id: str,
    clarification_id: str,
    answer: str,
    run_query: Callable[[str, str], Awaitable[Any]],
) -> Any:
    """Re-run the complete query path with the session-bound semantic version."""
    pending = store.get_pending(session_id, clarification_id)
    active = store.consume(pending)
    combined_query = combine_clarification_query(active, answer)
    try:
        result = await run_query(combined_query, active.semantic_version_id)
    except Exception:
        store.complete(session_id, clarification_id, "error")
        raise
    store.complete(session_id, clarification_id, "completed")
    return result
