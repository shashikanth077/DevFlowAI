import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import { monoFont } from '../theme';

export interface DiffLine {
  kind: 'add' | 'del' | 'hunk' | 'meta' | 'context';
  text: string;
  oldNo: number | null;
  newNo: number | null;
}

/** Parse a unified git diff into displayable lines with old/new line numbers. */
export function parseDiff(diff: string): DiffLine[] {
  const lines: DiffLine[] = [];
  let oldNo = 0;
  let newNo = 0;
  for (const raw of diff.split('\n')) {
    if (raw.startsWith('@@')) {
      const match = /@@ -(\d+)(?:,\d+)? \+(\d+)/.exec(raw);
      oldNo = match ? Number(match[1]) : 0;
      newNo = match ? Number(match[2]) : 0;
      lines.push({ kind: 'hunk', text: raw, oldNo: null, newNo: null });
    } else if (raw.startsWith('diff --git') || raw.startsWith('index ') || raw.startsWith('+++') || raw.startsWith('---') || raw.startsWith('new file') || raw.startsWith('\\')) {
      lines.push({ kind: 'meta', text: raw, oldNo: null, newNo: null });
    } else if (raw.startsWith('+')) {
      lines.push({ kind: 'add', text: raw.slice(1), oldNo: null, newNo: newNo++ });
    } else if (raw.startsWith('-')) {
      lines.push({ kind: 'del', text: raw.slice(1), oldNo: oldNo++, newNo: null });
    } else if (raw.length || lines.length) {
      lines.push({ kind: 'context', text: raw.slice(1), oldNo: oldNo++, newNo: newNo++ });
    }
  }
  while (lines.length && lines[lines.length - 1].kind === 'context' && lines[lines.length - 1].text === '') lines.pop();
  return lines;
}

const BG: Record<DiffLine['kind'], string> = {
  add: 'rgba(34,197,94,0.14)',
  del: 'rgba(239,68,68,0.14)',
  hunk: 'rgba(79,70,229,0.10)',
  meta: 'transparent',
  context: 'transparent',
};

export default function DiffViewer({ diff, showMeta = false }: { diff: string; showMeta?: boolean }) {
  const lines = parseDiff(diff).filter((l) => showMeta || l.kind !== 'meta');
  if (!lines.length) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ p: 2 }}>
        No textual changes.
      </Typography>
    );
  }
  return (
    <Box sx={{ overflowX: 'auto', width: '100%' }}>
    <Box
      component="table"
      aria-label="code diff"
      sx={{ width: '100%', minWidth: 'max-content', borderCollapse: 'collapse', fontFamily: monoFont, fontSize: 12.5, lineHeight: 1.55 }}
    >
      <tbody>
        {lines.map((line, index) => (
          <Box component="tr" key={index} sx={{ bgcolor: BG[line.kind] }} data-kind={line.kind}>
            <Box component="td" sx={{ px: 1, color: 'text.disabled', textAlign: 'right', userSelect: 'none', minWidth: 40 }}>
              {line.oldNo ?? ''}
            </Box>
            <Box component="td" sx={{ px: 1, color: 'text.disabled', textAlign: 'right', userSelect: 'none', minWidth: 40 }}>
              {line.newNo ?? ''}
            </Box>
            <Box component="td" sx={{ px: 1, userSelect: 'none', color: line.kind === 'add' ? 'success.main' : line.kind === 'del' ? 'error.main' : 'text.disabled' }}>
              {line.kind === 'add' ? '+' : line.kind === 'del' ? '−' : ' '}
            </Box>
            <Box component="td" sx={{ pr: 2, width: '100%', whiteSpace: 'pre', color: line.kind === 'hunk' ? 'primary.main' : 'text.primary' }}>
              {line.text}
            </Box>
          </Box>
        ))}
      </tbody>
    </Box>
    </Box>
  );
}
