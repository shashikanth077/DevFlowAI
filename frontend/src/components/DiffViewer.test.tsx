import { render, screen } from '@testing-library/react';
import DiffViewer, { parseDiff } from './DiffViewer';

const DIFF = `diff --git a/app/calc.py b/app/calc.py
index 1..2 100644
--- a/app/calc.py
+++ b/app/calc.py
@@ -3,2 +3,4 @@ def add(a, b):
 def add(a, b):
-    return a+b
+    return a + b
+
+def sub(a, b): return a - b`;

describe('parseDiff', () => {
  it('assigns old/new line numbers per hunk', () => {
    const lines = parseDiff(DIFF);
    const context = lines.find((l) => l.kind === 'context')!;
    expect(context).toMatchObject({ oldNo: 3, newNo: 3 });
    const removed = lines.find((l) => l.kind === 'del')!;
    expect(removed).toMatchObject({ oldNo: 4, newNo: null, text: '    return a+b' });
    const added = lines.filter((l) => l.kind === 'add');
    expect(added.map((l) => l.newNo)).toEqual([4, 5, 6]);
    expect(lines.filter((l) => l.kind === 'meta')).toHaveLength(4);
  });
});

describe('DiffViewer', () => {
  it('renders added and removed lines and hides meta lines by default', () => {
    const { container } = render(<DiffViewer diff={DIFF} />);
    expect(screen.getByText('def sub(a, b): return a - b')).toBeInTheDocument();
    expect(container.querySelectorAll('[data-kind="add"]')).toHaveLength(3);
    expect(container.querySelectorAll('[data-kind="del"]')).toHaveLength(1);
    expect(screen.queryByText(/^index /)).not.toBeInTheDocument();
  });

  it('shows an empty message when there is nothing to show', () => {
    render(<DiffViewer diff="" />);
    expect(screen.getByText('No textual changes.')).toBeInTheDocument();
  });
});
