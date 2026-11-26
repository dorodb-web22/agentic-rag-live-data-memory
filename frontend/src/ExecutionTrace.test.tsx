// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import ExecutionTrace from './ExecutionTrace';
import type { TraceStep } from './streaming';

afterEach(cleanup);

const done: TraceStep = { id: '1', node: 'planner', status: 'done', startedAt: 't', durationMs: 120 };
const running: TraceStep = { id: '2', node: 'worker', status: 'running', startedAt: 't' };

describe('ExecutionTrace', () => {
  it('shows an empty state with no steps', () => {
    render(<ExecutionTrace steps={[]} />);
    expect(screen.queryAllByTestId('trace-step')).toHaveLength(0);
    expect(screen.getByText(/will appear here/i)).toBeTruthy();
  });
  it('renders label and duration for finished steps', () => {
    render(<ExecutionTrace steps={[done]} />);
    expect(screen.getByText('Planning')).toBeTruthy();
    expect(screen.getByText('120 ms')).toBeTruthy();
  });
  it('marks running steps with a spinner', () => {
    const { container } = render(<ExecutionTrace steps={[done, running]} />);
    expect(container.querySelector('.trace-step.running .trace-spinner')).not.toBeNull();
    expect(screen.getByText('running…')).toBeTruthy();
  });
  it('shows the LangSmith link only when traceUrl is set', () => {
    const { rerender } = render(<ExecutionTrace steps={[done]} />);
    expect(screen.queryByText(/View in LangSmith/)).toBeNull();
    rerender(<ExecutionTrace steps={[done]} traceUrl="https://smith.langchain.com/x" />);
    expect(screen.getByText(/View in LangSmith/).getAttribute('href')).toBe('https://smith.langchain.com/x');
  });
});
