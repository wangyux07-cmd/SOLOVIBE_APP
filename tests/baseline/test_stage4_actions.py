from datetime import datetime, timedelta, timezone

import pytest

from services.actions import navigation_receipt, revalidate


def action(kind='navigate', minutes=25):
    return {'kind': kind, 'expires_at': datetime.now(timezone.utc) + timedelta(minutes=10),
            'plan_snapshot': {'place': {'provider': 'amap', 'poi_id': 'A1', 'name': '公园',
                'address': '道路 1 号', 'coordinate': '121.439000,31.196000'}},
            'context_snapshot': {'constraints': {'city': '上海', 'location_text': '徐家汇站',
                'available_minutes': 40, 'max_walk_minutes': minutes}}}


class Maps:
    def __init__(self, minutes=12):
        self.minutes = minutes
        self.calls = []

    async def detail(self, place):
        self.calls.append('detail')
        return {'provider': 'amap'}

    async def geocode(self, city, location):
        self.calls.append('geocode')
        return {'coordinate': '121.436000,31.194000'}

    async def walking(self, origin, destination, poi_id):
        self.calls.append('walking')
        return {'walking_minutes': self.minutes, 'distance_meters': 780}


@pytest.mark.asyncio
async def test_navigation_revalidates_identity_location_and_route_before_handoff():
    maps = Maps()
    evidence = await revalidate(action(), maps)
    assert evidence['valid'] and maps.calls == ['detail', 'geocode', 'walking']
    receipt = navigation_receipt(action(), evidence)
    assert receipt['kind'] == 'navigation_handoff_ready'
    assert 'mode=walk' in receipt['url']
    assert 'callnative=0' in receipt['url']
    assert receipt['url'].startswith('https://uri.amap.com/navigation?')


@pytest.mark.asyncio
async def test_route_limit_and_expiry_block_handoff():
    too_long = await revalidate(action(minutes=5), Maps())
    assert too_long == {'valid': False, 'reason': 'route_exceeds_limit'}
    expired = action()
    expired['expires_at'] = datetime.now(timezone.utc) - timedelta(seconds=1)
    maps = Maps()
    assert await revalidate(expired, maps) == {'valid': False, 'reason': 'expired'}
    assert maps.calls == []


@pytest.mark.asyncio
async def test_save_requires_confirmation_but_no_new_map_call():
    maps = Maps()
    assert (await revalidate(action('save'), maps))['valid']
    assert maps.calls == []
