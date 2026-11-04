import asyncio
from argparse import ArgumentParser
from datetime import timedelta

from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import meta_mysql_client_manager
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.clients.semantic_index_clients import ElasticsearchIndexClient, QdrantIndexClient
from app.conf.app_config import app_config
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.services.semantic_index_builder import IndexBuildConfig, SemanticIndexBuilder
from app.services.semantic_index_verification import MySQLIndexVerificationStore
from app.services.semantic_model_snapshot import SemanticModelSnapshotLoader


async def build(version_id: str, target: str, es_index_name: str, qdrant_collection_name: str, embedding_batch_size: int) -> None:
    embedding_client_manager.init()
    es_client_manager.init()
    qdrant_client_manager.init()
    meta_mysql_client_manager.init()
    try:
        async with meta_mysql_client_manager.session_factory() as session:
            snapshot = await SemanticModelSnapshotLoader(MetaMySQLRepository(session)).load_for_build(version_id)
            config = IndexBuildConfig(
                es_index_name=es_index_name,
                qdrant_collection_name=qdrant_collection_name,
                embedding_model=app_config.embedding.model,
                embedding_dimension=app_config.qdrant.embedding_size,
                embedding_batch_size=embedding_batch_size,
            )
            builder = SemanticIndexBuilder(
                ElasticsearchIndexClient(es_client_manager.client),
                QdrantIndexClient(qdrant_client_manager.client),
                embedding_client_manager.client,
                MySQLIndexVerificationStore(session),
            )
            manifest = await builder.build(snapshot, config, target)
            await session.commit()
            print(f"verified version_id={version_id} target={target} documents={len(manifest.documents)} manifest_hash={manifest.manifest_hash}")
    finally:
        await meta_mysql_client_manager.close()
        await qdrant_client_manager.close()
        await es_client_manager.close()


if __name__ == "__main__":
    parser = ArgumentParser(description="从 MySQL draft 语义快照构建版本化 ES/Qdrant 派生索引")
    parser.add_argument("--version-id", required=True)
    parser.add_argument("--target", choices=("es", "qdrant", "both"), default="both")
    parser.add_argument("--es-index", default=app_config.es.index_name)
    parser.add_argument("--qdrant-collection", default="data-agent-semantic")
    parser.add_argument("--embedding-batch-size", type=int, default=10)

    args = parser.parse_args()
    asyncio.run(build(args.version_id, args.target, args.es_index, args.qdrant_collection, args.embedding_batch_size))

