"""One opt-in real DeepSeek/Amap/PostgreSQL multi-stop action check.

Creates a synthetic conversation, verifies every route handoff, then deletes
the conversation and expires its anonymous session. Never prints credentials.
"""
import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import config  # noqa: F401
from services.application import Application


async def main():
    app = Application()
    owner = thread = None
    try:
        await app.start()
        app.require_ready()
        owner, _ = await app.repo.session(None)
        thread = (await app.repo.create(owner))['thread_id']
        result = await app.chat(owner, thread, str(uuid4()),
            '城市：上海。出发点：徐家汇地铁站。预算：180元。可用时间：240分钟。'
            '最多步行：90分钟。17:00出发。想逛公园和博物馆，还要吃晚饭。请规划一条多站路线。', 0)
        current = await app.repo.read(owner, thread)
        assert result['kind'] == 'itinerary_ready', result['kind']
        plans = current['plan_set']['plans']
        assert len(plans) == 1 and 2 <= len(plans[0]['itinerary']['stops']) <= 3
        itinerary = plans[0]['itinerary']
        assert itinerary['stops'][-1]['kind'] == 'dinner'
        assert len(itinerary['legs']) == len(itinerary['stops']) + 1
        action = await app.prepare_action(owner, thread, str(uuid4()),
            current['plan_set']['plan_set_id'], plans[0]['plan_id'], 'navigate',
            current['snapshot']['revision'])
        handed = await app.decide_action(owner, action['action_id'], str(uuid4()),
            action['proposal_version'], action['proposal_digest'], True)
        assert handed['status'] == 'completed', handed['status']
        assert len(handed['receipt']['segments']) == len(itinerary['legs'])
        print(json.dumps({'real_multistop_verified': True,
            'stop_count': len(itinerary['stops']), 'leg_count': len(itinerary['legs']),
            'dinner_last': True, 'navigation_segments': len(handed['receipt']['segments']),
            'total_walk_minutes': itinerary['total_walk_minutes'],
            'total_minutes': itinerary['total_minutes']}, ensure_ascii=False))
    finally:
        if owner and thread and app.repo:
            await app.repo.delete_owned(owner, thread)
        if owner and app.repo:
            async with app.pool.connection() as conn:
                await conn.execute("UPDATE solovibe_v1.sessions SET expires_at=now()-interval '1 second' WHERE owner_id=%s", (owner,))
            await app.repo.finish_expired_session(owner)
        await app.close()


if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
