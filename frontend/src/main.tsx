import { StrictMode, Component, ErrorInfo, ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import BaselineApp from './BaselineApp';
import './index.css';

// 1. 定义一个高强度的“错误捕获盾牌”
class ErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean; error: Error | null }> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error) {
    // 一旦子组件崩溃，触发这个状态，强行切换 UI
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    // 在这里可以打印具体的错误堆栈
    console.error("ErrorBoundary caught an error", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      // 2. 一旦崩溃，不再显示白屏，而是直接在网页上吐出大红色的错误原因！
      return (
        <div style={{ padding: '30px', maxWidth: '800px', margin: '50px auto', backgroundColor: '#fff5f5', border: '2px solid #feb2b2', borderRadius: '8px', color: '#c53030', fontFamily: 'monospace' }}>
          <h2 style={{ margin: '0 0 10px 0' }}>🚨 捕获到前端运行时致命崩溃！</h2>
          <p style={{ fontWeight: 'bold' }}>错误原因: {this.state.error?.toString()}</p>
          <pre style={{ backgroundColor: '#fff', padding: '15px', borderRadius: '4px', border: '1px solid #eee', overflowX: 'auto', fontSize: '12px', color: '#333' }}>
            请把这里显示的堆栈信息复制发给 AI，它一秒钟就能帮你修好 App.tsx！
          </pre>
        </div>
      );
    }

    return this.props.children;
  }
}

// 3. 把你的 App 用盾牌死死包裹住
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <BaselineApp />
    </ErrorBoundary>
  </StrictMode>,
);
