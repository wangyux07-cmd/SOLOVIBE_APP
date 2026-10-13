"""Read-only, evidence-first planning against Amap and optional web search.

Provider responses are untrusted observations. Only deterministic checks can
mark a route usable; missing cost, hours or web identity stay unknown.
"""
import asyncio
import math
import os
import re
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from domain.context import ContextSnapshot
from services.offer_policy import SHANGHAI_TZ


def schedule_evidence(facts, now=None):
    """Amap hours are a recorded schedule; matching them is only an inference."""
    recorded = facts.get('recorded_today_hours') if facts else None
    result = {'kind': 'recorded_schedule' if recorded else 'unknown',
              'recorded_today_hours': recorded, 'inference': 'unknown',
              'open_now': 'unknown', 'observed_at': facts.get('observed_at') if facts else None}
    if not recorded:
        return result
    periods = re.fullmatch(r'\s*(\d{2}):(\d{2})-(\d{2}):(\d{2})\s*', recorded)
    if not periods:
        return result
    start_h, start_m, end_h, end_m = map(int, periods.groups())
    if max(start_h, end_h) > 23 or max(start_m, end_m) > 59:
        return result
    local = (now or datetime.now(timezone.utc)).astimezone(SHANGHAI_TZ)
    minute = local.hour * 60 + local.minute
    start, end = start_h * 60 + start_m, end_h * 60 + end_m
    if start == end:
        return result
    result['inference'] = ('possibly_within_recorded_hours' if
                           (start <= minute < end if end > start else minute >= start or minute < end)
                           else 'outside_recorded_hours')
    return result


class ProviderFailure(Exception):
    def __init__(self, category: str):
        self.category = category
        super().__init__(category)


def coordinate(value):
    if not isinstance(value, str):
        return None
    try:
        longitude, latitude = (float(part) for part in value.split(','))
    except (ValueError, TypeError):
        return None
    if not (73 <= longitude <= 135 and 18 <= latitude <= 54):
        return None
    return f'{longitude:.6f},{latitude:.6f}'


def scalar(value):
    return value.strip() if isinstance(value, str) else ''


def decimal_fact(value, maximum):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 1) if math.isfinite(number) and 0 < number <= maximum else None


def venue_mentioned(place, text):
    """A search hit is only a lead if it mentions this exact venue name.

    Matching a chain name or shopping mall alone is not enough to attach
    merchant claims to a particular branch.
    """
    name = re.sub(r'[^\w]', '', scalar(place.get('name')).casefold())
    content = re.sub(r'[^\w]', '', text.casefold())
    return len(name) >= 4 and name in content


def specialty_tags(value):
    """Amap POI tags are historical descriptors, not a live menu or offer."""
    if not isinstance(value, str):
        return []
    return [tag[:60] for tag in (part.strip() for part in re.split(r'[,，]', value)) if tag][:6]


def matches_specific_interest(place, interests):
    """Prevent keyword matches such as a shop named after a park from ranking as parks."""
    if len(interests) == 1 and '公园' in interests[0]:
        name = scalar(place.get('name'))
        category = scalar(place.get('category'))
        return name.endswith('公园') and (
            category == '公园' or category.startswith('风景名胜')
            or category.startswith('体育休闲服务'))
    return True


