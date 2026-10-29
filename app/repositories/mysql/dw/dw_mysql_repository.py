import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.security.query_limits import QueryResult


class DWMySQLRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_column_types(self, table_name: str) -> dict[str, str]:
        sql = f"show columns from {table_name}"
        result = await self.session.execute(text(sql))
        return {row.Field: row.Type for row in result.fetchall()}

    async def get_column_values(self, table_name: str, column_name: str, limit: int):
        sql = f"select distinct {column_name} from {table_name} limit {limit}"
        result = await self.session.execute(text(sql))
        return result.scalars().fetchall()

    async def get_db_info(self):
        result = await self.session.execute(text("select version()"))
        version = result.scalar()
        dialect = self.session.get_bind().dialect.name
        return {"version": version, "dialect": dialect}

    async def validate_sql(self, sql, params=None):
        await self.session.execute(text(f"EXPLAIN {sql}"), params or {})

    async def execute_sql(
        self,
        sql: str,
        params: dict | None = None,
        *,
        max_rows: int = 100,
        timeout_seconds: float = 10.0,
    ) -> QueryResult:
        async def run_query():
            result = await self.session.execute(text(sql), params or {})
            rows = [dict(row) for row in result.mappings().fetchmany(max_rows + 1)]
            truncated = len(rows) > max_rows
            if truncated:
                rows = rows[:max_rows]
            return QueryResult(
                rows=rows,
                truncated=truncated,
                row_count=len(rows),
                max_rows=max_rows,
            )

        return await asyncio.wait_for(run_query(), timeout=timeout_seconds)
