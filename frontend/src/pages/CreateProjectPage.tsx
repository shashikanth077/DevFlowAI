import LockIcon from '@mui/icons-material/Lock';
import RocketLaunchIcon from '@mui/icons-material/RocketLaunch';
import Alert from '@mui/material/Alert';
import Autocomplete from '@mui/material/Autocomplete';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import MenuItem from '@mui/material/MenuItem';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import { useEffect, useMemo, useState } from 'react';
import { Link as RouterLink, useNavigate } from 'react-router-dom';
import ErrorAlert from '../components/ErrorAlert';
import LoadingState from '../components/LoadingState';
import { useAsync } from '../hooks/useAsync';
import { api, errorMessage } from '../services/api';
import { useAppDispatch } from '../store';
import { notify } from '../store/notificationsSlice';
import type { GitHubBranch, GitHubRepo } from '../types';

export const SAMPLE_REQUIREMENTS = [
  {
    label: 'Health endpoint',
    text: 'Add a GET /api/health endpoint that returns {"status": "ok", "version": <app version>} with HTTP 200, plus an automated test for it.',
  },
  {
    label: 'Todo filtering',
    text: 'Allow users to filter the todo list by status (all, active, completed). Add a filter control above the list in the UI, support a ?status= query parameter on the list API, validate unknown values with HTTP 422, and add tests for both frontend and backend.',
  },
  {
    label: 'Input validation',
    text: 'Validate the user registration payload: email must be a valid address, password must be at least 12 characters with one digit. Return clear 422 error messages and cover the rules with unit tests.',
  },
];

export default function CreateProjectPage() {
  const navigate = useNavigate();
  const dispatch = useAppDispatch();
  const github = useAsync(() => api.githubStatus());
  const connected = github.data?.connected ?? false;
  const repos = useAsync(() => api.githubRepos(), [connected], { enabled: connected });
  const [repo, setRepo] = useState<GitHubRepo | null>(null);
  const [branches, setBranches] = useState<GitHubBranch[]>([]);
  const [branchesLoading, setBranchesLoading] = useState(false);
  const [branch, setBranch] = useState('');
  const [name, setName] = useState('');
  const [requirement, setRequirement] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!repo) return;
    setName(repo.name);
    setBranch(repo.default_branch);
    setBranchesLoading(true);
    api
      .githubBranches(repo.full_name)
      .then(setBranches)
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setBranchesLoading(false));
  }, [repo]);

  const requirementError = requirement.length > 0 && requirement.trim().length < 10;
  const canSubmit = !!repo && !!branch && !!name.trim() && requirement.trim().length >= 10 && !submitting;
  const selectedBranch = useMemo(() => branches.find((b) => b.name === branch), [branches, branch]);

  const start = async () => {
    if (!repo) return;
    setSubmitting(true);
    setError(null);
    try {
      const connectedRepo = await api.connectRepository(repo.full_name);
      const projects = await api.projects();
      const project =
        projects.find((p) => p.repository.id === connectedRepo.id && p.base_branch === branch && p.name === name.trim()) ??
        (await api.createProject({ name: name.trim(), repository_id: connectedRepo.id, base_branch: branch }));
      const workflow = await api.startWorkflow({ project_id: project.id, requirement: requirement.trim(), base_branch: branch });
      dispatch(notify('Workflow started - agents are on it.', 'success'));
      navigate(`/workflows/${workflow.id}`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  if (github.loading) return <LoadingState label="Checking GitHub connection…" />;

  return (
    <Stack spacing={3} sx={{ maxWidth: 880 }}>
      <div>
        <Typography variant="h4" component="h1">
          Create project
        </Typography>
        <Typography color="text.secondary">
          Select a repository and base branch, describe the requirement, and the agent team takes it from there.
        </Typography>
      </div>
      <ErrorAlert error={github.error} title="Could not check GitHub connection" onRetry={github.reload} />
      {!connected && !github.error && (
        <Alert severity="warning" action={<Button component={RouterLink} to="/settings">Open settings</Button>}>
          Connect GitHub first: add a personal access token (Contents and Pull requests read/write) in Settings.
        </Alert>
      )}
      <ErrorAlert error={error} title="Could not start workflow" />
      <Card>
        <CardContent>
          <Stack spacing={3}>
            <Typography variant="h6">1. Repository</Typography>
            <ErrorAlert error={repos.error} title="Could not list repositories" onRetry={repos.reload} />
            <Autocomplete
              options={repos.data ?? []}
              loading={repos.loading}
              disabled={!connected}
              value={repo}
              onChange={(_, value) => setRepo(value)}
              getOptionLabel={(option) => option.full_name}
              isOptionEqualToValue={(a, b) => a.full_name === b.full_name}
              renderOption={(props, option) => {
                const { key, ...rest } = props as typeof props & { key: string };
                return (
                  <li key={key} {...rest}>
                    <Stack>
                      <Typography variant="body2" sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                        {option.full_name} {option.private && <LockIcon sx={{ fontSize: 14 }} />}
                      </Typography>
                      {option.description && (
                        <Typography variant="caption" color="text.secondary">
                          {option.description}
                        </Typography>
                      )}
                    </Stack>
                  </li>
                );
              }}
              renderInput={(params) => <TextField {...params} label="GitHub repository" placeholder="owner/name" />}
            />
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
              <TextField
                select
                label="Base branch"
                value={branches.some((b) => b.name === branch) ? branch : ''}
                onChange={(e) => setBranch(e.target.value)}
                disabled={!repo || branchesLoading}
                sx={{ flex: 1 }}
                helperText={
                  branchesLoading ? 'Loading branches…' : selectedBranch?.protected ? 'Protected branch: changes will go to a new feature branch' : 'Feature branch will be created from this branch'
                }
                slotProps={{ input: { endAdornment: branchesLoading ? <CircularProgress size={18} sx={{ mr: 3 }} /> : undefined } }}
              >
                {branches.map((b) => (
                  <MenuItem key={b.name} value={b.name}>
                    {b.name} {b.protected ? '🔒' : ''}
                  </MenuItem>
                ))}
              </TextField>
              <TextField label="Project name" value={name} onChange={(e) => setName(e.target.value)} disabled={!repo} sx={{ flex: 1 }} />
            </Stack>
            <Typography variant="h6">2. Requirement</Typography>
            <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1 }}>
              {SAMPLE_REQUIREMENTS.map((sample) => (
                <Chip key={sample.label} label={sample.label} variant="outlined" onClick={() => setRequirement(sample.text)} />
              ))}
            </Stack>
            <TextField
              label="Software requirement"
              multiline
              minRows={6}
              value={requirement}
              onChange={(e) => setRequirement(e.target.value)}
              error={requirementError}
              helperText={requirementError ? 'Describe the requirement in at least 10 characters' : 'Plain language. Include business goals, constraints and anything the team must not change.'}
            />
            <Alert severity="info">
              You will be asked to approve before generated code runs in the sandbox and again before anything is pushed or a pull request is opened.
            </Alert>
            <Stack direction="row" sx={{ justifyContent: 'flex-end' }}>
              <Button variant="contained" size="large" startIcon={<RocketLaunchIcon />} disabled={!canSubmit} onClick={start}>
                {submitting ? 'Starting…' : 'Start workflow'}
              </Button>
            </Stack>
          </Stack>
        </CardContent>
      </Card>
    </Stack>
  );
}
