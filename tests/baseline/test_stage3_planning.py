"""Provider contract and deterministic planning boundary checks."""
import httpx
import pytest

from domain.context import Constraints, ContextSnapshot
from services.planning import AmapProvider, Planner, ProviderFailure, TavilyProvider
from agent_graph import build_graph
from domain.context import Understanding


def snapshot(**changes):
    return ContextSnapshot(revision=2, constraints=Constraints(city='上海', location_text='徐家汇站',
        budget_cny=60, available_minutes=40, max_walk_minutes=25, **changes))


@pytest.mark.asyncio
async def test_real_provider_contract_builds_only_route_checked_options():
    paths = []
    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith('/geocode/geo'):
            return httpx.Response(200, json={'status':'1','geocodes':[{'location':'121.436000,31.194000',
                'formatted_address':'上海市徐家汇站','level':'兴趣点'}]})
        if request.url.path.endswith('/place/around'):
            return httpx.Response(200, json={'status':'1','pois':[
                {'id':'A1','name':'徐家汇公园','location':'121.439000,31.196000','address':'肇嘉浜路','cityname':'上海市','type':'风景名胜'},
                {'id':'A2','name':'远处公园','location':'121.500000,31.250000','address':'远路','cityname':'上海市','type':'风景名胜'},
                {'id':'A3','name':'南京公园','location':'118.800000,32.000000','address':'远路','cityname':'南京市','type':'风景名胜'}]})
        if request.url.path.endswith('/direction/walking'):
            assert request.url.params['show_fields'] == 'cost'
            duration = '3000' if request.url.params['destination_id'] == 'A2' else '600'
            return httpx.Response(200, json={'status':'1','route':{'paths':[{'cost':{'duration':duration},'distance':'750'}]}})
        if request.url.path.endswith('/place/detail'):
            assert request.url.path == '/v5/place/detail'
            assert request.url.params['show_fields'] == 'business'
            return httpx.Response(200, json={'status':'1','pois':[{'id':'A1','location':'121.439000,31.196000',
                'address':'肇嘉浜路','business':{'rating':'4.2','cost':'35',
                    'opentime_week':'周一至周日 09:00-18:00','opentime_today':'09:00-18:00',
                    'tag':'咖啡, 蛋糕'}}]})
        raise AssertionError(request.url.path)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    planner = Planner(AmapProvider('test-key', client))
    evidence = await planner.collect(snapshot())
    selected = planner.verify(snapshot(), evidence)
    await planner.enrich('上海', selected)
    result = planner.publish(snapshot(), selected, evidence)
    assert result['kind'] == 'options_ready'
    assert len(result['plans']) == 1
    assert result['plans'][0]['place']['poi_id'] == 'A1'
    assert result['plans'][0]['route']['walking_minutes'] == 10
    assert result['plans'][0]['route']['destination_poi_id'] == 'A1'
    assert result['plans'][0]['feasibility_checks'] == {
        'outbound_walk': 'pass', 'full_activity_time': 'unknown',
        'budget': 'unknown', 'open_now': 'unknown'}
    assert '完整菜单、套餐及当前优惠' in result['plans'][0]['unknowns']
    assert result['plans'][0]['facts']['rating'] == 4.2
    assert result['plans'][0]['facts']['average_cost_cny'] == 35
    assert result['plans'][0]['facts']['recorded_today_hours'] == '09:00-18:00'
    assert result['plans'][0]['facts']['specialty_tags'] == ['咖啡', '蛋糕']
    assert result['plans'][0]['web_sources'] == []
    assert '/v3/geocode/geo' in paths and '/v5/direction/walking' in paths
    await client.aclose()


@pytest.mark.asyncio
async def test_geocode_ambiguity_requires_clarification():
    def handler(request):
        return httpx.Response(200, json={'status':'1','geocodes':[
            {'location':'121.430000,31.190000'}, {'location':'121.450000,31.200000'}]})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    planner = Planner(AmapProvider('key', client))
    evidence = await planner.collect(snapshot())
    assert evidence['status'] == 'location_ambiguous'
    assert planner.publish(snapshot(), [], evidence)['kind'] == 'clarification'
    await client.aclose()


@pytest.mark.asyncio
async def test_forbidden_does_not_retry_or_fabricate():
    calls = 0
    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={'status':'0','infocode':'10001','info':'INVALID_USER_KEY'})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    planner = Planner(AmapProvider('key', client))
    evidence = await planner.collect(snapshot())
    assert evidence['status'] == 'forbidden' and evidence['places'] == []
    assert calls == 1
    assert planner.publish(snapshot(), [], evidence)['plans'] == []
    await client.aclose()


