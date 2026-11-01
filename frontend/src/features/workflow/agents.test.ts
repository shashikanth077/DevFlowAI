import { workflowFixture } from '../../test/fixtures';
import { agentProgress, overallProgress, stageLabel } from './agents';

describe('agentProgress', () => {
  it('derives status and retry counts from executions', () => {
    const agents = agentProgress(workflowFixture());
    const byKey = Object.fromEntries(agents.map((a) => [a.key, a]));
    expect(byKey.requirement_analyst.status).toBe('completed');
    expect(byKey.backend_developer.retries).toBe(1);
    expect(byKey.qa_engineer.status).toBe('running');
    expect(byKey.release_engineer.status).toBe('pending');
    expect(byKey.frontend_developer.relevant).toBe(false); // only backend tasks planned
  });

  it('marks unstarted agents as skipped when the workflow failed', () => {
    const agents = agentProgress(workflowFixture({ status: 'failed' }));
    expect(agents.find((a) => a.key === 'release_engineer')!.status).toBe('cancelled');
  });

  it('computes progress over relevant agents', () => {
    expect(overallProgress(workflowFixture())).toBe(25); // 2 of 8 relevant agents completed
    expect(overallProgress(workflowFixture({ status: 'completed' }))).toBe(100);
    expect(stageLabel('execution_approval')).toBe('Awaiting execution approval');
  });
});
