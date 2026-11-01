import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import type { ReactNode } from 'react';
import StatusChip from '../../components/StatusChip';
import type { WorkflowResults } from '../../types';

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={{ xs: 0.25, sm: 2 }} sx={{ py: 1, borderBottom: 1, borderColor: 'divider' }}>
      <Typography variant="body2" color="text.secondary" sx={{ minWidth: 160 }}>
        {label}
      </Typography>
      <Box sx={{ wordBreak: 'break-all' }}>{children}</Box>
    </Stack>
  );
}

export default function GitHubResults({ results }: { results: WorkflowResults }) {
  const pr = results.pull_request;
  if (!pr) {
    return (
      <Alert severity="info">
        {results.status === 'completed'
          ? 'The workflow completed without a pull request.'
          : 'The GitHub Release Agent runs after the code review is approved and you approve the release. Branch, commit and pull request details will appear here.'}
        {results.feature_branch && (
          <div>
            Planned feature branch: <code>{results.feature_branch}</code>
          </div>
        )}
      </Alert>
    );
  }
  return (
    <Stack spacing={2}>
      <Box>
        <Row label="Pull request">
          <Typography variant="body2">
            #{pr.number} {pr.title}
          </Typography>
        </Row>
        <Row label="Status">
          <Stack direction="row" spacing={1}>
            <StatusChip status={pr.merged ? 'merged' : pr.state} />
            {pr.draft && <StatusChip status="draft" />}
          </Stack>
        </Row>
        <Row label="Feature branch">
          <code>{pr.head_branch}</code>
        </Row>
        <Row label="Base branch">
          <code>{pr.base_branch}</code>
        </Row>
        <Row label="Commit">
          <code>{pr.commit_sha}</code>
        </Row>
        <Row label="Repository">{pr.repository_full_name}</Row>
      </Box>
      <Stack direction="row">
        <Button variant="contained" href={pr.url} target="_blank" rel="noopener noreferrer" endIcon={<OpenInNewIcon />}>
          Open pull request
        </Button>
      </Stack>
      <Typography variant="caption" color="text.secondary">
        DevFlow AI never merges pull requests. Review and merge on GitHub.
      </Typography>
    </Stack>
  );
}
