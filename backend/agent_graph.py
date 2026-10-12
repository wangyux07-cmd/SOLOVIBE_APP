"""Stage 1 StateGraph: HTTP requests traverse this compiled graph."""
import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from domain.context import ContextSnapshot, make_reply, apply_patch
from services.context_builder import ContextBuilder


class AgentState(TypedDict):
    schema_version: int
    thread_id: str
    run_id: str
    request_id: str
    input_event: dict
    context_snapshot: dict
    recent_messages: list[dict]
    rolling_summary: dict | None
    context_budget: dict
    understanding: dict
    model_meta: dict
    reply: dict
    output: dict


def build_graph(repository, model, checkpointer=None, context_builder=None):
    builder = context_builder or (ContextBuilder(repository, model) if repository and model else None)
    async def accept_event(state):
        run = await repository.run(state['run_id'])
        return {
            'schema_version': 1, 'request_id': str(run['request_id']),
            'input_event': {'message_id':str(run['message_id']), 'content':run['input_text']},
            'context_snapshot':run['base_snapshot'], 'recent_messages':[],
            'rolling_summary':None, 'context_budget':{},
            'understanding':{}, 'model_meta':{}, 'reply':{}, 'output':{},
        }

    async def prepare_context(state):
        row = await repository.summary(state['thread_id'])
        return {'rolling_summary':({key:row[key] for key in ('revision','covered_until_sequence','content')}
                                   if row else None)}

    async def compact_history(state):
        # Re-read after a crash between summary commit and graph checkpoint.
        # A saved prepare_context result may point at the previous cursor.
        row = await repository.summary(state['thread_id'])
        current_summary = ({key:row[key] for key in ('revision','covered_until_sequence','content')}
                           if row else None)
        return await builder.build(state['thread_id'], state['run_id'],
                                   state['context_snapshot'], state['input_event']['content'],
                                   current_summary)

    async def understand_context(state):
        proposal, meta = await model.understand(state['context_snapshot'],state['recent_messages'],
                                                state['input_event']['content'],
                                                rolling_summary=state['rolling_summary'],
                                                max_input_tokens=state['context_budget']['input_limit'])
        meta['context_budget'] = state['context_budget']
        # Reject unsupported patches before checkpointing them so retry re-extracts.
        apply_patch(ContextSnapshot.model_validate(state['context_snapshot']),proposal,
                    state['input_event']['content'],state['input_event']['message_id'])
        return {'understanding':proposal.model_dump(), 'model_meta':meta}

    async def validate_and_commit_patch(state):
        snapshot = await repository.commit(state['run_id'],state['understanding'],state['model_meta'])
        return {'context_snapshot':snapshot}

    def route(state):
        return make_reply(ContextSnapshot.model_validate(state['context_snapshot']), state['understanding']['intent'])['kind']

    async def publish(state):
        return {'reply':make_reply(ContextSnapshot.model_validate(state['context_snapshot']),state['understanding']['intent'])}

    async def persist_reply(state):
        return {'output':await repository.save_reply(state['run_id'],state['reply'])}

    def tracked(name, action):
        async def node(state):
            started = time.monotonic()
            try:
                value = await action(state)
            except Exception:
                await repository.event(state['run_id'],name,'failed',round((time.monotonic()-started)*1000))
                raise
            await repository.event(state['run_id'],name,'completed',round((time.monotonic()-started)*1000))
            return value
        return node

    graph = StateGraph(AgentState)
    actions = {'accept_event':accept_event, 'prepare_context':prepare_context,
               'compact_history':compact_history,
               'understand_context':understand_context, 'validate_and_commit_patch':validate_and_commit_patch,
               'clarification':publish, 'state_summary':publish, 'supportive':publish,
               'context_ready':publish, 'persist_reply':persist_reply}
    for name, action in actions.items():
        graph.add_node(name,tracked(name,action))
    graph.add_edge(START,'accept_event')
    graph.add_edge('accept_event','prepare_context')
    graph.add_edge('prepare_context','compact_history')
    graph.add_edge('compact_history','understand_context')
    graph.add_edge('understand_context','validate_and_commit_patch')
    routes = {name:name for name in ('clarification','state_summary','supportive','context_ready')}
    graph.add_conditional_edges('validate_and_commit_patch',route,routes)
    for name in routes:
        graph.add_edge(name,'persist_reply')
    graph.add_edge('persist_reply',END)
    return graph.compile(checkpointer=checkpointer)
