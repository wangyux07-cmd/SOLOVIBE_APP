"""Child process for verifying durable action-interrupt recovery. Reads IDs on stdin."""
import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import config  # noqa: F401
from services.application import Application


async def main():
    args = json.loads(sys.stdin.readline())
    app = Application()
    await app.start()
    try:
        app.require_ready()
        result = await app.decide_action(args['owner'], args['action_id'], str(uuid4()),
                                         args['version'], args['digest'], True)
        print(json.dumps({'status': result['status'], 'receipt_kind': result['receipt']['kind']}))
    finally:
        await app.close()


if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
