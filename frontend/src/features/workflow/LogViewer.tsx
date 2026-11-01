import Box from '@mui/material/Box';
import MenuItem from '@mui/material/MenuItem';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import { useEffect, useMemo, useRef, useState } from 'react';
import EmptyState from '../../components/EmptyState';
import { monoFont } from '../../theme';
import type { WorkflowLog } from '../../types';

const LEVEL_COLOR = { info: 'text.primary', warning: 'warning.main', error: 'error.main' } as const;

export default function LogViewer({ logs }: { logs: WorkflowLog[] }) {
  const [agent, setAgent] = useState('all');
  const [level, setLevel] = useState('all');
  const endRef = useRef<HTMLDivElement>(null);
  const agents = useMemo(() => Array.from(new Set(logs.map((l) => l.agent ?? 'system'))), [logs]);
  const visible = logs.filter((l) => (agent === 'all' || (l.agent ?? 'system') === agent) && (level === 'all' || l.level === level));

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: 'nearest' });
  }, [visible.length]);

  if (!logs.length) return <EmptyState title="No logs yet" />;
  return (
    <Stack spacing={1.5}>
      <Stack direction="row" spacing={1}>
        <TextField select size="small" label="Agent" value={agent} onChange={(e) => setAgent(e.target.value)} sx={{ minWidth: 200 }}>
          <MenuItem value="all">All agents</MenuItem>
          {agents.map((a) => (
            <MenuItem key={a} value={a}>
              {a}
            </MenuItem>
          ))}
        </TextField>
        <TextField select size="small" label="Level" value={level} onChange={(e) => setLevel(e.target.value)} sx={{ minWidth: 140 }}>
          {['all', 'info', 'warning', 'error'].map((l) => (
            <MenuItem key={l} value={l}>
              {l}
            </MenuItem>
          ))}
        </TextField>
      </Stack>
      <Box sx={{ fontFamily: monoFont, fontSize: 12.5, bgcolor: 'action.hover', borderRadius: 2, p: 1.5, maxHeight: 520, overflow: 'auto' }} role="log" aria-live="polite">
        {visible.map((entry) => (
          <Box key={entry.id} sx={{ color: LEVEL_COLOR[entry.level], whiteSpace: 'pre-wrap', py: 0.25 }}>
            <Box component="span" sx={{ color: 'text.disabled' }}>
              {new Date(entry.created_at).toLocaleTimeString()}{' '}
            </Box>
            <Box component="span" sx={{ color: 'primary.main' }}>
              [{entry.agent ?? 'system'}]
            </Box>{' '}
            {entry.message}
          </Box>
        ))}
        <div ref={endRef} />
      </Box>
    </Stack>
  );
}
