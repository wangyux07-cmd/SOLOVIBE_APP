"""Live Stage 4 check against configured DeepSeek, Amap and PostgreSQL.

Creates a fresh anonymous conversation and performs real planning, save, and
navigation-link handoff. Never prints credentials or a session cookie.
"""
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
    await app.start()
    try:
        app.require_ready()
        owner, _ = await app.repo.session(None)
        thread = (await app.repo.create(owner))['thread_id']
        chat_request = str(uuid4())
        first_message = '城市：上海。出发点：徐家汇地铁站。预算：60元。可用时间：40分钟。最多步行：25分钟。偏好：公园。请规划。'
        result = await app.chat(owner, thread, chat_request, first_message, 0)
        state = await app.repo.read(owner, thread)
        plans = state['plan_set']['plans'] if state['plan_set'] else []
        assert plans and result['kind'] == 'options_ready'
        plan_id = plans[0]['plan_id']
        plan_set_id = state['plan_set']['plan_set_id']
        revision = state['snapshot']['revision']

        save_request = str(uuid4())
        save = await app.prepare_action(owner, thread, save_request, plan_set_id, plan_id, 'save', revision)
        assert save['status'] == 'awaiting_confirmation'
        assert (await app.prepare_action(owner, thread, save_request, plan_set_id, plan_id, 'save', revision))['action_id'] == save['action_id']
        try:
            await app.prepare_action(owner, thread, save_request, plan_set_id, plan_id, 'navigate', revision)
        except AppError as exc:
            assert exc.code == 'REQUEST_ID_REUSED'
        else:
            raise AssertionError('Request ID was reused for another action')
        try:
            await app.decide_action(owner, save['action_id'], str(uuid4()), 1, '0' * 64, True)
        except AppError as exc:
            assert exc.code == 'PROPOSAL_MISMATCH'
        else:
            raise AssertionError('Mismatched digest was accepted')
        try:
            await app.repo.actions.get(str(uuid4()), save['action_id'])
        except AppError as exc:
            assert exc.code == 'NOT_FOUND'
        else:
            raise AssertionError('Other owner could read the action')
        decision_id = str(uuid4())
        saved = await app.decide_action(owner, save['action_id'], decision_id, 1, save['proposal_digest'], True)
        assert saved['status'] == 'completed' and saved['receipt']['kind'] == 'plan_saved'
        assert (await app.decide_action(owner, save['action_id'], decision_id, 1,
                                        save['proposal_digest'], True))['status'] == 'completed'
        async with app.pool.connection() as conn:
            count = await (await conn.execute('SELECT count(*) AS n FROM solovibe_v1.saved_plans WHERE action_id=%s',
                                              (save['action_id'],))).fetchone()
        assert count['n'] == 1
        assert any(item['action_id'] == save['action_id'] for item in
                   (await app.repo.read(owner, thread))['saved_plans'])

        # A newly started Python process must resume the persisted interrupt.
        cross = await app.prepare_action(owner, thread, str(uuid4()), plan_set_id, plan_id, 'save', revision)
        child = await asyncio.to_thread(subprocess.run,
            [sys.executable, str(Path(__file__).with_name('stage4_recover_child.py'))],
            input=json.dumps({'owner': owner, 'action_id': cross['action_id'],
                'version': cross['proposal_version'], 'digest': cross['proposal_digest']}) + '\n',
            text=True, capture_output=True, timeout=60)
        assert child.returncode == 0, child.stderr
        cross_result = json.loads(child.stdout)
        assert cross_result == {'status': 'completed', 'receipt_kind': 'plan_saved'}

        nav = await app.prepare_action(owner, thread, str(uuid4()), plan_set_id, plan_id, 'navigate', revision)
        assert nav['status'] == 'awaiting_confirmation'
        handed = await app.decide_action(owner, nav['action_id'], str(uuid4()), 1, nav['proposal_digest'], True)
        assert handed['status'] == 'completed', handed
        assert handed['receipt']['kind'] == 'navigation_handoff_ready'
        assert handed['receipt']['url'].startswith('https://uri.amap.com/navigation?')
        assert 'mode=walk' in handed['receipt']['url']
        assert any(item['action_id'] == save['action_id'] for item in
                   (await app.repo.read(owner, thread))['saved_plans'])
        handoff_id = str(uuid4())
        recorded = await app.repo.actions.record_handoff(owner, nav['action_id'], handoff_id)
        assert recorded['handoff_requested_at'] is not None
        repeated = await app.repo.actions.record_handoff(owner, nav['action_id'], handoff_id)
        assert repeated['handoff_requested_at'] == recorded['handoff_requested_at']

        rejected = await app.prepare_action(owner, thread, str(uuid4()), plan_set_id, plan_id, 'save', revision)
        rejection = await app.decide_action(owner, rejected['action_id'], str(uuid4()), 1,
                                            rejected['proposal_digest'], False)
        assert rejection['status'] == 'rejected'
        expired = await app.prepare_action(owner, thread, str(uuid4()), plan_set_id, plan_id, 'save', revision)
        async with app.pool.connection() as conn:
            await conn.execute("UPDATE solovibe_v1.actions SET expires_at=now()-interval '1 second' WHERE action_id=%s",
                               (expired['action_id'],))
        expired_result = await app.decide_action(owner, expired['action_id'], str(uuid4()), 1,
                                                 expired['proposal_digest'], True)
        assert expired_result['status'] == 'invalidated'
        pending = await app.prepare_action(owner, thread, str(uuid4()), plan_set_id, plan_id, 'save', revision)
        replay = await app.chat(owner, thread, chat_request, first_message, 0)
        assert replay['run_id'] == result['run_id']
        assert (await app.repo.actions.get(owner, pending['action_id']))['status'] == 'awaiting_confirmation'
        await app.chat(owner, thread, str(uuid4()), '请复述我当前的出行条件。', revision)
        invalidated = await app.repo.actions.get(owner, pending['action_id'])
        assert invalidated['status'] == 'invalidated'
        print(json.dumps({'stage4_verified': True, 'real_plans': len(plans),
                          'saved_rows': count['n'], 'navigation_handoff': handed['receipt']['kind'],
                          'handoff_requested_recorded': True,
                          'cross_process_resume': True,
                          'rejected': rejection['status'], 'expired': expired_result['status'],
                          'new_message': invalidated['status'],
                          'chat_replay_preserved_pending_action': True,
                          'wrong_digest_and_owner_denied': True}, ensure_ascii=False))
    finally:
        await app.close()


if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
