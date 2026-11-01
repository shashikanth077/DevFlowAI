import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Button from '@mui/material/Button';

interface Props {
  error: string | null | undefined;
  title?: string;
  onRetry?: () => void;
}

export default function ErrorAlert({ error, title = 'Something went wrong', onRetry }: Props) {
  if (!error) return null;
  return (
    <Alert
      severity="error"
      sx={{ mb: 2 }}
      action={
        onRetry ? (
          <Button color="inherit" size="small" onClick={onRetry}>
            Retry
          </Button>
        ) : undefined
      }
    >
      <AlertTitle>{title}</AlertTitle>
      {error}
    </Alert>
  );
}
