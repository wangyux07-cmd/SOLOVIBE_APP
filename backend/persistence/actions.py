"""Durable authorization ledger. PostgreSQL rows, not graph state, authorize effects."""
import hashlib
import json
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from psycopg.types.json import Jsonb

from domain.errors import AppError, Conflict


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def public_action(row):
    return {key: str(row[key]) if key in ('action_id', 'thread_id', 'plan_set_id') else row[key]
            for key in ('action_id', 'thread_id', 'plan_set_id', 'plan_id', 'kind',
                        'context_revision', 'proposal_version', 'proposal_digest',
                        'plan_snapshot', 'status', 'receipt', 'expires_at',
                        'handoff_requested_at')}


class ActionRepository:
    def __init__(self, pool):
        self.pool = pool

    async def get(self, owner, action_id):
        async with self.pool.connection() as conn:
            row = await (await conn.execute(
                'SELECT * FROM solovibe_v1.actions WHERE action_id=%s AND owner_id=%s',
                (action_id, owner))).fetchone()
        if not row:
            raise AppError('NOT_FOUND', '动作不存在或不属于当前浏览器。', 404)
        return row

    async def latest(self, owner, thread):
        async with self.pool.connection() as conn:
            row = await (await conn.execute('''SELECT a.* FROM solovibe_v1.actions a
                JOIN solovibe_v1.conversations c ON c.thread_id=a.thread_id
                WHERE a.thread_id=%s AND c.owner_id=%s ORDER BY a.created_at DESC LIMIT 1''',
                (thread, owner))).fetchone()
        return public_action(row) if row else None

    async def by_request(self, owner, thread, request_id):
        async with self.pool.connection() as conn:
            return await (await conn.execute('''SELECT a.* FROM solovibe_v1.actions a
                JOIN solovibe_v1.conversations c ON c.thread_id=a.thread_id
                WHERE a.thread_id=%s AND a.request_id=%s AND a.owner_id=%s AND c.owner_id=%s''',
                (thread, request_id, owner, owner))).fetchone()

    async def plan_for_prepare(self, owner, thread, plan_set_id, plan_id, revision):
        async with self.pool.connection() as conn:
            row = await (await conn.execute('''SELECT p.payload FROM solovibe_v1.plan_sets p
                JOIN solovibe_v1.conversations c ON c.thread_id=p.thread_id
                JOIN solovibe_v1.runs r ON r.run_id=p.run_id AND r.status='completed'
                WHERE p.run_id=%s AND p.thread_id=%s AND p.context_revision=%s AND c.owner_id=%s''',
                (plan_set_id, thread, revision, owner))).fetchone()
        if not row:
            raise Conflict('PLAN_STALE', '方案集已失效，请重新生成。')
        plan = next((item for item in row['payload'].get('plans', [])
                     if item.get('plan_id') == plan_id), None)
        if not plan:
            raise Conflict('PLAN_NOT_FOUND', '所选地点不在该版本方案中。')
        return plan

    async def prepare(self, owner, thread, request_id, plan_set_id, plan_id, kind, revision):
        fingerprint = digest([plan_set_id, plan_id, kind, revision])
        async with self.pool.connection() as conn, conn.transaction():
            conversation = await (await conn.execute('''SELECT * FROM solovibe_v1.conversations
                WHERE thread_id=%s AND owner_id=%s FOR UPDATE''', (thread, owner))).fetchone()
            if not conversation:
                raise AppError('NOT_FOUND', '会话不存在。', 404)
            prior = await (await conn.execute('''SELECT * FROM solovibe_v1.actions
                WHERE thread_id=%s AND request_id=%s''', (thread, request_id))).fetchone()
            if prior:
                if prior['fingerprint'] != fingerprint:
                    raise Conflict('REQUEST_ID_REUSED', '同一 request_id 不能用于不同动作。')
                return prior
            if conversation['active_run']:
                raise Conflict('PENDING_RUN', '请先完成或重试上一条消息。')
            if conversation['snapshot']['revision'] != revision:
                raise Conflict('STALE_REVISION', '出行条件已改变，请刷新方案。')
            pending = await (await conn.execute('''SELECT action_id FROM solovibe_v1.actions
                WHERE thread_id=%s AND status IN ('awaiting_confirmation','authorized','claimed')''',
                (thread,))).fetchone()
            if pending:
                raise Conflict('PENDING_ACTION', '请先处理当前待确认动作。')
            plan_set = await (await conn.execute('''SELECT p.* FROM solovibe_v1.plan_sets p
                JOIN solovibe_v1.runs r ON r.run_id=p.run_id AND r.status='completed'
                WHERE p.run_id=%s AND p.thread_id=%s AND p.context_revision=%s''',
                (plan_set_id, thread, revision))).fetchone()
            if not plan_set:
                raise Conflict('PLAN_STALE', '方案集已失效，请重新生成。')
            latest = await (await conn.execute('''SELECT p.run_id FROM solovibe_v1.plan_sets p
                JOIN solovibe_v1.runs r ON r.run_id=p.run_id AND r.status='completed'
                WHERE p.thread_id=%s AND p.context_revision=%s
                ORDER BY p.created_at DESC LIMIT 1''', (thread, revision))).fetchone()
            if not latest or str(latest['run_id']) != plan_set_id:
                raise Conflict('PLAN_STALE', '已有更新的方案集，请刷新后选择。')
            plan = next((p for p in plan_set['payload'].get('plans', []) if p['plan_id'] == plan_id), None)
            if not plan or plan.get('context_revision') != revision:
                raise Conflict('PLAN_NOT_FOUND', '所选地点不在该版本方案中。')
            for offer in (plan.get('public_info') or {}).get('offers', []):
                try:
                    expiry = datetime.fromisoformat(offer['valid_until'])
                except (KeyError, TypeError, ValueError):
                    raise Conflict('OFFER_STALE', '优惠证据无效，请重新生成方案。') from None
                if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
                    raise Conflict('OFFER_STALE', '优惠已过期，请重新生成方案。')
            live = plan.get('live_info')
            if live:
                try:
                    live_expiry = datetime.fromisoformat(live['valid_until'])
                except (KeyError, TypeError, ValueError):
                    raise Conflict('MERCHANT_STATE_STALE', '商家状态证据无效，请重新生成方案。') from None
                if live_expiry.tzinfo is None or live_expiry <= datetime.now(timezone.utc):
                    raise Conflict('MERCHANT_STATE_STALE', '商家状态已过期，请重新生成方案。')
            try:
                observed = [datetime.fromisoformat(plan[key]['observed_at'].replace('Z', '+00:00'))
                            for key in ('place','route')]
                if plan.get('itinerary'):
                    observed.extend(datetime.fromisoformat(stop['place']['observed_at'].replace('Z', '+00:00'))
                                    for stop in plan['itinerary']['stops'])
                    observed.extend(datetime.fromisoformat(leg['route']['observed_at'].replace('Z', '+00:00'))
                                    for leg in plan['itinerary']['legs'])
            except (KeyError, TypeError, ValueError):
                raise Conflict('PLAN_STALE', '方案缺少可验证的时间信息，请重新生成。') from None
            if any(value.tzinfo is None or datetime.now(timezone.utc) - value > timedelta(minutes=30)
                   or value > datetime.now(timezone.utc) + timedelta(minutes=1) for value in observed):
                raise Conflict('PLAN_STALE', '地点或路线资料已过期，请重新生成方案。')
            proposal = {'thread_id': thread, 'plan_set_id': plan_set_id, 'plan_id': plan_id,
                        'kind': kind, 'revision': revision, 'plan': plan}
            action_id = str(uuid4())
            return await (await conn.execute('''INSERT INTO solovibe_v1.actions
                (action_id,thread_id,owner_id,plan_set_id,plan_id,context_revision,kind,
                 request_id,fingerprint,proposal_digest,plan_snapshot,context_snapshot,status,expires_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'awaiting_confirmation',
                        now() + interval '15 minutes') RETURNING *''',
                (action_id, thread, owner, plan_set_id, plan_id, revision, kind, request_id,
                 fingerprint, digest(proposal), Jsonb(plan), Jsonb(conversation['snapshot'])))).fetchone()

    async def decide(self, owner, action_id, decision_request_id, version, proposal_digest, approve):
        async with self.pool.connection() as conn, conn.transaction():
            row = await (await conn.execute('''SELECT a.* FROM solovibe_v1.actions a
                JOIN solovibe_v1.conversations c ON c.thread_id=a.thread_id
                WHERE a.action_id=%s AND a.owner_id=%s AND c.owner_id=%s FOR UPDATE OF a''',
                (action_id, owner, owner))).fetchone()
            if not row:
                raise AppError('NOT_FOUND', '动作不存在。', 404)
            if row['proposal_version'] != version or row['proposal_digest'] != proposal_digest:
                raise Conflict('PROPOSAL_MISMATCH', '确认信息与原提案不一致。')
            if row['decision_request_id']:
                if str(row['decision_request_id']) != decision_request_id or (approve and row['status'] == 'rejected') or (not approve and row['status'] != 'rejected'):
                    raise Conflict('ALREADY_DECIDED', '该动作已有不同的确认决定。')
                return row
            if row['status'] != 'awaiting_confirmation':
                raise Conflict('ACTION_NOT_PENDING', '该动作不再等待确认。')
            if row['expires_at'] <= datetime.now(timezone.utc):
                return await (await conn.execute("UPDATE solovibe_v1.actions SET status='invalidated',receipt=%s,updated_at=now() WHERE action_id=%s RETURNING *",
                                                (Jsonb({'reason':'expired'}), action_id))).fetchone()
            conversation = await (await conn.execute('''SELECT snapshot,active_run FROM solovibe_v1.conversations
                WHERE thread_id=%s FOR UPDATE''', (row['thread_id'],))).fetchone()
            if conversation['active_run'] or conversation['snapshot']['revision'] != row['context_revision']:
                return await (await conn.execute("UPDATE solovibe_v1.actions SET status='invalidated',receipt=%s,updated_at=now() WHERE action_id=%s RETURNING *",
                                                (Jsonb({'reason':'context_changed'}), action_id))).fetchone()
            return await (await conn.execute('''UPDATE solovibe_v1.actions SET status=%s,
                decision_request_id=%s,updated_at=now() WHERE action_id=%s RETURNING *''',
                ('authorized' if approve else 'rejected', decision_request_id, action_id))).fetchone()

    async def invalidate(self, action_id, reason):
        async with self.pool.connection() as conn:
            await conn.execute('''UPDATE solovibe_v1.actions SET status='invalidated',
                receipt=%s,updated_at=now() WHERE action_id=%s AND status IN
                ('awaiting_confirmation','authorized')''', (Jsonb({'reason': reason}), action_id))

    async def claim(self, action_id):
        async with self.pool.connection() as conn, conn.transaction():
            row = await (await conn.execute('SELECT * FROM solovibe_v1.actions WHERE action_id=%s FOR UPDATE',
                                            (action_id,))).fetchone()
            if row['status'] in ('claimed', 'completed'):
                return row
            if row['status'] != 'authorized':
                raise Conflict('ACTION_NOT_AUTHORIZED', '动作尚未获得有效确认。')
            if row['expires_at'] <= datetime.now(timezone.utc):
                return await (await conn.execute("UPDATE solovibe_v1.actions SET status='invalidated',receipt=%s,updated_at=now() WHERE action_id=%s RETURNING *",
                                                (Jsonb({'reason':'expired'}), action_id))).fetchone()
            current = await (await conn.execute('''SELECT snapshot,active_run FROM solovibe_v1.conversations
                WHERE thread_id=%s FOR UPDATE''', (row['thread_id'],))).fetchone()
            if current['active_run'] or current['snapshot']['revision'] != row['context_revision']:
                return await (await conn.execute("UPDATE solovibe_v1.actions SET status='invalidated',receipt=%s,updated_at=now() WHERE action_id=%s RETURNING *",
                                                (Jsonb({'reason':'context_changed'}), action_id))).fetchone()
            return await (await conn.execute('''UPDATE solovibe_v1.actions SET status='claimed',updated_at=now()
                WHERE action_id=%s RETURNING *''', (action_id,))).fetchone()

    async def finish(self, action_id, receipt):
        async with self.pool.connection() as conn, conn.transaction():
            row = await (await conn.execute('SELECT * FROM solovibe_v1.actions WHERE action_id=%s FOR UPDATE',
                                            (action_id,))).fetchone()
            if row['status'] == 'completed':
                return row
            if row['status'] != 'claimed':
                raise Conflict('ACTION_NOT_CLAIMED', '动作尚未领取。')
            if row['kind'] == 'save':
                await conn.execute('''INSERT INTO solovibe_v1.saved_plans(action_id,thread_id,plan_snapshot)
                    VALUES (%s,%s,%s) ON CONFLICT (action_id) DO NOTHING''',
                    (action_id,row['thread_id'],Jsonb(row['plan_snapshot'])))
            return await (await conn.execute('''UPDATE solovibe_v1.actions SET status='completed',
                receipt=%s,updated_at=now() WHERE action_id=%s RETURNING *''',
                (Jsonb(receipt), action_id))).fetchone()

    async def record_handoff(self, owner, action_id, request_id):
        async with self.pool.connection() as conn, conn.transaction():
            row = await (await conn.execute('''SELECT * FROM solovibe_v1.actions
                WHERE action_id=%s AND owner_id=%s FOR UPDATE''', (action_id, owner))).fetchone()
            if not row:
                raise AppError('NOT_FOUND', '动作不存在。', 404)
            if row['status'] != 'completed' or row['kind'] != 'navigate' or row['receipt']['kind'] != 'navigation_handoff_ready':
                raise Conflict('HANDOFF_NOT_READY', '导航链接尚未完成准备。')
            if row['handoff_request_id']:
                if str(row['handoff_request_id']) != request_id:
                    return row  # Repeated clicks keep the first request timestamp.
                return row
            return await (await conn.execute('''UPDATE solovibe_v1.actions SET
                handoff_requested_at=now(),handoff_request_id=%s,updated_at=now()
                WHERE action_id=%s RETURNING *''', (request_id, action_id))).fetchone()
