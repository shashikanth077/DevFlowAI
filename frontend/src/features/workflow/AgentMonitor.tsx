import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty';
import RemoveCircleOutlineIcon from '@mui/icons-material/RemoveCircleOutlineOutlined';
import Accordion from '@mui/material/Accordion';
import AccordionDetails from '@mui/material/AccordionDetails';
import AccordionSummary from '@mui/material/AccordionSummary';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import LinearProgress from '@mui/material/LinearProgress';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import StatusChip from '../../components/StatusChip';
import { monoFont } from '../../theme';
import type { AgentStatus, WorkflowDetail, WorkflowLog } from '../../types';
import { agentProgress, overallProgress, stageLabel } from './agents';

function StatusIcon({ status }: { status: AgentStatus }) {
  if (status === 'running') return <CircularProgress size={20} aria-label="running" />;
  if (status === 'completed') return <CheckCircleIcon color="success" />;
  if (status === 'failed' || status === 'rejected') return <ErrorIcon color="error" />;
  if (status === 'cancelled') return <RemoveCircleOutlineIcon color="disabled" />;
  return <HourglassEmptyIcon color="disabled" />;
}

function displayStatus(status: AgentStatus, relevant: boolean): string {
  if (!relevant && status === 'cancelled') return 'Not needed';
  return { pending: 'Pending', running: 'Running', completed: 'Completed', failed: 'Failed', cancelled: 'Skipped', rejected: 'Rejected', waiting: 'Waiting' }[status];
}

export default function AgentMonitor({ workflow, logs }: { workflow: WorkflowDetail; logs: WorkflowLog[] }) {
  const agents = agentProgress(workflow);
  const progress = overallProgress(workflow);
  return (
    <Stack spacing={2}>
      <Box>
        <Stack direction="row" sx={{ justifyContent: 'space-between', mb: 1, flexWrap: 'wrap', gap: 1 }}>
          <Typography variant="body2">
            Current stage: <strong>{workflow.current_stage ? stageLabel(workflow.current_stage) : 'Queued'}</strong>
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Retry {workflow.retry_count} of {workflow.max_retries} · {progress}% complete
          </Typography>
        </Stack>
        <LinearProgress
          variant={workflow.status === 'running' && progress === 0 ? 'indeterminate' : 'determinate'}
          value={progress}
          color={workflow.status === 'failed' ? 'error' : workflow.status === 'completed' ? 'success' : 'primary'}
          sx={{ height: 8, borderRadius: 4 }}
          aria-label="workflow progress"
        />
      </Box>
      {agents.map((agent) => {
        const agentLogs = logs.filter((l) => l.agent === agent.key);
        return (
          <Accordion key={agent.key} disableGutters sx={{ opacity: agent.relevant ? 1 : 0.55 }} data-testid={`agent-${agent.key}`}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Stack direction="row" spacing={2} sx={{ alignItems: 'center', width: '100%', pr: 1 }}>
                <StatusIcon status={agent.status} />
                <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                  <Typography sx={{ fontWeight: 600 }}>{agent.name}</Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ display: { xs: 'none', sm: 'block' } }}>
                    {agent.relevant ? agent.description : 'Not required for this requirement/repository'}
                  </Typography>
                </Box>
                {agent.retries > 0 && <Chip size="small" color="warning" variant="outlined" label={`${agent.retries} retr${agent.retries === 1 ? 'y' : 'ies'}`} />}
                <Chip size="small" label={displayStatus(agent.status, agent.relevant)} color={agent.status === 'completed' ? 'success' : agent.status === 'failed' ? 'error' : agent.status === 'running' ? 'info' : 'default'} variant={agent.status === 'running' ? 'filled' : 'outlined'} />
              </Stack>
            </AccordionSummary>
            <AccordionDetails>
              <Stack spacing={1.5}>
                {agent.executions.length === 0 && (
                  <Typography variant="body2" color="text.secondary">
                    Not started.
                  </Typography>
                )}
                {agent.executions.map((execution) => (
                  <Box key={execution.id} sx={{ border: 1, borderColor: 'divider', borderRadius: 2, p: 1.5 }}>
                    <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 1 }}>
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>
                        Attempt {execution.attempt}
                      </Typography>
                      <StatusChip status={execution.status} />
                      <Typography variant="caption" color="text.secondary">
                        {new Date(execution.started_at).toLocaleTimeString()}
                        {execution.duration_ms != null && ` · ${(execution.duration_ms / 1000).toFixed(1)}s`}
                      </Typography>
                    </Stack>
                    {execution.error && (
                      <Typography variant="body2" color="error" sx={{ mt: 1, whiteSpace: 'pre-wrap' }}>
                        {execution.error}
                      </Typography>
                    )}
                    {execution.output && Object.keys(execution.output).length > 0 && (
                      <Box component="pre" sx={{ m: 0, mt: 1, fontFamily: monoFont, fontSize: 12, whiteSpace: 'pre-wrap', color: 'text.secondary' }}>
                        {Object.entries(execution.output)
                          .map(([k, v]) => `${k}: ${String(v)}`)
                          .join('\n')}
                      </Box>
                    )}
                  </Box>
                ))}
                {agentLogs.length > 0 && (
                  <Box component="pre" sx={{ m: 0, p: 1.5, bgcolor: 'action.hover', borderRadius: 2, fontFamily: monoFont, fontSize: 12, whiteSpace: 'pre-wrap', maxHeight: 240, overflow: 'auto' }}>
                    {agentLogs.map((l) => `[${new Date(l.created_at).toLocaleTimeString()}] ${l.level.toUpperCase()} ${l.message}`).join('\n')}
                  </Box>
                )}
              </Stack>
            </AccordionDetails>
          </Accordion>
        );
      })}
    </Stack>
  );
}