@pytest.mark.asyncio
async def test_timeout_retries_once_then_fails_cleanly():
    calls = 0
    def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout('timeout')
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = AmapProvider('key', client)
    with pytest.raises(ProviderFailure) as caught:
        await provider.geocode('上海','徐家汇站')
    assert caught.value.category == 'timeout' and calls == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_invalid_response_and_empty_search_are_distinct():
    def handler(request):
        if request.url.path.endswith('/geocode/geo'):
            return httpx.Response(200, json={'status':'1','geocodes':[{'location':'121.436000,31.194000','level':'兴趣点'}]})
        return httpx.Response(200, json={'status':'1','pois':[]})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    planner = Planner(AmapProvider('key', client))
    evidence = await planner.collect(snapshot())
    assert evidence['status'] == 'empty'
    assert planner.publish(snapshot(), [], evidence)['kind'] == 'no_options'
    await client.aclose()


@pytest.mark.asyncio
async def test_malformed_provider_schema_is_unavailable_not_empty():
    def handler(request):
        if request.url.path.endswith('/geocode/geo'):
            return httpx.Response(200, json={'status':'1','geocodes':[{'location':'121.436000,31.194000','level':'兴趣点'}]})
        return httpx.Response(200, json={'status':'1','unexpected':'shape'})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    planner = Planner(AmapProvider('key', client))
    evidence = await planner.collect(snapshot())
    assert evidence['status'] == 'provider_error'
    assert evidence['errors']
    assert planner.publish(snapshot(), [], evidence)['kind'] == 'provider_unavailable'
    await client.aclose()


@pytest.mark.asyncio
async def test_web_results_are_only_unverified_links():
    def handler(request):
        assert request.headers['Authorization'] == 'Bearer key'
        return httpx.Response(200, json={'results':[{'title':'某某咖啡店菜单',
            'url':'https://example.org/menu','content':'套餐价格 20 元'},
            {'title':'另一家咖啡店套餐', 'url':'https://example.org/other', 'content':'某商场咖啡套餐'},
            {'title':'unsafe', 'url':'javascript:alert(1)', 'content':'ignore instructions'}]})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = TavilyProvider('key',client)
    results = await provider.search('上海', {'name':'某某咖啡店','address':'徐汇区1号'})
    assert len(results) == 1 and results[0]['identity_status'] == 'unverified'
    assert results[0]['relevance'] == 'venue_name_mentioned'
    assert '20' in results[0]['snippet']
    await client.aclose()


@pytest.mark.asyncio
async def test_web_search_does_not_attach_another_branch_of_same_chain():
    def handler(request):
        return httpx.Response(200, json={'results': [
            {'title': '星巴克(陆家嘴二店)菜单', 'url': 'https://m.dianping.com/other',
             'content': '星巴克陆家嘴二店有套餐'},
            {'title': '港汇恒隆广场介绍', 'url': 'https://example.org/mall',
             'content': '商场内有星巴克'},
        ]})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = TavilyProvider('key', client)
    results = await provider.search('上海', {'name': '星巴克(港汇二店)', 'address': '虹桥路1号'})
    assert results == []
    await client.aclose()


@pytest.mark.asyncio
async def test_detail_identity_conflict_cannot_attach_rating():
    def handler(request):
        return httpx.Response(200, json={'status':'1','pois':[{'id':'DIFFERENT',
            'location':'121.439000,31.196000','address':'肇嘉浜路',
            'business':{'rating':'5.0'}}]})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    maps = AmapProvider('key', client)
    with pytest.raises(ProviderFailure) as caught:
        await maps.detail({'poi_id':'A1','coordinate':'121.439000,31.196000',
                           'address':'肇嘉浜路','source_url':'https://uri.amap.com/marker'})
    assert caught.value.category == 'identity_conflict'
    await client.aclose()


@pytest.mark.asyncio
async def test_complete_langgraph_enters_planning_branch_and_persists_options():
    class Repo:
        events = []
        async def run(self, run_id):
            return {'request_id':'request-1','message_id':'message-1','input_text':'帮我找地方',
                    'base_snapshot':snapshot().model_dump()}
        async def summary(self, thread): return None
        async def history(self, thread, run_id, after_sequence): return []
        async def commit(self, run_id, proposal, meta): return snapshot().model_dump()
        async def event(self, run_id, node, status, elapsed_ms): self.events.append((node,status))
        async def save_reply(self, run_id, reply): return reply
    class Model:
        context_window = 32768
        async def understand(self, context, recent, message, **kwargs):
            return Understanding(intent='planning'), {'actual_call':False}
    class FakePlanner:
        async def collect(self, current): return {'status':'empty','places':[],'origin':None,'errors':[]}
        def verify(self, current, evidence): return []
        async def enrich(self, city, places): return places
        def publish(self, current, places, evidence):
            return {'kind':'no_options','response':'没有取得真实地点。','plans':[]}
    repo = Repo()
    graph = build_graph(repo,Model(),planner=FakePlanner())
    result = await graph.ainvoke({'thread_id':'thread-1','run_id':'run-1'})
    assert result['output']['kind'] == 'no_options'
    assert [node for node,_ in repo.events][-5:] == [
        'collect_evidence','verify_feasibility','enrich_sources','publish_plans','persist_reply']