class AmapProvider:
    BASE = 'https://restapi.amap.com'

    def __init__(self, key: str, client: httpx.AsyncClient | None = None):
        self.key = key
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(8, connect=3))
        self.owns_client = client is None

    async def close(self):
        if self.owns_client:
            await self.client.aclose()

    async def get(self, path, parameters):
        if not self.key:
            raise ProviderFailure('not_configured')
        for attempt in range(2):
            try:
                response = await self.client.get(self.BASE + path, params={**parameters, 'key': self.key, 'output': 'json'})
                if response.status_code in (401, 403):
                    raise ProviderFailure('forbidden')
                if response.status_code == 429 or response.status_code >= 500:
                    raise ProviderFailure('temporary')
                if response.status_code >= 400:
                    raise ProviderFailure('invalid_request')
                data = response.json()
                if not isinstance(data, dict):
                    raise ProviderFailure('invalid_response')
                if str(data.get('status')) != '1':
                    code = str(data.get('infocode', '')) if isinstance(data, dict) else ''
                    if code in {'10001', '10002', '10003', '10006', '10007', '10008', '10009', '10010'}:
                        raise ProviderFailure('forbidden')
                    raise ProviderFailure('provider_error')
                return data
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                failure = ProviderFailure('timeout' if isinstance(exc, httpx.TimeoutException) else 'network')
            except (ValueError, TypeError):
                raise ProviderFailure('invalid_response') from None
            except ProviderFailure as exc:
                failure = exc
            if failure.category not in {'timeout', 'network', 'temporary'} or attempt:
                raise failure
            await asyncio.sleep(0.15)
        raise ProviderFailure('temporary')

    async def geocode(self, city, location):
        address = location if city in location else f'{city}{location}'
        data = await self.get('/v3/geocode/geo', {'city': city, 'address': address})
        if not isinstance(data.get('geocodes'), list):
            raise ProviderFailure('invalid_response')
        matches = []
        for item in data.get('geocodes', []):
            if not isinstance(item, dict):
                continue
            point = coordinate(item.get('location'))
            if point:
                matches.append({'coordinate': point, 'address': scalar(item.get('formatted_address')),
                                'level': scalar(item.get('level'))})
        distinct = {item['coordinate'] for item in matches}
        if not distinct:
            raise ProviderFailure('location_not_found')
        if len(distinct) != 1:
            raise ProviderFailure('location_ambiguous')
        if matches[0]['level'] in {'国家', '省', '市', '区县', '乡镇', '村庄', '未知', ''}:
            raise ProviderFailure('location_ambiguous')
        return matches[0]

    async def browser_location(self, longitude: float, latitude: float, accuracy_m: float):
        if not (73 <= longitude <= 135 and 18 <= latitude <= 54 and 0 <= accuracy_m <= 300):
            raise ProviderFailure('location_inaccurate')
        gps = f'{longitude:.6f},{latitude:.6f}'
        converted = await self.get('/v3/assistant/coordinate/convert',
                                   {'locations': gps, 'coordsys': 'gps'})
        point = coordinate(converted.get('locations'))
        if not point:
            raise ProviderFailure('invalid_response')
        data = await self.get('/v3/geocode/regeo', {'location': point, 'extensions': 'base'})
        record = data.get('regeocode')
        if not isinstance(record, dict):
            raise ProviderFailure('invalid_response')
        component = record.get('addressComponent')
        if not isinstance(component, dict):
            raise ProviderFailure('invalid_response')
        city = scalar(component.get('city')) or scalar(component.get('province'))
        address = scalar(record.get('formatted_address'))
        if not city or not address:
            raise ProviderFailure('location_not_found')
        return {'coordinate': point, 'address': address, 'city': city,
                'accuracy_m': accuracy_m, 'source': 'browser_gps',
                'observed_at': datetime.now(timezone.utc).isoformat()}

    async def search(self, city, point, keyword):
        data = await self.get('/v3/place/around', {'location': point, 'keywords': keyword,
                              'radius': 5000, 'sortrule': 'distance', 'offset': 10,
                              'page': 1, 'extensions': 'all'})
        if not isinstance(data.get('pois'), list):
            raise ProviderFailure('invalid_response')
        items = []
        for raw in data.get('pois', []):
            if not isinstance(raw, dict):
                continue
            place_id, name, location = scalar(raw.get('id')), scalar(raw.get('name')), coordinate(raw.get('location'))
            if not (place_id and name and location):
                continue
            address = scalar(raw.get('address'))
            if not address:
                continue
            city_name = scalar(raw.get('cityname'))
            if city_name and city not in city_name and city_name not in city:
                continue
            items.append({'provider': 'amap', 'poi_id': place_id, 'name': name,
                          'address': address, 'city': city_name or city,
                          'coordinate': location, 'category': scalar(raw.get('type')),
                          'source_url': f'https://uri.amap.com/marker?position={quote(location)}&name={quote(name)}',
                          'observed_at': datetime.now(timezone.utc).isoformat()})
        return items

    async def walking(self, origin, destination, destination_id=None, *, origin_id=None, geometry=False):
        parameters = {'origin': origin, 'destination': destination,
                      'show_fields': 'cost,polyline' if geometry else 'cost'}
        if destination_id:
            parameters['destination_id'] = destination_id
        if origin_id:
            parameters['origin_id'] = origin_id
        data = await self.get('/v5/direction/walking', parameters)
        if not isinstance(data.get('route'), dict) or not isinstance(data['route'].get('paths'), list):
            raise ProviderFailure('invalid_response')
        paths = data['route']['paths']
        if not paths or not isinstance(paths[0], dict):
            raise ProviderFailure('route_not_found')
        try:
            seconds = math.ceil(float(paths[0]['cost']['duration']))
            meters = math.ceil(float(paths[0]['distance']))
        except (KeyError, ValueError, TypeError, OverflowError):
            raise ProviderFailure('invalid_response') from None
        if seconds < 0 or meters < 0:
            raise ProviderFailure('invalid_response')
        points = []
        if geometry:
            steps = paths[0].get('steps')
            if isinstance(steps, list):
                too_many = False
                for step in steps:
                    if not isinstance(step, dict):
                        continue
                    for raw_point in scalar(step.get('polyline')).split(';'):
                        point = coordinate(raw_point)
                        if point and (not points or point != points[-1]):
                            points.append(point)
                        if len(points) > 1000:
                            too_many = True
                            break
                    if too_many:
                        break
                if too_many:
                    points = []
        return {'walking_minutes': math.ceil(seconds / 60), 'distance_meters': meters,
                'provider': 'amap', 'origin_coordinate': origin,
                'origin_poi_id': origin_id,
                'destination_coordinate': destination, 'destination_poi_id': destination_id,
                'polyline': points,
                'observed_at': datetime.now(timezone.utc).isoformat()}

    async def detail(self, place):
        data = await self.get('/v5/place/detail', {'id': place['poi_id'], 'show_fields': 'business'})
        pois = data.get('pois')
        if not isinstance(pois, list):
            raise ProviderFailure('invalid_response')
        if not pois or not isinstance(pois[0], dict):
            raise ProviderFailure('detail_not_found')
        item = pois[0]
        if (scalar(item.get('id')) != place['poi_id'] or
                coordinate(item.get('location')) != place['coordinate'] or
                (scalar(item.get('name')) and scalar(item.get('name')) != place['name'])):
            raise ProviderFailure('identity_conflict')
        address = scalar(item.get('address'))
        if address and address != place['address']:
            raise ProviderFailure('identity_conflict')
        business = item.get('business') if isinstance(item.get('business'), dict) else {}
        return {'provider': 'amap', 'observed_at': datetime.now(timezone.utc).isoformat(),
                'rating': decimal_fact(business.get('rating'), 5),
                'average_cost_cny': decimal_fact(business.get('cost'), 100000),
                'recorded_hours': scalar(business.get('opentime_week'))[:120] or None,
                'recorded_today_hours': scalar(business.get('opentime_today'))[:120] or None,
                'specialty_tags': specialty_tags(business.get('tag')),
                'source_url': place['source_url']}


