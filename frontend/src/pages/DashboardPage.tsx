import AccountTreeIcon from '@mui/icons-material/AccountTree';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import FolderIcon from '@mui/icons-material/Folder';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import CardHeader from '@mui/material/CardHeader';
import Link from '@mui/material/Link';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemText from '@mui/material/ListItemText';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { Link as RouterLink } from 'react-router-dom';
import EmptyState from '../components/EmptyState';
import ErrorAlert from '../components/ErrorAlert';
import LoadingState from '../components/LoadingState';
import StatCard from '../components/StatCard';
import WorkflowTable from '../features/workflow/WorkflowTable';
import { useAsync } from '../hooks/useAsync';
import { api } from '../services/api';

export default function DashboardPage() {
  const { data, loading, error, reload } = useAsync(() => api.dashboard());

  return (
    <Stack spacing={3}>
      <Stack direction={{ xs: 'column', sm: 'row' }} sx={{ justifyContent: 'space-between', gap: 2 }}>
        <div>
          <Typography variant="h4" component="h1">
            Dashboard
          </Typography>
          <Typography color="text.secondary">Your AI engineering team at a glance.</Typography>
        </div>
        <Button variant="contained" component={RouterLink} to="/projects/new" sx={{ alignSelf: { sm: 'center' } }}>
          New requirement
        </Button>
      </Stack>
      <ErrorAlert error={error} title="Could not load dashboard" onRetry={reload} />
      {loading && !data ? (
        <LoadingState />
      ) : data ? (
        <>
          <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)', lg: 'repeat(4, 1fr)' } }}>
            <StatCard label="Total projects" value={data.total_projects} icon={<FolderIcon />} />
            <StatCard
              label="Active agent executions"
              value={data.active_workflows}
              icon={<AccountTreeIcon />}
              color="info.main"
              hint={data.awaiting_approval ? `${data.awaiting_approval} awaiting your approval` : undefined}
            />
            <StatCard label="Successful workflows" value={data.successful_workflows} icon={<CheckCircleIcon />} color="success.main" />
            <StatCard label="Failed workflows" value={data.failed_workflows} icon={<ErrorIcon />} color="error.main" />
          </Box>
          <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', lg: '2fr 1fr' }, alignItems: 'start' }}>
            <Card>
              <CardHeader title="Recent workflows" action={<Button component={RouterLink} to="/workflows">View all</Button>} />
              {data.recent_workflows.length ? (
                <WorkflowTable workflows={data.recent_workflows} dense />
              ) : (
                <EmptyState
                  title="No workflows yet"
                  description="Connect a GitHub repository and describe a requirement to start your first multi-agent workflow."
                  action={<Button component={RouterLink} to="/projects/new">Create project</Button>}
                />
              )}
            </Card>
            <Card>
              <CardHeader title="Recent pull requests" />
              <CardContent sx={{ pt: 0 }}>
                {data.recent_pull_requests.length ? (
                  <List dense disablePadding>
                    {data.recent_pull_requests.map((pr) => (
                      <ListItem key={pr.id} disableGutters>
                        <ListItemText
                          primary={
                            <Link href={pr.url} target="_blank" rel="noopener noreferrer" sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}>
                              {pr.repository_full_name}#{pr.number} <OpenInNewIcon sx={{ fontSize: 14 }} />
                            </Link>
                          }
                          secondary={`${pr.title} · ${pr.state}${pr.merged ? ' (merged)' : ''}`}
                        />
                      </ListItem>
                    ))}
                  </List>
                ) : (
                  <Typography variant="body2" color="text.secondary">
                    Pull requests created by the release agent appear here.
                  </Typography>
                )}
              </CardContent>
            </Card>
          </Box>
        </>
      ) : null}
    </Stack>
  );
}
