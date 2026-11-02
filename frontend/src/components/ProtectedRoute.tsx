import { Navigate, Outlet } from 'react-router-dom';
import { useAppSelector } from '../store';

export default function ProtectedRoute() {
  const token = useAppSelector((s) => s.auth.token);
  // No return-to state: remembering the current page here made sign-in return to it after a sign-out.
  if (!token) return <Navigate to="/login" replace />;
  return <Outlet />;
}
