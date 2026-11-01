import Alert from '@mui/material/Alert';
import Snackbar from '@mui/material/Snackbar';
import { useAppDispatch, useAppSelector } from '../store';
import { dismiss } from '../store/notificationsSlice';

export default function Notifier() {
  const notifications = useAppSelector((s) => s.notifications);
  const dispatch = useAppDispatch();
  const current = notifications[0];
  if (!current) return null;
  return (
    <Snackbar open autoHideDuration={5000} onClose={() => dispatch(dismiss(current.id))} anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}>
      <Alert severity={current.severity} onClose={() => dispatch(dismiss(current.id))} variant="filled" sx={{ width: '100%' }}>
        {current.message}
      </Alert>
    </Snackbar>
  );
}
