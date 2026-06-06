import { describe, it, expect } from 'vitest';
import {
  priceLowFraction,
  rsFraction,
  computeRsBand,
  rsBandForRange,
} from './rsBand';

// Layout constants mirrored from rsBand.js defaults, for assertion math.
const TOP = 0.05;
const FLOOR = 0.66;
const RS_BOTTOM = 0.78;
const MIN_BAND = 0.12;
const MAX_BAND = 0.38;
const FLOOR_TOP = RS_BOTTOM - MIN_BAND; // 0.66 — top of the RS floor strip (numerically equals FLOOR, but a different concept)
const CAP_TOP = RS_BOTTOM - MAX_BAND; // 0.40

const GAP = 0.012; // mirrors DEFAULTS.gap in rsBand.js

// Assert the RS line never sits above any candle low (no overlap), using the
// same screen-mapping the production code uses.
function assertNoOverlap({ lows, highs, rsValues }, rTop) {
  const priceMin = Math.min(...lows);
  const priceMax = Math.max(...highs);
  const rsMin = Math.min(...rsValues);
  const rsMax = Math.max(...rsValues);
  for (let i = 0; i < lows.length; i++) {
    const plf = priceLowFraction(lows[i], priceMin, priceMax, TOP, FLOOR);
    const rsf = rsFraction(rsValues[i], rsMin, rsMax, rTop, RS_BOTTOM);
    // rsf must be at or below the candle low (larger fraction = lower on screen).
    expect(rsf).toBeGreaterThanOrEqual(plf - 1e-9);
  }
}

// In the non-degraded cases (band not pinned to the floor) the RS line keeps a
// full `gap` gutter below every candle low. Asserts that stronger property.
function assertGapMet({ lows, highs, rsValues }, rTop) {
  const priceMin = Math.min(...lows);
  const priceMax = Math.max(...highs);
  const rsMin = Math.min(...rsValues);
  const rsMax = Math.max(...rsValues);
  for (let i = 0; i < lows.length; i++) {
    const plf = priceLowFraction(lows[i], priceMin, priceMax, TOP, FLOOR);
    const rsf = rsFraction(rsValues[i], rsMin, rsMax, rTop, RS_BOTTOM);
    expect(rsf).toBeGreaterThanOrEqual(plf + GAP - 1e-9);
  }
}

describe('computeRsBand', () => {
  it('returns the floor strip for fewer than 2 bars', () => {
    expect(computeRsBand({ lows: [10], highs: [11], rsValues: [1] })).toBeCloseTo(FLOOR_TOP, 6);
    expect(computeRsBand({ lows: [], highs: [], rsValues: [] })).toBeCloseTo(FLOOR_TOP, 6);
  });

  it('returns the floor strip when RS is flat', () => {
    const data = { lows: [10, 20, 30], highs: [11, 21, 31], rsValues: [2, 2, 2] };
    expect(computeRsBand(data)).toBeCloseTo(FLOOR_TOP, 6);
  });

  it('returns the floor strip when a price is non-positive (log undefined)', () => {
    const data = { lows: [0, 20, 30], highs: [11, 21, 31], rsValues: [1, 2, 3] };
    expect(computeRsBand(data)).toBeCloseTo(FLOOR_TOP, 6);
  });

  it('expands to a taller band on a correlated uptrend, with no overlap', () => {
    const data = {
      lows: [100, 110, 120, 130, 140, 150],
      highs: [102, 112, 122, 132, 142, 153],
      rsValues: [1, 2, 3, 4, 5, 6],
    };
    const rTop = computeRsBand(data);
    expect(rTop).toBeLessThan(FLOOR_TOP); // taller than the floor strip
    expect(rTop).toBeGreaterThanOrEqual(CAP_TOP); // never past the cap
    assertNoOverlap(data, rTop);
    assertGapMet(data, rTop);
  });

  it('caps the band height at maxBand on a steep correlated uptrend', () => {
    const data = {
      lows: [10, 20, 40, 80, 160, 320],
      highs: [11, 21, 42, 84, 168, 336],
      rsValues: [1, 2, 3, 4, 5, 6],
    };
    const rTop = computeRsBand(data);
    expect(rTop).toBeCloseTo(CAP_TOP, 6); // pinned to the 38% cap
    assertNoOverlap(data, rTop);
    assertGapMet(data, rTop);
  });

  it('collapses to the floor strip on divergence (price up, RS down)', () => {
    const data = {
      lows: [100, 110, 120, 130, 140, 150],
      highs: [102, 112, 122, 132, 142, 153],
      rsValues: [6, 5, 4, 3, 2, 1],
    };
    const rTop = computeRsBand(data);
    expect(rTop).toBeCloseTo(FLOOR_TOP, 6);
    assertNoOverlap(data, rTop);
  });

  it('lands at an intermediate height on partial divergence, no overlap', () => {
    const data = {
      lows: [100, 110, 120, 130, 140, 150],
      highs: [102, 112, 122, 132, 142, 153],
      rsValues: [3, 1, 2, 4, 5, 6], // lowest-price bar has a mid RS value
    };
    const rTop = computeRsBand(data);
    expect(rTop).toBeGreaterThan(CAP_TOP);
    expect(rTop).toBeLessThan(FLOOR_TOP);
    assertNoOverlap(data, rTop);
    assertGapMet(data, rTop);
  });
});

describe('rsBandForRange', () => {
  const candles = [
    { time: '2025-01-01', high: 102, low: 100 },
    { time: '2025-01-02', high: 112, low: 110 },
    { time: '2025-01-03', high: 122, low: 120 },
    { time: '2025-01-04', high: 132, low: 130 },
  ];
  const rsLine = [
    { time: '2025-01-01', value: 1 },
    { time: '2025-01-02', value: 2 },
    { time: '2025-01-03', value: 3 },
    { time: '2025-01-04', value: 4 },
  ];

  it('returns the floor strip when fewer than 2 bars are in range', () => {
    const r = rsBandForRange(candles, rsLine, { from: '2025-01-01', to: '2025-01-01' });
    expect(r).toBeCloseTo(FLOOR_TOP, 6); // rsBottom - minBand
  });

  it('uses all bars when range is null', () => {
    const full = rsBandForRange(candles, rsLine, null);
    expect(full).toBeLessThanOrEqual(FLOOR_TOP);
  });

  it('only includes bars present in BOTH candles and rs line, within range', () => {
    const partialRs = rsLine.slice(0, 2); // only first two have RS values
    const r = rsBandForRange(candles, partialRs, null);
    // 2 aligned bars -> still computes (>= cap, <= floor)
    expect(r).toBeGreaterThanOrEqual(CAP_TOP);
    expect(r).toBeLessThanOrEqual(FLOOR_TOP);
  });

  it('returns the floor strip when the range excludes all bars', () => {
    // Range is entirely after the data, so every candle is filtered out.
    const r = rsBandForRange(candles, rsLine, { from: '2025-02-01', to: '2025-02-28' });
    expect(r).toBeCloseTo(FLOOR_TOP, 6);
  });
});
