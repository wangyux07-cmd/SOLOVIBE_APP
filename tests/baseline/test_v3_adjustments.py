"""V3-5 deterministic contracts: explicit edits, evidence reuse, and safe rechecks."""
from datetime import datetime, timezone

import pytest

from domain.context import Constraints, ContextSnapshot, apply_patch, direct_adjustment
from domain.errors import AppError
from services.planning import Planner


def now():
    return datetime.now(timezone.utc).isoformat()


def state(**changes):
    return ContextSnapshot(revision=4, constraints=Constraints(
        city='上海', location_text='徐家汇站', budget_cny=80, available_minutes=90,
        max_walk_minutes=25, **changes))


def prior_plan():
    observed = now()
    return {'plan_set_id': 'old-set', 'plans': [{
        'plan_id': 'amap:A1:set:old-set',
        'place': {'provider': 'amap', 'poi_id': 'A1', 'name': '试点公园', 'city': '上海',
                  'address': '测试路 1 号', 'coordinate': '121.400000,31.200000',
                  'category': '公园', 'source_url': 'https://example.test/poi/A1',
                  'observed_at': observed},
        'origin': {'coordinate': '121.390000,31.190000'},
        'return_destination': {'coordinate': '121.390000,31.190000'},
        'route': {'observed_at': observed, 'walking_minutes': 10, 'distance_meters': 700},
        'return_route': {'observed_at': observed, 'walking_minutes': 10, 'distance_meters': 700},
        'facts': {'observed_at': observed, 'rating': 4.2},
        'public_info': {'sources': [], 'offers': []},
        'web_sources': [], 'web_status': 'empty', 'detail_status': 'matched',
    }]}


def test_direct_adjustment_is_explicit_and_does_not_call_the_model():
    message, proposal = direct_adjustment(state(), 'budget_cny', 50)
    assert proposal.changes[0].value == 50
    assert proposal.changes[0].quote in message
    with pytest.raises(AppError):
        direct_adjustment(state(), 'budget_cny', 80)
    with pytest.raises(AppError):
        direct_adjustment(state(), 'origin_coordinate', '121.0,31.0')


def test_reuse_matrix_allows_only_narrowing_or_presentation_changes():
    old = state()
    _, budget = direct_adjustment(old, 'budget_cny', 50)
    after_budget = ContextSnapshot(revision=5, constraints={**old.constraints.model_dump(), 'budget_cny': 50},
                                   sources=old.sources)
    assert Planner.reuse_mode(old, after_budget, prior_plan(), ['budget_cny']) == 'facts_and_routes'

    after_return = ContextSnapshot(revision=5, constraints={**old.constraints.model_dump(),
                                   'return_location_text': '上海图书馆'}, sources=old.sources)
    assert Planner.reuse_mode(old, after_return, prior_plan(), ['return_location_text']) == 'return_route'

    after_wider_walk = ContextSnapshot(revision=5, constraints={**old.constraints.model_dump(),
                                      'max_walk_minutes': 40}, sources=old.sources)
    assert Planner.reuse_mode(old, after_wider_walk, prior_plan(), ['max_walk_minutes']) is None

    after_city = ContextSnapshot(revision=5, constraints={**old.constraints.model_dump(),
                                  'city': '杭州'}, sources=old.sources)
    assert Planner.reuse_mode(old, after_city, prior_plan(), ['city']) is None


@pytest.mark.parametrize(('field', 'value', 'expected_reuse'), [
    ('available_minutes', 60, 'facts_and_routes'),
    ('location_text', '人民广场站', None),
    ('interests', ['书店'], None),
])
def test_time_location_and_preference_edits_cross_the_right_evidence_boundary(
        field, value, expected_reuse):
    before = state()
    message, proposal = direct_adjustment(before, field, value)
    after = apply_patch(before, proposal, message, 'test')
    assert getattr(after.constraints, field) == value
    assert Planner.reuse_mode(before, after, prior_plan(), [field]) == expected_reuse


def test_new_plan_ids_include_the_new_immutable_plan_set():
    planner = Planner(None)
    selected = [{**prior_plan()['plans'][0]['place'], 'route': prior_plan()['plans'][0]['route'],
                 'return_route': prior_plan()['plans'][0]['return_route'],
                 'facts': prior_plan()['plans'][0]['facts'], 'web_status': 'empty',
                 'web_sources': [], 'public_info': {'offers': []}}]
    result = planner.publish(state(), selected, {'origin': None, 'return_destination': None,
                             'status': 'ok', 'errors': []}, plan_set_id='new-set')
    assert result['plans'][0]['plan_id'] == 'amap:A1:set:new-set'
