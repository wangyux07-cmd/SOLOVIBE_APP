"""Bounded, deterministic multi-stop walking itinerary over verified Amap legs.

The winner is the shortest feasible route among permutations with the most
stops (up to three) in a small, explicitly bounded candidate set. It is not a
claim of a city-wide optimum or of live restaurant availability.
"""
import asyncio
from datetime import datetime
from itertools import permutations

from services.offer_policy import SHANGHAI_TZ
from services.planning import ProviderFailure, is_restaurant


def _clock(minutes):
    return f'{(minutes // 60) % 24:02d}:{minutes % 60:02d}'


def _departure(snapshot, now=None):
    current = (now or datetime.now(SHANGHAI_TZ)).astimezone(SHANGHAI_TZ)
    stated = snapshot.constraints.departure_time_local
    if stated:
        hour, minute = map(int, stated.split(':'))
        return hour * 60 + minute, 'user_local_clock'
    return current.hour * 60 + current.minute, 'current_local_clock'


def _sequence(snapshot, order, legs, departure_minute):
    """Return a feasible clock schedule, or None when hard time/walk limits fail."""
    c = snapshot.constraints
    elapsed = walking = waiting = 0
    stops = []
    for index, place in enumerate(order):
        previous = 'origin' if index == 0 else order[index - 1]['poi_id']
        route = legs.get((previous, place['poi_id']))
        if route is None:
            return None
        elapsed += route['walking_minutes']
        walking += route['walking_minutes']
        arrival = departure_minute + elapsed
        meal = is_restaurant(place) and c.meal_requirement == 'dinner'
        if meal:
            if arrival > 20 * 60 + 30:
                return None
            if arrival < 17 * 60:
                delay = 17 * 60 - arrival
                elapsed += delay
                waiting += delay
                arrival += delay
        dwell = 50 if meal else (c.desired_dwell_minutes or 25)
        stops.append({'place': place, 'arrival_local': _clock(arrival),
                      'dwell_minutes': dwell, 'route_from_previous': route,
                      'kind': 'dinner' if meal else 'visit'})
        elapsed += dwell
    last = legs.get((order[-1]['poi_id'], 'return'))
    if last is None:
        return None
    elapsed += last['walking_minutes'] + 10
    walking += last['walking_minutes']
    if elapsed > c.available_minutes or (c.max_walk_minutes is not None and walking > c.max_walk_minutes):
        return None
    return {'stops': stops, 'return_route': last, 'walking_minutes': walking,
            'waiting_minutes': waiting, 'total_minutes': elapsed,
            'dwell_minutes': sum(stop['dwell_minutes'] for stop in stops)}


