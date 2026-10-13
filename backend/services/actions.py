"""Deterministic action policy and map handoff. No booking or payment calls."""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from domain.errors import AppError
from services.planning import ProviderFailure, coordinate


async def revalidate(action, maps, public=None, merchant_live=None):
    if action['expires_at'] <= datetime.now(timezone.utc):
        return {'valid': False, 'reason': 'expired'}
    plan = action['plan_snapshot']
    context = action['context_snapshot']['constraints']
    advertised_live = plan.get('live_info')
    if advertised_live:
        from services.merchant_live import live_snapshot_current
        if not merchant_live:
            return {'valid': False, 'reason': 'merchant_source_unavailable'}
        try:
            result = await merchant_live.read(plan['place'])
        except Exception:
            result = None
        if not live_snapshot_current(advertised_live, result['info'] if result else None):
            return {'valid': False, 'reason': 'merchant_state_changed'}
    advertised = (plan.get('public_info') or {}).get('offers') or []
    if advertised:
        if not public:
            return {'valid': False, 'reason': 'offer_source_unavailable'}
        try:
            fresh = await public.collect(plan['place'])
        except Exception:
            return {'valid': False, 'reason': 'offer_source_unavailable'}
        if not isinstance(fresh, dict) or fresh.get('status') != 'success':
            return {'valid': False, 'reason': 'offer_source_unavailable'}
        now = datetime.now(timezone.utc)
        def identity(offer):
            return (offer['description'], offer['price_cny'], offer['terms'],
                    offer['applies_to'], offer['valid_until'], offer['source_url'])
        try:
            current = {identity(offer) for offer in fresh['offers']
                       if datetime.fromisoformat(offer['valid_until']) > now}
            if any(datetime.fromisoformat(offer['valid_until']) <= now for offer in advertised):
                return {'valid': False, 'reason': 'offer_expired'}
            if any(identity(offer) not in current for offer in advertised):
                return {'valid': False, 'reason': 'offer_changed'}
        except (KeyError, TypeError, ValueError):
            return {'valid': False, 'reason': 'offer_invalid'}
    if action['kind'] == 'save':
        return {'valid': True, 'reason': None}
    if plan.get('itinerary'):
        try:
            itinerary = plan['itinerary']
            stops = itinerary['stops']
            if not 2 <= len(stops) <= 3:
                return {'valid': False, 'reason': 'invalid_itinerary'}
            if context.get('origin_source') == 'browser_gps' and context.get('origin_coordinate'):
                observed = datetime.fromisoformat(context['origin_observed_at'])
                if datetime.now(timezone.utc) - observed > timedelta(minutes=30):
                    return {'valid': False, 'reason': 'origin_stale'}
                origin = {'coordinate': context['origin_coordinate']}
            else:
                origin = await maps.geocode(context['city'], context['location_text'])
            returning = (await maps.geocode(context['city'], context['return_location_text'])
                         if context.get('return_location_text') else origin)
            for stop in stops:
                await maps.detail(stop['place'])
            legs = {}
            segments = []
            previous = origin['coordinate']
            previous_id = 'origin'
            for stop in stops:
                place = stop['place']
                route = await maps.walking(previous, place['coordinate'],
                    destination_id=place['poi_id'],
                    origin_id=previous_id if previous_id != 'origin' else None,
                    geometry=True)
                legs[(previous_id, place['poi_id'])] = route
                segments.append({'from_coordinate': previous, 'to_coordinate': place['coordinate'],
                    'to_name': place['name'], 'route': route})
                previous, previous_id = place['coordinate'], place['poi_id']
            route = await maps.walking(previous, returning['coordinate'],
                                       origin_id=previous_id, geometry=True)
            legs[(previous_id, 'return')] = route
            segments.append({'from_coordinate': previous, 'to_coordinate': returning['coordinate'],
                             'to_name': '返程终点', 'route': route})
            from domain.context import ContextSnapshot
            from services.itinerary import _sequence
            current = ContextSnapshot.model_validate(action['context_snapshot'])
            hour, minute = map(int, itinerary['departure_local'].split(':'))
            scheduled = _sequence(current, [stop['place'] for stop in stops], legs, hour * 60 + minute)
            if not scheduled:
                return {'valid': False, 'reason': 'itinerary_constraints_changed'}
            return {'valid': True, 'origin': origin, 'route': segments[0]['route'],
                    'return_route': segments[-1]['route'], 'segments': segments}
        except (ProviderFailure, KeyError, TypeError, ValueError) as exc:
            return {'valid': False, 'reason': exc.category if isinstance(exc, ProviderFailure) else 'invalid_itinerary'}
    try:
        place = plan['place']
        if coordinate(place['coordinate']) != place['coordinate']:
            return {'valid': False, 'reason': 'invalid_coordinate'}
        await maps.detail(place)
        if context.get('origin_source') == 'browser_gps' and context.get('origin_coordinate'):
            observed = datetime.fromisoformat(context['origin_observed_at'])
            if datetime.now(timezone.utc) - observed > timedelta(minutes=30):
                return {'valid': False, 'reason': 'origin_stale'}
            origin = {'coordinate': context['origin_coordinate'],
                      'address': context['location_text'], 'source': 'browser_gps'}
        else:
            origin = await maps.geocode(context['city'], context['location_text'])
        route = await maps.walking(origin['coordinate'], place['coordinate'], place['poi_id'])
        return_destination = (await maps.geocode(context['city'], context['return_location_text'])
                              if context.get('return_location_text') else origin)
        return_route = await maps.walking(place['coordinate'], return_destination['coordinate'],
                                          origin_id=place['poi_id'])
    except (ProviderFailure, KeyError, TypeError, ValueError) as exc:
        return {'valid': False, 'reason': exc.category if isinstance(exc, ProviderFailure) else 'invalid_plan'}
    limit = context['available_minutes']
    walk_limit = context['max_walk_minutes']
    if (route['walking_minutes'] > limit or
            (walk_limit is not None and max(route['walking_minutes'], return_route['walking_minutes']) > walk_limit)):
        return {'valid': False, 'reason': 'route_exceeds_limit'}
    dwell = context.get('desired_dwell_minutes')
    if dwell is not None and route['walking_minutes'] + dwell + return_route['walking_minutes'] + 10 > limit:
        return {'valid': False, 'reason': 'full_trip_exceeds_limit'}
    return {'valid': True, 'origin': origin, 'route': route, 'return_route': return_route}


