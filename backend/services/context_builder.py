"""Build bounded model input from authoritative state, raw turns and lossy history."""
import os
import json

from domain.errors import AppError, Conflict
from domain.token_budget import estimate_call, estimate_text, input_budget
from services.model_client import SUMMARY_PROMPT, SYSTEM_PROMPT


def summary_input(row):
    return {'historical_record_only': True, 'content': row['content']} if row else None


class ContextBuilder:
    def __init__(self, repository, model):
        self.repository = repository
        self.model = model
        self.node_cap = int(os.getenv('SOLOVIBE_UNDERSTAND_INPUT_TOKENS', '8000'))
        if not 512 <= self.node_cap <= 16000:
            raise AppError('CONTEXT_CONFIG_INVALID', '理解节点的输入预算配置无效。')

    def limit(self):
        window = self.model.context_window
        if not isinstance(window, int):
            raise AppError('MODEL_CAPABILITY_UNKNOWN', '模型上下文窗口尚未核实。')
        value = input_budget(window, self.node_cap)
        if value < 512:
            raise AppError('CONTEXT_CONFIG_INVALID', '模型窗口不足以容纳保留输出和安全余量。')
        return value

    @staticmethod
    def estimate(snapshot, history, message, summary):
        return estimate_call(SYSTEM_PROMPT, {
            'context': snapshot, 'rolling_summary': summary_input(summary),
            'recent_messages': history, 'current_message': message,
        })

    @staticmethod
    def select_batch(previous, candidates, cap):
        chosen = []
        for pair_start in range(0, len(candidates) - 1, 2):
            pair = candidates[pair_start:pair_start + 2]
            if [row['role'] for row in pair] != ['user', 'assistant']:
                break
            next_rows = chosen + pair
            estimated = estimate_call(SUMMARY_PROMPT, {
                'previous_summary': previous['content'] if previous else None,
                'completed_history': next_rows,
            })
            if estimated > cap:
                break
            chosen = next_rows
        return chosen

    async def build(self, thread, run_id, snapshot, message, old_summary):
        limit = self.limit()
        summary = old_summary
        cursor = summary['covered_until_sequence'] if summary else 0
        history = await self.repository.history(thread, run_id, cursor)
        estimated = self.estimate(snapshot, history, message, summary)
        compacted = 0
        degraded = False
        attempts = 0
        summary_failure_code = None
        while estimated >= int(limit * 0.8) and len(history) > 8 and compacted < 6:
            candidates = history[:-8]
            batch_cap = min(6000, self.model.context_window - 800 - 1024)
            batch = self.select_batch(summary, candidates, batch_cap)
            if not batch:
                break
            attempts += 1
            try:
                draft, _ = await self.model.summarize_history(
                    summary['content'] if summary else None, batch, batch_cap)
                summary = await self.repository.advance_summary(
                    thread, run_id, summary, batch, draft,
                    estimate_text(json.dumps(draft, ensure_ascii=False)),
                    snapshot['revision'])
            except Conflict:
                raise
            except AppError as exc:
                summary_failure_code = exc.code
                # A failed summarizer cannot advance the cursor. Retain the
                # old record and use the exact recent turns only if they fit.
                if estimated > limit:
                    recent = history[-8:]
                    if self.estimate(snapshot, recent, message, summary) > limit:
                        raise AppError('CONTEXT_OVERFLOW', '摘要失败且近期对话仍超出输入预算。', 413) from None
                    history = recent
                    degraded = True
                break
            history = history[len(batch):]
            compacted += 1
            estimated = self.estimate(snapshot, history, message, summary)
            if estimated <= int(limit * 0.6):
                break
        estimated = self.estimate(snapshot, history, message, summary)
        if estimated > limit:
            raise AppError('CONTEXT_OVERFLOW', '当前输入与必要近期对话超出模型输入预算，未截断原文。', 413)
        return {'recent_messages': history, 'rolling_summary': summary_input(summary),
                'context_budget': {'estimated_input_tokens': estimated, 'input_limit': limit,
                                   'summary_revision': summary['revision'] if summary else 0,
                                   'summary_attempts': attempts, 'compaction_calls': compacted,
                                   'summary_failure_code': summary_failure_code,
                                   'degraded': degraded}}
