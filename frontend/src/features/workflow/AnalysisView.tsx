import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import EmptyState from '../../components/EmptyState';
import type { WorkflowDetail } from '../../types';

function Section({ title, items }: { title: string; items?: string[] }) {
  if (!items?.length) return null;
  return (
    <Box>
      <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
        {title}
      </Typography>
      <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
        {items.map((item, i) => (
          <li key={i}>
            <Typography variant="body2">{item}</Typography>
          </li>
        ))}
      </Box>
    </Box>
  );
}

export default function AnalysisView({ workflow }: { workflow: WorkflowDetail }) {
  const req = workflow.requirement_analysis;
  const repo = workflow.repository_analysis;
  const plan = workflow.architecture_plan;
  if (!req && !repo && !plan) return <EmptyState title="Analysis in progress" description="Requirement, repository and architecture analysis appear here." />;
  return (
    <Box sx={{ display: 'grid', gap: 3, gridTemplateColumns: { xs: '1fr', lg: 'repeat(3, 1fr)' }, alignItems: 'start' }}>
      {req && (
        <Stack spacing={1.5}>
          <Typography variant="h6">Requirement analysis</Typography>
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
            {req.title}
          </Typography>
          <Typography variant="body2">{req.summary}</Typography>
          <Section title="Business objectives" items={req.business_objectives} />
          <Section title="Functional requirements" items={req.functional_requirements?.map((f) => `${f.id} (${f.priority}): ${f.description}`)} />
          <Section title="Non-functional requirements" items={req.non_functional_requirements} />
          <Section title="Acceptance criteria" items={req.acceptance_criteria} />
          <Section title="Open questions / ambiguities" items={req.ambiguities} />
          <Section title="Assumptions" items={req.assumptions} />
        </Stack>
      )}
      {repo && (
        <Stack spacing={1.5}>
          <Typography variant="h6">Repository analysis</Typography>
          <Typography variant="body2">{repo.architecture_summary}</Typography>
          <Stack direction="row" spacing={0.5} sx={{ flexWrap: 'wrap', rowGap: 0.5 }}>
            {Object.entries((repo.languages ?? {}) as Record<string, number>).map(([lang, count]) => (
              <Chip key={lang} size="small" label={`${lang} · ${count}`} />
            ))}
            {(repo.frameworks as string[] | undefined)?.map((f) => <Chip key={f} size="small" variant="outlined" label={f} />)}
          </Stack>
          <Section
            title="Components"
            items={(repo.components as { path: string; kind: string; language: string; test_commands: string[] }[] | undefined)?.map(
              (c) => `${c.path} — ${c.kind} (${c.language}); tests: ${c.test_commands.join(', ') || 'none detected'}`,
            )}
          />
          <Section title="Conventions" items={repo.conventions as string[]} />
          <Section title="Relevant files" items={(repo.relevant_files as { path: string; action: string; reason: string }[] | undefined)?.map((f) => `${f.action}: ${f.path}${f.reason ? ` — ${f.reason}` : ''}`)} />
          <Typography variant="caption" color="text.secondary">
            {repo.total_files} files scanned · {(repo.test_files as string[] | undefined)?.length ?? 0} test files
          </Typography>
        </Stack>
      )}
      {plan && (
        <Stack spacing={1.5}>
          <Typography variant="h6">Architecture plan</Typography>
          <Typography variant="body2">{plan.approach}</Typography>
          <Section title="Backend changes" items={plan.backend_changes} />
          <Section title="Frontend changes" items={plan.frontend_changes} />
          <Section title="API endpoints" items={(plan.api_endpoints as { method: string; path: string; description: string }[] | undefined)?.map((e) => `${e.method} ${e.path} — ${e.description}`)} />
          <Section title="Data models" items={(plan.data_models as { name: string; fields: string[] }[] | undefined)?.map((m) => `${m.name}: ${m.fields.join(', ')}`)} />
          <Section title="File plan" items={(plan.file_plan as { action: string; path: string; area: string }[] | undefined)?.map((f) => `${f.action} ${f.path} [${f.area}]`)} />
          <Section title="Testing strategy" items={plan.testing_strategy} />
          <Section title="Risks" items={plan.risks} />
        </Stack>
      )}
    </Box>
  );
}
