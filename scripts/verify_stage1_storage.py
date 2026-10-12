"""Read-only counts proving business records and native checkpoints exist."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import config  # noqa: F401 - loads the ignored backend/.env
from services.application import database_dsn, make_pool


async def main():
    pool = make_pool(database_dsn())
    async with pool:
        async with pool.connection() as conn:
            row = await (await conn.execute('''
                SELECT
                  (SELECT count(*) FROM solovibe_v1.runs WHERE status='completed') AS completed_runs,
                  (SELECT count(*) FROM solovibe_v1.node_events WHERE status='completed') AS completed_nodes,
                  (SELECT count(*) FROM solovibe_graph.checkpoints) AS checkpoints
            ''')).fetchone()
    assert all(value > 0 for value in row.values())
    print(json.dumps({'storage_verified': True, **row}))


if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
