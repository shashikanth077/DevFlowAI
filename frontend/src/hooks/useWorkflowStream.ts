import { useEffect, useRef, useState } from 'react';
import { api } from '../services/api';
import type { WorkflowDetail, WorkflowLog } from '../types';

const TERMINAL = new Set(['completed', 'failed', 'cancelled']);

/** Append log entries, ignoring ids already present (SSE and polling can overlap). */
export function mergeLogs(current: WorkflowLog[], incoming: WorkflowLog[]): WorkflowLog[] {
  if (!incoming.length) return current;
  const seen = new Set(current.map((l) => l.id));
  const fresh = incoming.filter((l) => !seen.has(l.id));
  if (!fresh.length) return current;
  return [...current, ...fresh].sort((a, b) => a.id - b.id);
}

export interface WorkflowStream {
  workflow: WorkflowDetail | null;
  logs: WorkflowLog[];
  connected: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

/**
 * Live workflow updates over Server-Sent Events, with a polling fallback when
 * EventSource is unavailable or the stream drops.
 */
export function useWorkflowStream(workflowId: string | undefined): WorkflowStream {
  const [workflow, setWorkflow] = useState<WorkflowDetail | null>(null);
  const [logs, setLogs] = useState<WorkflowLog[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lastLogId = useRef(0);
  const finished = useRef(false);

  const refresh = async () => {
    if (!workflowId) return;
    try {
      const [detail, newLogs] = await Promise.all([api.workflow(workflowId), api.workflowLogs(workflowId, lastLogId.current)]);
      setWorkflow(detail);
      finished.current = TERMINAL.has(detail.status);
      if (newLogs.length) {
        lastLogId.current = Math.max(lastLogId.current, newLogs[newLogs.length - 1].id);
        setLogs((prev) => mergeLogs(prev, newLogs));
      }
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => {
    if (!workflowId) return undefined;
    lastLogId.current = 0;
    finished.current = false;
    setLogs([]);
    setWorkflow(null);
    let source: EventSource | null = null;
    let poll: ReturnType<typeof setInterval> | null = null;
    let stopped = false;

    const startPolling = () => {
      if (poll) return;
      poll = setInterval(() => {
        if (!finished.current) void refresh();
      }, 3000);
    };

    void refresh();
    if (typeof EventSource !== 'undefined') {
      source = new EventSource(api.workflowEventsUrl(workflowId));
      source.onopen = () => setConnected(true);
      source.addEventListener('workflow', (event) => {
        const detail = JSON.parse((event as MessageEvent).data) as WorkflowDetail;
        setWorkflow(detail);
      });
      source.addEventListener('log', (event) => {
        const entry = JSON.parse((event as MessageEvent).data) as WorkflowLog;
        lastLogId.current = Math.max(lastLogId.current, entry.id);
        setLogs((prev) => mergeLogs(prev, [entry]));
      });
      source.addEventListener('end', () => {
        source?.close();
        setConnected(false);
      });
      source.onerror = () => {
        setConnected(false);
        source?.close();
        if (!stopped) startPolling();
      };
    } else {
      startPolling();
    }
    return () => {
      stopped = true;
      source?.close();
      if (poll) clearInterval(poll);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflowId]);

  // Stop polling once the workflow is finished.
  useEffect(() => {
    if (workflow && TERMINAL.has(workflow.status)) setConnected(false);
  }, [workflow]);

  return { workflow, logs, connected, error, refresh };
}
