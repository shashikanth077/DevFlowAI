import HubIcon from '@mui/icons-material/Hub';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import CardHeader from '@mui/material/CardHeader';
import Chip from '@mui/material/Chip';
import FormControlLabel from '@mui/material/FormControlLabel';
import Stack from '@mui/material/Stack';
import Switch from '@mui/material/Switch';
import Typography from '@mui/material/Typography';
import { useState } from 'react';
import ErrorAlert from '../../components/ErrorAlert';
import LoadingState from '../../components/LoadingState';
import { useAsync } from '../../hooks/useAsync';
import { api, errorMessage } from '../../services/api';
import type { AppSettings, McpServerTest } from '../../types';

interface Props {
  form: AppSettings;
  onChange: (patch: Partial<Pick<AppSettings, 'mcp_enabled' | 'mcp_disabled_servers'>>) => void;
}

export default function IntegrationsCard({ form, onChange }: Props) {
  const status = useAsync(() => api.integrations());
  const [lsResult, setLsResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [lsBusy, setLsBusy] = useState(false);
  const [mcpResult, setMcpResult] = useState<McpServerTest[] | null>(null);
  const [mcpBusy, setMcpBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const testLangSmith = async () => {
    setLsBusy(true);
    setError(null);
    try {
      setLsResult(await api.testLangSmith());
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLsBusy(false);
    }
  };

  const testMcp = async () => {
    setMcpBusy(true);
    setError(null);
    try {
      setMcpResult((await api.testMcp()).servers);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setMcpBusy(false);
    }
  };

  const toggleServer = (name: string, enabled: boolean) => {
    const disabled = new Set(form.mcp_disabled_servers);
    if (enabled) disabled.delete(name);
    else disabled.add(name);
    onChange({ mcp_disabled_servers: [...disabled].sort() });
  };

  if (status.loading && !status.data) return <LoadingState label="Loading integrations…" />;
  const data = status.data;

  return (
    <Card>
      <CardHeader
        avatar={<HubIcon />}
        title="Observability & agent tools"
        subheader="LangSmith traces every run; MCP lets agents use read-only tools."
      />
      <CardContent>
        <Stack spacing={3}>
          <ErrorAlert error={status.error ?? error} title="Integrations" onRetry={status.reload} />
          {data && (
            <>
              <Box>
                <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mb: 1, flexWrap: 'wrap', rowGap: 1 }}>
                  <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                    LangSmith tracing
                  </Typography>
                  <Chip size="small" color={data.langsmith.enabled ? 'success' : 'default'} label={data.langsmith.enabled ? 'enabled' : 'disabled'} />
                  <Chip size="small" variant="outlined" label={`project: ${data.langsmith.project}`} />
                  <Chip size="small" variant="outlined" label={data.langsmith.redaction} />
                </Stack>
                {data.langsmith.enabled ? (
                  <Typography variant="body2" color="text.secondary">
                    Every workflow is traced: graph nodes, each LLM call (model, tokens, latency) and every MCP tool call. Approvals and outcomes are recorded as feedback. Credentials are redacted before leaving the server
                    {data.langsmith.hide_content ? '; prompts, code and outputs are hidden entirely.' : '.'}
                  </Typography>
                ) : (
                  <Alert severity="info" sx={{ mb: 1 }}>
                    Tracing is off. Set <code>LANGSMITH_TRACING=true</code> and <code>LANGSMITH_API_KEY</code> in the backend environment{data.langsmith.api_key_configured ? ' (a key is already configured)' : ''}, then restart. Set <code>LANGSMITH_HIDE_CONTENT=true</code> to send only metadata.
                  </Alert>
                )}
                <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mt: 1 }}>
                  <Button size="small" variant="outlined" onClick={testLangSmith} disabled={lsBusy}>
                    {lsBusy ? 'Testing…' : 'Test LangSmith connection'}
                  </Button>
                </Stack>
                {lsResult && (
                  <Alert severity={lsResult.ok ? 'success' : 'error'} sx={{ mt: 1 }}>
                    {lsResult.message}
                  </Alert>
                )}
              </Box>

              <Box>
                <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                  MCP tools for agents
                </Typography>
                {!data.mcp.available ? (
                  <Alert severity="warning" sx={{ mt: 1 }}>
                    MCP is disabled on this server (<code>MCP_ENABLED=false</code>).
                  </Alert>
                ) : (
                  <Stack spacing={1.5} sx={{ mt: 1 }}>
                    <FormControlLabel
                      control={<Switch checked={form.mcp_enabled} onChange={(e) => onChange({ mcp_enabled: e.target.checked })} />}
                      label={`Let agents call MCP tools (up to ${data.mcp.max_tool_calls} calls per agent run)`}
                    />
                    <Typography variant="caption" color="text.secondary">
                      Only tools that declare themselves read-only are callable. Each call is audited in the workflow and treated as untrusted data by the model. Servers are configured by the operator (<code>MCP_SERVERS_FILE</code>), never from the browser. Save settings to apply changes.
                    </Typography>
                    <ErrorAlert error={data.mcp.config_errors.join(' • ') || null} title="MCP configuration problems" />
                    {data.mcp.servers.map((server) => (
                      <Box key={server.name} sx={{ border: 1, borderColor: 'divider', borderRadius: 2, p: 1.5, opacity: form.mcp_enabled ? 1 : 0.6 }}>
                        <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 0.5 }}>
                          <Switch
                            size="small"
                            checked={!form.mcp_disabled_servers.includes(server.name)}
                            onChange={(e) => toggleServer(server.name, e.target.checked)}
                            slotProps={{ input: { 'aria-label': `enable ${server.name}` } }}
                          />
                          <Typography sx={{ fontWeight: 600 }}>{server.name}</Typography>
                          <Chip size="small" variant="outlined" label={server.transport} />
                          {server.builtin && <Chip size="small" color="primary" variant="outlined" label="built-in" />}
                          {server.allow_write_tools && <Chip size="small" color="warning" label="write tools allowed" />}
                        </Stack>
                        <Typography variant="body2" color="text.secondary" sx={{ ml: 6 }}>
                          {server.description || 'No description'} · agents: {server.agents.map((a) => a.replace(/_/g, ' ')).join(', ')}
                        </Typography>
                      </Box>
                    ))}
                    <Stack direction="row" spacing={1}>
                      <Button size="small" variant="outlined" onClick={testMcp} disabled={mcpBusy}>
                        {mcpBusy ? 'Connecting…' : 'Test MCP servers & list tools'}
                      </Button>
                    </Stack>
                    {mcpResult?.map((server) => (
                      <Alert key={server.name} severity={server.ok ? 'success' : 'error'} sx={{ '& .MuiAlert-message': { width: '100%' } }}>
                        <strong>{server.name}</strong>: {server.ok ? `${server.tools.length} tools` : server.error}
                        {server.ok && (
                          <Stack direction="row" spacing={0.5} sx={{ mt: 1, flexWrap: 'wrap', rowGap: 0.5 }}>
                            {server.tools.map((tool) => (
                              <Chip
                                key={tool.name}
                                size="small"
                                label={tool.name}
                                color={tool.allowed ? 'success' : 'default'}
                                variant={tool.allowed ? 'filled' : 'outlined'}
                                title={tool.allowed ? `${tool.reason}: ${tool.description}` : `blocked - ${tool.reason}`}
                              />
                            ))}
                          </Stack>
                        )}
                      </Alert>
                    ))}
                  </Stack>
                )}
              </Box>
            </>
          )}
        </Stack>
      </CardContent>
    </Card>
  );
}
