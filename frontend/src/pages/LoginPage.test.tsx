import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { api } from '../services/api';
import { renderWithProviders } from '../test/utils';
import LoginPage from './LoginPage';

afterEach(() => vi.restoreAllMocks());

it('logs in and stores the user', async () => {
  vi.spyOn(api, 'login').mockResolvedValue({ access_token: 'jwt' });
  vi.spyOn(api, 'me').mockResolvedValue({ id: 'u1', email: 'dev@example.com', full_name: 'Dev' });
  const { store } = renderWithProviders(<LoginPage />, { route: '/login', path: '/login' });
  await userEvent.type(screen.getByLabelText(/Email/), 'dev@example.com');
  await userEvent.type(screen.getByLabelText(/Password/), 'password123');
  await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
  await waitFor(() => expect(store.getState().auth.user?.email).toBe('dev@example.com'));
  expect(api.login).toHaveBeenCalledWith({ email: 'dev@example.com', password: 'password123' });
  expect(await screen.findByTestId('navigated')).toBeInTheDocument();
});

it('shows the API error on failed login', async () => {
  vi.spyOn(api, 'login').mockRejectedValue(new Error('Incorrect email or password'));
  renderWithProviders(<LoginPage />, { route: '/login', path: '/login' });
  await userEvent.type(screen.getByLabelText(/Email/), 'dev@example.com');
  await userEvent.type(screen.getByLabelText(/Password/), 'bad');
  await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
  expect(await screen.findByText('Incorrect email or password')).toBeInTheDocument();
});
