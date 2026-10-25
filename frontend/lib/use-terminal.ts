'use client';
import { useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, base } from './api';
import { useUI } from './store';
import type { Snapshot } from './types';
export function useTerminal() {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ['snapshot'],
    queryFn: () => api<Snapshot>('/api/snapshot'),
    refetchInterval: 10000,
    retry: 1,
  });
  const setConnection = useUI((s) => s.setConnection);
  useEffect(() => {
    let socket: WebSocket | undefined,
      timer: ReturnType<typeof setTimeout>,
      disposed = false,
      attempt = 0,
      lastSequence = 0;
    let refreshing = false,
      dirty = false;
    const refresh = async () => {
      dirty = true;
      if (refreshing) return;
      refreshing = true;
      try {
        while (dirty && !disposed) {
          dirty = false;
          const snapshot = await api<Snapshot>('/api/snapshot');
          if (!disposed) {
            lastSequence = Math.max(lastSequence, snapshot.sequence);
            client.setQueryData(['snapshot'], snapshot);
            setConnection('Connected');
          }
        }
      } catch {
        if (!disposed) setConnection('Snapshot unavailable');
      } finally {
        refreshing = false;
      }
    };
    const connect = () => {
      if (disposed) return;
      setConnection(attempt ? 'Reconnecting' : 'Connecting');
      socket = new WebSocket(base.replace(/^http/, 'ws') + '/ws/trading');
      socket.onopen = () => {
        attempt = 0;
        setConnection('Connected');
        void refresh();
      };
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.type === 'heartbeat') {
          if (message.sequence > lastSequence) void refresh();
          return;
        }
        if (message.type === 'snapshot_required') {
          void refresh();
          return;
        }
        if (message.sequence <= lastSequence) return;
        // Snapshot refreshes are serialized; events arriving during a fetch request another pass.
        void refresh();
      };
      socket.onerror = () => socket?.close();
      socket.onclose = () => {
        if (disposed) return;
        setConnection('Reconnecting');
        timer = setTimeout(connect, Math.min(30000, 1000 * 2 ** attempt++));
      };
    };
    connect();
    return () => {
      disposed = true;
      clearTimeout(timer);
      socket?.close();
      setConnection('Disconnected');
    };
  }, [client, setConnection]);
  return query;
}
