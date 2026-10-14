"""Run a frozen ten-case map failure matrix without network or model calls."""
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

from domain.context import Constraints, ContextSnapshot
from services.planning import AmapProvider, Planner


CASES = {
    'geocode_http_403': 'forbidden',
    'geocode_http_429': 'temporary',
    'geocode_timeout': 'timeout',
    'geocode_bad_json': 'invalid_response',
    'geocode_empty': 'location_not_found',
    'geocode_ambiguous': 'location_ambiguous',
    'search_empty': 'empty',
    'search_http_403': 'provider_error',
    'walking_missing': 'route_unavailable',
    'walking_invalid': 'route_unavailable',
}


def response(mode, request):
    path = request.url.path
    if path.endswith('/geocode/geo'):
        if mode == 'geocode_http_403':
            return httpx.Response(403)
        if mode == 'geocode_http_429':
            return httpx.Response(429)
        if mode == 'geocode_timeout':
            raise httpx.ReadTimeout('injected timeout', request=request)
        if mode == 'geocode_bad_json':
            return httpx.Response(200, text='<html>not JSON</html>')
        if mode == 'geocode_empty':
            return httpx.Response(200, json={'status': '1', 'geocodes': []})
        matches = [{'location': '121.474539,31.229381',
                    'formatted_address': '上海市人民广场', 'level': '兴趣点'}]
        if mode == 'geocode_ambiguous':
            matches.append({'location': '121.480000,31.230000',
                            'formatted_address': '上海市人民广场附近', 'level': '兴趣点'})
        return httpx.Response(200, json={'status': '1', 'geocodes': matches})
    if path.endswith('/place/around'):
        if mode == 'search_http_403':
            return httpx.Response(403)
        if mode == 'search_empty':
            return httpx.Response(200, json={'status': '1', 'pois': []})
        return httpx.Response(200, json={'status': '1', 'pois': [
            {'id': 'PARK1', 'name': '人民公园', 'location': '121.472000,31.231000',
             'address': '南京西路231号', 'cityname': '上海市', 'type': '风景名胜;公园'},
            {'id': 'FOOD1', 'name': '人民餐厅', 'location': '121.477000,31.232000',
             'address': '西藏中路1号', 'cityname': '上海市', 'type': '餐饮服务;中餐厅'}]})
    if path.endswith('/direction/walking'):
        if mode == 'walking_missing':
            return httpx.Response(200, json={'status': '1', 'route': {'paths': []}})
        return httpx.Response(200, json={'status': '1', 'route': {}})
    raise AssertionError(f'unexpected path: {path}')


async def run_case(mode):
    transport = httpx.MockTransport(lambda request: response(mode, request))
    async with httpx.AsyncClient(transport=transport) as client:
        planner = Planner(AmapProvider('injected-test-key', client))
        snapshot = ContextSnapshot(constraints=Constraints(
            city='上海', location_text='人民广场', budget_cny=300,
            available_minutes=240, max_walk_minutes=90,
            departure_time_local='17:00', meal_requirement='dinner',
            interests=['公园']))
        started = time.monotonic()
        evidence = await planner.collect(snapshot)
        selected = planner.verify(snapshot, evidence, limit=6)
        reply = await planner.build_itinerary(snapshot, selected, evidence, plan_set_id=mode)
        return {'id': mode, 'expected_status': CASES[mode],
                'evidence_status': evidence['status'], 'errors': evidence['errors'],
                'published_plan_count': len(reply['plans']),
                'latency_ms': round((time.monotonic() - started) * 1000),
                'passed': evidence['status'] == CASES[mode] and not reply['plans']}


async def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'docs' / 'evidence' / 'formal-fault-matrix.json'
    rounds = []
    for index in range(1, 4):
        results = [await run_case(mode) for mode in CASES]
        rounds.append({'round': index, 'results': results})
        print(f'round={index} passed={sum(item["passed"] for item in results)}/10', flush=True)
    report = {'run_at': datetime.now(timezone.utc).isoformat(),
              'mode': 'deterministic_fault_injection_no_network_no_model',
              'case_count': len(CASES), 'round_count': len(rounds),
              'passed_count': sum(item['passed'] for round_data in rounds for item in round_data['results']),
              'rounds': rounds}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'report={output}', flush=True)
    if report['passed_count'] != len(CASES) * 3:
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(main())
