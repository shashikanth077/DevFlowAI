import { screen, within } from '@testing-library/react';
import { renderWithProviders } from '../../test/utils';
import { workflowFixture } from '../../test/fixtures';
import AgentMonitor from './AgentMonitor';

it('renders every agent with its status and retries', () => {
  renderWithProviders(<AgentMonitor workflow={workflowFixture()} logs={[]} />);
  expect(screen.getAllByTestId(/^agent-/)).toHaveLength(9);
  const backend = screen.getByTestId('agent-backend_developer');
  expect(within(backend).getByText('1 retry')).toBeInTheDocument();
  expect(within(screen.getByTestId('agent-qa_engineer')).getAllByText('Running').length).toBeGreaterThan(0);
  expect(within(screen.getByTestId('agent-release_engineer')).getByText('Pending')).toBeInTheDocument();
  expect(screen.getByText(/Retry 1 of 3/)).toBeInTheDocument();
});
