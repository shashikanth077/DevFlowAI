import Link from '@mui/material/Link';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import Typography from '@mui/material/Typography';
import { Link as RouterLink } from 'react-router-dom';
import StatusChip from '../../components/StatusChip';
import type { WorkflowSummary } from '../../types';
import { stageLabel } from './agents';

export function formatDate(value: string | null): string {
  if (!value) return '—';
  return new Date(value).toLocaleString();
}

export default function WorkflowTable({ workflows, dense = false }: { workflows: WorkflowSummary[]; dense?: boolean }) {
  return (
    <TableContainer>
      <Table size={dense ? 'small' : 'medium'} aria-label="workflows">
        <TableHead>
          <TableRow>
            <TableCell>Requirement</TableCell>
            <TableCell>Repository</TableCell>
            <TableCell>Status</TableCell>
            {!dense && <TableCell>Stage</TableCell>}
            {!dense && <TableCell>Retries</TableCell>}
            <TableCell>Started</TableCell>
            <TableCell>PR</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {workflows.map((w) => (
            <TableRow key={w.id} hover>
              <TableCell sx={{ maxWidth: 360 }}>
                <Link component={RouterLink} to={`/workflows/${w.id}`} underline="hover">
                  <Typography variant="body2" noWrap title={w.requirement}>
                    {w.requirement}
                  </Typography>
                </Link>
              </TableCell>
              <TableCell>
                <Typography variant="body2" noWrap>
                  {w.repository_full_name}
                  <Typography component="span" variant="caption" color="text.secondary">
                    {' '}
                    ({w.base_branch})
                  </Typography>
                </Typography>
              </TableCell>
              <TableCell>
                <StatusChip status={w.status} />
              </TableCell>
              {!dense && <TableCell>{w.current_stage ? stageLabel(w.current_stage) : '—'}</TableCell>}
              {!dense && <TableCell>{w.retry_count}</TableCell>}
              <TableCell>
                <Typography variant="body2" noWrap>
                  {formatDate(w.created_at)}
                </Typography>
              </TableCell>
              <TableCell>
                {w.pull_request_url ? (
                  <Link href={w.pull_request_url} target="_blank" rel="noopener noreferrer">
                    Open
                  </Link>
                ) : (
                  '—'
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
