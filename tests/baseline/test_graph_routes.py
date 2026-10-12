"""Controlled model/repository unit test for the real graph topology."""
import pytest

from agent_graph import build_graph
from domain.context import ContextSnapshot, FieldChange, Understanding, apply_patch
from domain.errors import AppError


class RepositoryStub:
    def __init__(self):
        self.snapshot = ContextSnapshot()
        self.events = []
        self.output = None

    async def run(self, run_id):
        return {'request_id':'request-1','message_id':'message-1','input_text':'预算50元',
                'base_snapshot':self.snapshot.model_dump()}

    async def recent(self,thread,run_id):
        return []

    async def commit(self,run_id,proposal,meta):
        self.snapshot = apply_patch(self.snapshot,Understanding.model_validate(proposal),'预算50元','message-1')
        return self.snapshot.model_dump()

    async def event(self,run_id,node,status,elapsed_ms):
        self.events.append((node,status))

    async def save_reply(self,run_id,reply):
        self.output = {**reply,'snapshot':self.snapshot.model_dump()}
        return self.output


class ControlledModel:
    async def understand(self,context,recent,message):
        return Understanding(intent='planning',changes=[FieldChange(field='budget_cny',value=50,quote='预算50元')]),{'actual_call':False}


@pytest.mark.asyncio
async def test_compiled_graph_routes_through_persisted_state_and_clarification():
    repository = RepositoryStub()
    graph = build_graph(repository,ControlledModel())
    result = await graph.ainvoke({'thread_id':'thread-1','run_id':'run-1'})
    assert result['output']['kind'] == 'clarification'
    assert result['output']['snapshot']['constraints']['budget_cny'] == 50
    assert [node for node,status in repository.events] == [
        'accept_event','prepare_context','understand_context',
        'validate_and_commit_patch','clarification','persist_reply',
    ]
    assert all(status=='completed' for _,status in repository.events)


@pytest.mark.asyncio
async def test_invalid_model_patch_stops_before_business_commit():
    class UnsupportedModel:
        async def understand(self,context,recent,message):
            return Understanding(intent='planning',changes=[FieldChange(field='budget_cny',value=50,quote='not in user message')]),{'actual_call':False}

    class GuardedRepository(RepositoryStub):
        async def commit(self,*args):
            raise AssertionError('commit must not be reached')

    repository = GuardedRepository()
    with pytest.raises(AppError) as caught:
        await build_graph(repository,UnsupportedModel()).ainvoke({'thread_id':'thread-1','run_id':'run-1'})
    assert caught.value.code == 'INVALID_MODEL_PATCH'
    assert repository.snapshot.revision == 0
    assert ('understand_context','failed') in repository.events
