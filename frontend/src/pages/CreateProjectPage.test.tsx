import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { api } from '../services/api';
import { renderWithProviders } from '../test/utils';
import type { Project, Repository, WorkflowDetail } from '../types';
import CreateProjectPage from './CreateProjectPage';

afterEach(() => vi.restoreAllMocks());

const repo: Repository = { id: 'r1', owner: 'acme', name: 'calc', full_name: 'acme/calc', default_branch: 'main', private: false, html_url: '', created_at: '' };

it('warns when GitHub is not connected', async () => {
  vi.spyOn(api, 'githubStatus').mockResolvedValue({ connected: false, login: null, scopes: [], connected_at: null, source: null });
  renderWithProviders(<CreateProjectPage />);
  expect(await screen.findByText(/Connect GitHub first/)).toBeInTheDocument();
});

it('connects the repository, creates the project and starts the workflow', async () => {
  vi.spyOn(api, 'githubStatus').mockResolvedValue({ connected: true, login: 'octo', scopes: [], connected_at: null, source: 'user' });
  vi.spyOn(api, 'githubRepos').mockResolvedValue([
    { full_name: 'acme/calc', owner: 'acme', name: 'calc', private: false, default_branch: 'main', html_url: '', description: 'Calculator', updated_at: null },
  ]);
  vi.spyOn(api, 'githubBranches').mockResolvedValue([{ name: 'main', protected: true, sha: 'abc' }]);
  const connect = vi.spyOn(api, 'connectRepository').mockResolvedValue(repo);
  vi.spyOn(api, 'projects').mockResolvedValue([]);
  const create = vi.spyOn(api, 'createProject').mockResolvedValue({ id: 'p1', repository: repo } as Project);
  const start = vi.spyOn(api, 'startWorkflow').mockResolvedValue({ id: 'wf-9' } as WorkflowDetail);

  renderWithProviders(<CreateProjectPage />, { route: '/projects/new', path: '/projects/new' });
  const repoInput = await screen.findByLabelText('GitHub repository');
  await userEvent.click(repoInput);
  await userEvent.click(await screen.findByText('acme/calc'));
  await waitFor(() => expect(screen.getByText(/Protected branch/)).toBeInTheDocument());
  await userEvent.click(screen.getByText('Health endpoint'));
  await userEvent.click(screen.getByRole('button', { name: 'Start workflow' }));

  await waitFor(() => expect(start).toHaveBeenCalled());
  expect(connect).toHaveBeenCalledWith('acme/calc');
  expect(create).toHaveBeenCalledWith({ name: 'calc', repository_id: 'r1', base_branch: 'main' });
  expect(start.mock.calls[0][0]).toMatchObject({ project_id: 'p1', base_branch: 'main' });
  expect(await screen.findByTestId('navigated')).toBeInTheDocument();
});
