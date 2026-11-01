import type { WorkflowLog } from '../types';
import { mergeLogs } from './useWorkflowStream';

const log = (id: number): WorkflowLog => ({ id, created_at: '', level: 'info', agent: null, message: `m${id}`, data: null });

it('merges overlapping SSE and polled logs without duplicates', () => {
  const fromStream = mergeLogs([], [log(1), log(2), log(3)]);
  const merged = mergeLogs(fromStream, [log(2), log(3), log(4)]);
  expect(merged.map((l) => l.id)).toEqual([1, 2, 3, 4]);
  expect(mergeLogs(merged, [log(4)])).toBe(merged);
});
