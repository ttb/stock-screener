// Pure geometry helpers for placing the RS overlay line in the price chart's
// empty space without overlapping the candles. All Y values are fractions of
// the chart pane (0 = top, 1 = bottom). The price ("right") scale is
// logarithmic; the RS scale is linear. No React or chart imports — unit-tested
// in isolation (see rsBand.test.js) and consumed by CandlestickChart.jsx.

const DEFAULTS = {
  priceBandTop: 0.05, // top margin of the price band
  priceFloor: 0.66, // bottom of the price band when RS is shown
  rsBottom: 0.78, // bottom of the RS band (above the volume band at 0.80)
  gap: 0.012, // min screen gutter between the RS line and the nearest candle
  minBand: 0.12, // thinnest RS band (the always-empty floor strip)
  maxBand: 0.38, // tallest RS band (cap, so RS never dominates the chart)
};

// Screen fraction of a price low on the logarithmic price scale.
// Precondition: priceMin > 0 and priceMax > priceMin (callers validate this;
// computeRsBand guards before calling).
export function priceLowFraction(low, priceMin, priceMax, top, floor) {
  const lnMax = Math.log(priceMax);
  return top + ((lnMax - Math.log(low)) / (lnMax - Math.log(priceMin))) * (floor - top);
}

// Screen fraction of an RS value on the linear RS scale spanning [rTop, rsBottom].
export function rsFraction(rs, rsMin, rsMax, rTop, rsBottom) {
  const a = (rsMax - rs) / (rsMax - rsMin);
  return rTop + a * (rsBottom - rTop);
}

// Compute the RS scale's top margin (rTop) so the RS line uses as much empty
// space below the candles as possible while staying at or below every candle
// low. Returns a value in [rsBottom - maxBand, rsBottom - minBand].
export function computeRsBand(input) {
  const {
    lows, highs, rsValues,
    priceBandTop, priceFloor, rsBottom, gap, minBand, maxBand,
  } = { ...DEFAULTS, ...input };

  const floorTop = rsBottom - minBand; // thinnest band (degraded / safe floor)
  const capTop = rsBottom - maxBand; // tallest band (capped)

  const n = Math.min(lows?.length || 0, highs?.length || 0, rsValues?.length || 0);
  if (n < 2) return floorTop;

  const priceMin = Math.min(...lows.slice(0, n));
  const priceMax = Math.max(...highs.slice(0, n));
  const rsMin = Math.min(...rsValues.slice(0, n));
  const rsMax = Math.max(...rsValues.slice(0, n));

  // Degenerate cases fall back to the always-empty floor strip.
  if (rsMax === rsMin) return floorTop;
  if (priceMin <= 0 || priceMax <= 0 || priceMax === priceMin) return floorTop;

  // Start at the tallest allowed band; raise rTop as bars constrain it.
  let computedRTop = capTop;
  for (let i = 0; i < n; i++) {
    const a = (rsMax - rsValues[i]) / (rsMax - rsMin); // 0 at RS max, 1 at RS min
    // RS-min bar (a === 1): division by (1 - a) is undefined, so skip it. This
    // is safe because that bar maps to rsBottom (0.78), which is always below
    // priceFloor (0.66) by far more than `gap` — so the no-overlap + gap
    // constraint holds for it by construction.
    if (a >= 1) continue;
    const plf = priceLowFraction(lows[i], priceMin, priceMax, priceBandTop, priceFloor);
    // Smallest rTop keeping rsf_i >= plf_i + gap:
    const rTopI = (plf + gap - a * rsBottom) / (1 - a);
    if (rTopI > computedRTop) computedRTop = rTopI;
  }

  // Clamp into [capTop, floorTop]. The floor strip is empty by construction, so
  // pinning to floorTop is always overlap-free even if the gap can't be met.
  return Math.min(Math.max(computedRTop, capTop), floorTop);
}

// Align RS values to candles by time, filter to the visible range, and compute
// the RS band top. `range` is lightweight-charts' getVisibleRange() result
// ({ from, to }) or null. Times are the same type as the series data
// (ISO 'YYYY-MM-DD' strings here), so direct comparison is chronological.
export function rsBandForRange(candles, rsLine, range) {
  const rsByTime = new Map((rsLine || []).map((p) => [p.time, p.value]));
  const lows = [];
  const highs = [];
  const rsValues = [];
  for (const c of candles || []) {
    if (range && (c.time < range.from || c.time > range.to)) continue;
    const v = rsByTime.get(c.time);
    if (v === undefined) continue;
    lows.push(c.low);
    highs.push(c.high);
    rsValues.push(v);
  }
  return computeRsBand({ lows, highs, rsValues });
}
