import CircularProgress from '@mui/material/CircularProgress';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';

export default function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <Stack spacing={2} sx={{ alignItems: 'center', py: 6 }} role="status">
      <CircularProgress size={32} />
      <Typography color="text.secondary">{label}</Typography>
    </Stack>
  );
}
