import { Component, StrictMode, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import SoloVibeApp from './SoloVibeApp';
import './index.css';

class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return (
        <main className="mx-auto mt-24 max-w-lg px-6 text-center text-white">
          <h1 className="text-2xl font-semibold">页面暂时无法显示</h1>
          <p className="mt-3 text-sm text-white/70">请刷新页面，继续查看你的行程。</p>
          <button className="mt-6 rounded-lg border border-white/40 px-4 py-2" onClick={() => window.location.reload()}>
            刷新页面
          </button>
        </main>
      );
    }
    return this.props.children;
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <SoloVibeApp />
    </ErrorBoundary>
  </StrictMode>,
);
