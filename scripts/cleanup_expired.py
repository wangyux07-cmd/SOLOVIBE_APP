"""Purge expired anonymous sessions and their conversations/checkpoints.

Dry-run by default. Schedule --apply daily after testing a backup restore.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import config  # noqa: F401
from domain.errors import Conflict
from persistence.repository import Repository
from services.application import database_dsn, make_pool


async def run(apply: bool, limit: int, owner_filter: str | None = None):
    pool = make_pool(database_dsn())
    async with pool:
        repo = Repository(pool)
        if owner_filter:
            async with pool.connection() as conn:
                sessions = await (await conn.execute('''SELECT owner_id FROM solovibe_v1.sessions
                    WHERE owner_id=%s AND expires_at<=now() LIMIT 1''',
                    (owner_filter,))).fetchall()
        else:
            sessions = await repo.expired_sessions(limit)
        report = {'expired_sessions_found': len(sessions), 'candidate_conversations': 0,
                  'deleted_sessions': 0, 'deleted_conversations': 0,
                  'busy_conversations': 0, 'applied': apply}
        for item in sessions:
            owner = str(item['owner_id'])
            async with pool.connection() as conn:
                threads = await (await conn.execute('''SELECT thread_id FROM solovibe_v1.conversations
                    WHERE owner_id=%s ORDER BY created_at''', (owner,))).fetchall()
            report['candidate_conversations'] += len(threads)
            if not apply:
                continue
            for thread in threads:
                try:
                    await repo.delete_owned(owner, str(thread['thread_id']))
                    report['deleted_conversations'] += 1
                except Conflict as exc:
                    if exc.code != 'THREAD_BUSY':
                        raise
                    report['busy_conversations'] += 1
            if await repo.finish_expired_session(owner):
                report['deleted_sessions'] += 1
        return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--limit', type=int, default=100)
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 1000:
        parser.error('--limit must be 1..1000')
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    print(json.dumps(asyncio.run(run(args.apply, args.limit))))
