import GppGoodIcon from '@mui/icons-material/GppGood';
import Alert from '@mui/material/Alert';
import AlertTitle from '@mui/material/AlertTitle';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import { useState } from 'react';
import { monoFont } from '../../theme';
import type { PendingApproval } from '../../types';

interface Props {
  approval: PendingApproval;
  busy: boolean;
  onDecision: (approved: boolean, comment: string) => void;
}

export default function ApprovalPanel({ approval, busy, onDecision }: Props) {
  const [comment, setComment] = useState('');
  const files = approval.changed_files ?? approval.files ?? [];
  return (
    <Alert severity="warning" icon={<GppGoodIcon />} sx={{ '& .MuiAlert-message': { width: '100%' } }} data-testid="approval-panel">
      <AlertTitle>Human approval required: {approval.title}</AlertTitle>
      <Typography variant="body2" sx={{ mb: 1.5 }}>
        {approval.description}
      </Typography>
      {approval.gate === 'execution' && (
        <Stack spacing={1} sx={{ mb: 1.5 }}>
          {(approval.commands ?? []).map((plan) => (
            <Box key={plan.component} component="pre" sx={{ m: 0, p: 1.5, bgcolor: 'background.paper', borderRadius: 1, fontFamily: monoFont, fontSize: 12, whiteSpace: 'pre-wrap' }}>
              {`# component: ${plan.component} (${plan.kind ?? 'unknown'}) image: ${plan.image ?? 'n/a'}\n`}
              {plan.setup.map((c) => `[setup] ${c}`).join('\n')}
              {plan.setup.length ? '\n' : ''}
              {[...plan.test.map((c) => `[test]  ${c}`), ...plan.lint.map((c) => `[lint]  ${c}`), ...plan.build.map((c) => `[build] ${c}`)].join('\n') || '(no test commands detected)'}
            </Box>
          ))}
          {(approval.commands ?? []).length === 0 && <Typography variant="body2">No commands detected for the changed components; QA will report tests as not run.</Typography>}
          <Typography variant="caption">
            Network during dependency install: <strong>{approval.network_for_install ? 'allowed' : 'disabled'}</strong>. Tests always run with networking disabled.
          </Typography>
        </Stack>
      )}
      {approval.gate === 'release' && (
        <Stack spacing={0.5} sx={{ mb: 1.5 }}>
          <Typography variant="body2">
            Push <strong>{approval.feature_branch}</strong> to <strong>{approval.repository}</strong> and open a pull request into{' '}
            <strong>{approval.base_branch}</strong>.
          </Typography>
          <Typography variant="body2">
            Tests: <strong>{approval.test_status}</strong> — {approval.test_summary}
          </Typography>
          <Typography variant="body2">
            Review: <strong>{approval.review_approved ? 'approved' : 'not approved'}</strong> — {approval.review_summary}
          </Typography>
          {approval.test_status !== 'passed' && (
            <Typography variant="body2" color="error">
              Warning: automated tests did not pass/run. Approve only after verifying the changes yourself.
            </Typography>
          )}
        </Stack>
      )}
      {files.length > 0 && (
        <Typography variant="body2" sx={{ mb: 1.5 }}>
          Files: {files.map((f) => <code key={f} style={{ marginRight: 8 }}>{f}</code>)}
        </Typography>
      )}
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ alignItems: { sm: 'center' } }}>
        <TextField size="small" label="Comment (optional)" value={comment} onChange={(e) => setComment(e.target.value)} sx={{ flexGrow: 1, bgcolor: 'background.paper' }} />
        <Button variant="contained" color="success" disabled={busy} onClick={() => onDecision(true, comment)}>
          Approve
        </Button>
        <Button variant="outlined" color="error" disabled={busy} onClick={() => onDecision(false, comment)}>
          Reject
        </Button>
      </Stack>
    </Alert>
  );
}
