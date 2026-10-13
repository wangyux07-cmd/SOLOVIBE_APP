import httpx
import pytest

from domain.context import Constraints, ContextSnapshot, FieldChange, Understanding, apply_patch
from services.planning import AmapProvider, Planner, ProviderFailure


@pytest.mark.asyncio
async def test_browser_location_converts_gps_and_reverses_address():
    seen = []
    def handler(request):
        seen.append(request.url.path)
        if request.url.path.endswith('/coordinate/convert'):
            assert request.url.params['coordsys'] == 'gps'
            return httpx.Response(200, json={'status': '1', 'locations': '121.436000,31.194000'})
        if request.url.path.endswith('/geocode/regeo'):
            assert request.url.params['location'] == '121.436000,31.194000'
            return httpx.Response(200, json={'status': '1', 'regeocode': {
                'formatted_address': '上海市徐汇区虹桥路1号',
                'addressComponent': {'city': [], 'province': '上海市'}}})
        raise AssertionError(request.url.path)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    maps = AmapProvider('key', client)
    result = await maps.browser_location(121.435, 31.193, 18)
    assert result['coordinate'] == '121.436000,31.194000'
    assert result['city'] == '上海市' and result['accuracy_m'] == 18
    assert seen == ['/v3/assistant/coordinate/convert', '/v3/geocode/regeo']
    with pytest.raises(ProviderFailure) as exc:
        await maps.browser_location(121.435, 31.193, 500)
    assert exc.value.category == 'location_inaccurate' and len(seen) == 2
    await client.aclose()


class Maps:
    key = 'key'
    def __init__(self, fail_return=False):
        self.fail_return = fail_return
        self.routes = []

    async def geocode(self, city, text):
        if text == '返程酒店' and self.fail_return:
            raise ProviderFailure('location_not_found')
        coordinate = '121.450000,31.200000' if text == '返程酒店' else '121.436000,31.194000'
        return {'coordinate': coordinate, 'address': text}

    async def search(self, city, point, keyword):
        return [{'provider': 'amap', 'poi_id': 'A1', 'name': '徐家汇公园',
                 'address': '肇嘉浜路', 'city': city, 'coordinate': '121.439000,31.196000',
                 'category': '公园', 'source_url': 'https://uri.amap.com/marker', 'observed_at': 'now'}]

    async def walking(self, origin, destination, destination_id=None, **kwargs):
        self.routes.append((origin, destination, destination_id, kwargs.get('origin_id')))
        minutes = 17 if origin == '121.439000,31.196000' else 10
        return {'walking_minutes': minutes, 'distance_meters': minutes * 80,
                'polyline': [origin, destination], 'observed_at': 'now'}

    async def detail(self, place):
        return {'rating': None, 'average_cost_cny': None}


@pytest.mark.asyncio
async def test_park_keyword_does_not_turn_a_shop_into_a_park():
    class MisleadingMaps(Maps):
        async def search(self, city, point, keyword):
            actual = await super().search(city, point, keyword)
            return [{'provider': 'amap', 'poi_id': 'SHOP', 'name': "foo'mart 東西公园(书院店)",
                     'address': '示例路', 'city': city, 'coordinate': '121.437000,31.194000',
                     'category': '风景名胜;公园广场;公园',
                     'source_url': 'https://uri.amap.com/marker', 'observed_at': 'now'}, *actual]
    maps = MisleadingMaps()
    evidence = await Planner(maps).collect(context())
    assert [place['poi_id'] for place in evidence['places']] == ['A1']
    assert len(maps.routes) == 2


def context(available=90, walk=20, return_text='返程酒店', dwell=45):
    return ContextSnapshot(constraints=Constraints(city='上海市', location_text='徐家汇站',
        budget_cny=80, available_minutes=available, max_walk_minutes=walk,
        return_location_text=return_text, desired_dwell_minutes=dwell,
        interests=['公园']))


@pytest.mark.asyncio
async def test_full_trip_uses_separate_asymmetric_routes_and_user_dwell():
    maps = Maps()
    planner = Planner(maps)
    snapshot = context()
    evidence = await planner.collect(snapshot)
    assert len(maps.routes) == 2
    assert maps.routes[0][0] != maps.routes[1][0]
    places = planner.verify(snapshot, evidence)
    await planner.enrich('上海市', places)
    plan = planner.publish(snapshot, places, evidence)['plans'][0]
    assert plan['return_route']['walking_minutes'] == 17
    assert plan['time_breakdown']['total_minutes'] == 82
    assert plan['feasibility_checks']['full_activity_time'] == 'pass'
    assert '完整活动时长' not in plan['unknowns']
    assert planner.verify(context(available=80), evidence) == []
    assert planner.verify(context(walk=15), evidence) == []


@pytest.mark.asyncio
async def test_missing_return_route_stays_unknown():
    maps = Maps(fail_return=True)
    planner = Planner(maps)
    snapshot = context()
    evidence = await planner.collect(snapshot)
    places = planner.verify(snapshot, evidence)
    await planner.enrich('上海市', places)
    plan = planner.publish(snapshot, places, evidence)['plans'][0]
    assert plan['return_route'] is None
    assert plan['feasibility_checks']['full_activity_time'] == 'unknown'
    assert '完整活动时长' in plan['unknowns']


def test_manual_location_edit_discards_old_browser_coordinates():
    initial = ContextSnapshot(revision=2, constraints=Constraints(city='上海市',
        location_text='上海市徐汇区虹桥路1号', origin_coordinate='121.436000,31.194000',
        origin_accuracy_m=18, origin_observed_at='2026-10-13T12:00:00+00:00',
        origin_source='browser_gps'))
    proposal = Understanding(intent='planning', changes=[FieldChange(
        field='location_text', value='徐家汇站', quote='现在在徐家汇站')])
    updated = apply_patch(initial, proposal, '现在在徐家汇站', 'message-1')
    assert updated.constraints.location_text == '徐家汇站'
    assert updated.constraints.origin_coordinate is None
    assert updated.constraints.origin_source is None


def test_dwell_requires_number_in_user_message():
    initial = context()
    changed = apply_patch(initial, Understanding(intent='planning', changes=[FieldChange(
        field='desired_dwell_minutes', value=30, quote='停留30分钟')]), '停留30分钟', 'message-1')
    assert changed.constraints.desired_dwell_minutes == 30
    with pytest.raises(Exception):
        apply_patch(initial, Understanding(intent='planning', changes=[FieldChange(
            field='desired_dwell_minutes', value=90, quote='停留30分钟')]), '停留30分钟', 'message-1')


@pytest.mark.asyncio
async def test_expired_browser_position_requires_refresh_before_provider_search():
    maps = Maps()
    planner = Planner(maps)
    snapshot = ContextSnapshot(constraints=Constraints(city='上海市',
        location_text='上海市徐汇区虹桥路1号', origin_coordinate='121.436000,31.194000',
        origin_accuracy_m=18, origin_observed_at='2020-01-01T00:00:00+00:00',
        origin_source='browser_gps', budget_cny=80, available_minutes=90))
    evidence = await planner.collect(snapshot)
    assert evidence['status'] == 'location_stale'
    assert evidence['places'] == [] and maps.routes == []
    assert planner.publish(snapshot, [], evidence)['kind'] == 'clarification'
