import { useCallback, useEffect, useState } from 'react';
import { ArrowRight, Compass, RefreshCw, RotateCcw } from 'lucide-react';
import { apiUrl } from './api';
import RouteSketch from './RouteSketch';
import ItineraryRouteSketch from './ItineraryRouteSketch';

type Health = { ready: boolean; stage: string; blocker?: { code: string; message: string } | null };
type Snapshot = { revision: number; constraints: Record<string, string | number | string[] | null>; sources: Record<string, { quote: string; basis: string; revision: number }> };
type Message = { message_id: string; role: 'user' | 'assistant'; content: string; sequence: number };
type Pending = { run_id: string; status: string; error_code: string | null } | null;
type WalkRoute = { walking_minutes: number; distance_meters: number; observed_at: string; polyline?: string[] };
type PublicItem = { name: string; category: string; price_cny: number | null; source_url: string; observed_at: string; scope: string };
type PublicOffer = { claim_id: string; description: string; price_cny: number; terms: string; applies_to: string; valid_until: string; source_url: string; observed_at: string; budget_option: string };
type PublicInfo = { status: string; sources: { url: string; observed_at: string; scope: string; source_domain: string; extract_status: string; field_scope: string }[]; brand_menu_items: PublicItem[]; branch_menu_items: PublicItem[]; admission_prices: { description: string; price_cny: number; source_url: string; observed_at: string; scope: string }[]; offers?: PublicOffer[] };
type LiveInfo = { status: 'verified'; source_kind: 'merchant_direct'; source_url: string; branch_id: string; amap_poi_id: string; observed_at: string; valid_until: string; open_now?: boolean; availability?: 'available' | 'limited' | 'unavailable' };
type Itinerary = { optimization: string; candidate_count: number; departure_local: string; clock_basis: string; meal_requirement: string | null; total_walk_minutes: number; total_wait_minutes: number; total_minutes: number; reservation?: { status: 'unavailable' | 'awaiting_confirmation' | 'submitting' | 'confirmed' | 'failed' | 'unknown'; restaurant_poi_id: string; entry_kind: 'place_detail'; entry_url: string; provider_confirmation_id: string | null; reason: string } | null; stops: { order: number; kind: string; arrival_local: string; dwell_minutes: number; route_from_previous: WalkRoute; place: { poi_id: string; name: string; address: string; category: string; source_url: string }; facts?: { rating: number | null; average_cost_cny: number | null; recorded_hours: string | null } | null }[]; legs: { from_name: string; to_name: string; route: WalkRoute }[] };
type Plan = { plan_id: string; context_revision: number; place: { name: string; address: string; category: string; source_url: string; observed_at: string; poi_id: string }; route: WalkRoute; return_route?: WalkRoute | null; itinerary?: Itinerary; time_breakdown?: { outbound_minutes: number; dwell_minutes: number | null; return_minutes: number | null; buffer_minutes: number; total_minutes: number | null; dwell_source: string }; feasibility_checks?: { full_activity_time: string; budget?: string; open_now?: string }; budget_option?: string; hours_evidence?: { kind: string; recorded_today_hours: string | null; inference: string; open_now: string; observed_at: string | null }; facts: { rating: number | null; average_cost_cny: number | null; recorded_hours: string | null; recorded_today_hours?: string | null; specialty_tags?: string[]; observed_at: string } | null; unknowns: string[]; tradeoff: string; web_status: string; web_sources: { title: string; url: string; snippet?: string; identity_status: string }[]; public_info?: PublicInfo | null; live_info?: LiveInfo | null; live_recheck_required?: boolean };
type PlanSet = { plan_set_id?: string; kind: string; plans: Plan[]; evidence_status: string; provider_errors: string[]; replanning?: { changed_fields: string[]; retrieval: string; parent_plan_set_id: string | null } };
type Action = { action_id: string; plan_id: string; kind: 'save' | 'navigate'; proposal_version: number; proposal_digest: string;
  plan_snapshot: Plan; status: string; receipt: { kind?: string; url?: string; reason?: string; place_name?: string; note?: string; segments?: { order: number; to_name: string; url: string; route: WalkRoute }[] } | null; expires_at: string; handoff_requested_at?: string | null };
type Conversation = { thread_id: string; snapshot: Snapshot; messages: Message[]; pending_run: Pending;
  plan_set: PlanSet | null;
  latest_action?: Action | null;
  saved_plans?: { action_id: string; plan_snapshot: Plan; saved_at: string }[];
  context_memory: { summary_revision: number; covered_until_sequence: number; raw_messages_retained: boolean } };
type ChatResult = { response: string; kind: string; run_id: string; snapshot: Snapshot; model: { provider: string; model: string; input_tokens: number | null; output_tokens: number | null; actual_call: boolean } };
type TraceEvent = { node: string; status: string; elapsed_ms: number };
type TimelineEvent = { event_type: 'run' | 'node' | 'action' | 'user_report'; created_at: string; status?: string; node?: string; kind?: string; category?: string; note?: string; error_code?: string };
type EditField = 'budget_cny' | 'available_minutes' | 'max_walk_minutes' | 'desired_dwell_minutes' | 'departure_time_local' | 'meal_requirement' | 'interests' | 'exclusions' | 'location_text' | 'city';

