"""Phase 2 context boundaries using controlled model and storage interfaces."""
import pytest

from domain.context import ContextSnapshot
from domain.errors import AppError
from services.context_builder import ContextBuilder


def turns(count=6, size=180):
    rows = []
    for index in range(count):
        rows.extend([
            {'sequence': index * 2 + 1, 'role': 'user', 'content': f'第{index}轮' + '散步' * (size // 2)},
            {'sequence': index * 2 + 2, 'role': 'assistant', 'content': '已记录' + '天气' * (size // 2)},
        ])
    return rows


class Storage:
    def __init__(self, rows):
        self.rows = rows
        self.saved = None

    async def history(self, thread, run, cursor):
        return [row for row in self.rows if row['sequence'] > cursor]

    async def advance_summary(self, thread, run, old, rows, content, estimate, revision):
        assert rows == self.rows[:len(rows)]
        assert rows[-1]['role'] == 'assistant'
        self.saved = {'revision': 1, 'covered_until_sequence': rows[-1]['sequence'],
                      'content': content, 'based_on_context_revision': revision}
        return self.saved


class Model:
    context_window = 1048576

    def __init__(self, error=None):
        self.calls = 0
        self.error = error

    async def summarize_history(self, previous, messages, limit):
        self.calls += 1
        if self.error:
            raise self.error
        return {'topic': '独自散步', 'preference_reasons': [],
                'rejected_ideas': [], 'unresolved_questions': []}, {'actual_call': False}


@pytest.mark.asyncio
async def test_short_conversation_never_calls_summary(monkeypatch):
    monkeypatch.setenv('SOLOVIBE_UNDERSTAND_INPUT_TOKENS', '8000')
    model, storage = Model(), Storage(turns(1, 20))
    result = await ContextBuilder(storage, model).build('thread', 'run', ContextSnapshot().model_dump(), '你好', None)
    assert model.calls == 0
    assert result['recent_messages'] == storage.rows
    assert result['context_budget']['estimated_input_tokens'] <= result['context_budget']['input_limit']


@pytest.mark.asyncio
async def test_compacts_only_completed_old_pairs_and_keeps_four_recent_turns(monkeypatch):
    monkeypatch.setenv('SOLOVIBE_UNDERSTAND_INPUT_TOKENS', '5000')
    model, storage = Model(), Storage(turns())
    snapshot = ContextSnapshot(revision=2, constraints={'budget_cny': 80}).model_dump()
    result = await ContextBuilder(storage, model).build('thread', 'run', snapshot, '现在呢？', None)
    assert model.calls == 1
    assert storage.saved['based_on_context_revision'] == 2
    assert result['recent_messages'] == storage.rows[-8:]
    assert result['rolling_summary']['historical_record_only'] is True
    assert result['context_budget']['summary_revision'] == 1
    assert snapshot['constraints']['budget_cny'] == 80


@pytest.mark.asyncio
async def test_failed_summary_keeps_cursor_and_uses_bounded_safe_subset(monkeypatch):
    monkeypatch.setenv('SOLOVIBE_UNDERSTAND_INPUT_TOKENS', '5000')
    storage = Storage(turns())
    model = Model(AppError('SUMMARY_UNAVAILABLE', 'timeout'))
    result = await ContextBuilder(storage, model).build('thread', 'run', ContextSnapshot().model_dump(), '现在呢？', None)
    assert model.calls == 1
    assert storage.saved is None
    assert result['recent_messages'] == storage.rows[-8:]
    assert result['context_budget']['degraded'] is True
    assert result['context_budget']['summary_failure_code'] == 'SUMMARY_UNAVAILABLE'


@pytest.mark.asyncio
async def test_single_oversized_current_message_is_never_truncated(monkeypatch):
    monkeypatch.setenv('SOLOVIBE_UNDERSTAND_INPUT_TOKENS', '2200')
    model = Model()
    with pytest.raises(AppError) as caught:
        await ContextBuilder(Storage([]), model).build('thread', 'run', ContextSnapshot().model_dump(), '更正' * 1000, None)
    assert caught.value.code == 'CONTEXT_OVERFLOW'
    assert model.calls == 0
