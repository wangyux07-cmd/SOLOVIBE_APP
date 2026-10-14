"""Opt-in, repeatable real-Amap itinerary evaluation. No model or private logs.

Writes aggregate counts and per-scenario status/latency without addresses,
coordinates, POI names, keys or user messages. An empty result is a failure,
never a simulated success.
"""
import argparse
import asyncio
import json
import math
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
import config  # noqa: F401
from config import is_configured
from domain.context import Constraints, ContextSnapshot
from services.planning import AmapProvider, Planner, ProviderFailure


class MeasuredAmap(AmapProvider):
    def __init__(self, key):
        super().__init__(key)
        self.calls = Counter()
        self.failures = Counter()

    async def get(self, path, parameters):
        kind = path.split('/')[2] if len(path.split('/')) > 2 else path
        self.calls[kind] += 1
        try:
            return await super().get(path, parameters)
        except ProviderFailure as exc:
            self.failures[exc.category] += 1
            raise


def percentile(values, percent):
    if not values:
        return None
    ordered = sorted(values)
    # Nearest-rank: on a six-scenario run P95 is the slowest observation.
    return round(ordered[math.ceil(len(ordered) * percent) - 1], 1)


def itinerary_contract(itinerary, constraints):
    if not itinerary:
        return {'route_leg_count': 0, 'geometry_leg_count': 0,
                'hard_constraints_pass': False, 'dinner_in_window': False}
    stops = itinerary.get('stops', [])
    legs = itinerary.get('legs', [])
    verified = sum(1 for leg in legs if (
        leg.get('route', {}).get('provider') == 'amap'
        and leg['route'].get('origin_coordinate') == leg.get('from_coordinate')
        and leg['route'].get('destination_coordinate') == leg.get('to_coordinate')
        and leg['route'].get('distance_meters', 0) > 0
        and leg['route'].get('walking_minutes', 0) >= 0
        and leg['route'].get('observed_at')))
    geometry = sum(1 for leg in legs if len(leg.get('route', {}).get('polyline') or []) >= 2)
    dinner = constraints.meal_requirement != 'dinner' or bool(
        stops and stops[-1]['kind'] == 'dinner'
        and '17:00' <= stops[-1]['arrival_local'] <= '20:30')
    hard_pass = bool(2 <= len(stops) <= 3 and len(legs) == len(stops) + 1
                     and verified == len(legs) and geometry == len(legs)
                     and itinerary['total_minutes'] <= constraints.available_minutes
                     and (constraints.max_walk_minutes is None
                          or itinerary['total_walk_minutes'] <= constraints.max_walk_minutes)
                     and dinner)
    return {'route_leg_count': verified, 'geometry_leg_count': geometry,
            'hard_constraints_pass': hard_pass, 'dinner_in_window': dinner}


async def evaluate(scenarios, key):
    maps = MeasuredAmap(key)
    planner = Planner(maps)
    results = []
    try:
        for item in scenarios:
            started = time.monotonic()
            before = maps.calls.copy()
            failure_before = maps.failures.copy()
            snapshot = ContextSnapshot(constraints=Constraints.model_validate(
                {key: value for key, value in item.items() if key not in ('id', 'expected')}))
            try:
                evidence = await planner.collect(snapshot)
                vetted = planner.verify(snapshot, evidence, limit=6)
                enriched = await planner.enrich_basic(vetted)
                reply = await planner.build_itinerary(snapshot, enriched, evidence, plan_set_id=item['id'])
                plan = reply['plans'][0] if reply['plans'] else None
                itinerary = plan.get('itinerary') if plan else None
                contract = itinerary_contract(itinerary, snapshot.constraints)
                status = ('passed' if contract['hard_constraints_pass'] else
                          'contract_failed' if itinerary else 'no_itinerary')
                record = {'id': item['id'], 'status': status, 'evidence_status': evidence['status'],
                    'candidate_count': len(enriched), 'stop_count': len(itinerary['stops']) if itinerary else 0,
                    'leg_count': len(itinerary['legs']) if itinerary else 0,
                    **contract,
                    'walk_minutes': itinerary['total_walk_minutes'] if itinerary else None,
                    'total_minutes': itinerary['total_minutes'] if itinerary else None,
                    'dinner_satisfied': bool(itinerary and contract['dinner_in_window'])}
            except Exception as exc:
                record = {'id': item['id'], 'status': 'error', 'error_type': type(exc).__name__}
            record['latency_ms'] = round((time.monotonic() - started) * 1000)
            record['expected'] = item.get('expected', 'itinerary')
            record['outcome_match'] = record['status'] == record['expected']
            record['map_calls'] = sum((maps.calls - before).values())
            record['provider_failures'] = dict(maps.failures - failure_before)
            results.append(record)
            print(f"{record['id']}: {record['status']} stops={record.get('stop_count', 0)} "
                  f"latency_ms={record['latency_ms']} map_calls={record['map_calls']}")
    finally:
        await maps.close()
    latencies = [item['latency_ms'] for item in results]
    aggregate = {'run_at': datetime.now(timezone.utc).isoformat(), 'mode': 'real_amap_no_model',
        'scenario_count': len(results), 'itinerary_success_count': sum(item['status'] == 'passed' for item in results),
        'itinerary_success_rate': round(sum(item['status'] == 'passed' for item in results) / len(results), 3),
        'expected_outcome_match_count': sum(item['outcome_match'] for item in results),
        'p50_latency_ms': percentile(latencies, 0.5), 'p95_latency_ms': percentile(latencies, 0.95),
        'logical_map_calls': sum(item['map_calls'] for item in results),
        'provider_failures': dict(maps.failures), 'results': results}
    return aggregate


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=ROOT / 'eval' / 'itinerary_scenarios.json')
    parser.add_argument('--output', type=Path, default=ROOT / '.runtime' / 'evaluations' / 'itinerary-live.json')
    parser.add_argument('--limit', type=int, default=None)
    args = parser.parse_args()
    if not is_configured('AMAP_API_KEY'):
        raise SystemExit('AMAP_API_KEY is not configured; no live result was produced')
    dataset = json.loads(args.dataset.read_text(encoding='utf-8'))
    if isinstance(dataset, dict):
        defaults = dataset.get('defaults', {})
        scenarios = [{**defaults, **item} for item in dataset.get('scenarios', [])]
    else:
        scenarios = dataset
    if not isinstance(scenarios, list) or not scenarios:
        raise SystemExit('Dataset must contain at least one scenario')
    if len({item.get('id') for item in scenarios}) != len(scenarios):
        raise SystemExit('Scenario IDs must be unique')
    if args.limit is not None:
        scenarios = scenarios[:args.limit]
    import os
    report = await evaluate(scenarios, os.environ['AMAP_API_KEY'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"report={args.output} success={report['itinerary_success_count']}/{report['scenario_count']} "
          f"p95_latency_ms={report['p95_latency_ms']}")


if __name__ == '__main__':
    asyncio.run(main())
