"""Stage 1 StateGraph: HTTP requests traverse this compiled graph."""
import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from domain.context import ContextSnapshot, make_reply, apply_patch
from services.context_builder import ContextBuilder
from services.planning import create_planner


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
    evidence: dict
    vetted_places: list[dict]
    output: dict


def build_graph(repository, model, checkpointer=None, context_builder=None, planner=None):
    builder = context_builder or (ContextBuilder(repository, model) if repository and model else None)
    def planning_service():
        nonlocal planner
        if planner is None:
            planner = create_planner()
        return planner
    async def accept_event(state):
        run = await repository.run(state['run_id'])
        return {
            'schema_version': 1, 'request_id': str(run['request_id']),
            'input_event': {'message_id':str(run['message_id']), 'content':run['input_text']},
            'context_snapshot':run['base_snapshot'], 'recent_messages':[],
            'rolling_summary':None, 'context_budget':{},
            'understanding':{}, 'model_meta':{}, 'reply':{}, 'output':{},
            'evidence':{}, 'vetted_places':[],
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
        kind = make_reply(ContextSnapshot.model_validate(state['context_snapshot']), state['understanding']['intent'])['kind']
        return 'collect_evidence' if kind == 'context_ready' else kind

    async def collect_evidence(state):
        return {'evidence':await planning_service().collect(ContextSnapshot.model_validate(state['context_snapshot']))}

    async def verify_feasibility(state):
        return {'vetted_places':planning_service().verify(ContextSnapshot.model_validate(state['context_snapshot']),state['evidence'])}

    async def enrich_sources(state):
        snapshot = ContextSnapshot.model_validate(state['context_snapshot'])
        return {'vetted_places':await planning_service().enrich(snapshot.constraints.city,state['vetted_places'])}

    async def publish_plans(state):
        return {'reply':planning_service().publish(ContextSnapshot.model_validate(state['context_snapshot']),
                                        state['vetted_places'],state['evidence'])}

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
               'collect_evidence':collect_evidence, 'verify_feasibility':verify_feasibility,
               'enrich_sources':enrich_sources, 'publish_plans':publish_plans,
               'persist_reply':persist_reply}
    for name, action in actions.items():
        graph.add_node(name,tracked(name,action))
    graph.add_edge(START,'accept_event')
    graph.add_edge('accept_event','prepare_context')
    graph.add_edge('prepare_context','compact_history')
    graph.add_edge('compact_history','understand_context')
    graph.add_edge('understand_context','validate_and_commit_patch')
    routes = {name:name for name in ('clarification','state_summary','supportive','collect_evidence')}
    graph.add_conditional_edges('validate_and_commit_patch',route,routes)
    for name in ('clarification','state_summary','supportive'):
        graph.add_edge(name,'persist_reply')
    graph.add_edge('collect_evidence','verify_feasibility')
    graph.add_edge('verify_feasibility','enrich_sources')
    graph.add_edge('enrich_sources','publish_plans')
    graph.add_edge('publish_plans','persist_reply')
    graph.add_edge('persist_reply',END)
    return graph.compile(checkpointer=checkpointer)
