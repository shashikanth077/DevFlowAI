import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Link from '@mui/material/Link';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import { useState, type FormEvent } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useAppDispatch, useAppSelector } from '../store';
import { login, register } from '../store/authSlice';

export default function LoginPage() {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const location = useLocation();
  const { token, status, error } = useAppSelector((s) => s.auth);
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');

  const target = (location.state as { from?: string } | null)?.from ?? '/';
  if (token) return <Navigate to={target} replace />;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const action = mode === 'login' ? login({ email, password }) : register({ email, password, full_name: fullName });
    const result = await dispatch(action);
    if (result.meta.requestStatus === 'fulfilled') navigate(target, { replace: true });
  };

  return (
    <Box sx={{ minHeight: '100vh', display: 'grid', placeItems: 'center', bgcolor: 'background.default', p: 2 }}>
      <Card sx={{ width: '100%', maxWidth: 420 }}>
        <CardContent sx={{ p: 4 }}>
          <Stack spacing={1} sx={{ mb: 3 }}>
            <Typography variant="h5" component="h1">
              DevFlow AI
            </Typography>
            <Typography color="text.secondary">
              {mode === 'login' ? 'Sign in to your engineering control room.' : 'Create your DevFlow AI account.'}
            </Typography>
          </Stack>
          <form onSubmit={submit} noValidate>
            <Stack spacing={2}>
              {error && status === 'error' && <Alert severity="error">{error}</Alert>}
              {mode === 'register' && (
                <TextField label="Full name" value={fullName} onChange={(e) => setFullName(e.target.value)} autoComplete="name" />
              )}
              <TextField label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
              <TextField
                label="Password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                helperText={mode === 'register' ? 'At least 8 characters' : undefined}
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              />
              <Button type="submit" variant="contained" size="large" disabled={status === 'loading' || !email || !password}>
                {status === 'loading' ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
              </Button>
              <Typography variant="body2" sx={{ textAlign: 'center' }}>
                {mode === 'login' ? 'New to DevFlow AI? ' : 'Already have an account? '}
                <Link component="button" type="button" onClick={() => setMode(mode === 'login' ? 'register' : 'login')}>
                  {mode === 'login' ? 'Create an account' : 'Sign in'}
                </Link>
              </Typography>
            </Stack>
          </form>
        </CardContent>
      </Card>
    </Box>
  );
}
