import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { api } from '../../services/api';
import { renderWithProviders } from '../../test/utils';
import type { AppSettings, IntegrationsStatus } from '../../types';
import IntegrationsCard from './IntegrationsCard';

afterEach(() => vi.restoreAllMocks());

const form = { mcp_enabled: true, mcp_disabled_servers: [] } as unknown as AppSettings;
const status: IntegrationsStatus = {
  langsmith: { enabled: false, api_key_configured: false, project: 'devflow-ai', endpoint: 'https://api.smith.langchain.com', hide_content: false, redaction: 'credentials redacted' },
  mcp: {
    available: true, enabled_for_user: true, max_tool_calls: 6, config_errors: ['Server "bad": needs a command'],
    servers: [
      { name: 'devflow-repo', description: 'Read-only repository tools', transport: 'stdio', builtin: true, agents: ['architect', 'code_reviewer'], allow_write_tools: false, enabled_for_user: true },
      { name: 'docs', description: '', transport: 'http', builtin: false, agents: ['architect'], allow_write_tools: true, enabled_for_user: true },
    ],
  },
};

it('shows LangSmith guidance, MCP servers and config errors; toggling a server reports the new list', async () => {
  vi.spyOn(api, 'integrations').mockResolvedValue(status);
  const onChange = vi.fn();
  renderWithProviders(<IntegrationsCard form={form} onChange={onChange} />);
  expect(await screen.findByText(/Tracing is off/)).toBeInTheDocument();
  expect(screen.getByText('devflow-repo')).toBeInTheDocument();
  expect(screen.getByText('built-in')).toBeInTheDocument();
  expect(screen.getByText('write tools allowed')).toBeInTheDocument();
  expect(screen.getByText(/needs a command/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole('switch', { name: 'enable docs' }));
  expect(onChange).toHaveBeenCalledWith({ mcp_disabled_servers: ['docs'] });
  await userEvent.click(screen.getByRole('switch', { name: /Let agents call MCP tools/ }));
  expect(onChange).toHaveBeenCalledWith({ mcp_enabled: false });
});

it('lists discovered tools with their policy classification', async () => {
  vi.spyOn(api, 'integrations').mockResolvedValue(status);
  vi.spyOn(api, 'testMcp').mockResolvedValue({
    servers: [{
      name: 'devflow-repo', ok: true, error: null,
      tools: [
        { name: 'read_file', description: 'Read', read_only: true, allowed: true, reason: 'read-only', parameters: ['path'] },
        { name: 'write_thing', description: 'Write', read_only: false, allowed: false, reason: 'not marked read-only', parameters: [] },
      ],
    }, { name: 'docs', ok: false, error: 'Could not connect', tools: [] }],
  });
  renderWithProviders(<IntegrationsCard form={form} onChange={vi.fn()} />);
  await userEvent.click(await screen.findByRole('button', { name: /Test MCP servers/ }));
  expect(await screen.findByText(/2 tools/)).toBeInTheDocument();
  expect(screen.getByTitle('blocked - not marked read-only')).toBeInTheDocument();
  expect(screen.getByText(/Could not connect/)).toBeInTheDocument();
});

it('reports the LangSmith connection test result', async () => {
  vi.spyOn(api, 'integrations').mockResolvedValue(status);
  vi.spyOn(api, 'testLangSmith').mockResolvedValue({ ok: false, message: 'LANGSMITH_API_KEY is not set.' });
  renderWithProviders(<IntegrationsCard form={form} onChange={vi.fn()} />);
  await userEvent.click(await screen.findByRole('button', { name: /Test LangSmith connection/ }));
  await waitFor(() => expect(screen.getByText('LANGSMITH_API_KEY is not set.')).toBeInTheDocument());
});
