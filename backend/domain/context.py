"""The model proposes edits; validated, versioned snapshots remain authoritative."""

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from domain.errors import AppError


class Constraints(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    city: str | None = Field(default=None, max_length=80)
    location_text: str | None = Field(default=None, max_length=180)
    origin_coordinate: str | None = Field(default=None, pattern=r"^\d{2,3}\.\d{6},\d{2}\.\d{6}$")
    origin_accuracy_m: float | None = Field(default=None, ge=0, le=300)
    origin_observed_at: str | None = None
    origin_source: Literal["browser_gps"] | None = None
    return_location_text: str | None = Field(default=None, max_length=180)
    desired_dwell_minutes: int | None = Field(default=None, ge=1, le=720)
    budget_cny: float | None = Field(default=None, ge=0, le=100000)
    available_minutes: int | None = Field(default=None, ge=1, le=1440)
    max_walk_minutes: int | None = Field(default=None, ge=0, le=360)
    energy: Literal["low", "medium", "high"] | None = None
    interests: list[str] = Field(default_factory=list, max_length=12)
    exclusions: list[str] = Field(default_factory=list, max_length=12)


class FieldSource(BaseModel):
    message_id: str
    quote: str
    basis: Literal["explicit", "inferred"]
    revision: int


class ContextSnapshot(BaseModel):
    schema_version: int = 2
    revision: int = 0
    constraints: Constraints = Field(default_factory=Constraints)
    sources: dict[str, FieldSource] = Field(default_factory=dict)


class FieldChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: Literal["city", "location_text", "return_location_text", "desired_dwell_minutes", "budget_cny", "available_minutes", "max_walk_minutes", "energy", "interests", "exclusions"]
    value: Any
    quote: str = Field(min_length=1, max_length=1000)
    basis: Literal["explicit", "inferred"] = "explicit"


class Understanding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: Literal["planning", "state_query", "chat"]
    changes: list[FieldChange] = Field(default_factory=list, max_length=8)


def _number_supported(field: str, value: int | float | None, quote: str, previous: int | float | None) -> bool:
    """Conservatively reject invented numeric values in model-proposed patches."""
    if value is None:
        return bool(re.search(r'取消|清除|不设|不限|随便|不考虑|不限制|都行', quote))
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    candidates = [float(number) for number in re.findall(r'(?<!\d)\d+(?:\.\d+)?', quote)]
    if field.endswith('minutes'):
        for match in re.finditer(r'(\d+(?:\.\d+)?|半|一|两|二|三|四|五|六|七|八|九|十)\s*个?\s*小时', quote):
            amount = match.group(1)
            hours = {'半':0.5,'一':1,'两':2,'二':2,'三':3,'四':4,'五':5,
                     '六':6,'七':7,'八':8,'九':9,'十':10}.get(amount)
            candidates.append(60 * (hours if hours is not None else float(amount)))
        if '半小时' in quote:
            candidates.append(30)
    if any(abs(value - candidate) < 0.001 for candidate in candidates):
        return True
    if value == 0 and re.search(r'不想花钱|不花钱|免费|不走路|不步行', quote):
        return True
    if previous is not None:
        if re.search(r'再加|增加|多(?:花|走|留|出)|提高|上调', quote):
            return any(abs(value - previous - candidate) < 0.001 for candidate in candidates)
        if re.search(r'减少|再减|降低|下调|少(?:花|走|留|出)', quote):
            return any(abs(value - previous + candidate) < 0.001 for candidate in candidates)
    return False


def apply_patch(snapshot: ContextSnapshot, proposal: Understanding, message: str, message_id: str) -> ContextSnapshot:
    values = snapshot.constraints.model_dump()
    sources = dict(snapshot.sources)
    seen: set[str] = set()
    for change in proposal.changes:
        if change.field in seen or change.quote not in message:
            raise AppError("INVALID_MODEL_PATCH", "模型给出的变更缺少本条消息的有效依据，请重试。")
        seen.add(change.field)
        if change.basis == "inferred" and change.field != "energy":
            raise AppError("INVALID_MODEL_PATCH", "不能推测预算、地点或时间等约束。")
        if isinstance(change.value, str) and not change.value.strip():
            raise AppError("INVALID_MODEL_PATCH", "空字段必须明确表示为 null。")
        if isinstance(change.value, list) and any(not isinstance(x, str) or not x.strip() or len(x) > 80 for x in change.value):
            raise AppError("INVALID_MODEL_PATCH", "偏好字段格式无效。")
        if change.field in ('budget_cny','available_minutes','max_walk_minutes','desired_dwell_minutes') and not _number_supported(change.field,change.value,change.quote,values[change.field]):
            raise AppError("INVALID_MODEL_PATCH", "模型给出的数值与本条消息依据不一致，请明确数值后重试。")
        values[change.field] = change.value
        if change.field in ('city', 'location_text') and values['origin_source'] == 'browser_gps':
            for origin_field in ('origin_coordinate', 'origin_accuracy_m', 'origin_observed_at', 'origin_source'):
                values[origin_field] = None
                sources.pop(origin_field, None)
        sources[change.field] = FieldSource(
            message_id=message_id, quote=change.quote, basis=change.basis,
            revision=snapshot.revision + 1,
        )
    try:
        constraints = Constraints.model_validate(values)
    except ValidationError as exc:
        raise AppError("INVALID_MODEL_PATCH", "模型返回的约束类型或范围不合法，请重试。") from exc
    changed = bool(proposal.changes)
    return ContextSnapshot(
        revision=snapshot.revision + int(changed), constraints=constraints,
        sources=sources,
    )


DIRECT_EDIT_LABELS = {
    'city': '城市', 'location_text': '出发位置', 'return_location_text': '返程终点',
    'desired_dwell_minutes': '计划停留分钟数', 'budget_cny': '预算元数',
    'available_minutes': '可用分钟数', 'max_walk_minutes': '步行分钟上限',
    'interests': '偏好', 'exclusions': '避开',
}


def direct_adjustment(snapshot: ContextSnapshot, field: str, value: Any):
    """Build a traceable, deterministic patch from an explicit form submission."""
    if field not in DIRECT_EDIT_LABELS:
        raise AppError('INVALID_ADJUSTMENT', '这个条件不能通过直接编辑修改。', 422)
    if isinstance(value, list):
        rendered = '、'.join(value)
    elif value is None:
        rendered = '取消限制'
    else:
        rendered = str(value)
    quote = f'{DIRECT_EDIT_LABELS[field]}改为{rendered}'
    message = f'请把{quote}。'
    proposal = Understanding(intent='planning', changes=[FieldChange(
        field=field, value=value, quote=quote, basis='explicit')])
    updated = apply_patch(snapshot, proposal, message, 'direct-adjustment-validation')
    if updated.constraints.model_dump()[field] == snapshot.constraints.model_dump()[field]:
        raise AppError('NO_CHANGE', '新值与当前条件相同。', 422)
    return message, proposal


def missing_fields(snapshot: ContextSnapshot) -> list[str]:
    c = snapshot.constraints
    return [name for name in ("city", "location_text", "budget_cny", "available_minutes") if getattr(c, name) is None]


def context_summary(snapshot: ContextSnapshot) -> str:
    c = snapshot.constraints
    parts = []
    if c.city: parts.append(f"城市：{c.city}")
    if c.location_text: parts.append(f"位置：{c.location_text}")
    if c.origin_source == "browser_gps": parts.append("位置来自本次授权的浏览器定位")
    if c.return_location_text: parts.append(f"返程终点：{c.return_location_text}")
    if c.desired_dwell_minutes is not None: parts.append(f"计划停留：{c.desired_dwell_minutes} 分钟")
    if c.budget_cny is not None: parts.append(f"预算：{c.budget_cny:g} 元")
    if c.available_minutes is not None: parts.append(f"可用时间：{c.available_minutes} 分钟")
    if c.max_walk_minutes is not None: parts.append(f"最多步行：{c.max_walk_minutes} 分钟")
    if c.energy: parts.append(f"精力：{dict(low='偏低', medium='一般', high='充足')[c.energy]}")
    if c.interests: parts.append("偏好：" + "、".join(c.interests))
    if c.exclusions: parts.append("避开：" + "、".join(c.exclusions))
    return "；".join(parts) or "目前还没有记录出行约束"


def make_reply(snapshot: ContextSnapshot, intent: str) -> dict:
    missing = missing_fields(snapshot)
    summary = context_summary(snapshot)
    if intent == "state_query":
        return {"kind": "state_summary", "response": f"目前记下的是：{summary}。", "missing_fields": missing}
    if intent == "chat":
        return {"kind": "supportive", "response": "我在。可以先说说你现在的状态，想出门时我们再一起整理地点、预算和时间。", "missing_fields": missing}
    if missing:
        questions = {
            "city": "你现在在哪个城市、哪个区域或地标附近？",
            "location_text": "你现在在哪个区域或地标附近？",
            "budget_cny": "这次出门的预算上限大约是多少元？",
            "available_minutes": "你大约有多少分钟可以安排？",
        }
        return {"kind": "clarification", "response": f"已记下：{summary}。{questions[missing[0]]}", "missing_fields": missing}
    return {
        "kind": "context_ready", "missing_fields": [],
        "response": f"出行条件已整理好：{summary}。正在查询真实地点与步行路线。",
    }
