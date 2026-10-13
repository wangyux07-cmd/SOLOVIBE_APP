"""Deterministic action policy and map handoff. No booking or payment calls."""
from datetime import datetime, timezone
from urllib.parse import urlencode

from domain.errors import AppError
from services.planning import ProviderFailure, coordinate


async def revalidate(action, maps):
    if action['expires_at'] <= datetime.now(timezone.utc):
        return {'valid': False, 'reason': 'expired'}
    plan = action['plan_snapshot']
    context = action['context_snapshot']['constraints']
    if action['kind'] == 'save':
        return {'valid': True, 'reason': None}
    try:
        place = plan['place']
        if coordinate(place['coordinate']) != place['coordinate']:
            return {'valid': False, 'reason': 'invalid_coordinate'}
        await maps.detail(place)
        origin = await maps.geocode(context['city'], context['location_text'])
        route = await maps.walking(origin['coordinate'], place['coordinate'], place['poi_id'])
    except (ProviderFailure, KeyError, TypeError) as exc:
        return {'valid': False, 'reason': exc.category if isinstance(exc, ProviderFailure) else 'invalid_plan'}
    limit = context['available_minutes']
    walk_limit = context['max_walk_minutes']
    if route['walking_minutes'] > limit or (walk_limit is not None and route['walking_minutes'] > walk_limit):
        return {'valid': False, 'reason': 'route_exceeds_limit'}
    return {'valid': True, 'origin': origin, 'route': route}


def navigation_receipt(action, evidence):
    if action['kind'] != 'navigate' or not evidence.get('valid'):
        raise AppError('ACTION_INVALID', '导航交接条件不足。')
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
