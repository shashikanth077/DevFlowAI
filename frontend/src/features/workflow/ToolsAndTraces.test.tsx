import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { api } from '../../services/api';
import { renderWithProviders } from '../../test/utils';
import type { ToolCall } from '../../types';
import { ToolCalls, TracePanel } from './ToolsAndTraces';

afterEach(() => vi.restoreAllMocks());

const call = (over: Partial<ToolCall>): ToolCall => ({
  id: 1, created_at: '', agent: 'architect', server: 'devflow-repo', tool: 'read_file',
  arguments: { path: 'app/calc.py' }, status: 'ok', result_preview: 'return a + b', duration_ms: 42, ...over,
});

describe('ToolCalls', () => {
  it('lists allowed and blocked calls with their status', () => {
    renderWithProviders(
      <ToolCalls calls={[call({}), call({ id: 2, agent: 'backend_developer', tool: 'write_thing', status: 'blocked', result_preview: 'blocked by policy' })]} />,
    );
    expect(screen.getByText('devflow-repo.read_file')).toBeInTheDocument();
    expect(screen.getByText('ok')).toBeInTheDocument();
    expect(screen.getByText('blocked')).toBeInTheDocument();
    expect(screen.getByText('backend developer')).toBeInTheDocument();
    expect(screen.getAllByText('42 ms')).toHaveLength(2);
  });

  it('explains the empty state', () => {
    renderWithProviders(<ToolCalls calls={[]} />);
    expect(screen.getByText('No MCP tool calls')).toBeInTheDocument();
  });
});

describe('TracePanel', () => {
  it('tells the operator how to enable tracing when there are no runs', () => {
    renderWithProviders(<TracePanel workflowId="wf-1" runIds={[]} />);
    expect(screen.getByText(/LANGSMITH_TRACING=true/)).toBeInTheDocument();
  });

  it('resolves LangSmith links on demand and degrades gracefully', async () => {
    const trace = vi.spyOn(api, 'workflowTrace')
      .mockResolvedValueOnce({ enabled: true, project: 'devflow-ai', run_ids: ['r1', 'r2'], urls: { r1: 'https://smith.langchain.com/o/1/r/r1', r2: null }, note: null });
    renderWithProviders(<TracePanel workflowId="wf-1" runIds={['r1', 'r2']} />);
    expect(screen.getByText('start')).toBeInTheDocument();
    expect(screen.getByText('resume 1')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Get LangSmith links' }));
    const link = await screen.findByRole('link', { name: /Open in LangSmith/ });
    expect(link).toHaveAttribute('href', 'https://smith.langchain.com/o/1/r/r1');
    expect(trace).toHaveBeenCalledWith('wf-1', true);
  });

  it('shows an error when link resolution fails', async () => {
    vi.spyOn(api, 'workflowTrace').mockRejectedValueOnce(new Error('boom'));
    renderWithProviders(<TracePanel workflowId="wf-1" runIds={['r1']} />);
    await userEvent.click(screen.getByRole('button', { name: 'Get LangSmith links' }));
    await waitFor(() => expect(screen.getByText('boom')).toBeInTheDocument());
  });
});
