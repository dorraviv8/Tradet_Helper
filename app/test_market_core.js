const assert = require("assert");
const Core = require("./market-core");

function candle(time, open, high, low, close, volume = 100) {
  return { time, open, high, low, close, volume };
}

{
  const base = Date.parse("2026-07-16T13:30:00Z");
  const merged = Core.mergeCandles([
    candle(base + 5_000, 100, 101, 99.8, 100.5, 10),
    candle(base + 45_000, 100.5, 102, 100.2, 101.8, 20),
  ]);
  assert.equal(merged.length, 1);
  assert.equal(merged[0].time, base);
  assert.equal(merged[0].open, 100);
  assert.equal(merged[0].high, 102);
  assert.equal(merged[0].low, 99.8);
  assert.equal(merged[0].close, 101.8);
  assert.equal(merged[0].volume, 20);
}

{
  const base = Date.parse("2026-07-17T21:00:00Z");
  const merged = Core.mergeCandles([
    candle(base, 100, 100.1, 92, 100.05, 0),
    candle(base + 60_000, 100, 100.1, 99.9, 100.05, 0),
  ]);
  assert.equal(merged.length, 1);
  assert.equal(merged[0].low, 99.9);
}

{
  const day1 = Date.parse("2026-07-16T13:30:00Z");
  const day2 = Date.parse("2026-07-17T13:30:00Z");
  const indicators = Core.calculateIndicators([
    candle(day1, 100, 102, 99, 101, 100),
    candle(day1 + 60_000, 101, 103, 100, 102, 100),
    candle(day2, 200, 201, 198, 199, 100),
  ]);
  const day2Typical = (201 + 198 + 199) / 3;
  assert.ok(Math.abs(indicators[2].vwap - day2Typical) < 1e-9);
}

{
  const base = Date.parse("2026-07-17T13:30:00Z");
  const resampled = Core.resample([
    candle(base, 100, 101, 99, 100.5, 1),
    candle(base + 60_000, 100.5, 102, 100, 101, 2),
    candle(base + 5 * 60_000, 101, 103, 100.8, 102, 3),
  ], 5);
  assert.equal(resampled.length, 2);
  assert.equal(resampled[0].time, base);
  assert.equal(resampled[0].open, 100);
  assert.equal(resampled[0].close, 101);
  assert.equal(resampled[0].volume, 3);
}

{
  const prior = Date.parse("2026-07-16T19:59:00Z");
  const current = Date.parse("2026-07-17T13:30:00Z");
  const close = Core.previousRegularClose([
    candle(prior, 100, 101, 99, 100.75, 100),
    candle(current, 101, 102, 100, 101.5, 100),
  ], current);
  assert.equal(close, 100.75);
}

{
  const premarket = Date.parse("2026-07-17T11:00:00Z");
  const regular = Date.parse("2026-07-17T13:30:00Z");
  const afterHours = Date.parse("2026-07-17T20:05:00Z");
  const daily = Core.resampleDaily([
    candle(premarket, 100, 101, 99, 100.5, 10),
    candle(regular, 100.5, 103, 100, 102, 20),
    candle(afterHours, 102, 104, 101.5, 103.5, 30),
  ]);
  assert.equal(daily.length, 1);
  assert.equal(daily[0].sessionDate, "2026-07-17");
  assert.equal(daily[0].open, 100);
  assert.equal(daily[0].high, 104);
  assert.equal(daily[0].low, 99);
  assert.equal(daily[0].close, 103.5);
  assert.equal(daily[0].volume, 60);
  assert.equal(daily[0].hasExtended, true);
}

{
  const saturday = Date.parse("2026-07-18T15:00:00Z");
  const session = Core.marketSession(saturday);
  assert.equal(session.phase, "closed");
  assert.equal(session.regular, false);
}

{
  const saturday = Date.parse("2026-07-18T15:00:00Z");
  const session = Core.marketSession(saturday, { continuous: true });
  assert.equal(session.phase, "continuous");
  assert.equal(session.regular, true);
  assert.equal(Core.marketParts(saturday, { continuous: true }).date, "2026-07-18");
}

{
  const viewport = Core.normalizeChartWindow(1000, undefined, undefined, { defaultCount: 120 });
  assert.deepEqual(viewport, { total: 1000, start: 880, end: 1000, count: 120, live: true });

  const zoomed = Core.zoomChartWindow(viewport, 0.5, 1, { defaultCount: 120 });
  assert.equal(zoomed.count, 60);
  assert.equal(zoomed.end, 1000);
  assert.equal(zoomed.live, true);

  const historical = Core.panChartWindow(viewport, 20, { defaultCount: 120 });
  assert.equal(historical.start, 860);
  assert.equal(historical.end, 980);
  assert.equal(historical.live, false);

  const clampedLive = Core.panChartWindow(historical, -200, { defaultCount: 120 });
  assert.equal(clampedLive.end, 1000);
  assert.equal(clampedLive.live, true);

  const futureOptions = { defaultCount: 120, maxFutureRatio: 0.5 };
  const futureSpace = Core.panChartWindow(viewport, -60, futureOptions);
  assert.deepEqual(futureSpace, {
    total: 1000,
    start: 940,
    end: 1060,
    count: 120,
    live: true,
  });
  const clampedFutureSpace = Core.panChartWindow(futureSpace, -200, futureOptions);
  assert.equal(clampedFutureSpace.end, 1060);
  assert.equal(clampedFutureSpace.start, 940);
}

console.log("market-core tests passed");
