/**
 * OscilloscopeBuffer.ts — Ring buffer for oscilloscope data using Float64Array.
 *
 * Zero-copy: fillWindow returns subarray views into a pre-allocated display buffer.
 * Thread-safe for single producer/consumer (no SharedArrayBuffer).
 */

export class OscilloscopeBuffer {
  private xs: Float64Array;
  private ys: Float64Array[];
  private writeIdx = 0;
  private filled = 0;
  private displayXs: Float64Array;
  private displayYs: Float64Array[];

  constructor(public readonly capacity: number, channels: number) {
    this.xs = new Float64Array(capacity);
    this.ys = Array.from({ length: channels }, () => new Float64Array(capacity));
    this.displayXs = new Float64Array(capacity);
    this.displayYs = Array.from({ length: channels }, () => new Float64Array(capacity));
  }

  push(t: number, values: number[]): void {
    this.xs[this.writeIdx] = t;
    for (let c = 0; c < this.ys.length; c++) {
      this.ys[c][this.writeIdx] = values[c] ?? 0;
    }
    this.writeIdx = (this.writeIdx + 1) % this.capacity;
    if (this.filled < this.capacity) this.filled++;
  }

  fillWindow(now: number, span: number): readonly Float64Array[] {
    const cutoff = now - span;
    let outIdx = 0;
    const start = this.filled < this.capacity ? 0 : this.writeIdx;

    for (let i = 0; i < this.filled; i++) {
      const idx = (start + i) % this.capacity;
      if (this.xs[idx] > cutoff) {
        this.displayXs[outIdx] = this.xs[idx];
        for (let c = 0; c < this.ys.length; c++) {
          this.displayYs[c][outIdx] = this.ys[c][idx];
        }
        outIdx++;
      }
    }

    return [
      this.displayXs.subarray(0, outIdx),
      ...this.displayYs.map((y) => y.subarray(0, outIdx)),
    ];
  }

  clear(): void {
    this.writeIdx = 0;
    this.filled = 0;
  }

  get length(): number {
    return this.filled;
  }
}
