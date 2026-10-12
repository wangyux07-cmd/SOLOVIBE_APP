"""Deterministic boundary tests; these never count as provider integration tests."""
import pytest
from pydantic import ValidationError

from domain.context import ContextSnapshot, FieldChange, Understanding, apply_patch, make_reply
from domain.errors import AppError


def patch(state, text, **changes):
    proposal = Understanding(intent='planning',changes=[FieldChange(**item) for item in changes.values()])
    return apply_patch(state,proposal,text,'message-id')


def test_two_turn_updates_preserve_earlier_constraints_and_sources():
    state = patch(ContextSnapshot(),'预算 50 元，我有点累',
                  budget={'field':'budget_cny','value':50,'quote':'预算 50 元'},
                  energy={'field':'energy','value':'low','quote':'有点累','basis':'inferred'})
    state = patch(state,'我在上海徐汇',
                  city={'field':'city','value':'上海','quote':'上海'},
                  location={'field':'location_text','value':'徐汇','quote':'徐汇'})
    assert state.revision == 2
    assert state.constraints.budget_cny == 50
    assert state.constraints.energy == 'low'
    assert state.constraints.city == '上海'
    assert state.sources['budget_cny'].revision == 1
    assert make_reply(state,'planning')['kind'] == 'clarification'


def test_zero_clear_and_no_change_are_distinct():
    state = patch(ContextSnapshot(),'不想花钱',budget={'field':'budget_cny','value':0,'quote':'不想花钱'})
    assert state.constraints.budget_cny == 0
    unchanged = apply_patch(state,Understanding(intent='state_query',changes=[]),'预算多少','m2')
    assert unchanged.revision == state.revision
    assert unchanged.constraints.budget_cny == 0
    cleared = patch(state,'取消预算限制',budget={'field':'budget_cny','value':None,'quote':'取消预算限制'})
    assert cleared.constraints.budget_cny is None


@pytest.mark.parametrize('change,text',[
    ({'field':'budget_cny','value':40,'quote':'预算 40 元'},'预算 50 元'),
    ({'field':'city','value':'上海','quote':'徐汇','basis':'inferred'},'我在徐汇'),
    ({'field':'available_minutes','value':0,'quote':'零分钟'},'零分钟'),
    ({'field':'budget_cny','value':'50','quote':'预算 50 元'},'预算 50 元'),
    ({'field':'budget_cny','value':80,'quote':'预算 50 元'},'预算 50 元'),
    ({'field':'budget_cny','value':None,'quote':'预算 50 元'},'预算 50 元'),
])
def test_untrusted_model_patch_is_rejected(change,text):
    with pytest.raises(AppError):
        patch(ContextSnapshot(),text,value=change)


def test_extra_constraint_fields_are_rejected():
    with pytest.raises(ValidationError):
        ContextSnapshot.model_validate({'constraints':{'owner_id':'another-user'}})


def test_hour_conversion_and_relative_budget_have_numeric_evidence():
    state = patch(ContextSnapshot(),'预算50元，有一小时',
                  budget={'field':'budget_cny','value':50,'quote':'预算50元'},
                  time={'field':'available_minutes','value':60,'quote':'一小时'})
    state = patch(state,'预算再加20元',budget={'field':'budget_cny','value':70,'quote':'再加20元'})
    assert state.constraints.budget_cny == 70
    assert state.constraints.available_minutes == 60