class TavilyProvider:
    URL = 'https://api.tavily.com/search'

    def __init__(self, key: str, client: httpx.AsyncClient | None = None):
        self.key = key
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(6, connect=3))
        self.owns_client = client is None

    async def close(self):
        if self.owns_client:
            await self.client.aclose()

    async def search(self, city, place):
        if not self.key:
            return []
        for attempt in range(2):
            try:
                response = await self.client.post(self.URL, headers={'Authorization': f'Bearer {self.key}'},
                    json={'query': f'{city} {place["name"]} {place["address"]} 官方 营业时间 门票 菜单',
                          'search_depth': 'basic', 'max_results': 3, 'include_answer': False,
                          'include_raw_content': False})
                if response.status_code in (401, 403, 432, 433):
                    raise ProviderFailure('forbidden')
                if response.status_code == 429 or response.status_code >= 500:
                    raise ProviderFailure('temporary')
                if response.status_code >= 400:
                    raise ProviderFailure('invalid_request')
                data = response.json()
                if not isinstance(data, dict) or not isinstance(data.get('results'), list):
                    raise ProviderFailure('invalid_response')
                return [{'title': scalar(item.get('title'))[:160], 'url': scalar(item.get('url')),
                         'snippet': scalar(item.get('content'))[:500], 'provider': 'tavily',
                         'identity_status': 'unverified', 'relevance': 'venue_name_mentioned',
                         'observed_at': datetime.now(timezone.utc).isoformat()}
                        for item in data['results'] if isinstance(item, dict)
                        and scalar(item.get('url')).startswith('https://')
                        and venue_mentioned(place, scalar(item.get('title')) + ' ' + scalar(item.get('content')))][:3]
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                failure = ProviderFailure('timeout' if isinstance(exc, httpx.TimeoutException) else 'network')
            except (ValueError, TypeError):
                raise ProviderFailure('invalid_response') from None
            except ProviderFailure as exc:
                failure = exc
            if failure.category not in {'timeout', 'network', 'temporary'} or attempt:
                raise failure
            await asyncio.sleep(0.2)
        raise ProviderFailure('temporary')


