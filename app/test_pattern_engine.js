const assert = require("assert");
const Engine = require("./pattern-engine");

function candle(index, open, high, low, close, volume = 1000) {
  return { time: index * 60_000, open, high, low, close, volume };
}

function boundedSeries(length, highAt, lowAt, closeAt = null, start = 0) {
  return Array.from({ length }, (_, offset) => {
    const index = start + offset;
    const high = highAt(offset);
    const low = lowAt(offset);
    const close = closeAt ? closeAt(offset, high, low) : (high + low) / 2;
    return candle(index, close, high, low, close);
  });
}

function names(patterns) {
  return patterns.map((pattern) => pattern.name);
}

function assertPattern(pattern, expectedName) {
  assert.ok(pattern, `${expectedName} was not detected`);
  assert.equal(pattern.name, expectedName);
  assert.ok(Number.isFinite(pattern.projection.target));
  assert.ok(pattern.lines.length > 0);
}

{
  const required = [
    "Ascending Triangle", "Descending Triangle", "Symmetrical Triangle",
    "Rising Wedge", "Falling Wedge", "Bull Pennant", "Bear Pennant",
    "Cup & Handle", "Inverse Cup & Handle", "Rounded Bottom", "Rounded Top",
    "Bullish Rectangle", "Bearish Rectangle", "Rising Channel", "Falling Channel",
    "Triple Top", "Triple Bottom", "Bullish Engulfing", "Bearish Engulfing",
    "Hammer", "Shooting Star", "Bullish Doji", "Bearish Doji", "Morning Star", "Evening Star",
  ];
  assert.deepEqual(Engine.SUPPORTED_PATTERNS, required);
}

{
  const point = (index, price) => ({ index, price });
  const pattern = {
    name: "Mapped pattern",
    label: point(1, 101),
    points: [point(0, 100), point(2, 102)],
    lines: [{ from: point(0, 100), to: point(2, 102) }],
    projection: { breakout: point(2, 102), target: 105 },
  };
  const mapped = Engine.remapPatternIndices(pattern, [3, 7, 11]);
  assert.equal(mapped.label.index, 7);
  assert.deepEqual(mapped.points.map((item) => item.index), [3, 11]);
  assert.equal(mapped.lines[0].from.index, 3);
  assert.equal(mapped.lines[0].to.index, 11);
  assert.equal(mapped.projection.breakout.index, 11);
}

{
  const ascending = boundedSeries(24, () => 110, (i) => 100 + i * 0.3);
  const descending = boundedSeries(24, (i) => 110 - i * 0.3, () => 100);
  const symmetrical = boundedSeries(24, (i) => 110 - i * 0.2, (i) => 100 + i * 0.2);
  const risingWedge = boundedSeries(18, (i) => 110 + i * 0.2, (i) => 100 + i * 0.6);
  const fallingWedge = boundedSeries(18, (i) => 110 - i * 0.6, (i) => 100 - i * 0.2);
  assert.ok(names(Engine.convergenceCandidates(ascending, 1)).includes("Ascending Triangle"));
  assert.ok(names(Engine.convergenceCandidates(descending, 1)).includes("Descending Triangle"));
  assert.ok(names(Engine.convergenceCandidates(symmetrical, 1)).includes("Symmetrical Triangle"));
  assert.ok(names(Engine.convergenceCandidates(risingWedge, 1)).includes("Rising Wedge"));
  assert.ok(names(Engine.convergenceCandidates(fallingWedge, 1)).includes("Falling Wedge"));
}

function pennantSeries(bullish) {
  const impulse = Array.from({ length: 18 }, (_, index) => {
    const open = bullish ? 100 + index * 0.3 : 110 - index * 0.3;
    const close = open + (bullish ? 0.25 : -0.25);
    return candle(index, open, Math.max(open, close) + 0.12, Math.min(open, close) - 0.12, close);
  });
  const center = impulse.at(-1).close;
  const pennant = boundedSeries(
    12,
    (i) => center + 1.6 - i * 0.12,
    (i) => center - 1.6 + i * 0.12,
    null,
    18,
  );
  return [...impulse, ...pennant];
}

assertPattern(Engine.detectPennant(pennantSeries(true), 1), "Bull Pennant");
assertPattern(Engine.detectPennant(pennantSeries(false), 1), "Bear Pennant");

function cupSeries(inverted) {
  const cupLength = 52;
  const cup = Array.from({ length: cupLength }, (_, index) => {
    const x = -1 + 2 * index / (cupLength - 1);
    const close = inverted ? 100 + 10 * (1 - x * x) : 110 - 10 * (1 - x * x);
    return candle(index, close, close + 0.3, close - 0.3, close);
  });
  const handleValues = inverted
    ? [102, 102.5, 103, 102.2, 101.7, 101.3, 101.1, 100.8]
    : [108, 107.5, 107, 107.8, 108.3, 108.7, 108.9, 109.2];
  const handle = handleValues.map((close, offset) => candle(cupLength + offset, close, close + 0.25, close - 0.25, close));
  return [...cup, ...handle];
}

assertPattern(Engine.detectCupAndHandle(cupSeries(false), 1, false), "Cup & Handle");
assertPattern(Engine.detectCupAndHandle(cupSeries(true), 1, true), "Inverse Cup & Handle");

function roundedSeries(top) {
  return Array.from({ length: 56 }, (_, index) => {
    const x = -1 + 2 * index / 55;
    const close = top ? 100 - 8 * x * x : 100 + 8 * x * x;
    return candle(index, close, close + 0.2, close - 0.2, close);
  });
}

