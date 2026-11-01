import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ApprovalPanel from './ApprovalPanel';

describe('ApprovalPanel', () => {
  it('shows sandbox commands and reports the decision with a comment', async () => {
    const onDecision = vi.fn();
    render(
      <ApprovalPanel
        busy={false}
        onDecision={onDecision}
        approval={{
          gate: 'execution',
          title: 'Approve execution of generated code in the sandbox',
          description: 'QA will run commands',
          commands: [{ component: '.', kind: 'backend', image: 'python:3.11-slim', setup: ['pip install -r requirements.txt'], test: ['python -m pytest -q'], lint: [], build: [] }],
          changed_files: ['app/calc.py'],
          network_for_install: false,
        }}
      />,
    );
    expect(screen.getByText(/python -m pytest -q/)).toBeInTheDocument();
    expect(screen.getByText('disabled')).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('Comment (optional)'), 'looks safe');
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }));
    expect(onDecision).toHaveBeenCalledWith(true, 'looks safe');
  });

  it('warns when releasing without passing tests', async () => {
    const onDecision = vi.fn();
    render(
      <ApprovalPanel
        busy={false}
        onDecision={onDecision}
        approval={{ gate: 'release', title: 'Approve push', description: '', test_status: 'not_run', test_summary: 'No tests', review_approved: true, review_summary: 'ok', feature_branch: 'devflow/x', repository: 'acme/calc', base_branch: 'main', files: [] }}
      />,
    );
    expect(screen.getByText(/automated tests did not pass\/run/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Reject' }));
    expect(onDecision).toHaveBeenCalledWith(false, '');
  });
});
