"""Independent process used by the opt-in recovery check."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import config  # noqa: F401
from persistence.repository import Repository
from services.application import database_dsn, make_pool


async def main():
    args = json.loads(sys.stdin.read())
    pool = make_pool(database_dsn())
    async with pool:
        repo = Repository(pool)
        status = await repo.run_status(args['owner'], args['thread'], request_id=args['request_id'])
        conversation = await repo.read(args['owner'], args['thread'])
    print(json.dumps({'status': status['status'], 'revision': conversation['snapshot']['revision']}))


if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
