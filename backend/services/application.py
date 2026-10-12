"""Coordinates authorization, single-writer execution, and durable graph recovery."""
import os
import asyncio

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from agent_graph import build_graph
from domain.errors import AppError
from persistence.repository import Repository
from services.model_client import DeepSeekClient


def database_dsn():
    value = os.getenv('DATABASE_URL','').strip()
    if not value:
        raise AppError('DATABASE_NOT_CONFIGURED','请在 backend/.env 配置真实 DATABASE_URL。')
    try:
        options = conninfo_to_dict(value)
    except Exception:
        raise AppError('DATABASE_NOT_CONFIGURED','DATABASE_URL 连接串格式无效。') from None
    password = options.get('password','').lower()
    if not password or any(marker in password for marker in ('your-password','your_password','your-db-password','[password]','<password>')) or password == 'password':
        raise AppError('DATABASE_NOT_CONFIGURED','DATABASE_URL 的数据库密码仍是占位符。')
    if options.get('port') == '6543':
        raise AppError('DATABASE_POOL_MODE','请使用 PostgreSQL 直连或 Session pooler（通常为 5432），本阶段不支持事务池模式。')
    return value


def make_pool(dsn, graph=False):
    kwargs = {'autocommit':True,'row_factory':dict_row,'prepare_threshold':None,'connect_timeout':8}
    async def graph_search_path(connection):
        # Session pooler supports session state; avoid startup-parameter support
        # differences between direct Postgres and the shared pooler.
        await connection.execute('SET search_path TO solovibe_graph,public')
    return AsyncConnectionPool(dsn,kwargs=kwargs,min_size=1,max_size=8,timeout=12,
                               open=False,configure=graph_search_path if graph else None)


class Application:
    def __init__(self):
        self.pool = self.graph_pool = self.model = self.graph = self.repo = None
        self.ready = False
        self.slots = asyncio.Semaphore(3)
        self.error = AppError('STARTING','服务正在启动。')

    async def start(self):
        try:
            dsn = database_dsn()
            if not os.getenv('DEEPSEEK_API_KEY'):
                raise AppError('MODEL_NOT_CONFIGURED','请配置 DEEPSEEK_API_KEY。')
            self.pool = make_pool(dsn)
            await self.pool.open(wait=True,timeout=12)
            async with self.pool.connection() as conn:
                tables = await (await conn.execute("SELECT to_regclass('solovibe_v1.conversations') AS business, to_regclass('solovibe_graph.checkpoints') AS checkpoints")).fetchone()
                if not all(tables.values()):
                    raise AppError('MIGRATION_REQUIRED','请先运行 scripts/migrate_stage1.py 初始化阶段一数据表。')
            self.graph_pool = make_pool(dsn,graph=True)
            await self.graph_pool.open(wait=True,timeout=12)
            self.model = DeepSeekClient(os.environ['DEEPSEEK_API_KEY'],os.getenv('DEEPSEEK_MODEL','deepseek-flash'))
            probe = await self.model.probe()
            if not probe['configured_model_available']:
                raise AppError('MODEL_NOT_AVAILABLE','配置的模型不在账户可用模型列表中。')
            # Listing models only verifies authentication. A tiny generation call
            # also catches accounts that cannot actually run completions.
            await self.model.understand({},[], '你好')
            self.repo = Repository(self.pool)
            self.graph = build_graph(self.repo,self.model,AsyncPostgresSaver(self.graph_pool))
            self.ready = True
            self.error = None
        except AppError as exc:
            self.error = exc
        except Exception:
            self.error = AppError('DATABASE_UNAVAILABLE','数据库连接或初始化检查失败；请检查连接串、网络和迁移状态。')
        if not self.ready:
            await self.close()

    async def close(self):
        if self.model:
            await self.model.close()
        if self.graph_pool:
            await self.graph_pool.close()
        if self.pool:
            await self.pool.close()

    def require_ready(self):
        if not self.ready:
            raise self.error

    async def chat(self, owner, thread, request_id, message, expected_revision):
        async with self.slots, self.repo.guard(owner,thread):
            run = await self.repo.accept(owner,thread,request_id,message,expected_revision)
            return await self.execute(run)

    async def retry(self, owner, thread, run_id):
        async with self.slots, self.repo.guard(owner,thread):
            run = await self.repo.run(run_id)
            if not run or str(run['thread_id']) != thread:
                raise AppError('NOT_FOUND','运行记录不存在。',404)
            return await self.execute(run)

    async def execute(self, run):
        if run['status'] == 'completed':
            return run['output']
        run_id = str(run['run_id'])
        config = {'configurable':{'thread_id':str(run['thread_id'])},'recursion_limit':20}
        try:
            checkpoint = await self.graph.aget_state(config)
            same_run = checkpoint.values.get('run_id') == run_id
            if same_run and not checkpoint.next and run['output']:
                result = {'output':run['output']}
            else:
                graph_input = None if same_run and checkpoint.next else {'thread_id':str(run['thread_id']),'run_id':run_id}
                result = await self.graph.ainvoke(graph_input,config,durability='sync')
            await self.repo.complete(run_id)
            return result['output']
        except Exception as exc:
            error = exc if isinstance(exc,AppError) else AppError('RUN_FAILED','本轮未完成，已保留进度。请重试本条消息。')
            try:
                await self.repo.fail(run_id,error.code)
            except Exception:
                pass  # Original error remains safe even when the database is unreachable.
            raise error from None
