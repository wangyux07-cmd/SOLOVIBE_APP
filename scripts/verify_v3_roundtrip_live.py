"""Live, bounded Amap check of two independent walking routes and route geometry."""
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
import config  # noqa: F401 - load ignored local .env
from services.planning import AmapProvider


async def main():
    cohort = json.loads((ROOT / 'docs/v3_pilot_shanghai.json').read_text(encoding='utf-8'))
    baseline = json.loads((ROOT / 'docs/V3_PILOT_BASELINE_2026-10-13.json').read_text(encoding='utf-8'))
    row = next(row for row in baseline['rows'] if row['id'] == 'park_01')
    place = next(item for item in row['candidates'] if item['name'] == '徐家汇公园')
    maps = AmapProvider(os.getenv('AMAP_API_KEY', '').strip())
    try:
        await maps.detail({**place, 'source_url': place['source_url']})
        origin, destination = cohort['anchor_amap_coordinate'], place['coordinate']
        outbound = await maps.walking(origin, destination, place['poi_id'], geometry=True)
        returning = await maps.walking(destination, origin, origin_id=place['poi_id'], geometry=True)
    finally:
        await maps.close()
    report = {'provider': 'amap', 'place_id': place['poi_id'], 'place_name': place['name'],
              'outbound': {'minutes': outbound['walking_minutes'], 'meters': outbound['distance_meters'],
                           'polyline_points': len(outbound['polyline']), 'observed_at': outbound['observed_at']},
              'return': {'minutes': returning['walking_minutes'], 'meters': returning['distance_meters'],
                         'polyline_points': len(returning['polyline']), 'observed_at': returning['observed_at']},
              'example_dwell_minutes': 30, 'buffer_minutes': 10,
              'example_full_minutes': outbound['walking_minutes'] + 30 + returning['walking_minutes'] + 10}
    if min(report['outbound']['polyline_points'], report['return']['polyline_points']) < 2:
        raise RuntimeError('Amap did not return both road polylines')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
