import asyncio
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine, async_sessionmaker

from app.conf.app_config import DBConfig, app_config


class MysqlClientManager:
    def __init__(self, db_config: DBConfig):
        self.db_config = db_config
        self.engine: Optional[AsyncEngine] = None
        self.session_factory = None

    def _get_url(self):
        #  asyncmy是连接MySQL的底层异步驱动，需要单独安装
        return f"mysql+asyncmy://{self.db_config.user}:{self.db_config.password}@{self.db_config.host}:{self.db_config.port}/{self.db_config.database}?charset=utf8mb4"

    def init(self):
        self.engine = create_async_engine(url=self._get_url(),
                                          pool_size=10, # 连接池的连接数设置
                                          pool_pre_ping=True)   # 启动连接池的预ping功能，测试连接是否正常可用
        self.session_factory = async_sessionmaker(self.engine,
                                                  # flush表示在事务没提交之前，将add的数据写入，成为可查询的数据，否则只有在commit之后add的数据才能查询
                                                  autoflush=True,
                                                  # 异步一定要设置为false， commit 后对象属性仍然保留在内存里，后续访问 user.name 不会因为 commit 而自动触发一次重新查询
                                                  # 而异步数据库 I/O 必须发生在可 await 的上下文里，所以这类“隐式加载”在 AsyncSession 下通常是不合适的，也经常直接报错，比如 MissingGreenlet
                                                  expire_on_commit=False,
                                                  autobegin=True)

    async def close(self):
        await self.engine.dispose()


dw_mysql_client_manager = MysqlClientManager(app_config.db_dw)
meta_mysql_client_manager = MysqlClientManager(app_config.db_meta)

if __name__ == '__main__':
    meta_mysql_client_manager.init()


    async def test():
        async with meta_mysql_client_manager.session_factory() as session:
            # 这里的execute方法只接收Executable的对象，不能是直接的str字符串
            result = await session.execute(text("select * from table_info limit 10"))

            # 真正得到查询的结果，需要进行fetch才能得到真正查询回来的数据结果
            rows = result.fetchall()
            # # 对返回的Row对象进行映射，用于可以直接通过字段名称访问一行row数据当中指定字段的数据
            # rows = result.mappings().fetchall()
            print(rows)


    asyncio.run(test())
