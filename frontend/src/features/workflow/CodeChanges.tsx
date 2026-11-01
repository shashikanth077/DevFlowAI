import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import Accordion from '@mui/material/Accordion';
import AccordionDetails from '@mui/material/AccordionDetails';
import AccordionSummary from '@mui/material/AccordionSummary';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import DiffViewer from '../../components/DiffViewer';
import EmptyState from '../../components/EmptyState';
import type { FileChange } from '../../types';

export default function CodeChanges({ changes }: { changes: FileChange[] }) {
  if (!changes.length) {
    return <EmptyState title="No code changes yet" description="Created and modified files appear here once the development agents finish." />;
  }
  const created = changes.filter((c) => c.change_type === 'created');
  const modified = changes.filter((c) => c.change_type === 'modified');
  const additions = changes.reduce((sum, c) => sum + c.additions, 0);
  const deletions = changes.reduce((sum, c) => sum + c.deletions, 0);
  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1 }}>
        <Chip label={`${created.length} created`} color="success" variant="outlined" />
        <Chip label={`${modified.length} modified`} color="info" variant="outlined" />
        <Chip label={`+${additions} / −${deletions}`} variant="outlined" />
      </Stack>
      {changes.map((change) => (
        <Accordion key={change.id} disableGutters defaultExpanded={changes.length <= 3}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Stack direction="row" spacing={1} sx={{ alignItems: 'center', width: '100%', flexWrap: 'wrap', rowGap: 0.5 }}>
              <Box component="code" sx={{ fontWeight: 600, wordBreak: 'break-all' }}>
                {change.path}
              </Box>
              <Chip size="small" label={change.change_type} color={change.change_type === 'created' ? 'success' : 'info'} />
              <Chip size="small" label={change.agent} variant="outlined" />
              {change.approved && <Chip size="small" label="committed" color="secondary" variant="outlined" />}
              <Typography variant="caption" sx={{ ml: 'auto' }}>
                <Box component="span" sx={{ color: 'success.main' }}>+{change.additions}</Box>{' '}
                <Box component="span" sx={{ color: 'error.main' }}>−{change.deletions}</Box>
              </Typography>
            </Stack>
          </AccordionSummary>
          <AccordionDetails sx={{ p: 0, overflowX: 'auto' }}>
            <DiffViewer diff={change.diff} />
          </AccordionDetails>
        </Accordion>
      ))}
    </Stack>
  );
}
