import asyncio
from argparse import ArgumentParser
from pathlib import Path

from app.clients.mysql_client_manager import (
    dw_mysql_client_manager,
    meta_mysql_client_manager,
)
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.conf.meta_config import load_meta_config
from app.services.meta_knowledge_service import MetaKnowledgeService


async def build(config_path: Path, version_id: str):
    meta_mysql_client_manager.init()
    dw_mysql_client_manager.init()

    try:
        async with (
            meta_mysql_client_manager.session_factory() as meta_session,
            dw_mysql_client_manager.session_factory() as dw_session,
        ):
            service = MetaKnowledgeService(
                meta_mysql_repository=MetaMySQLRepository(meta_session),
                dw_mysql_repository=DWMySQLRepository(dw_session),
            )
            await service.build(config_path, version_id)
    finally:
        await meta_mysql_client_manager.close()
        await dw_mysql_client_manager.close()


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("-c", "--conf", required=True)
    parser.add_argument("--version-id")
    parser.add_argument("--print-content-hash", action="store_true")
    args = parser.parse_args()

    config_path = Path(args.conf)
    if args.print_content_hash:
        print(MetaKnowledgeService.config_fingerprint(load_meta_config(config_path)))
    elif args.version_id:
        asyncio.run(build(config_path, args.version_id))
    else:
        parser.error("未指定 --version-id")
