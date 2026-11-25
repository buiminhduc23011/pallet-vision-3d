import { useEffect, useRef } from 'react';
import type { Session } from '../api/types';

export function useSessionEvents(
  sessionId: string | undefined,
  onEvent: (type: string, payload: Record<string, unknown>) => void,
) {
  const callback = useRef(onEvent);
  callback.current = onEvent;
  useEffect(() => {
    if (!sessionId) return;
    let socket: WebSocket | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let disposed = false;
    let delay = 500;
    const connect = () => {
      socket = new WebSocket(
        `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/v1/sessions/${sessionId}/events`,
      );
      socket.onopen = () => {
        delay = 500;
      };
      socket.onmessage = (event) => {
        const data = JSON.parse(event.data) as { type: string; payload: Record<string, unknown> };
        callback.current(data.type, data.payload);
      };
      socket.onclose = (event) => {
        if (!disposed && event.code !== 1008) {
          callback.current('connection.lost', {});
          timer = setTimeout(connect, delay);
          delay = Math.min(delay * 2, 10000);
        }
      };
    };
    connect();
    return () => {
      disposed = true;
      clearTimeout(timer);
      socket?.close();
    };
  }, [sessionId]);
}

export function isSession(payload: Record<string, unknown>): payload is Session & Record<string, unknown> {
  return typeof payload.id === 'string' && typeof payload.mode === 'string';
}
