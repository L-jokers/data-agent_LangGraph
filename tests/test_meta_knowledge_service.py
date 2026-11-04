import asyncio
import unittest
from types import SimpleNamespace

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.models import Base, ColumnInfoMySQL, SemanticModelVersionMySQL, TableInfoMySQL
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.services.meta_knowledge_service import MetaKnowledgeService


class AsyncSessionAdapter:
    def __init__(self, session: Session):
        self.session = session

    def add_all(self, models):
        self.session.add_all(models)

    async def flush(self):
        self.session.flush()


class FakeDWRepository:
    async def get_column_types(self, table_name):
        return {"region_id": "varchar(20)"}

    async def get_column_values(self, table_name, column_name, limit):
        return ["R001"]


class MetaKnowledgeServiceTests(unittest.TestCase):
    def test_table_rows_flush_before_composite_fk_column_rows(self):
        engine = create_engine("sqlite:///:memory:")

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(dbapi_connection, connection_record):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(engine)
        with Session(engine) as session:
            session.add(SemanticModelVersionMySQL(version_id="v1", content_hash="hash"))
            session.flush()

            adapter = AsyncSessionAdapter(session)
            repository = MetaMySQLRepository(adapter)
            service = MetaKnowledgeService(repository, FakeDWRepository())
            config = SimpleNamespace(
                tables=[
                    SimpleNamespace(
                        name="dim_region",
                        role="dim",
                        description="region",
                        columns=[
                            SimpleNamespace(
                                name="region_id",
                                role="primary_key",
                                description="id",
                                alias=["地区ID"],
                            )
                        ],
                    )
                ]
            )

            asyncio.run(service._save_tables_to_meta_db(config, "v1"))

            table = session.execute(
                select(TableInfoMySQL).where(TableInfoMySQL.id == "dim_region")
            ).scalar_one()
            column = session.execute(
                select(ColumnInfoMySQL).where(
                    ColumnInfoMySQL.id == "dim_region.region_id"
                )
            ).scalar_one()

            self.assertEqual(table.version_id, "v1")
            self.assertEqual(column.table_id, table.id)


if __name__ == "__main__":
    unittest.main()