class Planner:
    def __init__(self, maps: AmapProvider, web: TavilyProvider | None = None,
                 public=None, evidence_store=None):
        self.maps, self.web = maps, web
        self.public, self.evidence_store = public, evidence_store

    async def collect(self, snapshot: ContextSnapshot):
        c = snapshot.constraints
        if not self.maps.key:
            return {'status': 'maps_not_configured', 'places': [], 'origin': None,
                    'return_destination': None, 'errors': []}
        try:
            if c.origin_source == 'browser_gps' and c.origin_coordinate:
                try:
                    observed = datetime.fromisoformat(c.origin_observed_at or '')
                    age_seconds = (datetime.now(timezone.utc) - observed).total_seconds()
                except (ValueError, TypeError):
                    age_seconds = float('inf')
                if not 0 <= age_seconds <= 1800:
                    raise ProviderFailure('location_stale')
                origin = {'coordinate': c.origin_coordinate, 'address': c.location_text,
                          'source': 'browser_gps', 'accuracy_m': c.origin_accuracy_m,
                          'observed_at': c.origin_observed_at}
            else:
                origin = await self.maps.geocode(c.city, c.location_text)
                origin['source'] = 'manual_text'
        except ProviderFailure as exc:
            return {'status': exc.category, 'places': [], 'origin': None,
                    'return_destination': None, 'errors': [exc.category]}
        return_error = None
        if c.return_location_text:
            try:
                return_destination = await self.maps.geocode(c.city, c.return_location_text)
                return_destination['source'] = 'manual_text'
            except ProviderFailure as exc:
                return_destination, return_error = None, exc.category
        else:
            return_destination = origin
        keywords = [value.strip()[:40] for value in c.interests if value.strip()][:3] or ['公园', '博物馆', '咖啡馆']
        results = await asyncio.gather(*(self.maps.search(c.city, origin['coordinate'], word) for word in keywords),
                                       return_exceptions=True)
        errors, places = [], []
        seen = set()
        for result in results:
            if isinstance(result, Exception):
                errors.append(result.category if isinstance(result, ProviderFailure) else 'provider_error')
                continue
            for item in result:
                if item['poi_id'] not in seen:
                    seen.add(item['poi_id'])
                    places.append(item)
        if not places and not errors and c.interests:
            # One bounded broadening of a soft preference; never relax hard limits.
            broader = await asyncio.gather(*(self.maps.search(c.city, origin['coordinate'], word)
                                              for word in ('公园', '博物馆')), return_exceptions=True)
            for result in broader:
                if isinstance(result, Exception):
                    errors.append(result.category if isinstance(result, ProviderFailure) else 'provider_error')
                else:
                    for item in result:
                        if item['poi_id'] not in seen:
                            seen.add(item['poi_id'])
                            places.append(item)
        places = [place for place in places if matches_specific_interest(place, c.interests)][:6]
        semaphore = asyncio.Semaphore(2)
        async def route(place):
            async with semaphore:
                try:
                    place['route'] = await self.maps.walking(origin['coordinate'], place['coordinate'],
                                                              place['poi_id'], geometry=True)
                except ProviderFailure as exc:
                    place['route_error'] = exc.category
                if return_destination:
                    try:
                        place['return_route'] = await self.maps.walking(
                            place['coordinate'], return_destination['coordinate'],
                            origin_id=place['poi_id'], geometry=True)
                    except ProviderFailure as exc:
                        place['return_route_error'] = exc.category
        await asyncio.gather(*(route(place) for place in places))
        errors.extend(place['route_error'] for place in places if 'route_error' in place)
        errors.extend(place['return_route_error'] for place in places if 'return_route_error' in place)
        if return_error:
            errors.append(return_error)
        status = ('ok' if any('route' in place for place in places) else
                  'route_unavailable' if places else 'provider_error' if errors else 'empty')
        return {'status': status,
                'origin': origin, 'return_destination': return_destination,
                'return_error': return_error, 'places': places, 'errors': errors}

    def verify(self, snapshot: ContextSnapshot, evidence: dict):
        c = snapshot.constraints
        accepted = []
        for place in evidence['places']:
            route = place.get('route')
            if not route:
                continue
            if route['walking_minutes'] > c.available_minutes:
                continue
            if c.max_walk_minutes is not None and route['walking_minutes'] > c.max_walk_minutes:
                continue
            return_route = place.get('return_route')
            if (return_route and c.max_walk_minutes is not None
                    and return_route['walking_minutes'] > c.max_walk_minutes):
                continue
            if (return_route and c.desired_dwell_minutes is not None
                    and route['walking_minutes'] + c.desired_dwell_minutes
                    + return_route['walking_minutes'] + 10 > c.available_minutes):
                continue
            if any(word and (word.casefold() in (place['name'] + place['category']).casefold()) for word in c.exclusions):
                continue
            accepted.append(place)
        accepted.sort(key=lambda item: (
            c.desired_dwell_minutes is not None and not item.get('return_route'),
            item['route']['walking_minutes'], item['poi_id']))
        # Give the user different activities when the provider returned them.
        selected, seen_categories = [], set()
        for place in accepted:
            category = place['category'].split(';')[0]
            if category in seen_categories:
                continue
            selected.append(place)
            seen_categories.add(category)
            if len(selected) == 3:
                break
        if len(selected) < 3:
            selected.extend(item for item in accepted if item not in selected)
            selected = selected[:3]
        return selected

    async def enrich(self, city, selected, budget_cny=None):
        detail_limit = asyncio.Semaphore(3)
        async def detail_one(place):
            async with detail_limit:
                try:
                    place['facts'] = await self.maps.detail(place)
                    place['detail_status'] = 'matched'
                except ProviderFailure as exc:
                    place['facts'], place['detail_status'] = None, exc.category
        await asyncio.gather(*(detail_one(place) for place in selected))
        selected = [place for place in selected if place['detail_status'] != 'identity_conflict']
        if not self.web or not self.web.key:
            for place in selected:
                place['web_status'], place['web_sources'] = 'not_configured', []
        else:
            semaphore = asyncio.Semaphore(2)
            async def one(place):
                async with semaphore:
                    try:
                        place['web_sources'] = await self.web.search(city, place)
                        place['web_status'] = 'results_unverified' if place['web_sources'] else 'empty'
                    except ProviderFailure as exc:
                        place['web_status'], place['web_sources'] = exc.category, []
            await asyncio.gather(*(one(place) for place in selected))
        extraction_cache = {}
        for place in selected:
            place['public_info'] = {'status': 'no_official_source', 'sources': [],
                                    'brand_menu_items': [], 'branch_menu_items': [],
                                    'admission_prices': [], 'offers': []}
            if not self.public:
                continue
            try:
                information = await self.public.collect(place, extraction_cache)
                if self.evidence_store:
                    await self.evidence_store.persist(place, information)
                elif information['observations']:
                    information['status'] = 'persistence_unavailable'
                    information['brand_menu_items'] = []
                    information['branch_menu_items'] = []
                    information['admission_prices'] = []
                    information['offers'] = []
                now = datetime.now(timezone.utc)
                offers = [offer for offer in information['offers']
                          if datetime.fromisoformat(offer['valid_until']) > now]
                for offer in offers:
                    offer['budget_option'] = (
                        'within_limit' if budget_cny is not None and offer['price_cny'] <= budget_cny
                        else 'over_limit' if budget_cny is not None else 'unknown')
                place['public_info'] = {
                    'status': information['status'],
                    'sources': [{key: record[key] for key in ('observation_id','url','observed_at','scope',
                                'source_domain','extract_status','field_scope')}
                                for record in information['observations']],
                    'brand_menu_items': information['brand_menu_items'],
                    'branch_menu_items': information['branch_menu_items'],
                    'admission_prices': information['admission_prices']}
                place['public_info']['offers'] = offers
            except Exception:
                place['public_info']['status'] = 'pipeline_unavailable'
        if budget_cny is not None:
            selected.sort(key=lambda place: (
                0 if any(offer['budget_option'] == 'within_limit'
                         for offer in place['public_info']['offers']) else
                2 if place['public_info']['offers'] else 1))
        return selected

    def publish(self, snapshot: ContextSnapshot, selected, evidence):
        plans = []
        for place in selected:
            route = place['route']
            return_route = place.get('return_route')
            dwell = snapshot.constraints.desired_dwell_minutes
            full_minutes = (route['walking_minutes'] + dwell + return_route['walking_minutes'] + 10
                            if dwell is not None and return_route else None)
            full_status = ('pass' if full_minutes is not None and full_minutes <= snapshot.constraints.available_minutes
                           else 'fail' if full_minutes is not None else 'unknown')
            unknowns = ['实际消费', '当前营业状态', '到店可用性', '完整菜单、套餐及当前优惠']
            if full_status == 'unknown':
                unknowns.append('完整活动时长')
            facts = place.get('facts')
            public_info = place.get('public_info') or {}
            now = datetime.now(timezone.utc)
            offers = [offer for offer in public_info.get('offers', [])
                      if datetime.fromisoformat(offer['valid_until']) > now]
            if offers != public_info.get('offers', []):
                public_info = {**public_info, 'offers': offers}
            within_offer = any(offer['budget_option'] == 'within_limit' for offer in offers)
            budget_option = ('known_offer_within_limit' if within_offer else
                             'known_offer_over_limit' if offers and snapshot.constraints.budget_cny is not None
                             else 'unknown')
            plans.append({'plan_id': f'amap:{place["poi_id"]}', 'context_revision': snapshot.revision,
                          'evidence_contract_version': 1,
                          'place': {key: place[key] for key in ('provider', 'poi_id', 'name', 'address', 'city', 'coordinate', 'category', 'source_url', 'observed_at')},
                          'route': route, 'return_route': return_route,
                          'origin': evidence.get('origin'), 'return_destination': evidence.get('return_destination'),
                          'time_breakdown': {'outbound_minutes': route['walking_minutes'],
                                             'dwell_minutes': dwell,
                                             'return_minutes': return_route['walking_minutes'] if return_route else None,
                                             'buffer_minutes': 10, 'total_minutes': full_minutes,
                                             'dwell_source': 'user_selected' if dwell is not None else 'unknown'},
                          'facts': facts, 'detail_status': place.get('detail_status'),
                          'web_status': place['web_status'], 'web_sources': place['web_sources'],
                          'public_info': public_info,
                          'hours_evidence': schedule_evidence(facts),
                          'budget_option': budget_option,
                          'feasibility': 'outbound_route_verified_other_facts_unknown',
                          'feasibility_checks': {'outbound_walk': 'pass', 'full_activity_time': full_status,
                                                 'budget': 'unknown', 'open_now': 'unknown'},
                          'unknowns': unknowns,
                          'tradeoff': (f'去程 {route["walking_minutes"]} 分钟，返程 {return_route["walking_minutes"]} 分钟，'
                                       f'按计划停留 {dwell} 分钟并预留 10 分钟，总计约 {full_minutes} 分钟；预算与营业仍需核实。'
                                       if full_minutes is not None else
                                       f'去程步行约 {route["walking_minutes"]} 分钟，{route["distance_meters"]} 米；'
                                       '返程或停留时间尚未完整核实。')})
        if plans:
            response = f'找到 {len(plans)} 个真实地点，已查询去程和可用的返程路线。实际消费、营业时间和是否可进入仍未知，请查看来源后再决定。'
            kind = 'options_ready'
        elif evidence['status'] == 'maps_not_configured':
            response, kind = '地图服务尚未配置，暂时无法查询真实地点。请配置高德 Web 服务 Key 后重试。', 'provider_unavailable'
        elif evidence['status'] in {'location_not_found', 'location_ambiguous', 'location_stale'}:
            response, kind = ('之前的浏览器定位已过期，请重新点击“使用当前位置”或手动输入地标。'
                              if evidence['status'] == 'location_stale' else
                              '当前位置无法唯一定位。请补充更具体的街道地址或地标名称。'), 'clarification'
        elif evidence['status'] in {'forbidden', 'provider_error', 'timeout', 'network', 'temporary', 'invalid_response', 'invalid_request', 'route_unavailable'}:
            response, kind = '地图查询暂时失败，未生成地点方案。请检查服务状态后重试。', 'provider_unavailable'
        else:
            response, kind = '在当前地点、可用时间和步行限制下，未找到有路线证据的地点。可以补充偏好或调整约束后再试。', 'no_options'
        return {'kind': kind, 'response': response, 'missing_fields': [],
                'plans': plans, 'evidence_status': evidence['status'],
                'provider_errors': evidence['errors']}


def create_planner(evidence_store=None):
    from config import is_configured
    from services.public_sources import OfficialEvidenceService
    tavily_key = os.getenv('TAVILY_API_KEY', '').strip() if is_configured('TAVILY_API_KEY') else ''
    return Planner(AmapProvider(os.getenv('AMAP_API_KEY', '').strip() if is_configured('AMAP_API_KEY') else ''),
                   TavilyProvider(tavily_key), OfficialEvidenceService(tavily_key), evidence_store)
