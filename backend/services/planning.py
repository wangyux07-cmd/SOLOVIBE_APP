"""Read-only, evidence-first planning against Amap and optional web search.

Provider responses are untrusted observations. Only deterministic checks can
mark a route usable; missing cost, hours or web identity stay unknown.
"""
import asyncio
import math
import os
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from domain.context import ContextSnapshot


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


class AmapProvider:
    BASE = 'https://restapi.amap.com'

    def __init__(self, key: str, client: httpx.AsyncClient | None = None):
        self.key = key
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(5, connect=3))
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

    async def walking(self, origin, destination, destination_id):
        data = await self.get('/v5/direction/walking', {'origin': origin, 'destination': destination,
                                                         'destination_id': destination_id,
                                                         'show_fields': 'cost'})
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
        return {'walking_minutes': math.ceil(seconds / 60), 'distance_meters': meters,
                'provider': 'amap', 'observed_at': datetime.now(timezone.utc).isoformat()}

    async def detail(self, place):
        data = await self.get('/v3/place/detail', {'id': place['poi_id'], 'extensions': 'all'})
        pois = data.get('pois')
        if not isinstance(pois, list):
            raise ProviderFailure('invalid_response')
        if not pois or not isinstance(pois[0], dict):
            raise ProviderFailure('detail_not_found')
        item = pois[0]
        if scalar(item.get('id')) != place['poi_id'] or coordinate(item.get('location')) != place['coordinate']:
            raise ProviderFailure('identity_conflict')
        address = scalar(item.get('address'))
        if address and address != place['address']:
            raise ProviderFailure('identity_conflict')
        extension = item.get('biz_ext') if isinstance(item.get('biz_ext'), dict) else {}
        return {'provider': 'amap', 'observed_at': datetime.now(timezone.utc).isoformat(),
                'rating': decimal_fact(extension.get('rating'), 5),
                'average_cost_cny': decimal_fact(extension.get('cost'), 100000),
                'recorded_hours': scalar(extension.get('opentime2') or extension.get('open_time'))[:120] or None,
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
                         'identity_status': 'unverified', 'observed_at': datetime.now(timezone.utc).isoformat()}
                        for item in data['results'] if isinstance(item, dict)
                        and scalar(item.get('url')).startswith(('https://', 'http://'))][:3]
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
    def __init__(self, maps: AmapProvider, web: TavilyProvider | None = None):
        self.maps, self.web = maps, web

    async def collect(self, snapshot: ContextSnapshot):
        c = snapshot.constraints
        if not self.maps.key:
            return {'status': 'maps_not_configured', 'places': [], 'origin': None, 'errors': []}
        try:
            origin = await self.maps.geocode(c.city, c.location_text)
        except ProviderFailure as exc:
            return {'status': exc.category, 'places': [], 'origin': None, 'errors': [exc.category]}
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
        places = places[:8]
        semaphore = asyncio.Semaphore(4)
        async def route(place):
            async with semaphore:
                try:
                    place['route'] = await self.maps.walking(origin['coordinate'], place['coordinate'], place['poi_id'])
                except ProviderFailure as exc:
                    place['route_error'] = exc.category
        await asyncio.gather(*(route(place) for place in places))
        errors.extend(place['route_error'] for place in places if 'route_error' in place)
        status = ('ok' if any('route' in place for place in places) else
                  'route_unavailable' if places else 'provider_error' if errors else 'empty')
        return {'status': status,
                'origin': origin, 'places': places, 'errors': errors}

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
            if any(word and (word.casefold() in (place['name'] + place['category']).casefold()) for word in c.exclusions):
                continue
            accepted.append(place)
        accepted.sort(key=lambda item: (item['route']['walking_minutes'], item['poi_id']))
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

    async def enrich(self, city, selected):
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
            return selected
        semaphore = asyncio.Semaphore(2)
        async def one(place):
            async with semaphore:
                try:
                    place['web_sources'] = await self.web.search(city, place)
                    place['web_status'] = 'results_unverified' if place['web_sources'] else 'empty'
                except ProviderFailure as exc:
                    place['web_status'], place['web_sources'] = exc.category, []
        await asyncio.gather(*(one(place) for place in selected))
        return selected

    def publish(self, snapshot: ContextSnapshot, selected, evidence):
        plans = []
        for place in selected:
            route = place['route']
            plans.append({'plan_id': f'amap:{place["poi_id"]}', 'context_revision': snapshot.revision,
                          'place': {key: place[key] for key in ('provider', 'poi_id', 'name', 'address', 'city', 'coordinate', 'category', 'source_url', 'observed_at')},
                          'route': route, 'facts': place.get('facts'), 'detail_status': place.get('detail_status'),
                          'web_status': place['web_status'], 'web_sources': place['web_sources'],
                          'feasibility': 'route_verified_other_facts_unknown',
                          'unknowns': ['实际消费', '当前营业状态', '到店可用性'],
                          'tradeoff': f'步行约 {route["walking_minutes"]} 分钟，{route["distance_meters"]} 米；预算与营业情况尚需核实。'})
        if plans:
            response = f'找到 {len(plans)} 个真实地点，已核对从你提供的位置步行到达的路线。实际消费、营业时间和是否可进入仍未知，请查看来源后再决定。'
            kind = 'options_ready'
        elif evidence['status'] == 'maps_not_configured':
            response, kind = '地图服务尚未配置，暂时无法查询真实地点。请配置高德 Web 服务 Key 后重试。', 'provider_unavailable'
        elif evidence['status'] in {'location_not_found', 'location_ambiguous'}:
            response, kind = '当前位置无法唯一定位。请补充更具体的街道地址或地标名称。', 'clarification'
        elif evidence['status'] in {'forbidden', 'provider_error', 'timeout', 'network', 'temporary', 'invalid_response', 'invalid_request', 'route_unavailable'}:
            response, kind = '地图查询暂时失败，未生成地点方案。请检查服务状态后重试。', 'provider_unavailable'
        else:
            response, kind = '在当前地点、可用时间和步行限制下，未找到有路线证据的地点。可以补充偏好或调整约束后再试。', 'no_options'
        return {'kind': kind, 'response': response, 'missing_fields': [],
                'plans': plans, 'evidence_status': evidence['status'],
                'provider_errors': evidence['errors']}


def create_planner():
    from config import is_configured
    return Planner(AmapProvider(os.getenv('AMAP_API_KEY', '').strip() if is_configured('AMAP_API_KEY') else ''),
                   TavilyProvider(os.getenv('TAVILY_API_KEY', '').strip() if is_configured('TAVILY_API_KEY') else ''))
