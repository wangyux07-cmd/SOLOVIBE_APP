import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { API_BASE_URL } from '../api';
import {
  StreamChatRequest,
  StreamHookState,
  ParsedSSEData,
  UseSoloStreamOptions,
  WanderPlan,
  ThreadState,
  SSEEventType,
  StreamResponseType
} from '../types/api';

/**
 * SoloVibe SSE流式通信Hook
 * 实现与后端的SSE连接管理、消息解析和HITL中断处理
 */
export const useSoloStream = (options: UseSoloStreamOptions = {}) => {
  const {
    autoReconnect = true,
    reconnectInterval = 3000,
    maxReconnectAttempts = 5,
    onMessage,
    onWaitingForConfirmation,
    onError,
    onConnectionChange
  } = options;

  // 状态管理
  const [state, setState] = useState<StreamHookState>({
    isConnected: false,
    isWaiting: false,
    threadId: null,
    currentMessage: '',
    messages: [],
    error: null,
    plans: []
  });

  // 引用管理
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const abortControllerRef = useRef<AbortController | null>(null);

  // API基础URL

  // 解析SSE数据
  const parseSSEData = useCallback((rawData: string): ParsedSSEData => {
    try {
      // 检查是否为标签化数据
      if (rawData.includes('[EMPATHY]')) {
        const content = rawData.replace('[EMPATHY]', '').trim();
        return {
          type: 'empathy',
          content,
          raw: rawData
        };
      }

      if (rawData.includes('[PLANS]')) {
        const jsonPart = rawData.replace('[PLANS]', '').trim();
        try {
          const parsed = JSON.parse(jsonPart);
          return {
            type: 'plans',
            content: parsed,
            raw: rawData
          };
        } catch (e) {
          return {
            type: 'raw',
            content: jsonPart,
            raw: rawData
          };
        }
      }

      if (rawData.includes('[REQUIRE_USER_CONFIRM]')) {
        return {
          type: 'require_confirmation',
          content: '需要您的确认才能继续',
          raw: rawData
        };
      }

      // 默认返回原始数据
      return {
        type: 'raw',
        content: rawData,
        raw: rawData
      };
    } catch (error) {
      return {
        type: 'raw',
        content: rawData,
        raw: rawData
      };
    }
  }, []);

  // 处理SSE消息事件
  const handleSSEMessage = useCallback((event: MessageEvent) => {
    try {
      const rawData = event.data;
      const parsed = parseSSEData(rawData);

      setState(prevState => {
        const newState = { ...prevState };
        
        // 根据数据类型更新状态
        switch (parsed.type) {
          case 'empathy':
            newState.currentMessage = String(parsed.content);
            newState.messages = [...prevState.messages, parsed];
            break;

          case 'plans':
            if (parsed.content && typeof parsed.content === 'object') {
              const newPlan = parsed.content as WanderPlan;
              newState.plans = [...prevState.plans, newPlan];
            }
            newState.messages = [...prevState.messages, parsed];
            break;

          case 'require_confirmation':
            newState.isWaiting = true;
            newState.messages = [...prevState.messages, parsed];
            // 触发中断回调
            setTimeout(() => onWaitingForConfirmation?.(), 0);
            break;

          default:
            newState.messages = [...prevState.messages, parsed];
            break;
        }

        return newState;
      });

      // 触发消息回调
      onMessage?.(parsed);

    } catch (error) {
      const errorMsg = `处理SSE消息时出错: ${error}`;
      console.error(errorMsg);
      setState(prev => ({ ...prev, error: errorMsg }));
      onError?.(errorMsg);
    }
  }, [parseSSEData, onMessage, onWaitingForConfirmation, onError]);

  // 处理SSE错误
  const handleSSEError = useCallback((error: Event) => {
    console.error('SSE连接错误:', error);
    
    setState(prev => ({
      ...prev,
      isConnected: false,
      error: 'SSE连接失败'
    }));

    onConnectionChange?.(false);
    onError?.('SSE连接失败');

    // 自动重连逻辑
    if (autoReconnect && reconnectAttemptsRef.current < maxReconnectAttempts) {
      reconnectAttemptsRef.current += 1;
      console.log(`尝试重连 (${reconnectAttemptsRef.current}/${maxReconnectAttempts})...`);
      
      reconnectTimeoutRef.current = setTimeout(() => {
        // 重连逻辑将在sendMessage时触发
      }, reconnectInterval);
    }
  }, [autoReconnect, maxReconnectAttempts, reconnectInterval, onConnectionChange, onError]);

  // 关闭SSE连接
  const closeConnection = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    setState(prev => ({ ...prev, isConnected: false }));
    onConnectionChange?.(false);
  }, [onConnectionChange]);

  // 发送消息到后端
  const sendMessage = useCallback(async (message: string, threadId?: string) => {
    try {
      // 关闭现有连接
      closeConnection();

      // 确定thread_id
      const finalThreadId = threadId || state.threadId || `session-${Date.now()}`;
      
      const requestData: StreamChatRequest = {
        message,
        thread_id: finalThreadId
      };

      // 创建新的AbortController
      abortControllerRef.current = new AbortController();

      // 使用fetch进行SSE连接
      const response = await fetch(`${API_BASE_URL}/api/v1/stream_chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestData),
        signal: abortControllerRef.current.signal
      });

      if (!response.ok) {
        throw new Error(`HTTP错误: ${response.status}`);
      }

      if (!response.body) {
        throw new Error('响应没有body');
      }

      // 设置状态
      setState(prev => ({
        ...prev,
        isConnected: true,
        threadId: finalThreadId,
        error: null
      }));
      onConnectionChange?.(true);
      
      // 重置重连计数器
      reconnectAttemptsRef.current = 0;

      // 创建ReadableStream reader
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      // 读取流数据
      const readStream = async () => {
        try {
          while (true) {
            const { done, value } = await reader.read();
            
            if (done) break;
            
            // 解码数据
            buffer += decoder.decode(value, { stream: true });
            
            // 按行分割处理
            const lines = buffer.split('\n');
            buffer = lines.pop() || ''; // 保留不完整的行
            
            for (const line of lines) {
              const trimmedLine = line.trim();
              if (!trimmedLine) continue;
              
              // 处理SSE格式
              if (trimmedLine.startsWith('data: ')) {
                const data = trimmedLine.slice(6); // 移除 'data: '
                if (data === '[DONE]') break;
                
                // 创建模拟的MessageEvent
                const mockEvent = {
                  data,
                  type: 'message'
                } as MessageEvent;
                
                handleSSEMessage(mockEvent);
              }
            }
          }
        } catch (error) {
          console.error('流读取错误:', error);
          handleSSEError(new Event('error'));
        }
      };

      // 开始读取流
      readStream();

      return finalThreadId;

    } catch (error) {
      console.error('发送消息时出错:', error);
      const errorMsg = `发送消息失败: ${error}`;
      setState(prev => ({ ...prev, error: errorMsg, isConnected: false }));
      onError?.(errorMsg);
      throw error;
    }
  }, [state.threadId, closeConnection, handleSSEMessage, handleSSEError, onConnectionChange, onError, API_BASE_URL]);

  // 恢复中断的线程
  const resumeThread = useCallback(async (threadId: string, userConfirmed: boolean = true) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/threads/${threadId}/resume`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          thread_id: threadId,
          user_confirmed: userConfirmed
        })
      });

      if (!response.ok) {
        throw new Error(`恢复线程失败: ${response.status}`);
      }

      const data = await response.json();
      
      setState(prev => ({
        ...prev,
        isWaiting: false,
        isConnected: true
      }));

      return data;

    } catch (error) {
      console.error('恢复线程时出错:', error);
      const errorMsg = `恢复线程失败: ${error}`;
      setState(prev => ({ ...prev, error: errorMsg }));
      onError?.(errorMsg);
      throw error;
    }
  }, [onError, API_BASE_URL]);

  // 获取线程状态
  const getThreadStatus = useCallback(async (threadId: string): Promise<ThreadState | null> => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/threads/${threadId}`);
      
      if (!response.ok) {
        throw new Error(`获取线程状态失败: ${response.status}`);
      }

      const threadState = await response.json();
      return threadState;

    } catch (error) {
      console.error('获取线程状态时出错:', error);
      onError?.(`获取线程状态失败: ${error}`);
      return null;
    }
  }, [onError, API_BASE_URL]);

  // 重置状态
  const reset = useCallback(() => {
    closeConnection();
    setState({
      isConnected: false,
      isWaiting: false,
      threadId: null,
      currentMessage: '',
      messages: [],
      error: null,
      plans: []
    });
    reconnectAttemptsRef.current = 0;
  }, [closeConnection]);

  // 取消当前请求
  const cancelRequest = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    closeConnection();
  }, [closeConnection]);

  // 清理副作用
  useEffect(() => {
    return () => {
      closeConnection();
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [closeConnection]);

  // 暴露的API
  const api = useMemo(() => ({
    // 状态
    ...state,
    
    // 方法
    sendMessage,
    resumeThread,
    getThreadStatus,
    reset,
    cancelRequest,
    closeConnection
  }), [
    state,
    sendMessage,
    resumeThread,
    getThreadStatus,
    reset,
    cancelRequest,
    closeConnection
  ]);

  return api;
};

// 便捷Hook - 用于简单的流式聊天
export const useSimpleSoloStream = (threadId?: string) => {
  const stream = useSoloStream({
    onWaitingForConfirmation: () => {
      console.log('HITL中断: 等待用户确认');
    },
    onError: (error) => {
      console.error('流错误:', error);
    }
  });

  const sendSimpleMessage = useCallback(async (message: string) => {
    return stream.sendMessage(message, threadId);
  }, [stream, threadId]);

  return {
    ...stream,
    sendSimpleMessage
  };
};

// Hook配置验证器
export const validateStreamOptions = (options: UseSoloStreamOptions): boolean => {
  if (options.reconnectInterval !== undefined && options.reconnectInterval < 1000) {
    console.warn('reconnectInterval不应小于1000ms');
    return false;
  }
  
  if (options.maxReconnectAttempts !== undefined && options.maxReconnectAttempts < 1) {
    console.warn('maxReconnectAttempts不应小于1');
    return false;
  }
  
  return true;
};