const labels: Record<string, string> = {
  city: '城市', location_text: '所在位置', return_location_text: '返程终点（未填则回出发点）', desired_dwell_minutes: '计划停留（分钟）', budget_cny: '预算（元）', available_minutes: '可用时间（分钟）',
  max_walk_minutes: '最多步行（分钟）', energy: '精力', interests: '偏好', exclusions: '避开',
  departure_time_local: '出发时刻（HH:MM）', meal_requirement: '安排晚餐',
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

export default function SoloVibeApp() {
  const [health, setHealth] = useState<Health | null>(null);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [last, setLast] = useState<ChatResult | null>(null);
  const [trace, setTrace] = useState<TraceEvent[]>([]);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [action, setAction] = useState<Action | null>(null);
  const [returnText, setReturnText] = useState('');
  const [dwellText, setDwellText] = useState('');
  const [locationNotice, setLocationNotice] = useState('');
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [invalidLivePlanIds, setInvalidLivePlanIds] = useState<string[]>([]);
  const [editField, setEditField] = useState<EditField>('budget_cny');
  const [editValue, setEditValue] = useState('');
  const [feedbackPlanId, setFeedbackPlanId] = useState('');
  const [feedbackCategory, setFeedbackCategory] = useState('considered');
  const [feedbackNote, setFeedbackNote] = useState('');

  const refresh = useCallback(async () => {
    try {
      const value = await request<Health>('/api/v1/health');
      setHealth(value);
      if (!value.ready) { setConversation(null); return; }
      bootstrapPromise ??= bootstrap().catch(cause => { bootstrapPromise = null; throw cause; });
      const current = await bootstrapPromise;
      setConversation(current); setAction(current.latest_action ?? null);
      const history = await request<{ events: TimelineEvent[] }>(`/api/conversations/${current.thread_id}/timeline`).catch(() => ({ events: [] as TimelineEvent[] }));
      setTimeline(history.events);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '服务暂时不可用。');
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => { const timer = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(timer); }, []);

  async function reload() {
    if (!conversation) return;
    const current = await request<Conversation>(`/api/conversations/${conversation.thread_id}`);
    setConversation(current); setAction(current.latest_action ?? null);
    const history = await request<{ events: TimelineEvent[] }>(`/api/conversations/${current.thread_id}/timeline`).catch(() => ({ events: [] as TimelineEvent[] }));
    setTimeline(history.events);
  }

  async function loadTrace(thread: string, run: string) {
    const result = await request<{ events: TraceEvent[] }>(`/api/conversations/${thread}/runs/${run}/trace`);
    setTrace(result.events);
  }

  async function send(override?: string) {
    const message = (override ?? input).trim();
    if (!conversation || !message || busy || conversation.pending_run) return;
    setBusy(true); setError('');
    const requestId = crypto.randomUUID();
    try {
      const result = await request<ChatResult>('/api/chat', {
        ...post, body: JSON.stringify({ thread_id: conversation.thread_id, request_id: requestId,
          expected_revision: conversation.snapshot.revision, message }),
      });
      setLast(result); setInput('');
      setInvalidLivePlanIds([]);
      await reload();
      await loadTrace(conversation.thread_id, result.run_id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '请求失败。');
      await reload().catch(() => undefined);
    } finally { setBusy(false); }
  }

  async function useCurrentLocation() {
    if (!conversation || busy) return;
    if (!navigator.geolocation) { setError('此浏览器不支持定位，请手动输入附近地址。'); return; }
    setBusy(true); setError(''); setLocationNotice('正在请求定位权限并核对地址…');
    try {
      const position = await new Promise<GeolocationPosition>((resolve, reject) =>
        navigator.geolocation.getCurrentPosition(resolve, reject,
          { enableHighAccuracy: true, timeout: 12000, maximumAge: 0 }));
      if (position.coords.accuracy > 300) throw new Error('定位精度超过 300 米，请手动输入附近地标。');
      const result = await request<{ snapshot: Snapshot; origin: { address: string; city: string; accuracy_m: number } }>(
        `/api/conversations/${conversation.thread_id}/origin`, {
          ...post, body: JSON.stringify({ request_id: crypto.randomUUID(),
            expected_revision: conversation.snapshot.revision,
            longitude: position.coords.longitude, latitude: position.coords.latitude,
            accuracy_m: position.coords.accuracy }),
        });
      await reload();
      setLocationNotice(`已记录：${result.origin.address}（精度约 ${Math.round(result.origin.accuracy_m)} 米）。发送消息即可按这里重新规划。`);
    } catch (cause) {
      setLocationNotice('');
      setError(cause instanceof Error ? cause.message : '定位失败，请手动输入附近地址。');
    } finally { setBusy(false); }
  }

  function tripMessage() {
    const dwell = Number(dwellText);
    if (!Number.isInteger(dwell) || dwell < 1 || dwell > 720) {
      setError('请填写 1–720 分钟的计划停留时间。'); return;
    }
    const destination = returnText.trim();
    if (destination.length > 180) { setError('返程终点文字太长。'); return; }
    void send(`${destination ? `返程终点是${destination}` : '返程回到原出发点'}，计划停留${dwell}分钟。`);
  }

  async function submitAdjustment() {
    if (!conversation || busy || conversation.pending_run) return;
    let value: string | number | string[] | null = editValue.trim();
    if (['budget_cny', 'available_minutes', 'max_walk_minutes', 'desired_dwell_minutes'].includes(editField)) {
      value = Number(editValue);
      if (!Number.isFinite(value) || !editValue.trim() ||
          (editField !== 'budget_cny' && !Number.isInteger(value))) {
        setError('请输入有效数字；时间和步行分钟数必须是整数。'); return;
      }
    } else if (editField === 'interests' || editField === 'exclusions') {
      value = editValue.split(/[,，、]/).map(item => item.trim()).filter(Boolean);
    } else if (editField === 'meal_requirement') {
      if (!['晚餐', '取消晚餐'].includes(editValue.trim())) { setError('请输入“晚餐”或“取消晚餐”。'); return; }
      value = editValue.trim() === '晚餐' ? 'dinner' : null;
    } else if (editField === 'departure_time_local' && !/^([01]\d|2[0-3]):[0-5]\d$/.test(editValue.trim())) {
      setError('出发时刻请用 24 小时制 HH:MM，例如 17:30。'); return;
    } else if (!value) { setError('请输入新的位置或城市。'); return; }
    setBusy(true); setError('');
    try {
      const result = await request<ChatResult>(`/api/conversations/${conversation.thread_id}/adjustments`, {
        ...post, body: JSON.stringify({ request_id: crypto.randomUUID(), expected_revision: conversation.snapshot.revision,
          field: editField, value }),
      });
      setLast(result); setEditValue(''); setInvalidLivePlanIds([]);
      await reload(); await loadTrace(conversation.thread_id, result.run_id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '条件修改失败。');
      await reload().catch(() => undefined);
    } finally { setBusy(false); }
  }

  async function submitFeedback() {
    if (!conversation?.plan_set?.plan_set_id || !feedbackPlanId || !feedbackNote.trim() || busy) return;
    setBusy(true); setError('');
    try {
      await request(`/api/conversations/${conversation.thread_id}/feedback`, {
        ...post, body: JSON.stringify({ request_id: crypto.randomUUID(),
          plan_set_id: conversation.plan_set.plan_set_id, plan_id: feedbackPlanId,
          category: feedbackCategory, note: feedbackNote.trim() }),
      });
      setFeedbackNote(''); await reload();
    } catch (cause) { setError(cause instanceof Error ? cause.message : '反馈记录失败。'); }
    finally { setBusy(false); }
  }

  async function recheckPlace(plan: Plan) {
    if (!conversation?.plan_set?.plan_set_id || busy || conversation.pending_run) return;
    setBusy(true); setError('');
    try {
      const result = await request<ChatResult>(`/api/conversations/${conversation.thread_id}/recheck`, {
        ...post, body: JSON.stringify({ request_id: crypto.randomUUID(),
          expected_revision: conversation.snapshot.revision,
          plan_set_id: conversation.plan_set.plan_set_id, poi_id: plan.place.poi_id }),
      });
      setLast(result); setInvalidLivePlanIds([]);
      await reload(); await loadTrace(conversation.thread_id, result.run_id);
    } catch (cause) { setError(cause instanceof Error ? cause.message : '门店重查失败。');
      await reload().catch(() => undefined); }
    finally { setBusy(false); }
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
      setInvalidLivePlanIds([]);
    } catch (cause) { setError(cause instanceof Error ? cause.message : '创建会话失败。'); }
    finally { setBusy(false); }
  }

  async function deleteConversation() {
    if (!conversation || busy || !window.confirm('永久删除此会话、方案、反馈和恢复记录？')) return;
    setBusy(true); setError('');
    try {
      await request(`/api/conversations/${conversation.thread_id}`, { method: 'DELETE' });
      bootstrapPromise = null;
      const created = await request<Conversation>('/api/conversations', post);
      setConversation(created); setAction(null); setLast(null); setTrace([]); setTimeline([]);
      setInput(''); setInvalidLivePlanIds([]);
    } catch (cause) { setError(cause instanceof Error ? cause.message : '删除会话失败。'); }
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
    } catch (cause) { setError(cause instanceof Error ? cause.message : '无法准备动作。');
      if (plan.live_info) setInvalidLivePlanIds(previous => [...new Set([...previous, plan.plan_id])]);
      await reload().catch(() => undefined); }
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
      setAction(result);
      if (result.status === 'invalidated' && result.receipt?.reason === 'merchant_state_changed')
        setInvalidLivePlanIds(previous => [...new Set([...previous, result.plan_id])]);
      await reload();
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
        <span className="rounded-full border border-[#bdd7a2]/30 px-3 py-1 text-xs text-[#bdd7a2]">多站城市行程</span>
      </header>

      <section className="py-9">
        <h1 className="text-3xl font-medium tracking-tight md:text-4xl">把当下想做的事，慢慢说清楚。</h1>
        <p className="mt-4 max-w-3xl text-sm leading-7 text-[#a8b6ac]">告诉我城市、出发位置、预算、可用时间和想去的地方；想吃晚饭也请明确说。系统会在真实地点中串联一条 2–3 站步行行程，并给出每一段的高德导航入口。</p>
        <div className="mt-5 flex items-center gap-3 text-sm"><span className={health?.ready ? 'text-[#bdd7a2]' : 'text-orange-200'}>{health?.ready ? '数据库与模型启动检查已通过' : health ? `尚未就绪：${health.blocker?.message ?? '请检查后端配置'}` : '正在检查服务…'}</span><button type="button" aria-label="刷新服务状态" onClick={() => void refresh()} className="rounded-lg p-2 hover:bg-white/10"><RefreshCw size={16} /></button></div>
      </section>

      <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
        <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-5 md:p-7">
          <div className="flex items-center justify-between gap-3"><h2 className="text-lg font-medium">对话</h2><div className="flex gap-2"><button type="button" onClick={() => void deleteConversation()} disabled={!conversation || busy} className="rounded-lg border border-orange-200/30 px-3 py-2 text-xs text-orange-100 disabled:opacity-40">删除此会话</button><button type="button" onClick={() => void newConversation()} disabled={!health?.ready || busy} className="rounded-lg border border-white/15 px-3 py-2 text-xs disabled:opacity-40">新建会话</button></div></div>
          <div className="mt-6 min-h-64 space-y-4" aria-live="polite">
            {!conversation?.messages.length && <p className="text-sm leading-7 text-[#a8b6ac]">可以先说：“我在上海徐汇，17:30 出发，预算 120 元，有 3 小时，想逛公园并吃晚饭，最多步行 60 分钟。”</p>}
            {conversation?.messages.map(item => <div key={item.message_id} className={`rounded-xl p-4 text-sm leading-7 ${item.role === 'user' ? 'ml-7 bg-[#bdd7a2]/10' : 'mr-7 bg-white/[0.06]'}`}><div className="mb-1 text-xs text-[#9bb193]">{item.role === 'user' ? '你' : 'SoloVibe'}</div>{item.content}</div>)}
          </div>
          {conversation?.pending_run && <div className="mt-4 rounded-xl border border-orange-200/30 p-4 text-sm text-orange-100">上条消息仍有待恢复的运行（{conversation.pending_run.error_code ?? conversation.pending_run.status}）。<button type="button" disabled={busy} onClick={() => void retry()} className="ml-3 inline-flex items-center gap-1 underline"><RotateCcw size={14} />重试本条</button></div>}
          <div className="mt-6 flex gap-3"><textarea value={input} onChange={event => setInput(event.target.value)} disabled={!conversation || busy || !!conversation.pending_run} aria-label="输入出行需求" rows={3} maxLength={8000} placeholder="说说你现在的位置、预算、时间或心情…" className="min-w-0 flex-1 resize-none rounded-xl border border-white/15 bg-[#19231d] p-4 text-sm outline-none focus:border-[#bdd7a2]/60 disabled:opacity-50" /><button type="button" onClick={() => void send()} disabled={!conversation || busy || !input.trim() || !!conversation.pending_run} className="self-end rounded-xl bg-[#bdd7a2] p-4 text-[#182416] disabled:opacity-40" aria-label="发送消息"><ArrowRight size={19} /></button></div>
          <div className="mt-4 rounded-xl border border-white/10 p-4 text-sm">
            <div className="flex flex-wrap items-center gap-3"><button type="button" onClick={() => void useCurrentLocation()} disabled={!conversation || busy || !!conversation.pending_run} className="rounded-lg border border-[#bdd7a2]/40 px-3 py-2 disabled:opacity-40">使用当前位置</button><span className="text-xs text-[#a8b6ac]">仅在点击后请求浏览器权限；也可以在对话里手动输入地标。</span></div>
            {locationNotice && <p className="mt-2 text-xs text-[#bdd7a2]">{locationNotice}</p>}
            <div className="mt-4 flex flex-wrap gap-2"><input aria-label="返程终点" value={returnText} onChange={event => setReturnText(event.target.value)} placeholder="返程终点，留空回出发点" className="min-w-0 flex-1 rounded-lg border border-white/15 bg-[#19231d] p-2 text-xs" /><input aria-label="计划停留分钟" type="number" min="1" max="720" value={dwellText} onChange={event => setDwellText(event.target.value)} placeholder="停留分钟" className="w-28 rounded-lg border border-white/15 bg-[#19231d] p-2 text-xs" /><button type="button" disabled={!conversation || busy || !!conversation.pending_run} onClick={tripMessage} className="rounded-lg border border-white/15 px-3 py-2 text-xs disabled:opacity-40">更新返程与停留</button></div>
          </div>
          <div className="mt-4 rounded-xl border border-white/10 p-4 text-sm" aria-label="直接修改条件">
            <p className="font-medium">直接修改条件</p>
            <p className="mt-1 text-xs text-[#a8b6ac]">修改会生成新的方案组；旧方案仍可查看，但不能按旧条件确认。</p>
            <div className="mt-3 flex flex-wrap gap-2"><select aria-label="要修改的条件" value={editField} onChange={event => { setEditField(event.target.value as EditField); setEditValue(''); }} className="rounded-lg border border-white/15 bg-[#19231d] p-2 text-xs">
              {(['budget_cny','available_minutes','max_walk_minutes','desired_dwell_minutes','departure_time_local','meal_requirement','interests','exclusions','location_text','city'] as EditField[]).map(field => <option key={field} value={field}>{labels[field]}</option>)}
            </select><input aria-label="条件新值" value={editValue} onChange={event => setEditValue(event.target.value)} placeholder={editField === 'interests' || editField === 'exclusions' ? '用逗号分隔' : '输入新值'} className="min-w-0 flex-1 rounded-lg border border-white/15 bg-[#19231d] p-2 text-xs" /><button type="button" onClick={() => void submitAdjustment()} disabled={!conversation || busy || !!conversation.pending_run || !editValue.trim()} className="rounded-lg border border-[#bdd7a2]/40 px-3 py-2 text-xs disabled:opacity-40">重新规划</button></div>
          </div>
          {error && <p role="alert" className="mt-4 text-sm text-orange-200">{error}</p>}
        </section>

        <aside className="space-y-5">
          <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-5 md:p-7"><h2 className="text-lg font-medium">已确认的情境</h2><p className="mt-2 text-xs text-[#a8b6ac]">数据库中的结构化状态 · 版本 {conversation?.snapshot.revision ?? '—'}</p>{!!conversation?.context_memory.summary_revision && <p className="mt-2 text-xs text-[#a8b6ac]">较早对话已整理 · 原文仍保留</p>}<dl className="mt-4 space-y-3">{Object.entries(labels).map(([field,label]) => { const value = conversation?.snapshot.constraints[field]; const source = conversation?.snapshot.sources[field]; return <div key={field} className="border-t border-white/10 pt-3"><dt className="text-xs text-[#a8b6ac]">{label}</dt><dd className="mt-1 text-sm">{value === null || value === undefined || (Array.isArray(value) && !value.length) ? '未提供' : Array.isArray(value) ? value.join('、') : String(value)}</dd>{source && <p className="mt-1 text-xs text-[#92a48e]">依据：“{source.quote}” · {source.basis === 'explicit' ? '用户表达' : '推断'}</p>}</div>; })}</dl></section>
          <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-5 md:p-7"><h2 className="text-lg font-medium">运行记录</h2>{last && <p className="mt-3 text-xs leading-6 text-[#a8b6ac]">{last.model.provider} / {last.model.model} · 输入 {last.model.input_tokens ?? '未知'} tokens · 输出 {last.model.output_tokens ?? '未知'} tokens · {last.kind}</p>}{trace.length ? <ol className="mt-4 space-y-2">{trace.map((event,index) => <li key={`${index}-${event.node}`} className="flex justify-between gap-2 border-t border-white/10 pt-2 text-xs"><span>{event.node}</span><span className={event.status === 'completed' ? 'text-[#bdd7a2]' : 'text-orange-200'}>{event.status} · {event.elapsed_ms} ms</span></li>)}</ol> : <p className="mt-4 text-sm text-[#a8b6ac]">完成一次真实请求后显示节点执行记录。</p>}</section>
          <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-5 md:p-7"><h2 className="text-lg font-medium">事实时间线</h2><p className="mt-1 text-xs text-[#a8b6ac]">只记录服务端事件；体验反馈标为用户自述。</p><ol className="mt-3 space-y-2">{timeline.slice(0, 12).map((event,index) => <li key={`${event.event_type}-${event.created_at}-${index}`} className="border-t border-white/10 pt-2 text-xs text-[#a8b6ac]">{new Date(event.created_at).toLocaleString()} · {event.event_type === 'user_report' ? `用户自述：${event.note}` : event.event_type === 'node' ? `节点 ${event.node}：${event.status}` : event.event_type === 'action' ? `${event.kind === 'save' ? '保存' : '导航'}动作：${event.status}` : `运行：${event.status}${event.error_code ? `（${event.error_code}）` : ''}`}</li>)}</ol></section>
        </aside>
      </div>
      {action && <section className="mt-6 rounded-2xl border border-[#bdd7a2]/30 bg-[#19231d] p-5 md:p-7" aria-label="行动确认">
        <h2 className="text-lg font-medium">{action.kind === 'save' ? '保存方案' : '交接步行导航'} · {action.plan_snapshot.itinerary ? '多站行程' : action.plan_snapshot.place.name}</h2>
        <p className="mt-2 text-sm text-[#a8b6ac]">{action.plan_snapshot.itinerary ? action.plan_snapshot.itinerary.stops.map(stop => stop.place.name).join(' → ') : action.plan_snapshot.place.address}{action.plan_snapshot.time_breakdown?.total_minutes != null ? ` · 按计划总计约 ${action.plan_snapshot.time_breakdown.total_minutes} 分钟` : ''}</p>
        {action.status === 'awaiting_confirmation' && <><p className="mt-3 text-sm text-orange-100">请核对地点。确认后会{action.kind === 'save' ? '把此方案保存到数据库' : '重新核实地点和路线，再生成高德导航链接'}。营业、费用和可进入情况仍需你自行核实。确认有效期至 {new Date(action.expires_at).toLocaleString()}。</p>
          {(hasExpiredOffer(action.plan_snapshot.public_info, nowMs) || hasExpiredLive(action.plan_snapshot.live_info, nowMs) || Date.parse(action.expires_at) <= nowMs) && <p className="mt-2 text-xs text-orange-100">提案、套餐或商家状态已过期，请取消并重新生成方案。</p>}
          <div className="mt-4 flex gap-3"><button type="button" disabled={busy || hasExpiredOffer(action.plan_snapshot.public_info, nowMs) || hasExpiredLive(action.plan_snapshot.live_info, nowMs) || Date.parse(action.expires_at) <= nowMs} onClick={() => void decideAction(true)} className="rounded-lg bg-[#bdd7a2] px-4 py-2 text-sm text-[#182416] disabled:opacity-40">确认</button><button type="button" disabled={busy} onClick={() => void decideAction(false)} className="rounded-lg border border-white/20 px-4 py-2 text-sm disabled:opacity-40">取消</button></div></>}
        {(action.status === 'authorized' || action.status === 'claimed') && <p className="mt-3 text-sm text-orange-100">动作已确认但尚无完成回执。<button type="button" onClick={() => void recoverAction()} disabled={busy} className="ml-2 underline">恢复执行</button></p>}
        {action.status === 'completed' && action.receipt?.kind === 'plan_saved' && <p className="mt-3 text-sm text-[#bdd7a2]">方案已保存。</p>}
        {action.status === 'completed' && action.receipt?.kind === 'navigation_handoff_ready' && action.receipt.url && <div className="mt-3 text-sm">{action.receipt.segments?.length ? <ol className="space-y-2">{action.receipt.segments.map(segment => <li key={segment.order}><a href={segment.url} target="_blank" rel="noopener noreferrer" onClick={() => void recordHandoff()} className="text-[#bdd7a2] underline">第 {segment.order} 段：打开高德前往{segment.to_name}</a><span className="ml-2 text-[#a8b6ac]">约 {segment.route.walking_minutes} 分钟</span></li>)}</ol> : <a href={action.receipt.url} target="_blank" rel="noopener noreferrer" onClick={() => void recordHandoff()} className="text-[#bdd7a2] underline">打开高德步行导航</a>}<p className="mt-2 text-xs text-[#a8b6ac]">请按顺序手动打开每段；系统无法确认到站，也不会自动切换下一段。</p></div>}
        {(action.status === 'rejected' || action.status === 'invalidated') && <p className="mt-3 text-sm text-orange-100">动作已{action.status === 'rejected' ? '取消' : '失效'}{action.receipt?.reason ? `（${action.receipt.reason}）` : ''}，不会执行。</p>}
      </section>}
      {!!conversation?.saved_plans?.length && <section className="mt-6 rounded-2xl border border-white/10 bg-white/[0.03] p-5 md:p-7" aria-label="已保存方案">
        <h2 className="text-lg font-medium">已保存方案</h2>
        <p className="mt-2 text-xs text-[#a8b6ac]">这是保存时的地点与路线快照；出发前请重新核实路线、营业和费用。</p>
        <ul className="mt-4 grid gap-3 md:grid-cols-2">{conversation.saved_plans.map(item => <li key={item.action_id} className="rounded-xl border border-white/10 bg-[#19231d] p-4">
          <p className="text-sm font-medium">{item.plan_snapshot.itinerary ? '多站行程' : item.plan_snapshot.place.name}</p>
          <p className="mt-1 text-xs text-[#a8b6ac]">{item.plan_snapshot.itinerary ? item.plan_snapshot.itinerary.stops.map(stop => stop.place.name).join(' → ') : item.plan_snapshot.place.address} · 保存于 {new Date(item.saved_at).toLocaleString()}</p>
          <p className="mt-2 text-xs text-[#a8b6ac]">保存时步行约 {item.plan_snapshot.itinerary?.total_walk_minutes ?? item.plan_snapshot.route.walking_minutes} 分钟</p>
          {item.plan_snapshot.time_breakdown?.total_minutes != null && <p className="mt-1 text-xs text-[#a8b6ac]">按当时计划，往返与停留共约 {item.plan_snapshot.time_breakdown.total_minutes} 分钟</p>}
          <a href={item.plan_snapshot.place.source_url} target="_blank" rel="noopener noreferrer" className="mt-2 inline-block text-xs text-[#bdd7a2] underline">查看地点来源</a>
        </li>)}</ul>
      </section>}
      {conversation?.plan_set?.plans.length ? <section className="mt-6 rounded-2xl border border-white/10 bg-white/[0.03] p-5 md:p-7" aria-label="真实地点方案">
        <div className="flex flex-wrap items-baseline justify-between gap-2"><h2 className="text-lg font-medium">推荐游览顺序</h2><p className="text-xs text-[#a8b6ac]">条件版本 {conversation.snapshot.revision} · 在本次候选地点内按可行站数和实际步行路程排序</p></div>
        {conversation.plan_set.replanning && <p className="mt-2 text-xs text-[#a8b6ac]">本次变化：{conversation.plan_set.replanning.changed_fields.map(field => labels[field] ?? field).join('、') || '重查'} · 证据处理：{({ fresh: '重新查询', facts_and_routes: '复用未过期地点、路线和来源', return_route: '只重查返程路线', fresh_after_reuse_shortfall: '复用结果不足，重新查询', targeted_recheck: '只重查所选地点' } as Record<string,string>)[conversation.plan_set.replanning.retrieval] ?? conversation.plan_set.replanning.retrieval}</p>}
        <div className="mt-5 grid gap-4">{conversation.plan_set.plans.map(plan => plan.itinerary ? <article key={plan.plan_id} className="rounded-xl border border-white/10 bg-[#19231d] p-5">
          <p className="text-xs text-[#bdd7a2]">唯一推荐方案 · {plan.itinerary.stops.length} 站 · 本次比较 {plan.itinerary.candidate_count} 个候选点</p>
          <h3 className="mt-2 text-lg font-medium">{plan.itinerary.stops.map(stop => stop.place.name).join(' → ')}</h3>
          <p className="mt-2 text-sm text-[#a8b6ac]">{plan.itinerary.departure_local} 出发（{plan.itinerary.clock_basis === 'user_local_clock' ? '你指定的当地时刻' : '生成时的当地时刻'}） · 总步行约 {plan.itinerary.total_walk_minutes} 分钟 · 含停留、等待及缓冲约 {plan.itinerary.total_minutes} 分钟</p>
          <ItineraryRouteSketch legs={plan.itinerary.legs} />
          <ol className="mt-4 space-y-3">{plan.itinerary.stops.map(stop => <li key={stop.place.poi_id} className="rounded-lg border border-white/10 p-3 text-sm">
            <p className="font-medium">{stop.order}. {stop.place.name}{stop.kind === 'dinner' ? ' · 晚餐' : ' · 游览'}</p>
            <p className="mt-1 text-xs text-[#a8b6ac]">{stop.place.address} · 预计 {stop.arrival_local} 到达 · 上一段步行 {stop.route_from_previous.walking_minutes} 分钟 · 计划停留 {stop.dwell_minutes} 分钟</p>
            <p className="mt-1 text-xs text-[#a8b6ac]">高德评分 {stop.facts?.rating ?? '未知'} · 参考人均 {stop.facts?.average_cost_cny == null ? '未知' : `${stop.facts.average_cost_cny} 元`} · 登记营业时间 {stop.facts?.recorded_hours ?? '未知'}（非实时）</p>
            <a href={stop.place.source_url} target="_blank" rel="noopener noreferrer" className="mt-1 inline-block text-xs text-[#bdd7a2] underline">在高德查看地点</a>
            {stop.kind === 'dinner' && plan.itinerary?.reservation && <div className="mt-3 rounded-lg border border-amber-200/25 bg-amber-100/5 p-3 text-xs">
              <p className="text-amber-100">预订状态：尚未代订。没有商家授权预订接口或确认号。</p>
              <a href={plan.itinerary.reservation.entry_url} target="_blank" rel="noopener noreferrer" className="mt-2 inline-block text-[#bdd7a2] underline">查看餐厅信息，自行联系确认席位</a>
            </div>}
          </li>)}</ol>
          <p className="mt-3 text-xs text-[#a8b6ac]">{plan.tradeoff} 停留时间是计划估算；总消费与餐厅席位未知。尚未接通代订餐厅，保存或导航均不等于预订。</p>
          <div className="mt-4 flex gap-2"><button type="button" disabled={busy || action?.status === 'awaiting_confirmation' || action?.status === 'authorized' || action?.status === 'claimed'} onClick={() => void prepareAction(plan, 'save')} className="rounded-lg border border-[#bdd7a2]/40 px-3 py-2 text-xs disabled:opacity-40">确认并保存行程</button><button type="button" disabled={busy || action?.status === 'awaiting_confirmation' || action?.status === 'authorized' || action?.status === 'claimed'} onClick={() => void prepareAction(plan, 'navigate')} className="rounded-lg border border-[#bdd7a2]/40 px-3 py-2 text-xs disabled:opacity-40">确认后生成逐段导航</button></div>
        </article> : <article key={plan.plan_id} className="rounded-xl border border-white/10 bg-[#19231d] p-5">
          <p className="text-xs text-[#bdd7a2]">{plan.place.category || '地点'} · 高德 POI {plan.place.poi_id}</p>
          <h3 className="mt-2 text-lg font-medium">{plan.place.name}</h3>
          <p className="mt-2 text-sm text-[#a8b6ac]">{plan.place.address}</p>
          <p className="mt-4 text-sm">步行约 {plan.route.walking_minutes} 分钟 · {plan.route.distance_meters} 米</p>
          {plan.return_route && <p className="mt-1 text-sm">返程步行约 {plan.return_route.walking_minutes} 分钟 · {plan.return_route.distance_meters} 米</p>}
          {plan.time_breakdown?.total_minutes != null && <p className="mt-1 text-xs text-[#bdd7a2]">去程 {plan.time_breakdown.outbound_minutes} ＋计划停留 {plan.time_breakdown.dwell_minutes} ＋返程 {plan.time_breakdown.return_minutes} ＋缓冲 {plan.time_breakdown.buffer_minutes} ＝约 {plan.time_breakdown.total_minutes} 分钟</p>}
          <RouteSketch outbound={plan.route} returning={plan.return_route} />
          <p className="mt-2 text-xs text-[#a8b6ac]">高德地点资料：评分 {plan.facts?.rating ?? '未知'} · 参考人均 {plan.facts?.average_cost_cny == null ? '未知' : `${plan.facts.average_cost_cny} 元`}</p>
          {plan.facts?.recorded_hours && <p className="mt-1 text-xs text-[#a8b6ac]">登记营业时间：{plan.facts.recorded_hours}（非实时）</p>}
          {plan.facts?.recorded_today_hours && <p className="mt-1 text-xs text-[#a8b6ac]">高德所列今日时段：{plan.facts.recorded_today_hours}（不代表此刻营业）</p>}
          {plan.hours_evidence?.inference === 'possibly_within_recorded_hours' && <p className="mt-1 text-xs text-[#a8b6ac]">生成方案时按登记时段推测可能营业；实时营业仍未知。</p>}
          {plan.hours_evidence?.inference === 'outside_recorded_hours' && <p className="mt-1 text-xs text-[#a8b6ac]">生成方案时按登记时段推测不在营业时段；实时状态仍需核实。</p>}
          <LiveEvidencePanel info={invalidLivePlanIds.includes(plan.plan_id) ? null : plan.live_info} nowMs={nowMs} />
          {hasActiveOffer(plan.public_info, nowMs) && plan.budget_option === 'known_offer_within_limit' && <p className="mt-1 text-xs text-[#bdd7a2]">有来源套餐价格不超过预算；这不代表整次活动总消费可控。</p>}
          {hasActiveOffer(plan.public_info, nowMs) && plan.budget_option === 'known_offer_over_limit' && <p className="mt-1 text-xs text-orange-100">已核实的套餐价格超过预算；其他消费选项仍未知。</p>}
          {!!plan.facts?.specialty_tags?.length && <p className="mt-1 text-xs leading-5 text-[#a8b6ac]">高德特色标签：{plan.facts.specialty_tags.join('、')}（并非实时菜单或优惠）</p>}
          {plan.facts?.observed_at && <p className="mt-1 text-xs text-[#84938a]">地点资料查询于 {new Date(plan.facts.observed_at).toLocaleString()}</p>}
          <PublicEvidencePanel info={plan.public_info} nowMs={nowMs} />
          <p className="mt-2 text-xs leading-6 text-[#a8b6ac]">{plan.tradeoff}</p>
          <p className="mt-2 text-xs text-orange-100">待核实：{[...new Set([...plan.unknowns, ...(hasExpiredLive(plan.live_info, nowMs) || plan.live_recheck_required || invalidLivePlanIds.includes(plan.plan_id) ? ['当前营业状态', '到店可用性'] : [])])].join('、')}</p>
          <a className="mt-4 inline-block text-sm text-[#bdd7a2] underline" href={plan.place.source_url} target="_blank" rel="noopener noreferrer">在高德查看地点</a>
          {hasExpiredOffer(plan.public_info, nowMs) && <p className="mt-2 text-xs text-orange-100">套餐证据已过期，请重新生成方案后再确认。</p>}
          {(hasExpiredLive(plan.live_info, nowMs) || plan.live_recheck_required || invalidLivePlanIds.includes(plan.plan_id)) && <p className="mt-2 text-xs text-orange-100">商家实时状态已过期或复查失败，不再显示旧状态；请重新生成方案。</p>}
          {conversation.plan_set?.plan_set_id && <div className="mt-4 flex flex-wrap gap-2"><button type="button" disabled={busy || hasExpiredOffer(plan.public_info, nowMs) || hasExpiredLive(plan.live_info, nowMs) || plan.live_recheck_required || invalidLivePlanIds.includes(plan.plan_id) || action?.status === 'awaiting_confirmation' || action?.status === 'authorized' || action?.status === 'claimed'} onClick={() => void prepareAction(plan,'save')} className="rounded-lg border border-[#bdd7a2]/40 px-3 py-2 text-xs disabled:opacity-40">保存此方案</button><button type="button" disabled={busy || hasExpiredOffer(plan.public_info, nowMs) || hasExpiredLive(plan.live_info, nowMs) || plan.live_recheck_required || invalidLivePlanIds.includes(plan.plan_id) || action?.status === 'awaiting_confirmation' || action?.status === 'authorized' || action?.status === 'claimed'} onClick={() => void prepareAction(plan,'navigate')} className="rounded-lg border border-[#bdd7a2]/40 px-3 py-2 text-xs disabled:opacity-40">准备步行导航</button><button type="button" disabled={busy || !!conversation.pending_run} onClick={() => void recheckPlace(plan)} className="rounded-lg border border-white/20 px-3 py-2 text-xs disabled:opacity-40">重查该店</button></div>}
          {plan.web_sources.length > 0 && <div className="mt-4 border-t border-white/10 pt-3"><p className="text-xs text-[#a8b6ac]">网页线索 · 提及地点名称，尚未核实是否同一分店；内容不作为套餐或营业承诺</p><ul className="mt-2 space-y-2">{plan.web_sources.filter(source => source.url.startsWith('https://')).map(source => <li key={source.url}><a href={source.url} target="_blank" rel="noopener noreferrer" className="text-xs text-[#bdd7a2] underline">{source.title || source.url}</a>{source.snippet && <p className="mt-1 line-clamp-3 text-xs text-[#a8b6ac]">{source.snippet}</p>}</li>)}</ul></div>}
          {plan.web_status !== 'results_unverified' && <p className="mt-3 text-xs text-[#a8b6ac]">网页资料：{plan.web_status === 'not_configured' ? '未配置搜索服务' : '本次未取得可展示结果'}</p>}
        </article>)}</div>
      </section> : null}
      {!!conversation?.plan_set?.plans.length && <section className="mt-6 rounded-2xl border border-white/10 bg-white/[0.03] p-5 md:p-7" aria-label="用户体验反馈">
        <h2 className="text-lg font-medium">记录自己的体验</h2><p className="mt-2 text-xs text-[#a8b6ac]">以下只记录你的自述，不代表系统核实了到店、消费或预约结果。</p>
        <div className="mt-4 flex flex-wrap gap-2"><select aria-label="反馈对应方案" value={feedbackPlanId} onChange={event => setFeedbackPlanId(event.target.value)} className="rounded-lg border border-white/15 bg-[#19231d] p-2 text-xs"><option value="">选择地点</option>{conversation.plan_set.plans.map(plan => <option key={plan.plan_id} value={plan.plan_id}>{plan.place.name}</option>)}</select><select aria-label="反馈类型" value={feedbackCategory} onChange={event => setFeedbackCategory(event.target.value)} className="rounded-lg border border-white/15 bg-[#19231d] p-2 text-xs"><option value="considered">考虑过</option><option value="went">我说我去了</option><option value="did_not_go">我说我没去</option><option value="other">其他</option></select></div>
        <textarea aria-label="反馈内容" maxLength={500} rows={2} value={feedbackNote} onChange={event => setFeedbackNote(event.target.value)} className="mt-3 w-full rounded-lg border border-white/15 bg-[#19231d] p-3 text-sm" placeholder="写下你的感受或结果（最多 500 字）" /><button type="button" disabled={busy || !feedbackPlanId || !feedbackNote.trim()} onClick={() => void submitFeedback()} className="mt-2 rounded-lg border border-[#bdd7a2]/40 px-3 py-2 text-xs disabled:opacity-40">保存自述反馈</button>
      </section>}
      <footer className="mt-10 text-xs text-[#84938a]">SoloVibe · 按你的时间、步行与兴趣安排城市独行。</footer>
    </div>
  </main>;
}

function hasActiveOffer(info: PublicInfo | null | undefined, nowMs: number) {
  return !!info?.offers?.some(offer => Date.parse(offer.valid_until) > nowMs);
}

function hasExpiredOffer(info: PublicInfo | null | undefined, nowMs: number) {
  return !!info?.offers?.some(offer => !(Date.parse(offer.valid_until) > nowMs));
}

function hasExpiredLive(info: LiveInfo | null | undefined, nowMs: number) {
  return !!info && !(Date.parse(info.valid_until) > nowMs);
}

function LiveEvidencePanel({ info, nowMs }: { info?: LiveInfo | null; nowMs: number }) {
  if (!info || hasExpiredLive(info, nowMs) || info.status !== 'verified') return null;
  const availability = { available: '商家当前反馈可用', limited: '商家当前反馈有限', unavailable: '商家当前反馈不可用' };
  return <section className="mt-3 rounded-lg border border-[#bdd7a2]/30 bg-[#26372a] p-3 text-xs" aria-label="授权商家实时状态">
    <p className="font-medium text-[#bdd7a2]">授权商家分店状态</p>
    {info.open_now !== undefined && <p className="mt-1">{info.open_now ? '商家当前反馈营业中' : '商家当前反馈未营业'}</p>}
    {info.availability && <p className="mt-1">{availability[info.availability]}</p>}
    <p className="mt-1 text-[#a8b6ac]">核查于 {new Date(info.observed_at).toLocaleString()} · 有效至 {new Date(info.valid_until).toLocaleString()}。状态可能随时变化，不代表已预订。</p>
    {info.source_url.startsWith('https://') && <a href={info.source_url} target="_blank" rel="noopener noreferrer" className="mt-1 inline-block text-[#bdd7a2] underline">查看商家来源</a>}
  </section>;
}

function PublicEvidencePanel({ info, nowMs }: { info?: PublicInfo | null; nowMs: number }) {
  if (!info || (!info.sources.length && !info.brand_menu_items.length && !info.branch_menu_items.length && !info.offers?.length)) return null;
  const activeOffers = info.offers?.filter(offer => Date.parse(offer.valid_until) > nowMs) ?? [];
  return <section className="mt-4 rounded-lg border border-[#bdd7a2]/20 p-3 text-xs" aria-label="公开来源资料">
    {!!activeOffers.length && <div><p className="font-medium text-[#bdd7a2]">本地点有条件套餐 · 请按条款核对</p>
      <ul className="mt-2 space-y-2">{activeOffers.map(offer => <li key={offer.claim_id}>
        <span>{offer.description} · 来源价 {offer.price_cny} 元</span>
        <span className="block text-[#a8b6ac]">适用：{offer.applies_to}；条件：{offer.terms}；有效至 {new Date(offer.valid_until).toLocaleString()}</span>
        <a href={offer.source_url} target="_blank" rel="noopener noreferrer" className="text-[#bdd7a2] underline">查看官方条款</a>
      </li>)}</ul></div>}
    {!!info.brand_menu_items.length && <div><p className="font-medium text-[#bdd7a2]">品牌菜单示例 · 未证实本分店有售或现价</p>
      <ul className="mt-2 space-y-1">{info.brand_menu_items.slice(0, 5).map(item => <li key={`${item.source_url}-${item.name}`}>{item.name} · 价格未知</li>)}</ul></div>}
    {!!info.branch_menu_items.length && <div className="mt-2"><p className="font-medium text-[#bdd7a2]">本分店菜单资料 · 来源已匹配门店</p>
      <ul className="mt-2 space-y-1">{info.branch_menu_items.slice(0, 5).map(item => <li key={`${item.source_url}-${item.name}`}>{item.name} · {item.price_cny == null ? '价格未知' : `${item.price_cny} 元（来源所列）`}</li>)}</ul></div>}
    {!!info.admission_prices.length && <div className="mt-2"><p className="font-medium text-[#bdd7a2]">来源所列票价 · {info.admission_prices[0].scope === 'branch' ? '地点已匹配' : '适用地点待核实'}</p>
      <ul className="mt-2 space-y-1">{info.admission_prices.map(item => <li key={`${item.source_url}-${item.description}`}>{item.description} · {item.price_cny} 元</li>)}</ul></div>}
    <ul className="mt-3 space-y-1 border-t border-white/10 pt-2">{info.sources.filter(source => source.url.startsWith('https://')).map(source => <li key={source.url}>
      <a href={source.url} target="_blank" rel="noopener noreferrer" className="text-[#bdd7a2] underline">查看 {source.source_domain} 原始页</a>
      <span className="ml-1 text-[#a8b6ac]">· {new Date(source.observed_at).toLocaleString()} · {source.extract_status === 'success' ? '正文已获取' : `提取失败：${source.extract_status}`}</span>
    </li>)}</ul>
  </section>;
}
