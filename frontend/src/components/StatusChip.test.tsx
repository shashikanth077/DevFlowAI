import { render, screen } from '@testing-library/react';
import StatusChip, { statusLabel } from './StatusChip';

it('formats status labels', () => {
  expect(statusLabel('awaiting_approval')).toBe('Awaiting approval');
  render(<StatusChip status="failed" />);
  expect(screen.getByTestId('status-failed')).toHaveTextContent('Failed');
});
