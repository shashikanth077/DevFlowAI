import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import type { ReactNode } from 'react';

interface Props {
  label: string;
  value: number | string;
  icon: ReactNode;
  color?: string;
  hint?: string;
}

export default function StatCard({ label, value, icon, color = 'primary.main', hint }: Props) {
  return (
    <Card>
      <CardContent>
        <Stack direction="row" spacing={2} sx={{ alignItems: 'center' }}>
          <Stack
            sx={{ width: 44, height: 44, borderRadius: 2, alignItems: 'center', justifyContent: 'center', color, bgcolor: 'action.hover' }}
          >
            {icon}
          </Stack>
          <div>
            <Typography variant="h5" component="p">
              {value}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {label}
            </Typography>
            {hint && (
              <Typography variant="caption" color="text.secondary">
                {hint}
              </Typography>
            )}
          </div>
        </Stack>
      </CardContent>
    </Card>
  );
}