assertPattern(Engine.detectRounded(roundedSeries(false), 1, false), "Rounded Bottom");
assertPattern(Engine.detectRounded(roundedSeries(true), 1, true), "Rounded Top");

function rectangleSeries(bullish) {
  const prior = Array.from({ length: 8 }, (_, index) => {
    const close = bullish ? 98 + index * 0.8 : 112 - index * 0.8;
    return candle(index, close, close + 0.4, close - 0.4, close);
  });
  const range = Array.from({ length: 28 }, (_, offset) => {
    const close = 105 + Math.sin(offset * Math.PI / 2) * 4;
    return candle(8 + offset, close, close + 0.7, close - 0.7, close);
  });
  return [...prior, ...range];
}

assertPattern(Engine.detectRectangle(rectangleSeries(true), 1), "Bullish Rectangle");
assertPattern(Engine.detectRectangle(rectangleSeries(false), 1), "Bearish Rectangle");

function channelSeries(rising) {
  return Array.from({ length: 36 }, (_, index) => {
    const center = 100 + (rising ? 1 : -1) * index * 0.2;
    const wave = Math.sin(index * Math.PI / 4) * 1.4;
    const close = center + wave;
    return candle(index, close, close + 0.7, close - 0.7, close);
  });
}

assertPattern(Engine.detectChannel(channelSeries(true), 1), "Rising Channel");
assertPattern(Engine.detectChannel(channelSeries(false), 1), "Falling Channel");

function tripleSeries(bottom) {
  const anchors = bottom
    ? [[0, 105], [8, 100], [14, 110], [20, 100], [26, 110], [32, 100], [41, 111]]
    : [[0, 105], [8, 110], [14, 100], [20, 110], [26, 100], [32, 110], [41, 99]];
  const values = [];
  for (let segment = 0; segment < anchors.length - 1; segment += 1) {
    const [startIndex, startPrice] = anchors[segment];
    const [endIndex, endPrice] = anchors[segment + 1];
    for (let index = startIndex; index < endIndex; index += 1) {
      const ratio = (index - startIndex) / (endIndex - startIndex);
      values[index] = startPrice + (endPrice - startPrice) * ratio;
    }
  }
  values[41] = anchors.at(-1)[1];
  return values.map((close, index) => candle(index, close, close + 0.2, close - 0.2, close));
}

assertPattern(Engine.detectTriple(tripleSeries(false), 1, false), "Triple Top");
assertPattern(Engine.detectTriple(tripleSeries(true), 1, true), "Triple Bottom");

function baseTrend(up) {
  return Array.from({ length: 9 }, (_, index) => {
    const close = 100 + (up ? 1 : -1) * index * 0.5;
    return candle(index, close, close + 0.3, close - 0.3, close);
  });
}

function candlestickNames(series) {
  return names(Engine.detectCandlestickPatterns(series));
}

{
  const bullish = [...baseTrend(false), candle(9, 96, 96.2, 94.8, 95), candle(10, 94.8, 96.5, 94.6, 96.3), candle(11, 96.3, 96.5, 96, 96.4)];
  const bearish = [...baseTrend(true), candle(9, 104, 105.2, 103.8, 105), candle(10, 105.2, 105.4, 103.5, 103.7), candle(11, 103.7, 104, 103.5, 103.6)];
  assert.ok(candlestickNames(bullish.slice(0, 11)).includes("Bullish Engulfing"));
  assert.ok(candlestickNames(bearish.slice(0, 11)).includes("Bearish Engulfing"));
}

{
  const hammer = [...baseTrend(false), candle(9, 95.2, 95.4, 94.8, 95), candle(10, 94.9, 95.2, 91.8, 95.1), candle(11, 95.1, 95.3, 94.9, 95.2)];
  const star = [...baseTrend(true), candle(9, 104.8, 105.2, 104.6, 105), candle(10, 105.1, 108.2, 104.8, 104.9), candle(11, 104.9, 105.1, 104.7, 104.8)];
  assert.ok(candlestickNames(hammer.slice(0, 11)).includes("Hammer"));
  assert.ok(candlestickNames(star.slice(0, 11)).includes("Shooting Star"));
}

{
  const bullishDoji = [...baseTrend(false), candle(9, 95.5, 95.8, 95.2, 95.4), candle(10, 95, 97, 93, 95.05), candle(11, 95.1, 95.3, 94.9, 95.1)];
  const bearishDoji = [...baseTrend(true), candle(9, 104.5, 104.8, 104.2, 104.6), candle(10, 105, 107, 103, 105.05), candle(11, 105, 105.2, 104.8, 105)];
  assert.ok(candlestickNames(bullishDoji.slice(0, 11)).includes("Bullish Doji"));
  assert.ok(candlestickNames(bearishDoji.slice(0, 11)).includes("Bearish Doji"));
}

{
  const down = baseTrend(false);
  const morning = [...down, candle(9, 96, 96.2, 92.8, 93), candle(10, 92.9, 93.3, 92.6, 93.1), candle(11, 93.2, 95.5, 93, 95.3)];
  const up = baseTrend(true);
  const evening = [...up, candle(9, 104, 107.2, 103.8, 107), candle(10, 106.9, 107.3, 106.7, 106.8), candle(11, 106.7, 106.9, 104.4, 104.6)];
  assert.ok(candlestickNames(morning).includes("Morning Star"));
  assert.ok(candlestickNames(evening).includes("Evening Star"));
}

console.log("pattern-engine tests passed");
