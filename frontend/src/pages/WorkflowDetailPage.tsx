import CancelIcon from '@mui/icons-material/Cancel';
import FiberManualRecordIcon from '@mui/icons-material/FiberManualRecord';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Stack from '@mui/material/Stack';
import Tab from '@mui/material/Tab';
import Tabs from '@mui/material/Tabs';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import ErrorAlert from '../components/ErrorAlert';
import LoadingState from '../components/LoadingState';
import StatusChip from '../components/StatusChip';
import AgentMonitor from '../features/workflow/AgentMonitor';
import AnalysisView from '../features/workflow/AnalysisView';
import ApprovalPanel from '../features/workflow/ApprovalPanel';
import CodeChanges from '../features/workflow/CodeChanges';
import GitHubResults from '../features/workflow/GitHubResults';
import LogViewer from '../features/workflow/LogViewer';
import TaskBoard from '../features/workflow/TaskBoard';
import { ReviewReports, TestResults } from '../features/workflow/TestResults';
import { useWorkflowStream } from '../hooks/useWorkflowStream';
import { api, errorMessage } from '../services/api';
import { useAppDispatch } from '../store';
import { notify } from '../store/notificationsSlice';
import type { WorkflowResults } from '../types';

const TABS = ['Agent monitor', 'Analysis', 'Tasks', 'Code changes', 'Tests & review', 'GitHub results', 'Logs'] as const;
const ACTIVE = new Set(['queued', 'running', 'awaiting_approval']);

export default function WorkflowDetailPage() {
  const { workflowId } = useParams();
  const dispatch = useAppDispatch();
  const { workflow, logs, connected, error, refresh } = useWorkflowStream(workflowId);
  const [tab, setTab] = useState(0);
  const [results, setResults] = useState<WorkflowResults | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Refresh results whenever the workflow advances to a new stage or status.
  const stageKey = `${workflow?.status}:${workflow?.current_stage}:${workflow?.agent_executions.length}`;
  useEffect(() => {
    if (!workflowId || !workflow) return;
    api.workflowResults(workflowId).then(setResults).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflowId, stageKey]);

  if (!workflow) return error ? <ErrorAlert error={error} title="Could not load workflow" onRetry={refresh} /> : <LoadingState label="Loading workflow…" />;

  const decide = async (approved: boolean, comment: string) => {
    setBusy(true);
    setActionError(null);
    try {
      await api.approveWorkflow(workflow.id, approved, comment);
      dispatch(notify(approved ? 'Approved - continuing workflow.' : 'Rejected - workflow cancelled.', approved ? 'success' : 'warning'));
      await refresh();
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    setBusy(true);
    setActionError(null);
    try {
      await api.cancelWorkflow(workflow.id);
      dispatch(notify('Cancellation requested.', 'info'));
      await refresh();
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Stack spacing={2.5}>
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} sx={{ justifyContent: 'space-between' }}>
        <Box sx={{ minWidth: 0 }}>
          <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 1 }}>
            <Typography variant="h5" component="h1">
              {workflow.requirement_analysis?.title ?? 'Workflow'}
            </Typography>
            <StatusChip status={workflow.status} size="medium" />
            {ACTIVE.has(workflow.status) && (
              <Tooltip title={connected ? 'Live updates via Server-Sent Events' : 'Polling for updates'}>
                <FiberManualRecordIcon sx={{ fontSize: 14, color: connected ? 'success.main' : 'text.disabled' }} aria-label={connected ? 'live' : 'polling'} />
              </Tooltip>
            )}
          </Stack>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            {workflow.repository_full_name} · base <code>{workflow.base_branch}</code>
            {workflow.feature_branch && (
              <>
                {' '}
                → <code>{workflow.feature_branch}</code>
              </>
            )}
          </Typography>
        </Box>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'flex-start' }}>
          {workflow.pull_request_url && (
            <Button variant="contained" href={workflow.pull_request_url} target="_blank" rel="noopener noreferrer" endIcon={<OpenInNewIcon />}>
              Pull request
            </Button>
          )}
          {ACTIVE.has(workflow.status) && (
            <Button variant="outlined" color="error" startIcon={<CancelIcon />} onClick={cancel} disabled={busy || workflow.cancel_requested}>
              {workflow.cancel_requested ? 'Cancelling…' : 'Cancel'}
            </Button>
          )}
        </Stack>
      </Stack>

      <Card>
        <CardContent>
          <Typography variant="subtitle2" color="text.secondary">
            Requirement
          </Typography>
          <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
            {workflow.requirement}
          </Typography>
        </CardContent>
      </Card>

      <ErrorAlert error={actionError} title="Action failed" />
      {workflow.status === 'failed' && workflow.error_details && (
        <Alert severity="error">
          <AlertTitle>Workflow failed{workflow.error_details.agent ? ` in ${workflow.error_details.agent}` : ''}</AlertTitle>
          {workflow.error_details.message}
        </Alert>
      )}
      {workflow.status === 'cancelled' && <Alert severity="info">This workflow was cancelled. {workflow.error_details?.message ?? ''}</Alert>}
      {workflow.status === 'awaiting_approval' && workflow.pending_approval && (
        <ApprovalPanel approval={workflow.pending_approval} busy={busy} onDecision={decide} />
      )}
      {workflow.status === 'completed' && workflow.pull_request_url && (
        <Alert severity="success">
          <AlertTitle>Pull request created</AlertTitle>
          <a href={workflow.pull_request_url} target="_blank" rel="noopener noreferrer">
            {workflow.pull_request_url}
          </a>{' '}
          — commit <code>{workflow.commit_id?.slice(0, 10)}</code>
        </Alert>
      )}

      <Card>
        <Tabs value={tab} onChange={(_, value: number) => setTab(value)} variant="scrollable" scrollButtons="auto" sx={{ borderBottom: 1, borderColor: 'divider', px: 1 }}>
          {TABS.map((label) => (
            <Tab key={label} label={label} />
          ))}
        </Tabs>
        <CardContent>
          {tab === 0 && <AgentMonitor workflow={workflow} logs={logs} />}
          {tab === 1 && <AnalysisView workflow={workflow} />}
          {tab === 2 && <TaskBoard tasks={workflow.tasks} />}
          {tab === 3 && <CodeChanges changes={results?.file_changes ?? []} />}
          {tab === 4 && (
            <Stack spacing={3}>
              <Typography variant="h6">Test results</Typography>
              <TestResults results={results?.test_results ?? []} />
              <Typography variant="h6">Code review</Typography>
              <ReviewReports reports={results?.review_reports ?? []} />
            </Stack>
          )}
          {tab === 5 && results && <GitHubResults results={results} />}
          {tab === 6 && <LogViewer logs={logs} />}
        </CardContent>
      </Card>
    </Stack>
  );
}
