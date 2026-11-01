import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import Accordion from '@mui/material/Accordion';
import AccordionDetails from '@mui/material/AccordionDetails';
import AccordionSummary from '@mui/material/AccordionSummary';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import EmptyState from '../../components/EmptyState';
import StatusChip from '../../components/StatusChip';
import { monoFont } from '../../theme';
import type { ReviewReport, TestResult } from '../../types';

const SEVERITY_COLOR = { critical: 'error', high: 'error', medium: 'warning', low: 'info', info: 'default' } as const;

export function TestResults({ results }: { results: TestResult[] }) {
  if (!results.length) return <EmptyState title="No test runs yet" description="QA runs tests inside the Docker sandbox after you approve execution." />;
  return (
    <Stack spacing={2}>
      {results.map((run) => (
        <Accordion key={run.id} disableGutters defaultExpanded={run === results[results.length - 1]}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap', rowGap: 0.5 }}>
              <Typography sx={{ fontWeight: 600 }}>Round {run.attempt}</Typography>
              <StatusChip status={run.status} />
              <Typography variant="body2" color="text.secondary">
                {run.summary} · {(run.duration_ms / 1000).toFixed(1)}s
              </Typography>
            </Stack>
          </AccordionSummary>
          <AccordionDetails>
            <Stack spacing={1.5}>
              {run.status === 'not_run' && <Alert severity="warning">No automated tests were executed. This change is not verified by tests.</Alert>}
              {run.coverage_notes.map((note) => (
                <Alert key={note} severity="info" variant="outlined">
                  {note}
                </Alert>
              ))}
              {run.failures.map((failure, i) => (
                <Alert key={i} severity="error" variant="outlined">
                  <strong>{failure.command}</strong> — {failure.summary}
                  {failure.suggested_fix && <div>Suggested fix: {failure.suggested_fix}</div>}
                  <div>Routed to: {failure.responsible_agent} developer</div>
                </Alert>
              ))}
              {run.commands.map((command, i) => {
                const ok = command.exit_code === 0 && !command.timed_out;
                return (
                  <Box key={i} sx={{ border: 1, borderColor: 'divider', borderRadius: 2, overflow: 'hidden' }}>
                    <Stack direction="row" spacing={1} sx={{ alignItems: 'center', px: 1.5, py: 1, bgcolor: 'action.hover', flexWrap: 'wrap', rowGap: 0.5 }}>
                      <Chip size="small" label={command.phase} />
                      <Box component="code" sx={{ fontSize: 13, wordBreak: 'break-all' }}>
                        {command.command}
                      </Box>
                      <Box sx={{ flexGrow: 1 }} />
                      <Chip size="small" color={ok ? 'success' : 'error'} label={command.timed_out ? 'timed out' : `exit ${command.exit_code}`} />
                    </Stack>
                    {(command.stdout || command.stderr) && (
                      <Box component="pre" sx={{ m: 0, p: 1.5, fontFamily: monoFont, fontSize: 12, maxHeight: 280, overflow: 'auto', whiteSpace: 'pre-wrap' }}>
                        {command.stdout}
                        {command.stderr && <Box component="span" sx={{ color: 'error.main' }}>{command.stderr}</Box>}
                      </Box>
                    )}
                  </Box>
                );
              })}
            </Stack>
          </AccordionDetails>
        </Accordion>
      ))}
    </Stack>
  );
}

export function ReviewReports({ reports }: { reports: ReviewReport[] }) {
  if (!reports.length) return <EmptyState title="No reviews yet" description="The independent reviewer runs after the tests pass." />;
  return (
    <Stack spacing={2}>
      {reports.map((report) => (
        <Box key={report.id} sx={{ border: 1, borderColor: 'divider', borderRadius: 2, p: 2 }}>
          <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mb: 1, flexWrap: 'wrap', rowGap: 0.5 }}>
            <Typography sx={{ fontWeight: 600 }}>Review · round {report.attempt}</Typography>
            <StatusChip status={report.approved ? 'approved' : 'rejected'} />
            <Typography variant="caption" color="text.secondary">
              model {report.reviewer_model} · diff {report.diff_hash.slice(0, 12)}
            </Typography>
          </Stack>
          <Typography variant="body2" sx={{ mb: 1 }}>
            {report.summary}
          </Typography>
          <Stack spacing={0.75}>
            {[...report.automated_findings.map((i) => ({ ...i, source: 'automated' })), ...report.issues.map((i) => ({ ...i, source: 'reviewer' }))].map(
              (issue, index) => (
                <Stack key={index} direction="row" spacing={1} sx={{ alignItems: 'flex-start' }}>
                  <Chip size="small" label={issue.severity} color={SEVERITY_COLOR[issue.severity] ?? 'default'} />
                  <Typography variant="body2">
                    <strong>{issue.category}</strong> {issue.file && <code>{issue.file}{issue.line ? `:${issue.line}` : ''}</code>} — {issue.message}
                    {issue.suggestion && <Typography component="span" variant="body2" color="text.secondary"> ({issue.suggestion})</Typography>}
                    <Typography component="span" variant="caption" color="text.secondary"> [{issue.source}]</Typography>
                  </Typography>
                </Stack>
              ),
            )}
          </Stack>
        </Box>
      ))}
    </Stack>
  );
}
