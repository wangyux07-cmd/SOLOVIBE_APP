"""Live V3-1 integration with a declared sample GPS input, not device location."""
import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import config  # noqa: F401 - loads ignored local .env
from services.application import Application


async def main():
    app = Application()
    await app.start()
    try:
        app.require_ready()
        owner, _ = await app.repo.session(None)
        thread = (await app.repo.create(owner))['thread_id']
        located = await app.set_browser_origin(owner, thread, str(uuid4()), 0,
                                                121.430000, 31.190000, 18)
        assert located['snapshot']['revision'] == 1
        message = ('预算80元，可用时间120分钟，最多步行30分钟，想去公园，'
                   '计划停留30分钟，返程回到原出发点，请规划。')
        result = await app.chat(owner, thread, str(uuid4()), message, 1)
        state = await app.repo.read(owner, thread)
        plans = state['plan_set']['plans'] if state['plan_set'] else []
        assert result['kind'] == 'options_ready' and plans, result['kind']
        selected = next((p for p in plans if p['feasibility_checks']['full_activity_time'] == 'pass'
                         and len(p['route'].get('polyline', [])) >= 2
                         and p.get('return_route') and len(p['return_route'].get('polyline', [])) >= 2), None)
        assert selected, 'no full-trip plan with two real provider polylines'
        assert selected['time_breakdown']['total_minutes'] == (
            selected['route']['walking_minutes'] + 30
            + selected['return_route']['walking_minutes'] + 10)
        assert selected['origin']['source'] == 'browser_gps'
        action = await app.prepare_action(owner, thread, str(uuid4()), state['plan_set']['plan_set_id'],
                                          selected['plan_id'], 'navigate', state['snapshot']['revision'])
        handoff = await app.decide_action(owner, action['action_id'], str(uuid4()),
                                          action['proposal_version'], action['proposal_digest'], True)
        assert handoff['status'] == 'completed'
        assert handoff['receipt']['kind'] == 'navigation_handoff_ready'
        pending = await app.prepare_action(owner, thread, str(uuid4()), state['plan_set']['plan_set_id'],
                                           selected['plan_id'], 'save', state['snapshot']['revision'])
        moved = await app.set_browser_origin(owner, thread, str(uuid4()),
                                              state['snapshot']['revision'],
                                              121.431000, 31.191000, 18)
        assert moved['snapshot']['revision'] == state['snapshot']['revision'] + 1
        assert (await app.repo.actions.get(owner, pending['action_id']))['status'] == 'invalidated'
        assert (await app.repo.read(owner, thread))['plan_set'] is None
        resumed = await app.chat(owner, thread, str(uuid4()), '请复述我当前的出行条件。',
                                 moved['snapshot']['revision'])
        assert resumed['kind'] == 'state_summary'
        print(json.dumps({'v3_stage1_verified': True, 'input': 'declared_sample_gps_not_device_location',
                          'resolved_city': located['origin']['city'], 'plans': len(plans),
                          'selected_place': selected['place']['name'],
                          'outbound_minutes': selected['route']['walking_minutes'],
                          'return_minutes': selected['return_route']['walking_minutes'],
                          'outbound_polyline_points': len(selected['route']['polyline']),
                          'return_polyline_points': len(selected['return_route']['polyline']),
                          'full_minutes': selected['time_breakdown']['total_minutes'],
                          'navigation_handoff': handoff['receipt']['kind'],
                          'old_action_invalidated_on_origin_change': True,
                          'chat_resumed_after_origin_change': True}, ensure_ascii=False))
    finally:
        await app.close()


if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
