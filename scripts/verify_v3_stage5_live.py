"""Opt-in real V3-5 check; creates and removes one test conversation."""
import asyncio
import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import config  # noqa: F401
from domain.errors import AppError
from services.application import Application


async def main():
    app = Application()
    owner = thread = None
    deleted = False
    await app.start()
    try:
        app.require_ready()
        owner, _ = await app.repo.session(None)
        thread = (await app.repo.create(owner))['thread_id']
        await app.set_browser_origin(owner, thread, str(uuid4()), 0, 121.435, 31.193, 18)
        first = await app.chat(owner, thread, str(uuid4()),
            '预算80元，可用时间120分钟，最多步行30分钟，想去公园，计划停留30分钟，请规划。', 1)
        current = await app.repo.read(owner, thread)
        assert first['kind'] == 'options_ready' and current['plan_set']['plans']
        old_set = current['plan_set']['plan_set_id']
        old_plan = current['plan_set']['plans'][0]
        assert old_plan['route']['polyline'] and old_plan['return_route']['polyline']
        change_id = str(uuid4())
        changed = await app.adjust(owner, thread, change_id, 'budget_cny', 60.0,
                                   current['snapshot']['revision'])
        assert (await app.adjust(owner, thread, change_id, 'budget_cny', 60.0,
                                 current['snapshot']['revision']))['run_id'] == changed['run_id']
        current = await app.repo.read(owner, thread)
        assert current['snapshot']['constraints']['budget_cny'] == 60.0
        assert current['plan_set']['plan_set_id'] != old_set
        assert current['plan_set']['replanning']['changed_fields'] == ['budget_cny']
        try:
            await app.prepare_action(owner, thread, str(uuid4()), old_set,
                                     old_plan['plan_id'], 'save', current['snapshot']['revision'])
        except AppError as exc:
            assert exc.code in ('PLAN_STALE', 'PLAN_NOT_FOUND')
        else:
            raise AssertionError('Old plan accepted after adjustment')

        feedback_plan = current['plan_set']['plans'][0]
        feedback_id = str(uuid4())
        feedback = await app.repo.submit_feedback(owner, thread, feedback_id,
            current['plan_set']['plan_set_id'], feedback_plan['plan_id'], 'considered', '测试反馈')
        assert (await app.repo.submit_feedback(owner, thread, feedback_id,
            current['plan_set']['plan_set_id'], feedback_plan['plan_id'], 'considered', '测试反馈'))['feedback_id'] == feedback['feedback_id']
        timeline = await app.repo.timeline(owner, thread)
        assert any(item['event_type'] == 'user_report' for item in timeline)
        try:
            await app.repo.run_status(str(uuid4()), thread, request_id=change_id)
        except AppError as exc:
            assert exc.code == 'NOT_FOUND'
        else:
            raise AssertionError('Other owner read a run')
        try:
            await app.repo.delete_owned(str(uuid4()), thread)
        except AppError as exc:
            assert exc.code == 'NOT_FOUND'
        else:
            raise AssertionError('Other owner deleted a conversation')

        child = await asyncio.to_thread(subprocess.run,
            [sys.executable, str(Path(__file__).with_name('v3_stage5_read_child.py'))],
            input=json.dumps({'owner': owner, 'thread': thread, 'request_id': change_id}),
            text=True, capture_output=True, timeout=30)
        assert child.returncode == 0, child.stderr
        assert json.loads(child.stdout) == {'status': 'completed', 'revision': current['snapshot']['revision']}
        checked = await app.recheck_place(owner, thread, str(uuid4()),
            current['plan_set']['plan_set_id'], feedback_plan['place']['poi_id'],
            current['snapshot']['revision'])
        assert checked['kind'] in ('options_ready', 'planning_unavailable')
        await app.repo.delete_owned(owner, thread)
        deleted = True
        async with app.pool.connection() as conn:
            for table, key in (('conversations', 'thread_id'), ('runs', 'thread_id'),
                               ('messages', 'thread_id'), ('plan_sets', 'thread_id'),
                               ('user_feedback', 'thread_id')):
                count = await (await conn.execute(
                    f'SELECT count(*) AS n FROM solovibe_v1.{table} WHERE {key}=%s',
                    (thread,))).fetchone()
                assert count['n'] == 0, table
            for table in ('checkpoints', 'checkpoint_blobs', 'checkpoint_writes'):
                count = await (await conn.execute(
                    f'SELECT count(*) AS n FROM solovibe_graph.{table} WHERE thread_id=%s',
                    (thread,))).fetchone()
                assert count['n'] == 0, table
        print(json.dumps({'verified': True, 'real_first_plans': len(current['plan_set']['plans']),
            'adjustment_replayed': True, 'new_plan_set': True, 'old_plan_rejected': True,
            'owner_isolated': True, 'cross_process_status': True,
            'targeted_recheck_kind': checked['kind'], 'feedback_source': 'user_report',
            'business_and_checkpoints_deleted': True},
            ensure_ascii=False))
    finally:
        if owner and thread and app.repo and not deleted:
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
