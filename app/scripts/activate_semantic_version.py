import asyncio
from argparse import ArgumentParser

from app.clients.mysql_client_manager import meta_mysql_client_manager
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.services.semantic_index_builder import IndexBuildConfig, build_manifest
from app.services.semantic_index_verification import MySQLSemanticIndexActivationGate
from app.services.semantic_model_snapshot import SemanticModelSnapshotLoader


async def activate(version_id: str, es_index_name: str, qdrant_collection_name: str, embedding_model: str, embedding_dimension: int, embedding_batch_size: int) -> None:
    meta_mysql_client_manager.init()
    try:
        async with meta_mysql_client_manager.session_factory() as session:
            repository = MetaMySQLRepository(session)
            snapshot = await SemanticModelSnapshotLoader(repository).load_for_build(version_id)
            config = IndexBuildConfig(es_index_name, qdrant_collection_name, embedding_model, embedding_dimension, embedding_batch_size=embedding_batch_size)
            manifest = build_manifest(snapshot, config)
            if session.in_transaction():
                await session.rollback()
            gate = MySQLSemanticIndexActivationGate(session, config.config_hash, es_index_name, qdrant_collection_name, manifest.manifest_hash)
            await repository.activate_version(version_id, gate)
            await session.commit()
            print(f"activated version_id={version_id} manifest_hash={manifest.manifest_hash}")
    finally:
        await meta_mysql_client_manager.close()


if __name__ == "__main__":
    parser = ArgumentParser(description="仅在匹配的 ES/Qdrant 验证记录存在时激活语义版本")
    parser.add_argument("--version-id", required=True)
    parser.add_argument("--es-index", required=True)
    parser.add_argument("--qdrant-collection", required=True)
    parser.add_argument("--embedding-model", required=True)
    parser.add_argument("--embedding-dimension", required=True, type=int)
    parser.add_argument("--embedding-batch-size", type=int, default=10)
    args = parser.parse_args()
    asyncio.run(activate(args.version_id, args.es_index, args.qdrant_collection, args.embedding_model, args.embedding_dimension, args.embedding_batch_size))


