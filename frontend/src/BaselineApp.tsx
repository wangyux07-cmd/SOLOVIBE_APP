import { useCallback, useEffect, useState } from 'react';
import { ArrowRight, Check, Compass, RefreshCw, Server, Unplug } from 'lucide-react';
import { apiUrl } from './api';

type ServiceState = { configured: boolean; verification: string };
type Health = {
  status: string;
  ready: boolean;
  stage: string;
  version: string;
  services: Record<string, ServiceState>;
};

const labels: Record<string, string> = {
  model: '对话模型', maps: '高德地图', search: '网页搜索', database: '会话数据库',
};

const stages = ['开发基线', 'LangGraph 与状态', '上下文管理', '真实活动方案', '确认与行动', '联调与上线'];

export default function BaselineApp() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [checkingChat, setCheckingChat] = useState(false);
  const [result, setResult] = useState('');

  const refresh = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError('');
    try {
      const response = await fetch(apiUrl('/api/v1/health'), { signal, cache: 'no-store' });
      if (!response.ok) throw new Error(`后端状态检查失败（HTTP ${response.status}）`);
      const data = await response.json() as Health;
      if (data.status !== 'ok' || !data.services || data.stage !== 'baseline') {
        throw new Error('收到非预期的后端响应，请检查 API 地址。');
      }
      setHealth(data);
    } catch (cause) {
      if (signal?.aborted) return;
      setHealth(null);
      setError(cause instanceof Error ? cause.message : '暂时无法连接后端。');
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);

  async function checkChat() {
    setCheckingChat(true);
    setResult('');
    try {
      const response = await fetch(apiUrl('/api/chat'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: '开发基线连通性检查' }),
      });
      const data = await response.json();
      if (response.status === 503 && data.error?.code === 'AGENT_NOT_IMPLEMENTED') {
        setResult(data.error.message);
      } else {
        throw new Error(`聊天入口返回非预期结果（HTTP ${response.status}）。`);
      }
    } catch (cause) {
      setResult(cause instanceof Error ? cause.message : '通信失败，请检查后端。');
    } finally {
      setCheckingChat(false);
    }
  }

  return (
    <main className="min-h-screen bg-[#101613] text-[#e9eee8] px-5 py-10 md:py-16 font-sans">
      <div className="mx-auto max-w-5xl">
        <header className="flex items-center justify-between border-b border-white/10 pb-6">
          <div className="flex items-center gap-3"><Compass className="text-[#bdd7a2]" /><span className="text-xl font-semibold tracking-tight">SoloVibe</span></div>
          <span className="rounded-full border border-[#bdd7a2]/30 px-3 py-1 text-xs text-[#bdd7a2]">V1 · 开发工作台</span>
        </header>
        <section className="py-12 md:py-16">
          <p className="text-xs tracking-[0.25em] text-[#bdd7a2]">STEP 00 / 05</p>
          <h1 className="mt-5 text-3xl md:text-5xl font-medium tracking-tight leading-tight">让每一次出发，<br />都有真实的信息支撑。</h1>
          <p className="mt-6 max-w-xl text-sm leading-7 text-[#a8b6ac]">现在先把开发环境连起来。这个页面展示实际服务状态；城市推荐、上下文记忆和行动确认将在后续阶段接入。</p>
        </section>
        <div className="grid gap-5 md:grid-cols-[1.3fr_1fr]">
          <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-6 md:p-8">
            <div className="flex items-center justify-between gap-3">
              <h2 className="flex items-center gap-2 text-lg font-medium"><Server size={19} />前后端连接</h2>
              <button type="button" onClick={() => void refresh()} disabled={loading} aria-label="刷新服务状态" className="rounded-lg p-2 hover:bg-white/10 disabled:opacity-40"><RefreshCw size={17} className={loading ? 'animate-spin' : ''} /></button>
            </div>
            <p role="status" className={`mt-7 text-xl ${error ? 'text-orange-200' : 'text-[#bdd7a2]'}`}>{loading ? '正在检查连接…' : health ? '前端 → API → 后端，已连通' : '后端尚未连接'}</p>
            <p className="mt-3 text-sm leading-6 text-[#a8b6ac]">{error || (health ? `后端 ${health.version} · 基线服务运行中，Agent 尚未就绪。` : '请先启动本地后端服务。')}</p>
            <button type="button" onClick={() => void checkChat()} disabled={!health || checkingChat} className="mt-8 flex items-center gap-3 rounded-xl bg-[#bdd7a2] px-5 py-3 text-sm font-medium text-[#182416] hover:bg-[#cde3b7] disabled:opacity-40">{checkingChat ? '正在检查…' : '验证聊天入口'}<ArrowRight size={17} /></button>
            {result && <p role="status" className="mt-5 border-l-2 border-[#bdd7a2]/50 pl-4 text-sm leading-6 text-[#c9d5cb]">{result}</p>}
          </section>
          <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-6 md:p-8">
            <h2 className="text-lg font-medium">外部服务准备</h2>
            <p className="mt-2 text-xs leading-6 text-[#a8b6ac]">配置存在与真实调用成功分别核验。</p>
            <ul className="mt-4 divide-y divide-white/10">
              {Object.entries(labels).map(([key, label]) => <li key={key} className="flex items-center justify-between gap-3 py-4 text-sm"><span>{label}</span><span className="flex items-center gap-2 text-xs text-[#a8b6ac]"><Unplug size={13} />{!health ? '等待检查' : health.services[key]?.configured ? '已配置 · 未联调' : '待配置'}</span></li>)}
            </ul>
          </section>
        </div>
        <section className="mt-10 border-t border-white/10 pt-7">
          <h2 className="text-sm text-[#a8b6ac]">阶段交付</h2>
          <ol className="mt-5 grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">{stages.map((stage, index) => <li key={stage} className={`text-xs leading-6 ${index === 0 ? 'text-[#bdd7a2]' : 'text-[#84938a]'}`}><span className="mb-2 flex h-7 w-7 items-center justify-center rounded-full border border-current/30">{index === 0 && health ? <Check size={13} /> : index}</span>{stage}<span className="block text-[11px] opacity-70">{index === 0 ? '当前阶段' : '待开发'}</span></li>)}</ol>
        </section>
        <footer className="mt-12 text-xs leading-6 text-[#84938a]">开发预览 · 本页不生成商家、套餐或预约结果。</footer>
      </div>
    </main>
  );
}
