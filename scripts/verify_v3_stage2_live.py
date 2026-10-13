"""Real Tavily Extract + PostgreSQL evidence write for the fixed Starbucks pilot."""
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
import config  # noqa: F401 - loads ignored local credentials
from persistence.public_evidence import PublicEvidenceRepository
from services.application import database_dsn, make_pool
from services.public_sources import OfficialEvidenceService


async def main():
    baseline = json.loads((ROOT / 'docs/V3_PILOT_BASELINE_2026-10-13.json').read_text(encoding='utf-8'))
    row = next(row for row in baseline['rows'] if row['id'] == 'cafe_01')
    candidate = row['candidates'][0]
    place = {**candidate, 'city': '上海市'}
    service = OfficialEvidenceService(os.getenv('TAVILY_API_KEY', '').strip())
    pool = make_pool(database_dsn())
    try:
        information = await service.collect(place)
        if information['status'] != 'success' or not information['brand_menu_items']:
            raise RuntimeError('official brand menu was not extracted')
        if information['branch_menu_items'] or any(item['price_cny'] is not None
                                                   for item in information['brand_menu_items']):
            raise RuntimeError('brand page was promoted to branch availability or price')
        async with pool:
            await PublicEvidenceRepository(pool).persist(place, information)
            observation_id = information['observations'][0]['observation_id']
            async with pool.connection() as conn:
                stored = await (await conn.execute('''SELECT scope,outcome,source_domain,
                    extract_status,field_scope,content_length,length(evidence_excerpt) AS excerpt_length
                    FROM solovibe_v1.source_observation WHERE observation_id=%s''',
                    (observation_id,))).fetchone()
                claims = await (await conn.execute('''SELECT field,scope,status,value
                    FROM solovibe_v1.venue_claim WHERE observation_id=%s''',
                    (observation_id,))).fetchall()
        if not stored or stored['scope'] != 'brand' or stored['outcome'] != 'success':
            raise RuntimeError('observation was not stored as brand evidence')
        if not claims or any(item['scope'] != 'brand' or item['value'].get('price_cny') is not None
                             for item in claims):
            raise RuntimeError('persisted claims were not brand-scoped and unpriced')
        report = {'verified': True, 'sample_id': 'cafe_01', 'amap_poi_id': place['poi_id'],
                  'source_url': information['observations'][0]['url'],
                  'source_domain': stored['source_domain'], 'extract_status': stored['extract_status'],
                  'content_length': stored['content_length'],
                  'stored_excerpt_length': stored['excerpt_length'],
                  'brand_menu_items': len(information['brand_menu_items']),
                  'branch_menu_items': len(information['branch_menu_items']),
                  'priced_claims': sum(item['value'].get('price_cny') is not None for item in claims)}
        pilot_rows = []
        for pilot in baseline['rows']:
            candidate = pilot['candidates'][0] if pilot['candidates'] else None
            approved = bool(candidate and service.discover(candidate))
            pilot_rows.append({'id': pilot['id'], 'amap_outcome': pilot['outcome'],
                'candidate_count': len(pilot['candidates']),
                'official_source_status': ('brand_menu_extracted' if pilot['id'] == 'cafe_01' else
                                           'not_attempted_no_approved_source' if not approved else
                                           'not_attempted'),
                'branch_menu_or_price_verified': False})
        coverage = {'cohort_version': baseline['cohort_version'],
            'sample_count': len(pilot_rows), 'brand_menu_extracted': 1,
            'branch_menu_or_price_verified': 0,
            'branch_acceptance_target': 3, 'rows': pilot_rows}
        (ROOT / 'docs/V3_STAGE2_PILOT_RESULTS_2026-10-13.json').write_text(
            json.dumps(coverage, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, ensure_ascii=True))
    finally:
        await service.close()


if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
