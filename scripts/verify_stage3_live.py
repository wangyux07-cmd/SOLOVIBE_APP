r"""Live Stage 3 smoke test. Requires local .env; never prints credentials.

Run: .\.venv\Scripts\python.exe scripts/verify_stage3_live.py
Use --require-options after configuring an Amap Web Service key.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import config  # noqa: F401 - loads ignored local .env
from services.application import Application


async def verify(require_options):
    app = Application()
    await app.start()
    try:
        app.require_ready()
        owner, _ = await app.repo.session(None)
        thread = await app.repo.create(owner)
        result = await app.chat(owner, thread['thread_id'], str(uuid4()),
            '城市：上海。出发点：徐家汇地铁站。预算：60元。可用时间：40分钟。最多步行：25分钟。偏好：公园。请规划。', 0)
        stored = await app.repo.read(owner, thread['thread_id'])
        events = await app.repo.trace(owner, thread['thread_id'], result['run_id'])
        plans = result.get('plans', [])
        print(json.dumps({'kind':result['kind'], 'missing_fields':result.get('missing_fields', []),
                          'evidence_status':result.get('evidence_status'), 'plans':len(plans)},
                         ensure_ascii=False))
        assert stored['pending_run'] is None
        assert any(event['node'] == 'collect_evidence' and event['status'] == 'completed' for event in events)
        assert all(plan['place']['provider'] == 'amap' and plan['route']['provider'] == 'amap'
                   for plan in plans)
        assert all(plan['unknowns'] and plan['context_revision'] == result['snapshot']['revision']
                   for plan in plans)
        if require_options:
            assert result['kind'] == 'options_ready' and 1 <= len(plans) <= 3
            assert stored['plan_set'] and len(stored['plan_set']['plans']) == len(plans)
        print(json.dumps({'ready':True, 'kind':result['kind'], 'plans':len(plans),
            'evidence_status':result.get('evidence_status'), 'provider_errors':result.get('provider_errors', []),
            'detail_statuses':[plan.get('detail_status') for plan in plans],
            'ratings_with_source':sum(1 for plan in plans if plan.get('facts') and plan['facts'].get('rating') is not None),
            'web_source_counts':[len(plan.get('web_sources', [])) for plan in plans],
            'snapshot_revision':result['snapshot']['revision'],
            'plan_set_persisted':bool(stored['plan_set']),
            'graph_nodes':[event['node'] for event in events if event['status'] == 'completed']},
            ensure_ascii=False))
    finally:
        await app.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--require-options', action='store_true')
    args = parser.parse_args()
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(verify(args.require_options))