def navigation_receipt(action, evidence):
    if action['kind'] != 'navigate' or not evidence.get('valid'):
        raise AppError('ACTION_INVALID', '导航交接条件不足。')
    itinerary = action['plan_snapshot'].get('itinerary')
    if itinerary:
        segments = []
        for index, item in enumerate(evidence.get('segments', []), start=1):
            start, destination = item['from_coordinate'], item['to_coordinate']
            if not coordinate(start) or not coordinate(destination):
                raise AppError('ACTION_INVALID', '导航坐标无效。')
            segments.append({'order': index, 'to_name': item['to_name'],
                'url': 'https://uri.amap.com/navigation?' + urlencode({
                    'from': start, 'to': destination, 'mode': 'walk',
                    'src': 'solovibe', 'callnative': '0'}),
                'route': item['route']})
        if len(segments) != len(itinerary['stops']) + 1:
            raise AppError('ACTION_INVALID', '多站导航缺少路线段。')
        return {'kind': 'navigation_handoff_ready', 'url': segments[0]['url'],
                'segments': segments, 'provider': 'amap', 'place_name': '多站行程',
                'note': '请按顺序逐段打开高德；无法确认到站，也不会自动切换下一段。'}
    place = action['plan_snapshot']['place']
    start = evidence['origin']['coordinate']
    destination = place['coordinate']
    if not coordinate(start) or not coordinate(destination):
        raise AppError('ACTION_INVALID', '导航坐标无效。')
    url = 'https://uri.amap.com/navigation?' + urlencode({
        'from': start, 'to': destination, 'mode': 'walk',
        'src': 'solovibe', 'callnative': '0',
    })
    return {'kind': 'navigation_handoff_ready', 'url': url, 'provider': 'amap',
            'place_name': place['name'], 'route': evidence['route'],
            'note': '已生成高德步行导航链接；是否打开和实际出行由你决定。'}
