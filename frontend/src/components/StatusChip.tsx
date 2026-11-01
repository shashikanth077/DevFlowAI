import Chip, { type ChipProps } from '@mui/material/Chip';

const COLORS: Record<string, ChipProps['color']> = {
  queued: 'default',
  pending: 'default',
  running: 'info',
  in_progress: 'info',
  waiting: 'warning',
  awaiting_approval: 'warning',
  needs_fix: 'warning',
  not_run: 'warning',
  completed: 'success',
  passed: 'success',
  approved: 'success',
  open: 'success',
  failed: 'error',
  error: 'error',
  rejected: 'error',
  cancelled: 'default',
  closed: 'default',
  merged: 'secondary',
  blocked: 'default',
};

export function statusLabel(status: string): string {
  const text = status.replace(/_/g, ' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export default function StatusChip({ status, size = 'small' }: { status: string; size?: ChipProps['size'] }) {
  return (
    <Chip
      label={statusLabel(status)}
      color={COLORS[status] ?? 'default'}
      size={size}
      variant={status === 'running' || status === 'in_progress' ? 'filled' : 'outlined'}
      data-testid={`status-${status}`}
    />
  );
}
