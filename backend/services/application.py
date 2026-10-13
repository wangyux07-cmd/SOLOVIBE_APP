"""Coordinates authorization, single-writer execution, and durable graph recovery."""
import os
import asyncio

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from agent_graph import build_graph
from domain.context import ContextSnapshot, Understanding, direct_adjustment
from domain.errors import AppError, Conflict
from persistence.repository import Repository, request_fingerprint
from persistence.actions import public_action
from persistence.public_evidence import PublicEvidenceRepository
from services.model_client import DeepSeekClient
from services.planning import create_planner
from services.planning import ProviderFailure


def database_dsn():
    value = os.getenv('DATABASE_URL','').strip()
    if not value:
        raise AppError('DATABASE_NOT_CONFIGURED','请在 backend/.env 配置真实 DATABASE_URL。')
    try:
        options = conninfo_to_dict(value)
    except Exception:
        raise AppError('DATABASE_NOT_CONFIGURED','DATABASE_URL 连接串格式无效。') from None
    password = options.get('password','').lower()
    if not password or any(marker in password for marker in ('your-password','your_password','your-db-password','[password]','<password>')) or password == 'password':
        raise AppError('DATABASE_NOT_CONFIGURED','DATABASE_URL 的数据库密码仍是占位符。')
    if options.get('port') == '6543':
        raise AppError('DATABASE_POOL_MODE','请使用 PostgreSQL 直连或 Session pooler（通常为 5432），本阶段不支持事务池模式。')
    return value


def make_pool(dsn, graph=False):
    kwargs = {'autocommit':True,'row_factory':dict_row,'prepare_threshold':None,'connect_timeout':8}
    async def graph_search_path(connection):
        # Session pooler supports session state; avoid startup-parameter support
        # differences between direct Postgres and the shared pooler.
        await connection.execute('SET search_path TO solovibe_graph,public')
    return AsyncConnectionPool(dsn,kwargs=kwargs,min_size=1,max_size=8,timeout=12,
                               open=False,configure=graph_search_path if graph else None)


