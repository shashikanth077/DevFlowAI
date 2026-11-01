import { lazy, Suspense, useEffect } from 'react';
import { Route, Routes, useNavigate } from 'react-router-dom';
import Layout from './components/Layout';
import Notifier from './components/Notifier';
import ProtectedRoute from './components/ProtectedRoute';
import LoadingState from './components/LoadingState';
import LoginPage from './pages/LoginPage';
import { setUnauthorizedHandler } from './services/api';
import { useAppDispatch, useAppSelector } from './store';
import { loadUser, logout } from './store/authSlice';

const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const CreateProjectPage = lazy(() => import('./pages/CreateProjectPage'));
const WorkflowsPage = lazy(() => import('./pages/WorkflowsPage'));
const WorkflowDetailPage = lazy(() => import('./pages/WorkflowDetailPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));
const NotFoundPage = lazy(() => import('./pages/NotFoundPage'));

export default function App() {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const { token, user } = useAppSelector((s) => s.auth);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      dispatch(logout());
      navigate('/login');
    });
  }, [dispatch, navigate]);

  useEffect(() => {
    if (token && !user) void dispatch(loadUser());
  }, [token, user, dispatch]);

  return (
    <>
      <Suspense fallback={<LoadingState />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ProtectedRoute />}>
          <Route element={<Layout />}>
            <Route index element={<DashboardPage />} />
            <Route path="projects/new" element={<CreateProjectPage />} />
            <Route path="workflows" element={<WorkflowsPage />} />
            <Route path="workflows/:workflowId" element={<WorkflowDetailPage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Route>
      </Routes>
      </Suspense>
      <Notifier />
    </>
  );
}
