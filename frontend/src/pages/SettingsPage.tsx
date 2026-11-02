import GitHubIcon from '@mui/icons-material/GitHub';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import CardHeader from '@mui/material/CardHeader';
import Chip from '@mui/material/Chip';
import FormControlLabel from '@mui/material/FormControlLabel';
import MenuItem from '@mui/material/MenuItem';
import Slider from '@mui/material/Slider';
import Stack from '@mui/material/Stack';
import Switch from '@mui/material/Switch';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import { useEffect, useState } from 'react';
import ErrorAlert from '../components/ErrorAlert';
import IntegrationsCard from '../features/settings/IntegrationsCard';
import LoadingState from '../components/LoadingState';
import { useAsync } from '../hooks/useAsync';
import { api, errorMessage } from '../services/api';
import { useAppDispatch } from '../store';
import { notify } from '../store/notificationsSlice';
import type { AppSettings, LLMTestResult, SettingsUpdate } from '../types';

const PROVIDER_HINTS: Record<string, string> = {
  anthropic: 'Claude models via the Anthropic Messages API. Requires an API key from console.anthropic.com. Example models: claude-sonnet-5-5, claude-opus-5-5, claude-haiku-5-5.',
  openai: 'OpenAI chat-completions API with JSON-schema structured output. Requires an API key.',
  mistral: 'Mistral API (OpenAI-compatible wire format, JSON mode). Requires an API key.',
};

