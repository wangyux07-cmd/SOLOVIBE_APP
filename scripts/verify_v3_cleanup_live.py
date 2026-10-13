"""Real database check for scheduled expiry, scoped to one synthetic owner."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import config  # noqa: F401
from persistence.repository import Repository
from services.application import database_dsn, make_pool
from cleanup_expired import run


async def main():
    pool = make_pool(database_dsn())
    async with pool:
        repo = Repository(pool)
        owner, _ = await repo.session(None)
        thread = (await repo.create(owner))['thread_id']
        async with pool.connection() as conn:
            await conn.execute("UPDATE solovibe_v1.sessions SET expires_at=now()-interval '1 second' WHERE owner_id=%s", (owner,))
    preview = await run(False, 100, owner)
    assert preview['expired_sessions_found'] == 1 and preview['candidate_conversations'] == 1
    assert preview['deleted_conversations'] == 0
    applied = await run(True, 100, owner)
    assert applied['deleted_sessions'] == 1 and applied['deleted_conversations'] == 1
    pool = make_pool(database_dsn())
    async with pool:
        async with pool.connection() as conn:
            for table, field, value in (('sessions', 'owner_id', owner),
                                        ('conversations', 'thread_id', thread)):
                row = await (await conn.execute(
                    f'SELECT count(*) AS n FROM solovibe_v1.{table} WHERE {field}=%s',
                    (value,))).fetchone()
                assert row['n'] == 0
    print(json.dumps({'expiry_preview': True, 'expired_session_erased': True,
                      'conversation_erased': True}))


if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
