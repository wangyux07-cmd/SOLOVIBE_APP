import hashlib
import json
import secrets
from contextlib import asynccontextmanager
from uuid import uuid4

from psycopg.types.json import Jsonb

from domain.context import ContextSnapshot, Understanding, apply_patch
from domain.errors import AppError, Conflict
from persistence.actions import ActionRepository, public_action


class Repository:
    def __init__(self, pool):
        self.pool = pool
        self.actions = ActionRepository(pool)

    async def owner(self, token: str | None) -> str | None:
        if not token or len(token) > 128:
            return None
        async with self.pool.connection() as conn:
            row = await (await conn.execute(
                "SELECT owner_id FROM solovibe_v1.sessions WHERE token_hash=%s AND expires_at>now()",
                (hashlib.sha256(token.encode()).hexdigest(),),
            )).fetchone()
        return str(row['owner_id']) if row else None

    async def session(self, token):
        owner = await self.owner(token)
        if owner:
            return owner, token
        token, owner = secrets.token_urlsafe(32), str(uuid4())
        async with self.pool.connection() as conn:
            await conn.execute("INSERT INTO solovibe_v1.sessions(owner_id,token_hash) VALUES (%s,%s)",
                               (owner, hashlib.sha256(token.encode()).hexdigest()))
        return owner, token

    async def create(self, owner):
        thread = str(uuid4())
        async with self.pool.connection() as conn:
            await conn.execute("INSERT INTO solovibe_v1.conversations(thread_id,owner_id,snapshot) VALUES (%s,%s,%s)",
                               (thread, owner, Jsonb(ContextSnapshot().model_dump())))
        return await self.read(owner, thread)

    async def list_threads(self, owner):
        async with self.pool.connection() as conn:
            return await (await conn.execute(
                "SELECT thread_id,created_at FROM solovibe_v1.conversations WHERE owner_id=%s ORDER BY created_at DESC LIMIT 50", (owner,),
            )).fetchall()

    async def read(self, owner, thread):
        async with self.pool.connection() as conn:
            row = await (await conn.execute("SELECT * FROM solovibe_v1.conversations WHERE thread_id=%s AND owner_id=%s", (thread, owner))).fetchone()
            if not row:
                raise AppError('NOT_FOUND', '会话不存在或不属于当前浏览器。', 404)
            messages = await (await conn.execute(
                "SELECT message_id,role,content,sequence FROM (SELECT * FROM solovibe_v1.messages WHERE thread_id=%s ORDER BY sequence DESC LIMIT 100) m ORDER BY sequence", (thread,),
            )).fetchall()
            pending = None
            if row['active_run']:
                pending = await (await conn.execute("SELECT run_id,status,error_code FROM solovibe_v1.runs WHERE run_id=%s", (row['active_run'],))).fetchone()
            summary = await (await conn.execute(
                'SELECT revision,covered_until_sequence FROM solovibe_v1.rolling_summaries WHERE thread_id=%s',
                (thread,),
            )).fetchone()
            plan_set = await (await conn.execute(
                '''SELECT p.run_id,p.payload FROM solovibe_v1.plan_sets p
                   JOIN solovibe_v1.runs r ON r.run_id=p.run_id AND r.status='completed'
                   WHERE p.thread_id=%s AND p.context_revision=%s
                   ORDER BY p.created_at DESC LIMIT 1''',
                (thread, row['snapshot']['revision']),
            )).fetchone()
            action = await (await conn.execute('''SELECT * FROM solovibe_v1.actions
                WHERE thread_id=%s ORDER BY created_at DESC LIMIT 1''', (thread,))).fetchone()
            saved = await (await conn.execute('''SELECT action_id,plan_snapshot,saved_at
                FROM solovibe_v1.saved_plans WHERE thread_id=%s ORDER BY saved_at DESC LIMIT 20''',
                (thread,))).fetchall()
        return {'thread_id': str(row['thread_id']), 'snapshot': row['snapshot'], 'messages': messages,
                'pending_run': pending,
                'plan_set': {**plan_set['payload'], 'plan_set_id': str(plan_set['run_id'])} if plan_set else None,
                'latest_action': public_action(action) if action else None,
                'saved_plans': [{'action_id':str(item['action_id']),
                                 'plan_snapshot':item['plan_snapshot'], 'saved_at':item['saved_at']}
                                for item in saved],
                'context_memory': {'summary_revision': summary['revision'] if summary else 0,
                                   'covered_until_sequence': summary['covered_until_sequence'] if summary else 0,
                                   'raw_messages_retained': True}}

    @asynccontextmanager
    async def guard(self, owner, thread):
        # Session lock survives short transactions, but never holds a transaction during HTTP.
        # Requires direct PostgreSQL or a SESSION pooler, not transaction pooling.
        await self.read(owner, thread)
        async with self.pool.connection() as conn:
            locked = await (await conn.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, 7314)) AS acquired", (thread,))).fetchone()
            if not locked['acquired']:
                raise Conflict('THREAD_BUSY', '此会话正在处理另一条消息，请稍后重试。')
            try:
                yield
            finally:
                await conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 7314))", (thread,))

    async def accept(self, owner, thread, request_id, message, expected_revision):
        fingerprint = hashlib.sha256(f'{expected_revision}\n{message}'.encode()).hexdigest()
        async with self.pool.connection() as conn, conn.transaction():
            conversation = await (await conn.execute("SELECT * FROM solovibe_v1.conversations WHERE thread_id=%s AND owner_id=%s FOR UPDATE", (thread, owner))).fetchone()
            if not conversation:
                raise AppError('NOT_FOUND', '会话不存在。', 404)
            run = await (await conn.execute("SELECT * FROM solovibe_v1.runs WHERE thread_id=%s AND request_id=%s", (thread, request_id))).fetchone()
            if run:
                if run['fingerprint'] != fingerprint:
                    raise Conflict('REQUEST_ID_REUSED', '同一个 request_id 不能用于不同消息或版本。')
                return run
            if conversation['active_run']:
                raise Conflict('PENDING_RUN', '请先重试上一条尚未完成的消息。')
            if conversation['snapshot']['revision'] != expected_revision:
                raise Conflict('STALE_REVISION', '状态已有更新，请刷新后重新发送。')
            run_id, message_id = str(uuid4()), str(uuid4())
            run = await (await conn.execute(
                "INSERT INTO solovibe_v1.runs(run_id,thread_id,request_id,fingerprint,message_id,input_text,base_snapshot) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                (run_id,thread,request_id,fingerprint,message_id,message,Jsonb(conversation['snapshot'])),
            )).fetchone()
            await conn.execute("UPDATE solovibe_v1.conversations SET active_run=%s,sequence=sequence+1 WHERE thread_id=%s", (run_id,thread))
            await conn.execute("INSERT INTO solovibe_v1.messages VALUES (%s,%s,%s,%s,'user',%s)", (message_id,thread,run_id,conversation['sequence']+1,message))
            return run

    async def run(self, run_id):
        async with self.pool.connection() as conn:
            return await (await conn.execute("SELECT * FROM solovibe_v1.runs WHERE run_id=%s", (run_id,))).fetchone()

    async def request_run(self, thread, request_id):
        async with self.pool.connection() as conn:
            return await (await conn.execute("SELECT * FROM solovibe_v1.runs WHERE thread_id=%s AND request_id=%s",
                                             (thread, request_id))).fetchone()

    async def recent(self, thread, run_id):
        async with self.pool.connection() as conn:
            rows = await (await conn.execute(
                "SELECT m.role,m.content FROM solovibe_v1.messages m JOIN solovibe_v1.runs r USING(run_id) WHERE m.thread_id=%s AND r.status='completed' AND r.run_id<>%s ORDER BY m.sequence DESC LIMIT 12", (thread,run_id),
            )).fetchall()
        return list(reversed(rows))

    async def summary(self, thread):
        async with self.pool.connection() as conn:
            return await (await conn.execute(
                'SELECT * FROM solovibe_v1.rolling_summaries WHERE thread_id=%s', (thread,),
            )).fetchone()

    async def history(self, thread, run_id, after_sequence):
        async with self.pool.connection() as conn:
            return await (await conn.execute('''
                SELECT m.sequence,m.role,m.content FROM solovibe_v1.messages m
                JOIN solovibe_v1.runs r USING(run_id)
                WHERE m.thread_id=%s AND m.sequence>%s AND r.status='completed' AND r.run_id<>%s
                ORDER BY m.sequence
            ''', (thread, after_sequence, run_id))).fetchall()

    async def advance_summary(self, thread, run_id, old_summary, rows, content, token_estimate,
                              context_revision):
        if not rows or rows[-1]['role'] != 'assistant':
            raise AppError('SUMMARY_RANGE_INVALID', '摘要范围必须以已完成回合结束。')
        old_cursor = old_summary['covered_until_sequence'] if old_summary else 0
        old_revision = old_summary['revision'] if old_summary else 0
        digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        async with self.pool.connection() as conn, conn.transaction():
            conversation = await (await conn.execute(
                'SELECT snapshot,active_run FROM solovibe_v1.conversations WHERE thread_id=%s FOR UPDATE',
                (thread,),
            )).fetchone()
            if not conversation or str(conversation['active_run']) != run_id or conversation['snapshot']['revision'] != context_revision:
                raise Conflict('SUMMARY_STALE', '摘要期间状态已经改变，旧结果未写入。')
            current = await (await conn.execute(
                'SELECT revision,covered_until_sequence FROM solovibe_v1.rolling_summaries WHERE thread_id=%s FOR UPDATE',
                (thread,),
            )).fetchone()
            if (current['revision'] if current else 0) != old_revision or (current['covered_until_sequence'] if current else 0) != old_cursor:
                raise Conflict('SUMMARY_STALE', '摘要游标已经改变，旧结果未写入。')
            actual = await (await conn.execute('''
                SELECT m.sequence,m.role,m.content FROM solovibe_v1.messages m
                JOIN solovibe_v1.runs r USING(run_id)
                WHERE m.thread_id=%s AND m.sequence>%s AND m.sequence<=%s AND r.status='completed'
                ORDER BY m.sequence
            ''', (thread, old_cursor, rows[-1]['sequence']))).fetchall()
            if actual != rows or rows[0]['sequence'] != old_cursor + 1:
                raise Conflict('SUMMARY_RANGE_INVALID', '原文范围已变化，摘要没有覆盖完整前缀。')
            values = (thread, str(uuid4()), old_revision + 1, rows[-1]['sequence'],
                      rows[0]['sequence'], rows[-1]['sequence'], digest, context_revision,
                      Jsonb(content), token_estimate)
            await conn.execute('''
                INSERT INTO solovibe_v1.rolling_summaries
                (thread_id,summary_id,revision,covered_until_sequence,source_first_sequence,
                 source_last_sequence,source_digest,based_on_context_revision,content,token_estimate)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (thread_id) DO UPDATE SET
                  summary_id=EXCLUDED.summary_id,revision=EXCLUDED.revision,
                  covered_until_sequence=EXCLUDED.covered_until_sequence,
                  source_first_sequence=EXCLUDED.source_first_sequence,
                  source_last_sequence=EXCLUDED.source_last_sequence,
                  source_digest=EXCLUDED.source_digest,
                  based_on_context_revision=EXCLUDED.based_on_context_revision,
                  content=EXCLUDED.content,token_estimate=EXCLUDED.token_estimate,
                  generated_at=now()
            ''', values)
        return await self.summary(thread)

    async def commit(self, run_id, proposal, meta):
        async with self.pool.connection() as conn, conn.transaction():
            run = await (await conn.execute("SELECT * FROM solovibe_v1.runs WHERE run_id=%s FOR UPDATE", (run_id,))).fetchone()
            if run['committed_snapshot'] is not None:
                return run['committed_snapshot']
            snapshot = apply_patch(ContextSnapshot.model_validate(run['base_snapshot']), Understanding.model_validate(proposal), run['input_text'], str(run['message_id'])).model_dump()
            updated = await conn.execute("UPDATE solovibe_v1.conversations SET snapshot=%s WHERE thread_id=%s AND active_run=%s AND (snapshot->>'revision')::int=%s", (Jsonb(snapshot),run['thread_id'],run_id,run['base_snapshot']['revision']))
            if updated.rowcount != 1:
                raise Conflict('STATE_CONFLICT', '运行状态发生冲突，未覆盖已有状态。')
            await conn.execute("UPDATE solovibe_v1.runs SET committed_snapshot=%s,model_meta=%s WHERE run_id=%s", (Jsonb(snapshot),Jsonb(meta),run_id))
            return snapshot

    async def save_reply(self, run_id, reply):
        async with self.pool.connection() as conn, conn.transaction():
            run = await (await conn.execute("SELECT * FROM solovibe_v1.runs WHERE run_id=%s FOR UPDATE", (run_id,))).fetchone()
            if run['output'] is not None:
                return run['output']
            output = {**reply, 'thread_id':str(run['thread_id']), 'run_id':str(run_id), 'request_id':str(run['request_id']), 'snapshot':run['committed_snapshot'], 'model':run['model_meta']}
            row = await (await conn.execute("UPDATE solovibe_v1.conversations SET sequence=sequence+1 WHERE thread_id=%s RETURNING sequence", (run['thread_id'],))).fetchone()
            await conn.execute("INSERT INTO solovibe_v1.messages VALUES (%s,%s,%s,%s,'assistant',%s)", (uuid4(),run['thread_id'],run_id,row['sequence'],reply['response']))
            await conn.execute("UPDATE solovibe_v1.runs SET output=%s WHERE run_id=%s", (Jsonb(output),run_id))
            if 'plans' in reply:
                await conn.execute('''INSERT INTO solovibe_v1.plan_sets(run_id,thread_id,context_revision,payload)
                    VALUES (%s,%s,%s,%s) ON CONFLICT (run_id) DO NOTHING''',
                    (run_id,run['thread_id'],run['committed_snapshot']['revision'],Jsonb(reply)))
            return output

    async def complete(self, run_id):
        async with self.pool.connection() as conn, conn.transaction():
            completed = await conn.execute("UPDATE solovibe_v1.runs SET status='completed',error_code=NULL WHERE run_id=%s AND output IS NOT NULL", (run_id,))
            if completed.rowcount != 1:
                raise AppError('RUN_OUTPUT_MISSING','图运行没有产生可保存的回复，不能结束本轮。')
            await conn.execute("UPDATE solovibe_v1.conversations SET active_run=NULL WHERE active_run=%s", (run_id,))

    async def fail(self, run_id, code):
        async with self.pool.connection() as conn:
            await conn.execute("UPDATE solovibe_v1.runs SET status='failed',error_code=%s WHERE run_id=%s AND status<>'completed'", (code,run_id))

    async def event(self, run_id, node, status, elapsed_ms):
        async with self.pool.connection() as conn:
            await conn.execute("INSERT INTO solovibe_v1.node_events(run_id,node,status,elapsed_ms) VALUES (%s,%s,%s,%s)", (run_id,node,status,elapsed_ms))

    async def trace(self, owner, thread, run_id):
        await self.read(owner, thread)
        async with self.pool.connection() as conn:
            return await (await conn.execute("SELECT e.node,e.status,e.elapsed_ms,e.created_at FROM solovibe_v1.node_events e JOIN solovibe_v1.runs r USING(run_id) WHERE e.run_id=%s AND r.thread_id=%s ORDER BY e.id", (run_id,thread))).fetchall()
