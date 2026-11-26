import { describe, expect, it } from 'vitest';
import {
  applyStepEvent,
  closeRunningSteps,
  linkifyCitations,
  parseSseFrame,
  splitSseFrames,
} from './streaming';

describe('parseSseFrame', () => {
  it('parses a step frame', () => {
    const ev = parseSseFrame(
      'event: step\r\ndata: {"node":"planner","status":"start","timestamp":"2026-11-25T11:20:00Z"}',
    );
    expect(ev).toEqual({
      type: 'step',
      data: { node: 'planner', status: 'start', timestamp: '2026-11-25T11:20:00Z' },
    });
  });

  it('ignores SSE keepalive comments cleanly', () => {
    expect(parseSseFrame(': keepalive')).toBeNull();
    const ev = parseSseFrame(
      ': keepalive\nevent: trace\ndata: {"url":"https://smith.langchain.com/r/1"}',
    );
    expect(ev).toEqual({ type: 'trace', data: { url: 'https://smith.langchain.com/r/1' } });
  });

  it('skips unknown event types and malformed JSON', () => {
    expect(parseSseFrame('event: weird\ndata: {}')).toBeNull();
    expect(parseSseFrame('event: step\ndata: {oops')).toBeNull();
    expect(parseSseFrame('data: {}')).toBeNull();
  });
});

describe('splitSseFrames', () => {
  it('keeps partial frames in the remainder and separates keepalive frames', () => {
    const [frames, rest] = splitSseFrames(
      ': keepalive\n\nevent: done\r\ndata: {}\r\n\r\nevent: step\r\ndata: {"no',
    );
    expect(frames).toHaveLength(2);
    expect(parseSseFrame(frames[0])).toBeNull();
    expect(parseSseFrame(frames[1])).toEqual({ type: 'done', data: {} });
    expect(rest).toBe('event: step\r\ndata: {"no');
  });
});

describe('applyStepEvent', () => {
  it('opens then closes a step with duration', () => {
    let steps = applyStepEvent([], {
      node: 'planner',
      status: 'start',
      timestamp: '2026-11-25T11:20:00.000Z',
    });
    expect(steps[0].status).toBe('running');
    steps = applyStepEvent(steps, {
      node: 'planner',
      status: 'end',
      timestamp: '2026-11-25T11:20:00.120Z',
    });
    expect(steps).toHaveLength(1);
    expect(steps[0].status).toBe('done');
    expect(steps[0].durationMs).toBe(120);
  });

  it('ignores unknown nodes and synthesizes a step when start was missed', () => {
    expect(applyStepEvent([], { node: 'mystery', status: 'start', timestamp: 'x' })).toEqual([]);
    const steps = applyStepEvent([], {
      node: 'worker',
      status: 'end',
      timestamp: '2026-11-25T11:20:00Z',
    });
    expect(steps[0]).toMatchObject({ node: 'worker', status: 'done' });
  });

  it('closeRunningSteps finalizes running steps', () => {
    const steps = closeRunningSteps(
      applyStepEvent([], { node: 'worker', status: 'start', timestamp: 't' }),
    );
    expect(steps[0].status).toBe('done');
  });
});

describe('linkifyCitations', () => {
  it('turns citation markers into cite links and leaves other brackets alone', () => {
    expect(linkifyCitations('Costs $5000 [Product-3]. See [docs](http://x) and [note].')).toBe(
      'Costs $5000 [Product-3](#cite-Product-3). See [docs](http://x) and [note].',
    );
  });

  it('is idempotent', () => {
    const once = linkifyCitations('a [Product-1]');
    expect(linkifyCitations(once)).toBe(once);
  });
});
