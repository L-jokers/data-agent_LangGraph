from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.models.semantic_index_verification_mysql import SemanticIndexVerificationMySQL
from app.repositories.mysql.meta.meta_mysql_repository import SemanticModelVersionError


class MySQLIndexVerificationStore:
    def __init__(self, session):
        self.session = session

    async def record_verified(self, record: dict[str, Any]) -> None:
        self.session.add(SemanticIndexVerificationMySQL(
            version_id=record["version_id"], content_hash=record["content_hash"],
            config_hash=record["config_hash"], target=record["target"],
            es_index_name=record["es_index_name"], qdrant_collection_name=record["qdrant_collection_name"],
            manifest_hash=record["manifest_hash"], status=record["status"],
            verified_at=record["verified_at"], expires_at=record.get("expires_at"),
            details=json.dumps({"document_count": record["document_count"]}, ensure_ascii=False),
        ))
        await self.session.flush()


class MySQLSemanticIndexActivationGate:
    def __init__(self, session, config_hash: str, es_index_name: str, qdrant_collection_name: str, manifest_hash: str):
        self.session = session
        self.config_hash = config_hash
        self.es_index_name = es_index_name
        self.qdrant_collection_name = qdrant_collection_name
        self.manifest_hash = manifest_hash

    async def assert_ready(self, version_id: str, content_hash: str) -> None:
        result = await self.session.execute(
            select(SemanticIndexVerificationMySQL).where(
                SemanticIndexVerificationMySQL.version_id == version_id,
                SemanticIndexVerificationMySQL.content_hash == content_hash,
                SemanticIndexVerificationMySQL.config_hash == self.config_hash,
                SemanticIndexVerificationMySQL.target == "both",
                SemanticIndexVerificationMySQL.es_index_name == self.es_index_name,
                SemanticIndexVerificationMySQL.qdrant_collection_name == self.qdrant_collection_name,
                SemanticIndexVerificationMySQL.manifest_hash == self.manifest_hash,
                SemanticIndexVerificationMySQL.status == "verified",
            ).order_by(SemanticIndexVerificationMySQL.verified_at.desc())
        )
        record = result.scalars().first()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if record is None or (record.expires_at is not None and record.expires_at <= now):
            raise SemanticModelVersionError("缺少匹配且未过期的 ES/Qdrant 索引验证记录，拒绝激活")


class InMemoryVerificationStore:
    def __init__(self):
        self.records: list[dict[str, Any]] = []

    async def record_verified(self, record: dict[str, Any]) -> None:
        self.records.append(record)

    async def assert_ready(self, version_id: str, content_hash: str, config_hash: str, es_index_name: str, qdrant_collection_name: str, manifest_hash: str) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for record in reversed(self.records):
            expected = {
                "version_id": version_id, "content_hash": content_hash, "config_hash": config_hash,
                "target": "both", "es_index_name": es_index_name,
                "qdrant_collection_name": qdrant_collection_name, "manifest_hash": manifest_hash,
                "status": "verified",
            }
            if all(record.get(key) == value for key, value in expected.items()) and (record.get("expires_at") is None or record["expires_at"] > now):
                return
        raise SemanticModelVersionError("缺少匹配且未过期的索引验证记录，拒绝激活")


