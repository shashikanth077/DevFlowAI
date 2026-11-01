import Card from '@mui/material/Card';
import MenuItem from '@mui/material/MenuItem';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import { useState } from 'react';
import EmptyState from '../components/EmptyState';
import ErrorAlert from '../components/ErrorAlert';
import LoadingState from '../components/LoadingState';
import WorkflowTable from '../features/workflow/WorkflowTable';
import { useAsync } from '../hooks/useAsync';
import { api } from '../services/api';

const STATUSES = ['', 'running', 'awaiting_approval', 'completed', 'failed', 'cancelled'];

export default function WorkflowsPage() {
  const [status, setStatus] = useState('');
  const { data, loading, error, reload } = useAsync(() => api.workflows(status ? { status } : undefined), [status]);
  return (
    <Stack spacing={3}>
      <Stack direction={{ xs: 'column', sm: 'row' }} sx={{ justifyContent: 'space-between', gap: 2 }}>
        <div>
          <Typography variant="h4" component="h1">
            Workflow history
          </Typography>
          <Typography color="text.secondary">Every run is persisted with its agents, tasks, diffs, tests and reviews.</Typography>
        </div>
        <TextField select size="small" label="Status" value={status} onChange={(e) => setStatus(e.target.value)} sx={{ minWidth: 200 }}>
          {STATUSES.map((s) => (
            <MenuItem key={s || 'all'} value={s}>
              {s ? s.replace('_', ' ') : 'All'}
            </MenuItem>
          ))}
        </TextField>
      </Stack>
      <ErrorAlert error={error} onRetry={reload} />
      <Card>
        {loading && !data ? (
          <LoadingState />
        ) : data?.length ? (
          <WorkflowTable workflows={data} />
        ) : (
          <EmptyState title="No workflows found" description="Start a workflow from the Create Project page." />
        )}
      </Card>
    </Stack>
  );
}
