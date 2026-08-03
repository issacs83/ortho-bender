import { describe, it, expect } from 'vitest';
import { OscilloscopeBuffer } from '../OscilloscopeBuffer';

describe('OscilloscopeBuffer', () => {
  it('starts empty', () => {
    const buf = new OscilloscopeBuffer(100, 2);
    const [xs, y0, y1] = buf.fillWindow(10, 10);
    expect(xs.length).toBe(0);
    expect(y0.length).toBe(0);
    expect(y1.length).toBe(0);
  });

  it('stores pushed data', () => {
    const buf = new OscilloscopeBuffer(100, 2);
    buf.push(1.0, [100, 200]);
    buf.push(2.0, [150, 250]);
    const [xs, y0, y1] = buf.fillWindow(3, 5);
    expect(xs.length).toBe(2);
    expect(xs[0]).toBe(1.0);
    expect(xs[1]).toBe(2.0);
    expect(y0[0]).toBe(100);
    expect(y1[1]).toBe(250);
  });

  it('wraps around at capacity', () => {
    const buf = new OscilloscopeBuffer(5, 1);
    for (let i = 0; i < 8; i++) buf.push(i, [i * 10]);
    // Should contain timestamps 3,4,5,6,7 (last 5)
    const [xs, y0] = buf.fillWindow(10, 20);
    expect(xs.length).toBe(5);
    expect(xs[0]).toBe(3);
    expect(xs[4]).toBe(7);
    expect(y0[0]).toBe(30);
    expect(y0[4]).toBe(70);
  });

  it('windows correctly', () => {
    const buf = new OscilloscopeBuffer(100, 1);
    for (let i = 0; i < 50; i++) buf.push(i, [i]);
    // Window: now=49, span=10 → timestamps 39..49
    const [xs] = buf.fillWindow(49, 10);
    expect(xs.length).toBe(10);
    expect(xs[0]).toBe(40);
    expect(xs[9]).toBe(49);
  });

  it('returns subarray views (zero copy)', () => {
    const buf = new OscilloscopeBuffer(100, 1);
    buf.push(1, [10]);
    buf.push(2, [20]);
    const result1 = buf.fillWindow(3, 5);
    const result2 = buf.fillWindow(3, 5);
    // Should reuse same underlying buffer
    expect(result1[0].buffer).toBe(result2[0].buffer);
  });
});
