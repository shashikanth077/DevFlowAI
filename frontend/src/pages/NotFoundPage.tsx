import Button from '@mui/material/Button';
import { Link as RouterLink } from 'react-router-dom';
import EmptyState from '../components/EmptyState';

export default function NotFoundPage() {
  return <EmptyState title="Page not found" action={<Button component={RouterLink} to="/">Back to dashboard</Button>} />;
}
