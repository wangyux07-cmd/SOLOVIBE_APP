import httpx
import pytest

from services.public_sources import OfficialEvidenceService, approved_url, parse_menu


PLACE = {'poi_id': 'A1', 'name': '星巴克(港汇恒隆广场店)',
         'address': '虹桥路1号', 'city': '上海市', 'coordinate': '121.436000,31.194000'}
OFFICIAL = 'https://www.starbucks.com.cn/menu/food/great-breakfast/'


def client_for(result, status=200):
    return httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(status, json=result)))


@pytest.mark.asyncio
async def test_official_brand_menu_is_real_evidence_but_not_branch_availability():
    content = '# 早安新一天\n### 谷物组合希腊式风味酸奶 Granola & Greek Flavored Yoghurt\n简介\n星巴克(港汇恒隆广场店) 虹桥路1号'
    client = client_for({'results': [{'url': OFFICIAL, 'raw_content': content}], 'failed_results': []})
    service = OfficialEvidenceService('key', client)
    result = await service.collect(PLACE)
    assert result['status'] == 'success'
    assert [item['name'] for item in result['brand_menu_items']] == ['谷物组合希腊式风味酸奶']
    assert result['branch_menu_items'] == []
    assert result['brand_menu_items'][0]['price_cny'] is None
    assert result['observations'][0]['scope'] == 'brand'
    assert result['observations'][0]['content_length'] == len(content)
    assert result['observations'][0]['content_sha256']
    assert content not in repr(result)
    await client.aclose()


@pytest.mark.asyncio
async def test_http_200_single_url_failure_is_not_a_success():
    client = client_for({'results': [], 'failed_results': [{'url': OFFICIAL, 'error': 'blocked'}]})
    service = OfficialEvidenceService('key', client)
    result = await service.collect(PLACE)
    assert result['status'] == 'extract_failed'
    assert result['observations'][0]['outcome'] == 'empty'
    assert result['claims'] == []
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(('status', 'expected'), [(403, 'forbidden'), (429, 'temporary')])
async def test_http_failure_never_produces_claims(status, expected):
    client = client_for({}, status)
    result = await OfficialEvidenceService('key', client).collect(PLACE)
    assert result['status'] == expected and result['claims'] == []
    await client.aclose()


@pytest.mark.asyncio
async def test_timeout_never_produces_claims():
    def timeout(request):
        raise httpx.ReadTimeout('timeout', request=request)
    client = httpx.AsyncClient(transport=httpx.MockTransport(timeout))
    result = await OfficialEvidenceService('key', client).collect(PLACE)
    assert result['status'] == 'timeout' and result['claims'] == []
    await client.aclose()


@pytest.mark.asyncio
async def test_wrong_branch_does_not_produce_branch_menu_claim():
    url = 'https://official.example/menu'
    catalog = ({'brand': '样例', 'hosts': ('official.example',), 'urls': (url,),
                'field_scope': 'menu_item', 'category': 'food', 'requires_branch': True,
                'branch_poi_id': 'A1'},)
    place = {**PLACE, 'name': '样例(虹桥路店)'}
    text = '样例(南京路店) 南京路20号\n### 拿铁 ￥28元'
    client = client_for({'results': [{'url': url, 'raw_content': text}], 'failed_results': []})
    result = await OfficialEvidenceService('key', client, catalog).collect(place)
    assert result['status'] == 'identity_conflict'
    assert result['observations'][0]['outcome'] == 'identity_conflict'
    assert result['claims'] == [] and result['branch_menu_items'] == []
    await client.aclose()


@pytest.mark.asyncio
async def test_conflicting_official_prices_degrade_both_claims():
    first, second = 'https://official.example/one', 'https://official.example/two'
    catalog = ({'brand': '样例', 'hosts': ('official.example',), 'urls': (first, second),
                'field_scope': 'menu_item', 'category': 'food', 'requires_branch': True,
                'branch_poi_id': 'A1'},)
    place = {**PLACE, 'name': '样例(虹桥路店)'}
    def handler(request):
        price = 28 if str(request.url).endswith('extract') and request.content.find(b'one') >= 0 else 32
        url = first if price == 28 else second
        return httpx.Response(200, json={'results': [{'url': url, 'raw_content':
            f'样例(虹桥路店) 虹桥路1号\n### 拿铁 ￥{price}元'}], 'failed_results': []})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await OfficialEvidenceService('key', client, catalog).collect(place)
    assert result['status'] == 'conflict'
    assert len(result['branch_menu_items']) == 2
    assert all(item['price_cny'] is None for item in result['branch_menu_items'])
    assert all(claim['status'] == 'conflict' for claim in result['claims'])
    await client.aclose()


