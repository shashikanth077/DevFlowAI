import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import Typography from '@mui/material/Typography';
import EmptyState from '../../components/EmptyState';
import StatusChip from '../../components/StatusChip';
import type { Task } from '../../types';

export default function TaskBoard({ tasks }: { tasks: Task[] }) {
  if (!tasks.length) {
    return <EmptyState title="No tasks yet" description="The Task Orchestrator creates development tasks after the architecture design." />;
  }
  return (
    <TableContainer>
      <Table aria-label="development tasks">
        <TableHead>
          <TableRow>
            <TableCell>Task</TableCell>
            <TableCell>Agent</TableCell>
            <TableCell>Depends on</TableCell>
            <TableCell>Files</TableCell>
            <TableCell>Status</TableCell>
            <TableCell>Attempts</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {tasks.map((task) => (
            <TableRow key={task.id}>
              <TableCell sx={{ minWidth: 240 }}>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  {task.task_key}: {task.title}
                </Typography>
                {task.description && (
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', whiteSpace: 'pre-wrap' }}>
                    {task.description}
                  </Typography>
                )}
                {task.notes && (
                  <Typography variant="caption" sx={{ display: 'block', mt: 0.5 }}>
                    Note: {task.notes}
                  </Typography>
                )}
              </TableCell>
              <TableCell>
                <Chip size="small" label={task.assigned_agent} color={task.assigned_agent === 'frontend' ? 'secondary' : 'primary'} variant="outlined" />
              </TableCell>
              <TableCell>{task.dependencies.length ? task.dependencies.join(', ') : '—'}</TableCell>
              <TableCell>
                <Stack spacing={0.25}>
                  {task.target_files.map((f) => (
                    <Box component="code" key={f} sx={{ fontSize: 12 }}>
                      {f}
                    </Box>
                  ))}
                </Stack>
              </TableCell>
              <TableCell>
                <StatusChip status={task.status} />
              </TableCell>
              <TableCell>{task.attempts}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
