"""Multi-stop itinerary contracts: actual directed legs, meal window and no invention."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from domain.context import Constraints, ContextSnapshot
from services.actions import navigation_receipt, revalidate
from services.itinerary import build_one
from services.planning import Planner, ProviderFailure


STAMP = datetime.now(timezone.utc).isoformat()
ORIGIN = '121.390000,31.190000'


def place(poi_id, name, category, coordinate, outbound, returning):
    route = lambda minutes: {'walking_minutes': minutes, 'distance_meters': minutes * 75,
        'observed_at': STAMP, 'polyline': [ORIGIN, coordinate], 'provider': 'amap'}
    return {'provider': 'amap', 'poi_id': poi_id, 'name': name, 'category': category,
        'coordinate': coordinate, 'address': '测试路 1 号', 'city': '上海',
        'source_url': f'https://uri.amap.com/marker?name={name}', 'observed_at': STAMP,
        'route': route(outbound), 'return_route': route(returning),
        'facts': {'rating': 4.2, 'average_cost_cny': None, 'recorded_hours': None,
                  'recorded_today_hours': None, 'observed_at': STAMP},
        'web_status': 'empty', 'web_sources': [],
        'public_info': {'sources': [], 'offers': [], 'brand_menu_items': [],
                        'branch_menu_items': [], 'admission_prices': []}}


A = place('A', '公园', '风景名胜;公园', '121.400000,31.200000', 5, 15)
B = place('B', '博物馆', '科教文化服务;博物馆', '121.410000,31.200000', 15, 15)
R = place('R', '晚餐餐厅', '餐饮服务;中餐厅', '121.420000,31.200000', 25, 15)
LOOKUP = {item['coordinate']: item for item in (A, B, R)}


class Maps:
    minutes = {('origin', 'A'): 5, ('origin', 'B'): 15, ('origin', 'R'): 25,
               ('A', 'return'): 15, ('B', 'return'): 15, ('R', 'return'): 15,
               ('A', 'B'): 6, ('B', 'A'): 20,
               ('A', 'R'): 12, ('B', 'R'): 5,
               ('R', 'A'): 22, ('R', 'B'): 25}

    async def walking(self, origin, destination, destination_id=None, *, origin_id=None, geometry=False):
        left = origin_id or ('origin' if origin == ORIGIN else LOOKUP[origin]['poi_id'])
        right = destination_id or ('return' if destination == ORIGIN else LOOKUP[destination]['poi_id'])
        minutes = self.minutes.get((left, right))
        if minutes is None:
            raise ProviderFailure('route_not_found')
        return {'walking_minutes': minutes, 'distance_meters': minutes * 75,
                'observed_at': STAMP, 'polyline': [origin, destination], 'provider': 'amap'}

    async def detail(self, item):
        return next(place['facts'] for place in (A, B, R) if place['poi_id'] == item['poi_id'])

    async def geocode(self, city, location):
        return {'coordinate': ORIGIN, 'address': location}


def context(**changes):
    values = {'city': '上海', 'location_text': '徐家汇站', 'budget_cny': 150,
              'available_minutes': 180, 'max_walk_minutes': 70,
              'departure_time_local': '17:00', 'meal_requirement': 'dinner'}
    values.update(changes)
    return ContextSnapshot(revision=2, constraints=Constraints(**values))


def evidence():
    return {'status': 'ok', 'origin': {'coordinate': ORIGIN, 'address': '徐家汇站'},
            'return_destination': {'coordinate': ORIGIN, 'address': '徐家汇站'},
            'errors': []}


@pytest.mark.asyncio
async def test_dinner_itinerary_orders_three_real_stops_and_every_leg():
    result = await build_one(Planner(Maps()), context(), [A, B, R], evidence(), 'run-1')
    assert result['kind'] == 'itinerary_ready'
    assert len(result['plans']) == 1
    itinerary = result['plans'][0]['itinerary']
    assert [stop['place']['poi_id'] for stop in itinerary['stops']] == ['A', 'B', 'R']
    assert [leg['route']['walking_minutes'] for leg in itinerary['legs']] == [5, 6, 5, 15]
    assert itinerary['total_walk_minutes'] == 31
    assert itinerary['total_minutes'] <= 180
    assert itinerary['stops'][-1]['arrival_local'] >= '17:00'
    assert itinerary['reservation'] == {
        'status': 'unavailable', 'restaurant_poi_id': 'R',
        'entry_kind': 'place_detail', 'entry_url': R['source_url'],
        'provider_confirmation_id': None, 'reason': 'no_authorized_booking_provider'}


@pytest.mark.asyncio
async def test_hard_limits_and_missing_meal_route_never_create_fabricated_plan():
    planner = Planner(Maps())
    short = await build_one(planner, context(available_minutes=80), [A, B, R], evidence(), 'short')
    assert short['plans'] == []
    class MissingMealLeg(Maps):
        minutes = {key: minutes for key, minutes in Maps.minutes.items() if key[1] != 'R'}
    missing = await build_one(Planner(MissingMealLeg()), context(), [A, B, R], evidence(), 'missing')
    assert missing['plans'] == []


@pytest.mark.asyncio
async def test_known_over_budget_restaurant_is_not_selected_for_dinner():
    cheap = deepcopy(A)
    cheap['name'] = '平价餐厅'
    cheap['category'] = '餐饮服务;中餐厅'
    cheap['facts']['average_cost_cny'] = 60
    expensive = deepcopy(R)
    expensive['facts']['average_cost_cny'] = 2557
    result = await build_one(Planner(Maps()), context(), [B, cheap, expensive], evidence(), 'budget')
    assert result['kind'] == 'itinerary_ready'
    assert [stop['place']['poi_id'] for stop in result['plans'][0]['itinerary']['stops']] == ['B', 'A']

    no_meal = await build_one(Planner(Maps()), context(), [B, expensive], evidence(), 'budget-fail')
    assert no_meal['plans'] == []


@pytest.mark.asyncio
async def test_navigation_revalidates_all_stops_and_returns_one_handoff_per_leg():
    maps = Maps()
    plan = (await build_one(Planner(maps), context(), [A, B, R], evidence(), 'run-1'))['plans'][0]
    action = {'kind': 'navigate', 'expires_at': datetime.now(timezone.utc).replace(year=2099),
              'plan_snapshot': plan, 'context_snapshot': context().model_dump()}
    checked = await revalidate(action, maps)
    assert checked['valid'] is True
    receipt = navigation_receipt(action, checked)
    assert len(receipt['segments']) == 4
    assert all(segment['url'].startswith('https://uri.amap.com/navigation?')
               for segment in receipt['segments'])
