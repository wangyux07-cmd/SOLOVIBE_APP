"""Real DeepSeek/LangGraph/Amap/Tavily/PostgreSQL public-menu integration."""
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
    await app.start()
    try:
        app.require_ready()
        owner, _ = await app.repo.session(None)
        thread = (await app.repo.create(owner))['thread_id']
        await app.set_browser_origin(owner, thread, str(uuid4()), 0, 121.435, 31.193, 18)
        result = await app.chat(owner, thread, str(uuid4()),
            '预算80元，可用时间120分钟，最多步行30分钟，只想去星巴克喝咖啡，计划停留30分钟，请规划。', 1)
        state = await app.repo.read(owner, thread)
        plans = state['plan_set']['plans'] if state['plan_set'] else []
        matching = [plan for plan in plans if plan['place']['name'].startswith('星巴克')]
        evidenced = [plan for plan in matching if plan.get('public_info', {}).get('brand_menu_items')]
        if result['kind'] != 'options_ready' or not evidenced:
            raise RuntimeError('graph did not publish the sourced Starbucks menu')
        if any(plan['public_info']['branch_menu_items'] for plan in evidenced):
            raise RuntimeError('brand page was presented as branch menu')
        print(json.dumps({'verified': True, 'kind': result['kind'],
            'plans': len(plans), 'starbucks_plans': len(matching),
            'brand_menu_items': len(evidenced[0]['public_info']['brand_menu_items']),
            'branch_menu_items': len(evidenced[0]['public_info']['branch_menu_items']),
            'source_url': evidenced[0]['public_info']['sources'][0]['url']}, ensure_ascii=True))
    finally:
        await app.close()


if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