export default function SettingsPage() {
  const dispatch = useAppDispatch();
  const settings = useAsync(() => api.settings());
  const github = useAsync(() => api.githubStatus());
  const [form, setForm] = useState<AppSettings | null>(null);
  const [apiKey, setApiKey] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [test, setTest] = useState<LLMTestResult | null>(null);
  const [testing, setTesting] = useState(false);
  const [token, setToken] = useState('');
  const [connecting, setConnecting] = useState(false);
  const [githubError, setGithubError] = useState<string | null>(null);

  useEffect(() => {
    if (settings.data) setForm(settings.data);
  }, [settings.data]);

  if (settings.loading && !form) return <LoadingState label="Loading settings…" />;
  if (!form) return <ErrorAlert error={settings.error} title="Could not load settings" onRetry={settings.reload} />;

  const update = <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => setForm({ ...form, [key]: value });

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const body: SettingsUpdate = {
        llm_provider: form.llm_provider,
        llm_model: form.llm_model,
        llm_temperature: form.llm_temperature,
        llm_base_url: form.llm_base_url ?? '',
        agent_models: form.agent_models,
        workflow_max_retries: form.workflow_max_retries,
        require_execution_approval: form.require_execution_approval,
        require_release_approval: form.require_release_approval,
        sandbox_allow_network_for_install: form.sandbox_allow_network_for_install,
        create_draft_pull_requests: form.create_draft_pull_requests,
        mcp_enabled: form.mcp_enabled,
        mcp_disabled_servers: form.mcp_disabled_servers,
      };
      if (apiKey) body.llm_api_key = apiKey;
      const saved = await api.updateSettings(body);
      settings.setData(saved);
      setApiKey('');
      dispatch(notify('Settings saved', 'success'));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const runTest = async () => {
    setTesting(true);
    setTest(null);
    try {
      setTest(await api.testLLM());
    } catch (err) {
      setTest({ ok: false, provider: form.llm_provider, model: form.llm_model, message: errorMessage(err), available_models: [] });
    } finally {
      setTesting(false);
    }
  };

  const connect = async () => {
    setConnecting(true);
    setGithubError(null);
    try {
      github.setData(await api.connectGitHub(token));
      setToken('');
      dispatch(notify('GitHub connected', 'success'));
    } catch (err) {
      setGithubError(errorMessage(err));
    } finally {
      setConnecting(false);
    }
  };

  const disconnect = async () => {
    try {
      await api.disconnectGitHub();
      await github.reload();
    } catch (err) {
      setGithubError(errorMessage(err));
    }
  };

  return (
    <Stack spacing={3} sx={{ maxWidth: 960 }}>
      <div>
        <Typography variant="h4" component="h1">
          Settings
        </Typography>
        <Typography color="text.secondary">Model providers, GitHub access and workflow policy.</Typography>
      </div>
      <ErrorAlert error={error} title="Could not save settings" />

      <Card>
        <CardHeader title="LLM provider" subheader="Provider-independent: every agent goes through the same LLM service." />
        <CardContent>
          <Stack spacing={2.5}>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
              <TextField select label="Provider" value={form.llm_provider} onChange={(e) => update('llm_provider', e.target.value as AppSettings['llm_provider'])} sx={{ minWidth: 180 }}>
                <MenuItem value="anthropic">Anthropic (Claude)</MenuItem>
                <MenuItem value="openai">OpenAI</MenuItem>
                <MenuItem value="mistral">Mistral</MenuItem>
              </TextField>
              <TextField label="Default model" value={form.llm_model} onChange={(e) => update('llm_model', e.target.value)} sx={{ flex: 1 }} helperText="e.g. claude-sonnet-5-5, gpt-4o-mini" />
              <TextField label="Base URL (optional)" value={form.llm_base_url ?? ''} onChange={(e) => update('llm_base_url', e.target.value)} sx={{ flex: 1 }} helperText="Overrides the server default" />
            </Stack>
            <Typography variant="body2" color="text.secondary">
              {PROVIDER_HINTS[form.llm_provider]}
            </Typography>
            <Box sx={{ maxWidth: 420 }}>
              <Typography variant="body2" gutterBottom id="temperature-label">
                Temperature: {form.llm_temperature.toFixed(2)}
              </Typography>
              <Slider aria-labelledby="temperature-label" min={0} max={1.5} step={0.05} value={form.llm_temperature} onChange={(_, value) => update('llm_temperature', value as number)} />
            </Box>
            {(
              <TextField
                label="API key"
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                helperText={form.llm_api_key_configured ? 'A key is stored (encrypted). Enter a new one to replace it.' : 'Stored encrypted; never shown again.'}
                autoComplete="off"
              />
            )}
            <Typography variant="subtitle2">Per-agent model overrides</Typography>
            <Box sx={{ display: 'grid', gap: 1.5, gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)', md: 'repeat(3, 1fr)' } }}>
              {form.available_agents.map((agent) => (
                <TextField
                  key={agent}
                  size="small"
                  label={agent.replace(/_/g, ' ')}
                  placeholder={form.llm_model}
                  value={form.agent_models[agent] ?? ''}
                  onChange={(e) => update('agent_models', { ...form.agent_models, [agent]: e.target.value })}
                />
              ))}
            </Box>
            <Typography variant="caption" color="text.secondary">
              Tip: pin the code reviewer to a different model than the developers for a more independent review.
            </Typography>
            <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
              <Button variant="outlined" onClick={runTest} disabled={testing}>
                {testing ? 'Testing…' : 'Test connection'}
              </Button>
              <Typography variant="caption" color="text.secondary">
                Uses saved settings.
              </Typography>
            </Stack>
            {test && (
              <Alert severity={test.ok ? 'success' : 'error'}>
                {test.provider}/{test.model}: {test.message}
                {test.available_models.length > 0 && (
                  <Stack direction="row" spacing={0.5} sx={{ mt: 1, flexWrap: 'wrap', rowGap: 0.5 }}>
                    {test.available_models.slice(0, 20).map((m) => (
                      <Chip key={m} size="small" label={m} onClick={() => update('llm_model', m)} />
                    ))}
                  </Stack>
                )}
              </Alert>
            )}
          </Stack>
        </CardContent>
      </Card>

      <Card>
        <CardHeader avatar={<GitHubIcon />} title="GitHub connection" subheader="Fine-grained personal access token with Contents and Pull requests (read & write) on selected repositories." />
        <CardContent>
          <Stack spacing={2}>
            <ErrorAlert error={githubError ?? github.error} title="GitHub" />
            {github.data?.connected ? (
              <Alert
                severity="success"
                action={
                  github.data.source === 'user' ? (
                    <Button color="inherit" size="small" onClick={disconnect}>
                      Disconnect
                    </Button>
                  ) : undefined
                }
              >
                {github.data.source === 'server'
                  ? 'Connected using the server-wide GITHUB_TOKEN.'
                  : `Connected as ${github.data.login}${github.data.scopes.length ? ` (scopes: ${github.data.scopes.join(', ')})` : ''}.`}
              </Alert>
            ) : (
              <Alert severity="warning">Not connected.</Alert>
            )}
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
              <TextField label="Personal access token" type="password" value={token} onChange={(e) => setToken(e.target.value)} sx={{ flex: 1 }} autoComplete="off" helperText="Validated with GitHub, stored encrypted, never sent to the browser or to an LLM." />
              <Button variant="contained" onClick={connect} disabled={connecting || token.length < 20} sx={{ alignSelf: { sm: 'flex-start' }, mt: { sm: 1 } }}>
                {connecting ? 'Connecting…' : github.data?.source === 'user' ? 'Replace token' : 'Connect'}
              </Button>
            </Stack>
          </Stack>
        </CardContent>
      </Card>

      <Card>
        <CardHeader title="Workflow policy" />
        <CardContent>
          <Stack spacing={2}>
            <TextField
              type="number"
              label="Maximum correction retries"
              value={form.workflow_max_retries}
              onChange={(e) => update('workflow_max_retries', Math.max(0, Math.min(10, Number(e.target.value))))}
              slotProps={{ htmlInput: { min: 0, max: 10 } }}
              sx={{ maxWidth: 260 }}
              helperText="Test/review failures routed back to developers before the workflow fails"
            />
            <FormControlLabel control={<Switch checked={form.require_execution_approval} onChange={(e) => update('require_execution_approval', e.target.checked)} />} label="Require approval before executing generated code in the sandbox" />
            <FormControlLabel control={<Switch checked={form.require_release_approval} onChange={(e) => update('require_release_approval', e.target.checked)} />} label="Require approval before pushing to GitHub and opening a pull request" />
            <FormControlLabel control={<Switch checked={form.sandbox_allow_network_for_install} onChange={(e) => update('sandbox_allow_network_for_install', e.target.checked)} />} label="Allow network access during dependency installation (tests always run offline)" />
            <FormControlLabel control={<Switch checked={form.create_draft_pull_requests} onChange={(e) => update('create_draft_pull_requests', e.target.checked)} />} label="Open pull requests as drafts" />
            {(!form.require_execution_approval || !form.require_release_approval) && (
              <Alert severity="warning">Disabling approval gates lets agents run code or push branches without a human check.</Alert>
            )}
          </Stack>
        </CardContent>
      </Card>

      <IntegrationsCard form={form} onChange={(patch) => setForm({ ...form, ...patch })} />

      <Stack direction="row" sx={{ justifyContent: 'flex-end' }}>
        <Button variant="contained" size="large" onClick={save} disabled={saving}>
          {saving ? 'Saving…' : 'Save settings'}
        </Button>
      </Stack>
    </Stack>
  );
}
