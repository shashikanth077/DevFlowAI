import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Link from '@mui/material/Link';
import Stack from '@mui/material/Stack';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import Typography from '@mui/material/Typography';
import { useState } from 'react';
import EmptyState from '../../components/EmptyState';
import { api, errorMessage } from '../../services/api';
import { monoFont } from '../../theme';
import type { ToolCall, TraceInfo } from '../../types';

const STATUS_COLOR = { ok: 'success', error: 'error', blocked: 'warning' } as const;

export function ToolCalls({ calls }: { calls: ToolCall[] }) {
  if (!calls.length) {
    return (
      <EmptyState
        title="No MCP tool calls"
        description="Agents call read-only MCP tools (repository search, documentation, ...) when MCP is enabled in Settings and the model decides it needs them. Every call, including blocked ones, is listed here."
      />
    );
  }
  return (
    <TableContainer>
      <Table size="small" aria-label="MCP tool calls">
        <TableHead>
          <TableRow>
            <TableCell>Agent</TableCell>
            <TableCell>Tool</TableCell>
            <TableCell>Arguments</TableCell>
            <TableCell>Status</TableCell>
            <TableCell>Result</TableCell>
            <TableCell align="right">Time</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {calls.map((call) => (
            <TableRow key={call.id}>
              <TableCell>{call.agent.replace(/_/g, ' ')}</TableCell>
              <TableCell>
                <Box component="code" sx={{ fontSize: 12 }}>
                  {call.server}.{call.tool}
                </Box>
              </TableCell>
              <TableCell sx={{ maxWidth: 220 }}>
                <Typography variant="caption" sx={{ fontFamily: monoFont, wordBreak: 'break-all' }}>
                  {JSON.stringify(call.arguments)}
                </Typography>
              </TableCell>
              <TableCell>
                <Chip size="small" label={call.status} color={STATUS_COLOR[call.status]} variant="outlined" />
              </TableCell>
              <TableCell sx={{ maxWidth: 420 }}>
                <Box component="pre" sx={{ m: 0, fontFamily: monoFont, fontSize: 11.5, whiteSpace: 'pre-wrap', maxHeight: 120, overflow: 'auto' }}>
                  {call.result_preview}
                </Box>
              </TableCell>
              <TableCell align="right">{call.duration_ms} ms</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

export function TracePanel({ workflowId, runIds }: { workflowId: string; runIds: string[] }) {
  const [trace, setTrace] = useState<TraceInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const resolve = async () => {
    setLoading(true);
    setError(null);
    try {
      setTrace(await api.workflowTrace(workflowId, true));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  if (!runIds.length) {
    return (
      <Alert severity="info">
        No LangSmith traces for this workflow. Set <code>LANGSMITH_TRACING=true</code> and <code>LANGSMITH_API_KEY</code> on the backend to trace every agent step, LLM call and tool call.
      </Alert>
    );
  }
  return (
    <Stack spacing={1.5}>
      <Typography variant="body2" color="text.secondary">
        Each approval pause splits the run into segments; all of them share <code>thread_id = {workflowId}</code> so LangSmith groups them into one thread.
      </Typography>
      {runIds.map((id, index) => (
        <Stack key={id} direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 1 }}>
          <Chip size="small" label={index === 0 ? 'start' : `resume ${index}`} />
          <Box component="code" sx={{ fontSize: 12 }}>
            {id}
          </Box>
          {trace?.urls[id] && (
            <Link href={trace.urls[id] ?? undefined} target="_blank" rel="noopener noreferrer" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}>
              Open in LangSmith <OpenInNewIcon sx={{ fontSize: 14 }} />
            </Link>
          )}
        </Stack>
      ))}
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
        <Button size="small" variant="outlined" onClick={resolve} disabled={loading}>
          {loading ? 'Resolving…' : 'Get LangSmith links'}
        </Button>
        {trace && !Object.values(trace.urls).some(Boolean) && (
          <Typography variant="caption" color="text.secondary">
            Links unavailable (LangSmith not reachable). Search project “{trace.project}” for the run ids above.
          </Typography>
        )}
      </Stack>
      {error && <Alert severity="error">{error}</Alert>}
    </Stack>
  );
}
