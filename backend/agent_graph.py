"""Stage 1 StateGraph: HTTP requests traverse this compiled graph."""
import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from domain.context import ContextSnapshot, make_reply, apply_patch
from services.context_builder import ContextBuilder
from services.planning import create_planner
from services.actions import revalidate, navigation_receipt


class AgentState(TypedDict):
    event_kind: str
    owner_id: str
    action_id: str
    action_decision: dict
    action_evidence: dict
    action_receipt: dict
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
            'event_kind': 'chat', 'action_id': '', 'action_decision': {},
            'action_evidence': {}, 'action_receipt': {},
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
        return {'vetted_places':await planning_service().enrich(snapshot.constraints.city,state['vetted_places'],
                                                                 snapshot.constraints.budget_cny)}

    async def publish_plans(state):
        return {'reply':planning_service().publish(ContextSnapshot.model_validate(state['context_snapshot']),
                                        state['vetted_places'],state['evidence'])}

    async def publish(state):
        return {'reply':make_reply(ContextSnapshot.model_validate(state['context_snapshot']),state['understanding']['intent'])}

    async def persist_reply(state):
        return {'output':await repository.save_reply(state['run_id'],state['reply'])}

    async def prepare_action(state):
        row = await repository.actions.get(state['owner_id'], state['action_id'])
        if str(row['thread_id']) != state['thread_id']:
            raise ValueError('Action belongs to another conversation')
        return {'action_decision': {}, 'action_evidence': {}, 'action_receipt': {},
                'output': {}}

    async def await_confirmation(state):
        # This node is replayed after Command(resume=...), so it has no side effects.
        decision = interrupt({'action_id': state['action_id'], 'kind': 'confirmation'})
        return {'action_decision': decision}

    async def read_action_decision(state):
        row = await repository.actions.get(state['owner_id'], state['action_id'])
        if state['action_decision'].get('action_id') != state['action_id']:
            raise ValueError('Resume action mismatch')
        return {'action_decision': {'status': row['status']}}

    async def cancel_action(state):
        row = await repository.actions.get(state['owner_id'], state['action_id'])
        return {'output': {'action_id': state['action_id'], 'status': row['status'],
                           'receipt': row['receipt']}}

    async def revalidate_selected(state):
        row = await repository.actions.get(state['owner_id'], state['action_id'])
        if row['status'] not in ('authorized','claimed'):
            return {'action_evidence': {'valid': False, 'reason': 'not_authorized'}}
        evidence = await revalidate(row, planning_service().maps, planning_service().public)
        if not evidence['valid']:
            await repository.actions.invalidate(state['action_id'], evidence['reason'])
        return {'action_evidence': evidence}

    async def invalidate_action(state):
        row = await repository.actions.get(state['owner_id'], state['action_id'])
        return {'output': {'action_id': state['action_id'], 'status': row['status'],
                           'receipt': row['receipt']}}

    async def claim_action(state):
        row = await repository.actions.claim(state['action_id'])
        return {'action_decision': {'status': row['status']}}

    async def execute_or_handoff(state):
        row = await repository.actions.get(state['owner_id'], state['action_id'])
        if row['status'] == 'completed':
            return {'action_receipt': row['receipt']}
        receipt = ({'kind': 'plan_saved', 'place_name': row['plan_snapshot']['place']['name']}
                   if row['kind'] == 'save' else navigation_receipt(row, state['action_evidence']))
        return {'action_receipt': receipt}

    async def persist_receipt(state):
        row = await repository.actions.finish(state['action_id'], state['action_receipt'])
        return {'output': {'action_id': state['action_id'], 'status': row['status'],
                           'receipt': row['receipt']}}

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
    for name, action in {'prepare_action':prepare_action, 'await_confirmation':await_confirmation,
                         'read_action_decision':read_action_decision, 'cancel_action':cancel_action,
                         'revalidate_selected':revalidate_selected, 'invalidate_action':invalidate_action,
                         'claim_action':claim_action, 'execute_or_handoff':execute_or_handoff,
                         'persist_receipt':persist_receipt}.items():
        graph.add_node(name,action)
    graph.add_conditional_edges(START, lambda state: 'prepare_action' if state.get('event_kind') == 'action' else 'accept_event',
                                {'prepare_action':'prepare_action','accept_event':'accept_event'})
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
    graph.add_edge('prepare_action','await_confirmation')
    graph.add_edge('await_confirmation','read_action_decision')
    graph.add_conditional_edges('read_action_decision',
        lambda state: 'revalidate_selected' if state['action_decision']['status'] in ('authorized','claimed') else 'cancel_action',
        {'revalidate_selected':'revalidate_selected','cancel_action':'cancel_action'})
    graph.add_edge('cancel_action',END)
    graph.add_conditional_edges('revalidate_selected',
        lambda state: 'claim_action' if state['action_evidence']['valid'] else 'invalidate_action',
        {'claim_action':'claim_action','invalidate_action':'invalidate_action'})
    graph.add_edge('invalidate_action',END)
    graph.add_conditional_edges('claim_action',
        lambda state: 'execute_or_handoff' if state['action_decision']['status'] in ('claimed','completed') else 'invalidate_action',
        {'execute_or_handoff':'execute_or_handoff','invalidate_action':'invalidate_action'})
    graph.add_edge('execute_or_handoff','persist_receipt')
    graph.add_edge('persist_receipt',END)
    return graph.compile(checkpointer=checkpointer)