class Application:
    def __init__(self):
        self.pool = self.graph_pool = self.model = self.graph = self.repo = self.planner = None
        self.ready = False
        self.slots = asyncio.Semaphore(3)
        self.error = AppError('STARTING','服务正在启动。')

    async def start(self):
        try:
            dsn = database_dsn()
            if not os.getenv('DEEPSEEK_API_KEY'):
                raise AppError('MODEL_NOT_CONFIGURED','请配置 DEEPSEEK_API_KEY。')
            self.pool = make_pool(dsn)
            await self.pool.open(wait=True,timeout=12)
            async with self.pool.connection() as conn:
                tables = await (await conn.execute("SELECT to_regclass('solovibe_v1.conversations') AS business, to_regclass('solovibe_v1.rolling_summaries') AS summaries, to_regclass('solovibe_v1.plan_sets') AS plans, to_regclass('solovibe_v1.actions') AS actions, to_regclass('solovibe_v1.saved_plans') AS saved_plans, to_regclass('solovibe_v1.user_feedback') AS feedback, EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='solovibe_v1' AND table_name='runs' AND column_name='input_patch') AS patch_column, EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='solovibe_v1' AND table_name='runs' AND column_name='recheck_poi_id') AS recheck_column, EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='solovibe_v1' AND table_name='runs' AND column_name='recheck_plan_set_id') AS recheck_set_column, to_regclass('solovibe_graph.checkpoints') AS checkpoints")).fetchone()
                if not all(tables.values()):
                    raise AppError('MIGRATION_REQUIRED','请先运行 scripts/migrate_stage1.py 初始化阶段一数据表。')
            self.graph_pool = make_pool(dsn,graph=True)
            await self.graph_pool.open(wait=True,timeout=12)
            self.model = DeepSeekClient(os.environ['DEEPSEEK_API_KEY'],os.getenv('DEEPSEEK_MODEL','deepseek-flash'))
            probe = await self.model.probe()
            if not probe['configured_model_available']:
                raise AppError('MODEL_NOT_AVAILABLE','配置的模型不在账户可用模型列表中。')
            if not probe['context_window']:
                raise AppError('MODEL_CAPABILITY_UNKNOWN','模型列表未提供有效的上下文窗口，无法安全计算输入预算。')
            # Listing models only verifies authentication. A tiny generation call
            # also catches accounts that cannot actually run completions.
            await self.model.understand({},[], '你好')
            self.repo = Repository(self.pool)
            self.planner = create_planner(PublicEvidenceRepository(self.pool))
            self.graph = build_graph(self.repo,self.model,AsyncPostgresSaver(self.graph_pool),planner=self.planner)
            self.ready = True
            self.error = None
        except AppError as exc:
            self.error = exc
        except Exception:
            self.error = AppError('DATABASE_UNAVAILABLE','数据库连接或初始化检查失败；请检查连接串、网络和迁移状态。')
        if not self.ready:
            await self.close()

    async def close(self):
        if self.planner:
            await self.planner.maps.close()
            if self.planner.web:
                await self.planner.web.close()
            if self.planner.public:
                await self.planner.public.close()
            if self.planner.merchant_live:
                await self.planner.merchant_live.close()
        if self.model:
            await self.model.close()
        if self.graph_pool:
            await self.graph_pool.close()
        if self.pool:
            await self.pool.close()

    def require_ready(self):
        if not self.ready:
            raise self.error

    async def read_conversation(self, owner, thread):
        """Recheck advertised merchant facts before returning a cached plan."""
        result = await self.repo.read(owner, thread)
        from services.merchant_live import live_snapshot_current
        for plan in (result.get('plan_set') or {}).get('plans', []):
            advertised = plan.get('live_info')
            if not advertised:
                continue
            try:
                fresh = await self.planner.merchant_live.read(plan['place'])
            except Exception:
                fresh = None
            if not live_snapshot_current(advertised, fresh['info'] if fresh else None):
                plan['live_info'] = None
                plan['live_recheck_required'] = True
                plan['unknowns'] = list(dict.fromkeys(
                    [*plan.get('unknowns', []), '当前营业状态', '到店可用性']))
        return result

    async def set_browser_origin(self, owner, thread, request_id, expected_revision,
                                 longitude, latitude, accuracy_m):
        async with self.slots, self.repo.guard(owner, thread):
            try:
                location = await self.planner.maps.browser_location(longitude, latitude, accuracy_m)
            except ProviderFailure as exc:
                status = 422 if exc.category in ('location_inaccurate', 'location_not_found') else 503
                raise AppError('LOCATION_' + exc.category.upper(),
                               '无法确认这次定位，请手动输入附近地标或稍后重试。', status) from None
            snapshot = await self.repo.set_browser_origin(
                owner, thread, request_id, expected_revision, location)
            return {'snapshot': snapshot, 'origin': location}

    async def chat(self, owner, thread, request_id, message, expected_revision):
        async with self.slots, self.repo.guard(owner,thread):
            prior = await self.repo.request_run(thread, request_id)
            if prior:
                fingerprint = request_fingerprint(expected_revision, message)
                if prior['fingerprint'] != fingerprint:
                    raise AppError('REQUEST_ID_REUSED','同一个 request_id 不能用于不同消息或版本。',409)
                return await self.execute(prior)
            await self.clear_pending_action(owner, thread)
            run = await self.repo.accept(owner,thread,request_id,message,expected_revision)
            return await self.execute(run)

    async def adjust(self, owner, thread, request_id, field, value, expected_revision):
        async with self.slots, self.repo.guard(owner, thread):
            prior = await self.repo.request_run(thread, request_id)
            if prior:
                message, proposal = direct_adjustment(
                    ContextSnapshot.model_validate(prior['base_snapshot']), field, value)
                fingerprint = request_fingerprint(expected_revision, message, proposal.model_dump())
                if prior['fingerprint'] != fingerprint:
                    raise Conflict('REQUEST_ID_REUSED', '同一个 request_id 不能用于不同条件修改。')
                return await self.execute(prior)
            current = await self.repo.read(owner, thread)
            if current['snapshot']['revision'] != expected_revision:
                raise Conflict('STALE_REVISION', '状态已有更新，请刷新后重新修改。')
            message, proposal = direct_adjustment(
                ContextSnapshot.model_validate(current['snapshot']), field, value)
            await self.clear_pending_action(owner, thread)
            run = await self.repo.accept(owner, thread, request_id, message,
                                         expected_revision, proposal.model_dump())
            return await self.execute(run)

    async def recheck_place(self, owner, thread, request_id, plan_set_id,
                            poi_id, expected_revision):
        patch = Understanding(intent='planning', changes=[]).model_dump()
        async with self.slots, self.repo.guard(owner, thread):
            prior = await self.repo.request_run(thread, request_id)
            if prior:
                fingerprint = request_fingerprint(expected_revision, prior['input_text'],
                                                  patch, poi_id, plan_set_id)
                if (prior.get('recheck_poi_id') != poi_id
                        or str(prior.get('recheck_plan_set_id')) != plan_set_id
                        or prior['fingerprint'] != fingerprint):
                    raise Conflict('REQUEST_ID_REUSED', '同一 request_id 不能用于不同门店重查。')
                return await self.execute(prior)
            current = await self.repo.read(owner, thread)
            if current['snapshot']['revision'] != expected_revision:
                raise Conflict('STALE_REVISION', '条件已改变，请刷新方案。')
            plan_set = current.get('plan_set') or {}
            if plan_set.get('plan_set_id') != plan_set_id:
                raise Conflict('PLAN_STALE', '已有更新的方案组，请刷新后选择。')
            place = next((plan['place'] for plan in plan_set.get('plans', [])
                          if plan.get('place', {}).get('poi_id') == poi_id), None)
            if not place:
                raise Conflict('PLAN_NOT_FOUND', '所选门店不在当前方案中。')
            await self.clear_pending_action(owner, thread)
            message = f"请重查{place['name']}这家店。"
            run = await self.repo.accept(owner, thread, request_id, message,
                                         expected_revision, patch, poi_id, plan_set_id)
            return await self.execute(run)

    async def clear_pending_action(self, owner, thread):
        pending = await self.repo.actions.latest(owner, thread)
        if pending and pending['status'] == 'awaiting_confirmation':
            action_id = pending['action_id']
            await self.repo.actions.invalidate(action_id, 'new_message')
            config = {'configurable':{'thread_id':thread},'recursion_limit':25}
            checkpoint = await self.graph.aget_state(config)
            if checkpoint.next and checkpoint.values.get('action_id') == action_id:
                if 'await_confirmation' in checkpoint.next:
                    await self.graph.ainvoke(Command(resume={'action_id':action_id}),config,durability='sync')
                else:
                    await self.graph.ainvoke(None,config,durability='sync')
        elif pending and pending['status'] in ('authorized','claimed'):
            raise AppError('ACTION_RECOVERY_REQUIRED','请先恢复上一项已确认动作。',409)
        elif pending and pending['status'] in ('rejected','invalidated'):
            await self.resume_action(owner, await self.repo.actions.get(owner,pending['action_id']))

    async def prepare_action(self, owner, thread, request_id, plan_set_id, plan_id, kind, expected_revision):
        async with self.slots, self.repo.guard(owner,thread):
            previous = await self.repo.actions.latest(owner, thread)
            if previous and previous['status'] in ('rejected','invalidated'):
                await self.resume_action(owner, await self.repo.actions.get(owner,previous['action_id']))
            if not await self.repo.actions.by_request(owner, thread, request_id):
                plan = await self.repo.actions.plan_for_prepare(
                    owner, thread, plan_set_id, plan_id, expected_revision)
                advertised = plan.get('live_info')
                if advertised:
                    from services.merchant_live import live_snapshot_current
                    try:
                        result = await self.planner.merchant_live.read(plan['place'])
                    except Exception:
                        result = None
                    if not live_snapshot_current(advertised, result['info'] if result else None):
                        raise Conflict('MERCHANT_STATE_CHANGED',
                                       '商家实时状态已过期、变化或暂时不可核实，请重新生成方案后确认。')
            row = await self.repo.actions.prepare(owner, thread, request_id, plan_set_id, plan_id,
                                                  kind, expected_revision)
            if row['status'] != 'awaiting_confirmation':
                return public_action(row)
            config = {'configurable':{'thread_id':thread},'recursion_limit':25}
            checkpoint = await self.graph.aget_state(config)
            if checkpoint.next and checkpoint.values.get('action_id') == str(row['action_id']):
                if 'await_confirmation' not in checkpoint.next:
                    await self.graph.ainvoke(None,config,durability='sync')
            else:
                await self.graph.ainvoke({'event_kind':'action','thread_id':thread,
                                          'owner_id':owner,'action_id':str(row['action_id'])},
                                         config,durability='sync')
            checkpoint = await self.graph.aget_state(config)
            if 'await_confirmation' not in checkpoint.next:
                raise AppError('ACTION_CHECKPOINT_MISSING','确认中断尚未保存，请用相同 request_id 重试。',503)
            return public_action(await self.repo.actions.get(owner, str(row['action_id'])))

    async def decide_action(self, owner, action_id, decision_request_id, version, proposal_digest, approve):
        row = await self.repo.actions.get(owner, action_id)
        thread = str(row['thread_id'])
        async with self.slots, self.repo.guard(owner,thread):
            row = await self.repo.actions.decide(owner, action_id, decision_request_id,
                                                 version, proposal_digest, approve)
            return await self.resume_action(owner, row)

    async def recover_action(self, owner, action_id):
        row = await self.repo.actions.get(owner, action_id)
        async with self.slots, self.repo.guard(owner,str(row['thread_id'])):
            if row['status'] == 'awaiting_confirmation':
                return public_action(row)
            return await self.resume_action(owner, row)

    async def resume_action(self, owner, row):
        if row['status'] == 'completed':
            return public_action(row)
        thread, action_id = str(row['thread_id']), str(row['action_id'])
        config = {'configurable':{'thread_id':thread},'recursion_limit':25}
        for _ in range(4):
            checkpoint = await self.graph.aget_state(config)
            current = await self.repo.actions.get(owner, action_id)
            if not checkpoint.next:
                if current['status'] in ('rejected','invalidated','completed'):
                    return public_action(current)
                raise AppError('ACTION_CHECKPOINT_MISSING','动作检查点不可恢复；未重复执行。',409)
            if checkpoint.values.get('action_id') != action_id:
                raise AppError('ACTION_CHECKPOINT_MISMATCH','当前会话正在恢复另一项动作。',409)
            graph_input = (Command(resume={'action_id':action_id})
                           if 'await_confirmation' in checkpoint.next else None)
            await self.graph.ainvoke(graph_input,config,durability='sync')
        raise AppError('ACTION_RECOVERY_INCOMPLETE','动作仍在恢复中，请重试同一请求。',503)

    async def retry(self, owner, thread, run_id):
        async with self.slots, self.repo.guard(owner,thread):
            run = await self.repo.run(run_id)
            if not run or str(run['thread_id']) != thread:
                raise AppError('NOT_FOUND','运行记录不存在。',404)
            return await self.execute(run)

    async def execute(self, run):
        if run['status'] == 'completed':
            return run['output']
        run_id = str(run['run_id'])
        config = {'configurable':{'thread_id':str(run['thread_id'])},'recursion_limit':20}
        try:
            checkpoint = await self.graph.aget_state(config)
            same_run = checkpoint.values.get('run_id') == run_id
            if same_run and not checkpoint.next and run['output']:
                result = {'output':run['output']}
            else:
                graph_input = None if same_run and checkpoint.next else {'event_kind':'chat',
                    'thread_id':str(run['thread_id']),'run_id':run_id}
                result = await self.graph.ainvoke(graph_input,config,durability='sync')
            await self.repo.complete(run_id)
            return result['output']
        except Exception as exc:
            error = exc if isinstance(exc,AppError) else AppError('RUN_FAILED','本轮未完成，已保留进度。请重试本条消息。')
            try:
                await self.repo.fail(run_id,error.code)
            except Exception:
                pass  # Original error remains safe even when the database is unreachable.
            raise error from None