@pytest.mark.asyncio
async def test_attraction_price_requires_explicit_page_price_and_branch_identity():
    url = 'https://museum.example/tickets'
    catalog = ({'brand': '样例博物馆', 'hosts': ('museum.example',), 'urls': (url,),
                'field_scope': 'ticket_price', 'category': 'attraction', 'requires_branch': True,
                'branch_poi_id': 'A1'},)
    place = {**PLACE, 'name': '样例博物馆'}
    content = '样例博物馆 虹桥路1号\n门票 成人票 ￥60元\n营业中'
    client = client_for({'results': [{'url': url, 'raw_content': content}], 'failed_results': []})
    result = await OfficialEvidenceService('key', client, catalog).collect(place)
    assert result['admission_prices'][0]['price_cny'] == 60
    assert result['admission_prices'][0]['scope'] == 'branch'
    assert not any(claim['field'] in {'open_now', 'availability'} for claim in result['claims'])
    await client.aclose()


@pytest.mark.asyncio
async def test_removed_price_does_not_reuse_an_earlier_value():
    url = 'https://official.example/menu'
    catalog = ({'brand': '样例', 'hosts': ('official.example',), 'urls': (url,),
                'field_scope': 'menu_item', 'category': 'food', 'requires_branch': True,
                'branch_poi_id': 'A1'},)
    place = {**PLACE, 'name': '样例(虹桥路店)'}
    pages = ['样例(虹桥路店) 虹桥路1号\n### 拿铁 ￥28元',
             '样例(虹桥路店) 虹桥路1号\n### 拿铁']
    def handler(request):
        return httpx.Response(200, json={'results': [{'url': url, 'raw_content': pages.pop(0)}],
                                          'failed_results': []})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = OfficialEvidenceService('key', client, catalog)
    earlier = await service.collect(place)
    current = await service.collect(place)
    assert earlier['branch_menu_items'][0]['price_cny'] == 28
    assert current['branch_menu_items'][0]['price_cny'] is None
    assert current['claims'][0]['value']['price_cny'] is None
    await client.aclose()


@pytest.mark.asyncio
async def test_same_official_page_is_fetched_once_per_planning_turn():
    calls = 0
    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={'results': [{'url': OFFICIAL,
            'raw_content': '### 谷物酸奶\n品牌菜单'}], 'failed_results': []})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = OfficialEvidenceService('key', client)
    shared = {}
    first = await service.collect(PLACE, shared)
    second = await service.collect({**PLACE, 'poi_id': 'A2', 'name': '星巴克(另一店)'}, shared)
    assert calls == 1
    assert first['claims'][0]['amap_poi_id'] == 'A1'
    assert second['claims'][0]['amap_poi_id'] == 'A2'
    assert first['claims'][0]['scope'] == second['claims'][0]['scope'] == 'brand'
    await client.aclose()


def test_unapproved_url_never_reaches_extractor():
    assert approved_url(OFFICIAL, ('starbucks.com.cn',)) is False  # subdomains need explicit allowlisting
    assert approved_url(OFFICIAL, ('www.starbucks.com.cn',)) is True
    assert not approved_url('https://www.starbucks.com.cn.evil.test/x', ('www.starbucks.com.cn',))
    assert not approved_url('https://127.0.0.1/menu', ('127.0.0.1',))
    assert not approved_url('https://www.starbucks.com.cn:bad/menu', ('www.starbucks.com.cn',))


def test_region_exclusions_are_not_shown_as_local_menu_examples():
    content = ('### 高达芝士香肠肉可颂堡\n仅在北京、广州和深圳售卖。\n'
               '### 美式松饼\n江浙沪地区门店不售卖。\n'
               '### 谷物酸奶\n部分城市有售。')
    assert [item.name for item in parse_menu(content, 'food', '上海市')] == ['谷物酸奶']
