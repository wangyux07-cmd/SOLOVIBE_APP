import { useCallback, useEffect, useState } from 'react';
import { ArrowRight, Compass, RefreshCw, RotateCcw } from 'lucide-react';
import { apiUrl } from './api';

type Health = { ready: boolean; stage: string; blocker?: { code: string; message: string } | null };
type Snapshot = { revision: number; constraints: Record<string, string | number | string[] | null>; sources: Record<string, { quote: string; basis: string; revision: number }> };
type Message = { message_id: string; role: 'user' | 'assistant'; content: string; sequence: number };
type Pending = { run_id: string; status: string; error_code: string | null } | null;
type Plan = { plan_id: string; context_revision: number; place: { name: string; address: string; category: string; source_url: string; observed_at: string; poi_id: string }; route: { walking_minutes: number; distance_meters: number; observed_at: string }; facts: { rating: number | null; average_cost_cny: number | null; recorded_hours: string | null; observed_at: string } | null; unknowns: string[]; tradeoff: string; web_status: string; web_sources: { title: string; url: string; identity_status: string }[] };
type PlanSet = { plan_set_id?: string; kind: string; plans: Plan[]; evidence_status: string; provider_errors: string[] };
type Action = { action_id: string; plan_id: string; kind: 'save' | 'navigate'; proposal_version: number; proposal_digest: string;
  plan_snapshot: Plan; status: string; receipt: { kind?: string; url?: string; reason?: string; place_name?: string; note?: string } | null; expires_at: string; handoff_requested_at?: string | null };
type Conversation = { thread_id: string; snapshot: Snapshot; messages: Message[]; pending_run: Pending;
  plan_set: PlanSet | null;
  latest_action?: Action | null;
  context_memory: { summary_revision: number; covered_until_sequence: number; raw_messages_retained: boolean } };
type ChatResult = { response: string; kind: string; run_id: string; snapshot: Snapshot; model: { provider: string; model: string; input_tokens: number | null; output_tokens: number | null; actual_call: boolean } };
type TraceEvent = { node: string; status: string; elapsed_ms: number };

const labels: Record<string, string> = {
  city: '城市', location_text: '所在位置', budget_cny: '预算（元）', available_minutes: '可用时间（分钟）',
  max_walk_minutes: '最多步行（分钟）', energy: '精力', interests: '偏好', exclusions: '避开',
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), { credentials: 'include', cache: 'no-store', ...init });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message || `请求失败（HTTP ${response.status}）`);
  return data as T;
}

const post = { method: 'POST', headers: { 'Content-Type': 'application/json' } };
let bootstrapPromise: Promise<Conversation> | null = null;

async function bootstrap(): Promise<Conversation> {
  await request('/api/session', post);
  const existing = await request<{ conversations: { thread_id: string }[] }>('/api/conversations');
  if (existing.conversations.length) return request(`/api/conversations/${existing.conversations[0].thread_id}`);
  return request('/api/conversations', post);
}

