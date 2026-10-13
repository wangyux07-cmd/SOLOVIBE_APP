"""Explicit, additive migration. Does not modify the legacy public tables."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'backend'))
import config  # loads ignored local .env
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from services.application import database_dsn, make_pool
from domain.errors import AppError


async def main():
    pool = make_pool(database_dsn())
    async with pool:
        async with pool.connection() as conn:
            await conn.execute('SELECT pg_advisory_lock(731415)')
            try:
                sql = (Path(__file__).resolve().parents[1]/'backend/persistence/schema.sql').read_text(encoding='utf-8')
                async with conn.transaction():
                    await conn.execute(sql)
                evidence_tables = await (await conn.execute('''SELECT
                    to_regclass('solovibe_v1.venue_identity') IS NOT NULL AS venue_identity,
                    to_regclass('solovibe_v1.source_observation') IS NOT NULL AS source_observation,
                    to_regclass('solovibe_v1.venue_claim') IS NOT NULL AS venue_claim''')).fetchone()
                if not all(evidence_tables.values()):
                    raise RuntimeError('evidence tables missing after migration')
                graph_pool = make_pool(database_dsn(),graph=True)
                async with graph_pool:
                    await AsyncPostgresSaver(graph_pool).setup()
            finally:
                await conn.execute('SELECT pg_advisory_unlock(731415)')
    print(json.dumps({'migrated':True,'business_schema':'solovibe_v1',
                      'summary_table':'solovibe_v1.rolling_summaries',
                      'evidence_tables': dict(evidence_tables),
                      'checkpoint_schema':'solovibe_graph'}))


if __name__ == '__main__':
    try:
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except Exception as exc:
        print(json.dumps({'migrated':False,'error':exc.code if isinstance(exc,AppError) else type(exc).__name__}))
        sys.exit(1)