async def build_one(planner, snapshot, candidates, evidence, plan_set_id, now=None):
    """Build exactly one evidence-backed itinerary; never invent a missing leg."""
    if not evidence.get('origin') or not evidence.get('return_destination'):
        return _empty(planner, snapshot, evidence, '出发点或返程终点无法核实，暂时不能生成多站路线。', plan_set_id)
    meal_required = snapshot.constraints.meal_requirement == 'dinner'
    attractions = [place for place in candidates if not is_restaurant(place)][:2 if meal_required else 3]
    restaurants = [place for place in candidates if is_restaurant(place)][:2]
    if meal_required and not restaurants:
        return _empty(planner, snapshot, evidence, '附近未找到有可核实路线的餐厅，不能满足晚餐要求。', plan_set_id)
    pool = attractions + (restaurants if meal_required else [])
    if len(pool) < 2 or (meal_required and not attractions):
        return _empty(planner, snapshot, evidence, '当前约束下不足两个可串联的真实地点。', plan_set_id)
    legs = {}
    for place in pool:
        if place.get('route'):
            legs[('origin', place['poi_id'])] = place['route']
        if place.get('return_route'):
            legs[(place['poi_id'], 'return')] = place['return_route']
    semaphore = asyncio.Semaphore(4)

    async def between(left, right):
        async with semaphore:
            try:
                route = await planner.maps.walking(left['coordinate'], right['coordinate'],
                    destination_id=right['poi_id'], origin_id=left['poi_id'], geometry=True)
                legs[(left['poi_id'], right['poi_id'])] = route
            except ProviderFailure:
                pass

    await asyncio.gather(*(between(left, right) for left in pool for right in pool
                           if left['poi_id'] != right['poi_id']))
    departure_minute, clock_basis = _departure(snapshot, now)
    best = None
    for count in (3, 2):
        for order in permutations(pool, count):
            if meal_required and (not is_restaurant(order[-1]) or
                                  any(is_restaurant(place) for place in order[:-1])):
                continue
            scheduled = _sequence(snapshot, order, legs, departure_minute)
            if not scheduled:
                continue
            score = (-count, scheduled['walking_minutes'], scheduled['total_minutes'],
                     tuple(place['poi_id'] for place in order))
            if best is None or score < best[0]:
                best = (score, order, scheduled)
    if best is None:
        return _empty(planner, snapshot, evidence,
            '候选地点存在，但没有一条已核实的多站步行路线同时满足总时间、总步行与晚餐时段。请调整条件。', plan_set_id)
    _, order, scheduled = best
    first = order[0]
    base = planner.publish(snapshot, [first], evidence, plan_set_id=plan_set_id)['plans'][0]
    stops = []
    journey_legs = []
    for index, stop in enumerate(scheduled['stops']):
        place = stop['place']
        source = '出发点' if index == 0 else order[index - 1]['name']
        route = stop['route_from_previous']
        journey_legs.append({'from_name': source, 'to_name': place['name'],
            'from_coordinate': evidence['origin']['coordinate'] if index == 0 else order[index - 1]['coordinate'],
            'to_coordinate': place['coordinate'], 'to_poi_id': place['poi_id'], 'route': route})
        stops.append({'order': index + 1, 'kind': stop['kind'],
            'place': {key: place[key] for key in ('provider', 'poi_id', 'name', 'address', 'city',
                'coordinate', 'category', 'source_url', 'observed_at')},
            'facts': place.get('facts'), 'arrival_local': stop['arrival_local'],
            'dwell_minutes': stop['dwell_minutes'], 'route_from_previous': route})
    return_destination = evidence['return_destination']
    journey_legs.append({'from_name': order[-1]['name'], 'to_name': '返程终点',
        'from_coordinate': order[-1]['coordinate'], 'to_coordinate': return_destination['coordinate'],
        'to_poi_id': None, 'route': scheduled['return_route']})
    restaurant = next((stop for stop in stops if stop['kind'] == 'dinner'), None)
    reservation = ({'status': 'unavailable', 'restaurant_poi_id': restaurant['place']['poi_id'],
        'entry_kind': 'place_detail', 'entry_url': restaurant['place']['source_url'],
        'provider_confirmation_id': None, 'reason': 'no_authorized_booking_provider'}
        if restaurant else None)
    base.update({'plan_id': f'itinerary:{plan_set_id}', 'itinerary': {
        'optimization': 'most_feasible_stops_then_shortest_verified_walk_in_bounded_candidates',
        'candidate_count': len(pool), 'departure_local': _clock(departure_minute),
        'clock_basis': clock_basis, 'meal_requirement': snapshot.constraints.meal_requirement,
        'stops': stops, 'legs': journey_legs,
        'reservation': reservation,
        'total_walk_minutes': scheduled['walking_minutes'],
        'total_wait_minutes': scheduled['waiting_minutes'],
        'total_minutes': scheduled['total_minutes']},
        'route': journey_legs[0]['route'], 'return_route': journey_legs[-1]['route'],
        'time_breakdown': {'outbound_minutes': journey_legs[0]['route']['walking_minutes'],
            'dwell_minutes': scheduled['dwell_minutes'],
            'return_minutes': journey_legs[-1]['route']['walking_minutes'],
            'buffer_minutes': 10, 'waiting_minutes': scheduled['waiting_minutes'],
            'walking_minutes': scheduled['walking_minutes'],
            'total_minutes': scheduled['total_minutes'], 'dwell_source': 'user_or_planning_estimate'},
        'feasibility': 'all_walking_legs_verified_time_and_walk_pass',
        'feasibility_checks': {**base['feasibility_checks'], 'full_activity_time': 'pass',
                               'total_walk': 'pass', 'dinner_window': 'pass' if meal_required else 'not_requested'},
        'tradeoff': (f'{len(stops)} 站，含{("晚餐" if meal_required else "景点")}；'
                     f'步行约 {scheduled["walking_minutes"]} 分钟，含停留和缓冲共约 '
                     f'{scheduled["total_minutes"]} 分钟。只在本次有路线证据的候选点内排序；'
                     '餐厅营业、席位与价格仍需核实。')})
    base['unknowns'] = [item for item in base['unknowns'] if item != '完整活动时长']
    return {'kind': 'itinerary_ready', 'response': f'已串联 {len(stops)} 个真实地点，形成一条有顺序的步行行程。每段可单独交给高德导航。',
            'missing_fields': [], 'plans': [base], 'evidence_status': evidence['status'],
            'provider_errors': evidence['errors']}


def _empty(planner, snapshot, evidence, message, plan_set_id):
    reply = planner.publish(snapshot, [], evidence, plan_set_id=plan_set_id)
    reply.update(kind='no_options', response=message, plans=[])
    return reply