export default function StageOneApp() {
  const [health, setHealth] = useState<Health | null>(null);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [last, setLast] = useState<ChatResult | null>(null);
  const [trace, setTrace] = useState<TraceEvent[]>([]);
  const [action, setAction] = useState<Action | null>(null);

  const refresh = useCallback(async () => {
    try {
      const value = await request<Health>('/api/v1/health');
      setHealth(value);
      if (!value.ready) { setConversation(null); return; }
      bootstrapPromise ??= bootstrap().catch(cause => { bootstrapPromise = null; throw cause; });
      const current = await bootstrapPromise;
      setConversation(current); setAction(current.latest_action ?? null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '服务暂时不可用。');
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  async function reload() {
    if (!conversation) return;
    const current = await request<Conversation>(`/api/conversations/${conversation.thread_id}`);
    setConversation(current); setAction(current.latest_action ?? null);
  }

  async function loadTrace(thread: string, run: string) {
    const result = await request<{ events: TraceEvent[] }>(`/api/conversations/${thread}/runs/${run}/trace`);
    setTrace(result.events);
  }

  async function send() {
    const message = input.trim();
    if (!conversation || !message || busy || conversation.pending_run) return;
    setBusy(true); setError('');
    const requestId = crypto.randomUUID();
    try {
      const result = await request<ChatResult>('/api/chat', {
        ...post, body: JSON.stringify({ thread_id: conversation.thread_id, request_id: requestId,
          expected_revision: conversation.snapshot.revision, message }),
      });
      setLast(result); setInput('');
      await reload();
      await loadTrace(conversation.thread_id, result.run_id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '请求失败。');
      await reload().catch(() => undefined);
    } finally { setBusy(false); }
  }

  async function retry() {
    if (!conversation?.pending_run || busy) return;
    setBusy(true); setError('');
    try {
      const result = await request<ChatResult>(`/api/conversations/${conversation.thread_id}/runs/${conversation.pending_run.run_id}/retry`, post);
      setLast(result);
      await reload();
      await loadTrace(conversation.thread_id, result.run_id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '重试失败。');
      await reload().catch(() => undefined);
    } finally { setBusy(false); }
  }

  async function newConversation() {
    setBusy(true); setError('');
    try {
      const created = await request<Conversation>('/api/conversations', post);
      setConversation(created); setAction(null); setLast(null); setTrace([]); setInput('');
    } catch (cause) { setError(cause instanceof Error ? cause.message : '创建会话失败。'); }
    finally { setBusy(false); }
  }

  async function prepareAction(plan: Plan, kind: 'save' | 'navigate') {
    if (!conversation?.plan_set?.plan_set_id || busy) return;
    setBusy(true); setError('');
    try {
      const result = await request<Action>(`/api/conversations/${conversation.thread_id}/actions`, {
        ...post, body: JSON.stringify({ request_id: crypto.randomUUID(), plan_set_id: conversation.plan_set.plan_set_id,
          plan_id: plan.plan_id, kind, expected_revision: conversation.snapshot.revision }),
      });
      setAction(result);
    } catch (cause) { setError(cause instanceof Error ? cause.message : '无法准备动作。'); await reload().catch(() => undefined); }
    finally { setBusy(false); }
  }

  async function decideAction(approve: boolean) {
    if (!action || busy) return;
    setBusy(true); setError('');
    try {
      const result = await request<Action>(`/api/actions/${action.action_id}/decision`, {
        ...post, body: JSON.stringify({ request_id: crypto.randomUUID(), proposal_version: action.proposal_version,
          proposal_digest: action.proposal_digest, approve }),
      });
      setAction(result); await reload();
    } catch (cause) { setError(cause instanceof Error ? cause.message : '动作处理失败。'); await reload().catch(() => undefined); }
    finally { setBusy(false); }
  }

  async function recoverAction() {
    if (!action || busy) return;
    setBusy(true); setError('');
    try { setAction(await request<Action>(`/api/actions/${action.action_id}/recover`, post)); await reload(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : '恢复失败。'); }
    finally { setBusy(false); }
  }

  async function recordHandoff() {
    if (!action) return;
    try {
      const recorded = await request<Action>(`/api/actions/${action.action_id}/handoff`, {
        ...post, body: JSON.stringify({ request_id: crypto.randomUUID() }),
      });
      setAction(recorded);
    } catch (cause) { setError(cause instanceof Error ? cause.message : '导航交接记录失败。'); }
  }

  return <main className="min-h-screen bg-[#101613] px-5 py-8 text-[#edf3ea] md:py-12">
    <div className="mx-auto max-w-6xl">
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 pb-6">
        <div className="flex items-center gap-3"><Compass className="text-[#bdd7a2]" /><span className="text-xl font-semibold">SoloVibe</span></div>
        <span className="rounded-full border border-[#bdd7a2]/30 px-3 py-1 text-xs text-[#bdd7a2]">阶段 4 · 选择与确认</span>
      </header>

      <section className="py-9">
        <h1 className="text-3xl font-medium tracking-tight md:text-4xl">把当下想做的事，慢慢说清楚。</h1>
        <p className="mt-4 max-w-3xl text-sm leading-7 text-[#a8b6ac]">告诉我城市、出发位置、预算与时间。地点和步行路线来自高德；网页资料只展示来源，未经核实的价格、营业时间与套餐会标成未知。</p>
        <div className="mt-5 flex items-center gap-3 text-sm"><span className={health?.ready ? 'text-[#bdd7a2]' : 'text-orange-200'}>{health?.ready ? '数据库与模型启动检查已通过' : health ? `尚未就绪：${health.blocker?.message ?? '请检查后端配置'}` : '正在检查服务…'}</span><button type="button" aria-label="刷新服务状态" onClick={() => void refresh()} className="rounded-lg p-2 hover:bg-white/10"><RefreshCw size={16} /></button></div>
      </section>

      <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
        <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-5 md:p-7">
          <div className="flex items-center justify-between gap-3"><h2 className="text-lg font-medium">对话</h2><button type="button" onClick={() => void newConversation()} disabled={!health?.ready || busy} className="rounded-lg border border-white/15 px-3 py-2 text-xs disabled:opacity-40">新建会话</button></div>
          <div className="mt-6 min-h-64 space-y-4" aria-live="polite">
            {!conversation?.messages.length && <p className="text-sm leading-7 text-[#a8b6ac]">可以先说：“我在上海徐汇，今天有点累，预算 80 元，只有一小时。”</p>}
            {conversation?.messages.map(item => <div key={item.message_id} className={`rounded-xl p-4 text-sm leading-7 ${item.role === 'user' ? 'ml-7 bg-[#bdd7a2]/10' : 'mr-7 bg-white/[0.06]'}`}><div className="mb-1 text-xs text-[#9bb193]">{item.role === 'user' ? '你' : 'SoloVibe'}</div>{item.content}</div>)}
          </div>
          {conversation?.pending_run && <div className="mt-4 rounded-xl border border-orange-200/30 p-4 text-sm text-orange-100">上条消息仍有待恢复的运行（{conversation.pending_run.error_code ?? conversation.pending_run.status}）。<button type="button" disabled={busy} onClick={() => void retry()} className="ml-3 inline-flex items-center gap-1 underline"><RotateCcw size={14} />重试本条</button></div>}
          <div className="mt-6 flex gap-3"><textarea value={input} onChange={event => setInput(event.target.value)} disabled={!conversation || busy || !!conversation.pending_run} aria-label="输入出行需求" rows={3} maxLength={8000} placeholder="说说你现在的位置、预算、时间或心情…" className="min-w-0 flex-1 resize-none rounded-xl border border-white/15 bg-[#19231d] p-4 text-sm outline-none focus:border-[#bdd7a2]/60 disabled:opacity-50" /><button type="button" onClick={() => void send()} disabled={!conversation || busy || !input.trim() || !!conversation.pending_run} className="self-end rounded-xl bg-[#bdd7a2] p-4 text-[#182416] disabled:opacity-40" aria-label="发送消息"><ArrowRight size={19} /></button></div>
          {error && <p role="alert" className="mt-4 text-sm text-orange-200">{error}</p>}
        </section>

        <aside className="space-y-5">
          <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-5 md:p-7"><h2 className="text-lg font-medium">已确认的情境</h2><p className="mt-2 text-xs text-[#a8b6ac]">数据库中的结构化状态 · 版本 {conversation?.snapshot.revision ?? '—'}</p>{!!conversation?.context_memory.summary_revision && <p className="mt-2 text-xs text-[#a8b6ac]">较早对话已整理 · 原文仍保留</p>}<dl className="mt-4 space-y-3">{Object.entries(labels).map(([field,label]) => { const value = conversation?.snapshot.constraints[field]; const source = conversation?.snapshot.sources[field]; return <div key={field} className="border-t border-white/10 pt-3"><dt className="text-xs text-[#a8b6ac]">{label}</dt><dd className="mt-1 text-sm">{value === null || value === undefined || (Array.isArray(value) && !value.length) ? '未提供' : Array.isArray(value) ? value.join('、') : String(value)}</dd>{source && <p className="mt-1 text-xs text-[#92a48e]">依据：“{source.quote}” · {source.basis === 'explicit' ? '用户表达' : '推断'}</p>}</div>; })}</dl></section>
          <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-5 md:p-7"><h2 className="text-lg font-medium">运行记录</h2>{last && <p className="mt-3 text-xs leading-6 text-[#a8b6ac]">{last.model.provider} / {last.model.model} · 输入 {last.model.input_tokens ?? '未知'} tokens · 输出 {last.model.output_tokens ?? '未知'} tokens · {last.kind}</p>}{trace.length ? <ol className="mt-4 space-y-2">{trace.map((event,index) => <li key={`${index}-${event.node}`} className="flex justify-between gap-2 border-t border-white/10 pt-2 text-xs"><span>{event.node}</span><span className={event.status === 'completed' ? 'text-[#bdd7a2]' : 'text-orange-200'}>{event.status} · {event.elapsed_ms} ms</span></li>)}</ol> : <p className="mt-4 text-sm text-[#a8b6ac]">完成一次真实请求后显示节点执行记录。</p>}</section>
        </aside>
      </div>
      {action && <section className="mt-6 rounded-2xl border border-[#bdd7a2]/30 bg-[#19231d] p-5 md:p-7" aria-label="行动确认">
        <h2 className="text-lg font-medium">{action.kind === 'save' ? '保存方案' : '交接步行导航'} · {action.plan_snapshot.place.name}</h2>
        <p className="mt-2 text-sm text-[#a8b6ac]">{action.plan_snapshot.place.address} · 原方案步行约 {action.plan_snapshot.route.walking_minutes} 分钟</p>
        {action.status === 'awaiting_confirmation' && <><p className="mt-3 text-sm text-orange-100">请核对地点。确认后会{action.kind === 'save' ? '把此方案保存到数据库' : '重新核实地点和路线，再生成高德导航链接'}。营业、费用和可进入情况仍需你自行核实。确认有效期至 {new Date(action.expires_at).toLocaleString()}。</p>
          <div className="mt-4 flex gap-3"><button type="button" disabled={busy} onClick={() => void decideAction(true)} className="rounded-lg bg-[#bdd7a2] px-4 py-2 text-sm text-[#182416] disabled:opacity-40">确认</button><button type="button" disabled={busy} onClick={() => void decideAction(false)} className="rounded-lg border border-white/20 px-4 py-2 text-sm disabled:opacity-40">取消</button></div></>}
        {(action.status === 'authorized' || action.status === 'claimed') && <p className="mt-3 text-sm text-orange-100">动作已确认但尚无完成回执。<button type="button" onClick={() => void recoverAction()} disabled={busy} className="ml-2 underline">恢复执行</button></p>}
        {action.status === 'completed' && action.receipt?.kind === 'plan_saved' && <p className="mt-3 text-sm text-[#bdd7a2]">方案已保存。</p>}
        {action.status === 'completed' && action.receipt?.kind === 'navigation_handoff_ready' && action.receipt.url && <p className="mt-3 text-sm"><a href={action.receipt.url} target="_blank" rel="noopener noreferrer" onClick={() => void recordHandoff()} className="text-[#bdd7a2] underline">打开高德步行导航</a><span className="ml-2 text-[#a8b6ac]">{action.handoff_requested_at ? '已请求打开导航；无法确认高德是否接收。' : '链接已生成，尚未代你出发。'}</span></p>}
        {(action.status === 'rejected' || action.status === 'invalidated') && <p className="mt-3 text-sm text-orange-100">动作已{action.status === 'rejected' ? '取消' : '失效'}{action.receipt?.reason ? `（${action.receipt.reason}）` : ''}，不会执行。</p>}
      </section>}
      {conversation?.plan_set?.plans.length ? <section className="mt-6 rounded-2xl border border-white/10 bg-white/[0.03] p-5 md:p-7" aria-label="真实地点方案">
        <div className="flex flex-wrap items-baseline justify-between gap-2"><h2 className="text-lg font-medium">可考虑的地点</h2><p className="text-xs text-[#a8b6ac]">依据当前条件版本 {conversation.snapshot.revision} · 仅路线已核实</p></div>
        <div className="mt-5 grid gap-4 md:grid-cols-3">{conversation.plan_set.plans.map(plan => <article key={plan.plan_id} className="rounded-xl border border-white/10 bg-[#19231d] p-5">
          <p className="text-xs text-[#bdd7a2]">{plan.place.category || '地点'} · 高德 POI {plan.place.poi_id}</p>
          <h3 className="mt-2 text-lg font-medium">{plan.place.name}</h3>
          <p className="mt-2 text-sm text-[#a8b6ac]">{plan.place.address}</p>
          <p className="mt-4 text-sm">步行约 {plan.route.walking_minutes} 分钟 · {plan.route.distance_meters} 米</p>
          <p className="mt-2 text-xs text-[#a8b6ac]">高德记录：评分 {plan.facts?.rating ?? '未知'} · 参考人均 {plan.facts?.average_cost_cny == null ? '未知' : `${plan.facts.average_cost_cny} 元`}</p>
          {plan.facts?.recorded_hours && <p className="mt-1 text-xs text-[#a8b6ac]">登记营业时间：{plan.facts.recorded_hours}（非实时）</p>}
          <p className="mt-2 text-xs leading-6 text-[#a8b6ac]">{plan.tradeoff}</p>
          <p className="mt-2 text-xs text-orange-100">待核实：{plan.unknowns.join('、')}</p>
          <a className="mt-4 inline-block text-sm text-[#bdd7a2] underline" href={plan.place.source_url} target="_blank" rel="noopener noreferrer">在高德查看地点</a>
          {conversation.plan_set?.plan_set_id && <div className="mt-4 flex gap-2"><button type="button" disabled={busy || action?.status === 'awaiting_confirmation' || action?.status === 'authorized' || action?.status === 'claimed'} onClick={() => void prepareAction(plan,'save')} className="rounded-lg border border-[#bdd7a2]/40 px-3 py-2 text-xs disabled:opacity-40">保存此方案</button><button type="button" disabled={busy || action?.status === 'awaiting_confirmation' || action?.status === 'authorized' || action?.status === 'claimed'} onClick={() => void prepareAction(plan,'navigate')} className="rounded-lg border border-[#bdd7a2]/40 px-3 py-2 text-xs disabled:opacity-40">准备步行导航</button></div>}
          {plan.web_sources.length > 0 && <div className="mt-4 border-t border-white/10 pt-3"><p className="text-xs text-[#a8b6ac]">网页搜索结果 · 未核实是否同一分店</p><ul className="mt-2 space-y-2">{plan.web_sources.map(source => <li key={source.url}><a href={source.url} target="_blank" rel="noopener noreferrer" className="text-xs text-[#bdd7a2] underline">{source.title || source.url}</a></li>)}</ul></div>}
          {plan.web_status !== 'results_unverified' && <p className="mt-3 text-xs text-[#a8b6ac]">网页资料：{plan.web_status === 'not_configured' ? '未配置搜索服务' : '本次未取得可展示结果'}</p>}
        </article>)}</div>
      </section> : null}
      <footer className="mt-10 text-xs text-[#84938a]">阶段 4 开发预览 · 可确认保存方案或交接导航；不代订、不付款。出发前请核实营业和费用。</footer>
    </div>
  </main>;
}
