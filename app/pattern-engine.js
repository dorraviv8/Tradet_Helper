(function attachPatternEngine(root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.PatternEngine = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function buildPatternEngine() {
  const BULLISH = "#2fd17c";
  const BEARISH = "#ff5c66";
  const NEUTRAL = "#f4c95d";

  const SUPPORTED_PATTERNS = [
    "Ascending Triangle",
    "Descending Triangle",
    "Symmetrical Triangle",
    "Rising Wedge",
    "Falling Wedge",
    "Bull Pennant",
    "Bear Pennant",
    "Cup & Handle",
    "Inverse Cup & Handle",
    "Rounded Bottom",
    "Rounded Top",
    "Bullish Rectangle",
    "Bearish Rectangle",
    "Rising Channel",
    "Falling Channel",
    "Triple Top",
    "Triple Bottom",
    "Bullish Engulfing",
    "Bearish Engulfing",
    "Hammer",
    "Shooting Star",
    "Bullish Doji",
    "Bearish Doji",
    "Morning Star",
    "Evening Star",
  ];

  function finite(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function cleanCandles(candles) {
    return (candles || []).map((candle) => ({
      time: finite(candle.time),
      open: finite(candle.open),
      high: finite(candle.high),
      low: finite(candle.low),
      close: finite(candle.close),
      volume: Math.max(0, finite(candle.volume) || 0),
    })).filter((candle) => (
      [candle.time, candle.open, candle.high, candle.low, candle.close].every((value) => value !== null)
      && candle.low > 0
      && candle.high >= Math.max(candle.open, candle.close)
      && candle.low <= Math.min(candle.open, candle.close)
    ));
  }

  function averageRange(candles) {
    if (!candles.length) return 0;
    return candles.reduce((sum, candle) => sum + candle.high - candle.low, 0) / candles.length;
  }

  function average(values) {
    return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
  }

  function quantile(values, ratio) {
    if (!values.length) return 0;
    const sorted = [...values].sort((a, b) => a - b);
    const position = (sorted.length - 1) * ratio;
    const lower = Math.floor(position);
    const upper = Math.ceil(position);
    if (lower === upper) return sorted[lower];
    return sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower);
  }

  function fitLine(candles, key) {
    const n = candles.length;
    if (n < 2) return { slope: 0, intercept: finite(candles[0]?.[key]) || 0, r2: 0, at: () => 0 };
    const meanX = (n - 1) / 2;
    const meanY = average(candles.map((candle) => candle[key]));
    let numerator = 0;
    let denominator = 0;
    let total = 0;
    candles.forEach((candle, index) => {
      const dx = index - meanX;
      numerator += dx * (candle[key] - meanY);
      denominator += dx * dx;
      total += (candle[key] - meanY) ** 2;
    });
    const slope = denominator ? numerator / denominator : 0;
    const intercept = meanY - slope * meanX;
    let residual = 0;
    candles.forEach((candle, index) => {
      residual += (candle[key] - (intercept + slope * index)) ** 2;
    });
    const r2 = total > 0 ? Math.max(0, 1 - residual / total) : 0;
    return { slope, intercept, r2, at: (index) => intercept + slope * index };
  }

  function movementThreshold(price, timeframe) {
    if (timeframe >= 1440) return price * 0.025;
    if (timeframe >= 15) return price * 0.006;
    if (timeframe >= 5) return price * 0.0045;
    return price * 0.0025;
  }

  function point(index, price) {
    return { index, price };
  }

  function line(from, to, color = NEUTRAL, dash = []) {
    return { from, to, color, dash };
  }

  function projection(name, breakout, target) {
    const move = target - breakout.price;
    return {
      name,
      direction: move >= 0 ? "up" : "down",
      breakout,
      target,
      measuredMove: Math.abs(move),
      move,
      pct: breakout.price ? move / breakout.price * 100 : 0,
    };
  }

  function makePattern({ name, direction, score, breakout, target, basis, label, points, lines }) {
    if (!Number.isFinite(target) || target <= 0 || !Number.isFinite(breakout?.price)) return null;
    const color = direction === "bullish" ? BULLISH : direction === "bearish" ? BEARISH : NEUTRAL;
    return {
      name,
      direction,
      score,
      color,
      projection: projection(basis, breakout, target),
      label,
      points,
      lines,
    };
  }

  function pivotPoints(candles, span) {
    const pivots = [];
    for (let index = span; index < candles.length - span; index += 1) {
      const window = candles.slice(index - span, index + span + 1);
      if (candles[index].high === Math.max(...window.map((item) => item.high))) {
        pivots.push({ index, type: "H", price: candles[index].high });
      }
      if (candles[index].low === Math.min(...window.map((item) => item.low))) {
        pivots.push({ index, type: "L", price: candles[index].low });
      }
    }
    return pivots.sort((a, b) => a.index - b.index).reduce((output, pivot) => {
      const prior = output.at(-1);
      if (!prior || prior.type !== pivot.type) {
        output.push(pivot);
      } else if ((pivot.type === "H" && pivot.price > prior.price) || (pivot.type === "L" && pivot.price < prior.price)) {
        output[output.length - 1] = pivot;
      }
      return output;
    }, []);
  }

  function convergenceCandidates(candles, timeframe) {
    const candidates = [];
    const lengths = timeframe >= 1440 ? [30, 24, 18] : [30, 24, 18, 14];
    for (const length of lengths) {
      if (candles.length < length) continue;
      const start = candles.length - length;
      const sample = candles.slice(start);
      const highFit = fitLine(sample, "high");
      const lowFit = fitLine(sample, "low");
      const avgRange = averageRange(sample);
      const startWidth = highFit.at(0) - lowFit.at(0);
      const endWidth = highFit.at(length - 1) - lowFit.at(length - 1);
      if (startWidth <= avgRange * 1.5 || endWidth <= 0 || endWidth > startWidth * 0.82) continue;
      const minimumSlope = avgRange * 0.018;
      const flatSlope = avgRange * 0.025;
      const topStart = point(start, highFit.at(0));
      const topEnd = point(candles.length - 1, highFit.at(length - 1));
      const bottomStart = point(start, lowFit.at(0));
      const bottomEnd = point(candles.length - 1, lowFit.at(length - 1));
      const middleIndex = start + Math.floor(length / 2);
      const commonLines = [line(topStart, topEnd), line(bottomStart, bottomEnd)];
      let pattern = null;

      if (Math.abs(highFit.slope) <= flatSlope && lowFit.slope > minimumSlope && lowFit.r2 >= 0.16) {
        pattern = makePattern({
          name: "Ascending Triangle", direction: "bullish", score: 70,
          breakout: topEnd, target: topEnd.price + startWidth,
          basis: "Triangle height above resistance",
          label: point(middleIndex, highFit.at(Math.floor(length / 2))),
          points: [topStart, bottomStart, topEnd, bottomEnd], lines: commonLines,
        });
      } else if (Math.abs(lowFit.slope) <= flatSlope && highFit.slope < -minimumSlope && highFit.r2 >= 0.16) {
        pattern = makePattern({
          name: "Descending Triangle", direction: "bearish", score: 70,
          breakout: bottomEnd, target: bottomEnd.price - startWidth,
          basis: "Triangle height below support",
          label: point(middleIndex, lowFit.at(Math.floor(length / 2))),
          points: [topStart, bottomStart, topEnd, bottomEnd], lines: commonLines,
        });
      } else if (highFit.slope < -minimumSlope && lowFit.slope > minimumSlope && highFit.r2 >= 0.12 && lowFit.r2 >= 0.12) {
        const recentSlope = fitLine(sample.slice(-6), "close").slope;
        const bullish = recentSlope >= 0;
        const breakout = bullish ? topEnd : bottomEnd;
        pattern = makePattern({
          name: "Symmetrical Triangle", direction: bullish ? "bullish" : "bearish", score: 68,
          breakout, target: breakout.price + (bullish ? startWidth : -startWidth),
          basis: bullish ? "Triangle height above resistance" : "Triangle height below support",
          label: point(middleIndex, (highFit.at(Math.floor(length / 2)) + lowFit.at(Math.floor(length / 2))) / 2),
          points: [topStart, bottomStart, topEnd, bottomEnd], lines: commonLines,
        });
      } else if (highFit.slope > minimumSlope && lowFit.slope > highFit.slope * 1.1 && highFit.r2 >= 0.12 && lowFit.r2 >= 0.12) {
        pattern = makePattern({
          name: "Rising Wedge", direction: "bearish", score: 69,
          breakout: bottomEnd, target: bottomEnd.price - startWidth,
          basis: "Wedge opening below rising support",
          label: point(middleIndex, highFit.at(Math.floor(length / 2))),
          points: [topStart, bottomStart, topEnd, bottomEnd], lines: commonLines,
        });
      } else if (lowFit.slope < -minimumSlope && Math.abs(highFit.slope) > Math.abs(lowFit.slope) * 1.1 && highFit.r2 >= 0.12 && lowFit.r2 >= 0.12) {
        pattern = makePattern({
          name: "Falling Wedge", direction: "bullish", score: 69,
          breakout: topEnd, target: topEnd.price + startWidth,
          basis: "Wedge opening above falling resistance",
          label: point(middleIndex, lowFit.at(Math.floor(length / 2))),
          points: [topStart, bottomStart, topEnd, bottomEnd], lines: commonLines,
        });
      }
      if (pattern) {
        candidates.push(pattern);
        break;
      }
    }
    return candidates;
  }

  function detectPennant(candles, timeframe) {
    const pennantLength = timeframe >= 1440 ? 10 : 12;
    const impulseLength = timeframe >= 1440 ? 16 : 18;
    if (candles.length < pennantLength + impulseLength) return null;
    const start = candles.length - pennantLength;
    const impulse = candles.slice(start - impulseLength, start);
    const pennant = candles.slice(start);
    const poleMove = impulse.at(-1).close - impulse[0].open;
    const minimumMove = movementThreshold(candles.at(-1).close, timeframe) * (timeframe >= 1440 ? 1.2 : 1.6);
    if (Math.abs(poleMove) < minimumMove) return null;
    const highFit = fitLine(pennant, "high");
    const lowFit = fitLine(pennant, "low");
    const startWidth = highFit.at(0) - lowFit.at(0);
    const endWidth = highFit.at(pennantLength - 1) - lowFit.at(pennantLength - 1);
    if (highFit.slope >= 0 || lowFit.slope <= 0 || endWidth <= 0 || endWidth > startWidth * 0.72) return null;
    if (startWidth > Math.abs(poleMove) * 0.62) return null;
    const bullish = poleMove > 0;
    const poleStart = point(start - impulseLength, impulse[0].open);
    const poleEnd = point(start - 1, impulse.at(-1).close);
    const topStart = point(start, highFit.at(0));
    const topEnd = point(candles.length - 1, highFit.at(pennantLength - 1));
    const bottomStart = point(start, lowFit.at(0));
    const bottomEnd = point(candles.length - 1, lowFit.at(pennantLength - 1));
    const breakout = bullish ? topEnd : bottomEnd;
    return makePattern({
      name: bullish ? "Bull Pennant" : "Bear Pennant",
      direction: bullish ? "bullish" : "bearish", score: 74,
      breakout, target: breakout.price + poleMove,
      basis: bullish ? "Pennant pole measured move up" : "Pennant pole measured move down",
      label: point(start + Math.floor(pennantLength / 2), bullish ? highFit.at(pennantLength / 2) : lowFit.at(pennantLength / 2)),
      points: [poleStart, poleEnd, topEnd, bottomEnd],
      lines: [line(poleStart, poleEnd), line(topStart, topEnd, NEUTRAL, [6, 4]), line(bottomStart, bottomEnd, NEUTRAL, [6, 4])],
    });
  }

  function detectCupAndHandle(candles, timeframe, inverted = false) {
    const handleLength = timeframe >= 1440 ? 10 : 8;
    const lengths = timeframe >= 1440 ? [90, 75, 60] : [72, 60, 48];
    for (const length of lengths) {
      if (candles.length < length) continue;
      const start = candles.length - length;
      const sample = candles.slice(start);
      const cup = sample.slice(0, -handleLength);
      const handle = sample.slice(-handleLength);
      const edgeSize = Math.max(5, Math.floor(cup.length * 0.22));
      const left = cup.slice(0, edgeSize);
      const right = cup.slice(-edgeSize);
      const middleStart = edgeSize;
      const middleEnd = cup.length - edgeSize;
      const middle = cup.slice(middleStart, middleEnd);
      if (!middle.length) continue;

      const leftIndex = inverted
        ? left.findIndex((item) => item.low === Math.min(...left.map((candle) => candle.low)))
        : left.findIndex((item) => item.high === Math.max(...left.map((candle) => candle.high)));
      const rightLocal = inverted
        ? right.findIndex((item) => item.low === Math.min(...right.map((candle) => candle.low)))
        : right.findIndex((item) => item.high === Math.max(...right.map((candle) => candle.high)));
      const leftPrice = inverted ? left[leftIndex].low : left[leftIndex].high;
      const rightPrice = inverted ? right[rightLocal].low : right[rightLocal].high;
      const extremePrice = inverted
        ? Math.max(...middle.map((candle) => candle.high))
        : Math.min(...middle.map((candle) => candle.low));
      const extremeLocal = middle.findIndex((item) => (inverted ? item.high : item.low) === extremePrice);
      const rim = (leftPrice + rightPrice) / 2;
      const depth = inverted ? extremePrice - rim : rim - extremePrice;
      const tolerance = Math.max(averageRange(sample) * 1.8, Math.abs(rim) * (timeframe >= 1440 ? 0.025 : 0.005));
      if (depth < movementThreshold(sample.at(-1).close, timeframe) * 1.35) continue;
      if (Math.abs(leftPrice - rightPrice) > Math.max(tolerance, depth * 0.38)) continue;
      const extremeRatio = (middleStart + extremeLocal) / cup.length;
      if (extremeRatio < 0.25 || extremeRatio > 0.75) continue;

      const handleExtreme = inverted
        ? Math.max(...handle.map((candle) => candle.high))
        : Math.min(...handle.map((candle) => candle.low));
      const handleRetrace = inverted ? handleExtreme - rim : rim - handleExtreme;
      if (handleRetrace < -tolerance || handleRetrace > depth * 0.58) continue;
      const current = handle.at(-1).close;
      if ((!inverted && current < rim - depth * 0.42) || (inverted && current > rim + depth * 0.42)) continue;

      const leftPoint = point(start + leftIndex, leftPrice);
      const bottomPoint = point(start + middleStart + extremeLocal, extremePrice);
      const rightPoint = point(start + cup.length - edgeSize + rightLocal, rightPrice);
      const handlePoint = point(candles.length - 1, handleExtreme);
      const breakout = point(candles.length - 1, rim);
      return makePattern({
        name: inverted ? "Inverse Cup & Handle" : "Cup & Handle",
        direction: inverted ? "bearish" : "bullish", score: 78,
        breakout, target: rim + (inverted ? -depth : depth),
        basis: inverted ? "Cup depth below rim support" : "Cup depth above rim resistance",
        label: bottomPoint,
        points: [leftPoint, bottomPoint, rightPoint, handlePoint],
        lines: [line(leftPoint, bottomPoint), line(bottomPoint, rightPoint), line(rightPoint, handlePoint), line(leftPoint, point(candles.length - 1, rim), NEUTRAL, [5, 5])],
      });
    }
    return null;
  }

  function solveThree(matrix, vector) {
    const rows = matrix.map((row, index) => [...row, vector[index]]);
    for (let column = 0; column < 3; column += 1) {
      let pivot = column;
      for (let row = column + 1; row < 3; row += 1) {
        if (Math.abs(rows[row][column]) > Math.abs(rows[pivot][column])) pivot = row;
      }
      if (Math.abs(rows[pivot][column]) < 1e-12) return null;
      [rows[column], rows[pivot]] = [rows[pivot], rows[column]];
      const divisor = rows[column][column];
      for (let index = column; index < 4; index += 1) rows[column][index] /= divisor;
      for (let row = 0; row < 3; row += 1) {
        if (row === column) continue;
        const factor = rows[row][column];
        for (let index = column; index < 4; index += 1) rows[row][index] -= factor * rows[column][index];
      }
    }
    return rows.map((row) => row[3]);
  }

  function quadraticFit(values) {
    const n = values.length;
    if (n < 5) return null;
    const xs = values.map((_, index) => -1 + 2 * index / (n - 1));
    const sums = (power) => xs.reduce((sum, x) => sum + x ** power, 0);
    const matrix = [
      [sums(4), sums(3), sums(2)],
      [sums(3), sums(2), sums(1)],
      [sums(2), sums(1), n],
    ];
    const vector = [
      values.reduce((sum, value, index) => sum + value * xs[index] ** 2, 0),
      values.reduce((sum, value, index) => sum + value * xs[index], 0),
      values.reduce((sum, value) => sum + value, 0),
    ];
    const coefficients = solveThree(matrix, vector);
    if (!coefficients) return null;
    const [a, b, c] = coefficients;
    const predicted = xs.map((x) => a * x * x + b * x + c);
    const mean = average(values);
    const total = values.reduce((sum, value) => sum + (value - mean) ** 2, 0);
    const residual = values.reduce((sum, value, index) => sum + (value - predicted[index]) ** 2, 0);
    return { a, b, c, r2: total ? Math.max(0, 1 - residual / total) : 0, vertex: a ? -b / (2 * a) : 0, predicted };
  }

  function detectRounded(candles, timeframe, top = false) {
    const lengths = timeframe >= 1440 ? [90, 70, 50] : [72, 56, 42];
    for (const length of lengths) {
      if (candles.length < length) continue;
      const start = candles.length - length;
      const sample = candles.slice(start);
      const fit = quadraticFit(sample.map((candle) => candle.close));
      if (!fit || fit.r2 < 0.52 || Math.abs(fit.vertex) > 0.38) continue;
      if ((!top && fit.a <= 0) || (top && fit.a >= 0)) continue;
      const depth = Math.abs(fit.a);
      if (depth < movementThreshold(sample.at(-1).close, timeframe) * 1.25) continue;
      const edgeDifference = Math.abs(fit.predicted[0] - fit.predicted.at(-1));
      if (edgeDifference > depth * 0.72) continue;
      const vertexIndex = Math.max(0, Math.min(length - 1, Math.round((fit.vertex + 1) / 2 * (length - 1))));
      const neckline = (fit.predicted[0] + fit.predicted.at(-1)) / 2;
      const breakout = point(candles.length - 1, neckline);
      const curvePoints = [0, Math.floor(length / 4), vertexIndex, Math.floor(length * 3 / 4), length - 1]
        .map((index) => point(start + index, fit.predicted[index]));
      return makePattern({
        name: top ? "Rounded Top" : "Rounded Bottom",
        direction: top ? "bearish" : "bullish", score: 65,
        breakout, target: neckline + (top ? -depth : depth),
        basis: top ? "Rounded depth below neckline" : "Rounded depth above neckline",
        label: curvePoints[2], points: curvePoints,
        lines: curvePoints.slice(1).map((item, index) => line(curvePoints[index], item)),
      });
    }
    return null;
  }

  function detectRectangle(candles, timeframe) {
    const length = timeframe >= 1440 ? 24 : 28;
    if (candles.length < length + 8) return null;
    const start = candles.length - length;
    const sample = candles.slice(start);
    const avgRange = averageRange(sample);
    const resistance = quantile(sample.map((candle) => candle.high), 0.82);
    const support = quantile(sample.map((candle) => candle.low), 0.18);
    const height = resistance - support;
    if (height < avgRange * 2.1) return null;
    const tolerance = Math.max(avgRange * 0.48, height * 0.08);
    const highTouches = sample.filter((candle) => Math.abs(candle.high - resistance) <= tolerance).length;
    const lowTouches = sample.filter((candle) => Math.abs(candle.low - support) <= tolerance).length;
    const closeFit = fitLine(sample, "close");
    if (highTouches < 3 || lowTouches < 3 || Math.abs(closeFit.slope) > avgRange * 0.065) return null;
    const prior = candles.slice(start - 8, start);
    const priorMove = prior.at(-1).close - prior[0].open;
    const recentMove = sample.at(-1).close - sample[Math.max(0, sample.length - 6)].close;
    const bullish = Math.abs(priorMove) >= height * 0.35 ? priorMove > 0 : recentMove >= 0;
    const breakout = point(candles.length - 1, bullish ? resistance : support);
    return makePattern({
      name: bullish ? "Bullish Rectangle" : "Bearish Rectangle",
      direction: bullish ? "bullish" : "bearish", score: 61,
      breakout, target: breakout.price + (bullish ? height : -height),
      basis: bullish ? "Range height above resistance" : "Range height below support",
      label: point(start + Math.floor(length / 2), bullish ? resistance : support),
      points: [point(start, resistance), point(start, support), point(candles.length - 1, resistance), point(candles.length - 1, support)],
      lines: [line(point(start, resistance), point(candles.length - 1, resistance)), line(point(start, support), point(candles.length - 1, support))],
    });
  }

  function detectChannel(candles, timeframe) {
    const length = timeframe >= 1440 ? 32 : 36;
    if (candles.length < length) return null;
    const start = candles.length - length;
    const sample = candles.slice(start);
    const highFit = fitLine(sample, "high");
    const lowFit = fitLine(sample, "low");
    const avgRange = averageRange(sample);
    const averageSlope = (highFit.slope + lowFit.slope) / 2;
    const minimumSlope = avgRange * 0.028;
    if (Math.abs(averageSlope) < minimumSlope || highFit.slope * lowFit.slope <= 0) return null;
    if (Math.abs(highFit.slope - lowFit.slope) > Math.max(Math.abs(averageSlope) * 0.45, avgRange * 0.025)) return null;
    if (highFit.r2 < 0.2 || lowFit.r2 < 0.2) return null;
    const startWidth = highFit.at(0) - lowFit.at(0);
    const endWidth = highFit.at(length - 1) - lowFit.at(length - 1);
    if (startWidth <= avgRange * 0.8 || endWidth / startWidth < 0.65 || endWidth / startWidth > 1.35) return null;
    const rising = averageSlope > 0;
    const future = length + 7;
    const target = rising ? highFit.at(future) : lowFit.at(future);
    const breakout = point(candles.length - 1, sample.at(-1).close);
    const highStart = point(start, highFit.at(0));
    const highEnd = point(candles.length - 1, highFit.at(length - 1));
    const lowStart = point(start, lowFit.at(0));
    const lowEnd = point(candles.length - 1, lowFit.at(length - 1));
    return makePattern({
      name: rising ? "Rising Channel" : "Falling Channel",
      direction: rising ? "bullish" : "bearish", score: 58,
      breakout, target,
      basis: rising ? "Projected upper channel boundary" : "Projected lower channel boundary",
      label: point(start + Math.floor(length / 2), rising ? highFit.at(length / 2) : lowFit.at(length / 2)),
      points: [highStart, highEnd, lowStart, lowEnd], lines: [line(highStart, highEnd), line(lowStart, lowEnd)],
    });
  }

  function detectTriple(candles, timeframe, bottom = false) {
    const pivots = pivotPoints(candles, timeframe >= 1440 ? 2 : 3);
    const type = bottom ? "L" : "H";
    const recent = pivots.filter((pivot) => pivot.type === type).slice(-6);
    const tolerance = Math.max(averageRange(candles.slice(-40)) * 0.9, candles.at(-1).close * (timeframe >= 1440 ? 0.014 : 0.0025));
    for (let index = 0; index <= recent.length - 3; index += 1) {
      const group = recent.slice(index, index + 3);
      if (group[1].index - group[0].index < 4 || group[2].index - group[1].index < 4) continue;
      if (Math.max(...group.map((pivot) => pivot.price)) - Math.min(...group.map((pivot) => pivot.price)) > tolerance) continue;
      const between = candles.slice(group[0].index, group[2].index + 1);
      const necklinePrice = bottom
        ? Math.max(...between.map((candle) => candle.high))
        : Math.min(...between.map((candle) => candle.low));
      const level = average(group.map((pivot) => pivot.price));
      const depth = bottom ? necklinePrice - level : level - necklinePrice;
      if (depth < tolerance * 1.35) continue;
      const confirmed = bottom ? candles.at(-1).close > necklinePrice : candles.at(-1).close < necklinePrice;
      if (!confirmed) continue;
      const breakout = point(group[2].index, necklinePrice);
      return makePattern({
        name: bottom ? "Triple Bottom" : "Triple Top",
        direction: bottom ? "bullish" : "bearish", score: 82,
        breakout, target: necklinePrice + (bottom ? depth : -depth),
        basis: bottom ? "Range depth above neckline" : "Range depth below neckline",
        label: group[1], points: group,
        lines: [line(group[0], group[1]), line(group[1], group[2]), line(point(group[0].index, necklinePrice), point(candles.length - 1, necklinePrice), NEUTRAL, [5, 5])],
      });
    }
    return null;
  }

  function candlePattern({ name, direction, score, candles, startIndex, breakoutPrice, target, basis }) {
    const color = direction === "bullish" ? BULLISH : BEARISH;
    const latestIndex = candles.length - 1;
    const selected = candles.slice(startIndex);
    const points = selected.map((candle, offset) => point(startIndex + offset, candle.close));
    return makePattern({
      name, direction, score,
      breakout: point(latestIndex, breakoutPrice), target, basis,
      label: point(latestIndex, direction === "bullish" ? candles.at(-1).high : candles.at(-1).low),
      points,
      lines: selected.map((candle, offset) => line(
        point(startIndex + offset, candle.low),
        point(startIndex + offset, candle.high),
        color,
      )),
    });
  }

  function detectCandlestickPatterns(candles) {
    if (candles.length < 8) return [];
    const candidates = [];
    const latest = candles.at(-1);
    const previous = candles.at(-2);
    const third = candles.at(-3);
    const avgRange = averageRange(candles.slice(-12));
    const body = Math.abs(latest.close - latest.open);
    const range = latest.high - latest.low;
    const upperWick = latest.high - Math.max(latest.open, latest.close);
    const lowerWick = Math.min(latest.open, latest.close) - latest.low;
    const shortTrend = fitLine(candles.slice(-8, -1), "close").slope;

    const bullishEngulfing = previous.close < previous.open && latest.close > latest.open
      && latest.open <= previous.close && latest.close >= previous.open
      && body >= avgRange * 0.35;
    const bearishEngulfing = previous.close > previous.open && latest.close < latest.open
      && latest.open >= previous.close && latest.close <= previous.open
      && body >= avgRange * 0.35;
    if (bullishEngulfing) {
      candidates.push(candlePattern({
        name: "Bullish Engulfing", direction: "bullish", score: 56, candles, startIndex: candles.length - 2,
        breakoutPrice: latest.high, target: latest.high + Math.max(body, avgRange), basis: "Engulfing body measured move up",
      }));
    }
    if (bearishEngulfing) {
      candidates.push(candlePattern({
        name: "Bearish Engulfing", direction: "bearish", score: 56, candles, startIndex: candles.length - 2,
        breakoutPrice: latest.low, target: latest.low - Math.max(body, avgRange), basis: "Engulfing body measured move down",
      }));
    }

    if (shortTrend < 0 && lowerWick >= Math.max(body * 2, range * 0.5) && upperWick <= Math.max(body, range * 0.18)) {
      candidates.push(candlePattern({
        name: "Hammer", direction: "bullish", score: 54, candles, startIndex: candles.length - 1,
        breakoutPrice: latest.high, target: latest.high + Math.max(range, avgRange), basis: "Hammer range above its high",
      }));
    }
    if (shortTrend > 0 && upperWick >= Math.max(body * 2, range * 0.5) && lowerWick <= Math.max(body, range * 0.18)) {
      candidates.push(candlePattern({
        name: "Shooting Star", direction: "bearish", score: 54, candles, startIndex: candles.length - 1,
        breakoutPrice: latest.low, target: latest.low - Math.max(range, avgRange), basis: "Shooting-star range below its low",
      }));
    }

    if (range >= avgRange * 0.6 && body <= range * 0.1 && Math.abs(shortTrend) >= avgRange * 0.025) {
      const bullish = shortTrend < 0;
      candidates.push(candlePattern({
        name: bullish ? "Bullish Doji" : "Bearish Doji",
        direction: bullish ? "bullish" : "bearish", score: 48, candles, startIndex: candles.length - 1,
        breakoutPrice: bullish ? latest.high : latest.low,
        target: (bullish ? latest.high : latest.low) + (bullish ? range : -range),
        basis: bullish ? "Doji range above its high" : "Doji range below its low",
      }));
    }

    const firstBody = Math.abs(third.close - third.open);
    const middleBody = Math.abs(previous.close - previous.open);
    const lastBody = body;
    const morning = third.close < third.open && middleBody <= firstBody * 0.48
      && latest.close > latest.open && lastBody >= avgRange * 0.42
      && latest.close >= (third.open + third.close) / 2;
    const evening = third.close > third.open && middleBody <= firstBody * 0.48
      && latest.close < latest.open && lastBody >= avgRange * 0.42
      && latest.close <= (third.open + third.close) / 2;
    const threeRange = Math.max(third.high, previous.high, latest.high) - Math.min(third.low, previous.low, latest.low);
    if (morning) {
      const breakoutPrice = Math.max(third.high, previous.high, latest.high);
      candidates.push(candlePattern({
        name: "Morning Star", direction: "bullish", score: 63, candles, startIndex: candles.length - 3,
        breakoutPrice, target: breakoutPrice + threeRange, basis: "Three-candle range above pattern high",
      }));
    }
    if (evening) {
      const breakoutPrice = Math.min(third.low, previous.low, latest.low);
      candidates.push(candlePattern({
        name: "Evening Star", direction: "bearish", score: 63, candles, startIndex: candles.length - 3,
        breakoutPrice, target: breakoutPrice - threeRange, basis: "Three-candle range below pattern low",
      }));
    }
    return candidates.filter(Boolean);
  }

  function detectAdditionalPatterns(rawCandles, options = {}) {
    const candles = cleanCandles(rawCandles);
    const timeframe = Number(options.timeframe || 1);
    if (candles.length < 12) return [];
    return [
      ...convergenceCandidates(candles, timeframe),
      detectPennant(candles, timeframe),
      detectCupAndHandle(candles, timeframe, false),
      detectCupAndHandle(candles, timeframe, true),
      detectRounded(candles, timeframe, false),
      detectRounded(candles, timeframe, true),
      detectRectangle(candles, timeframe),
      detectChannel(candles, timeframe),
      detectTriple(candles, timeframe, false),
      detectTriple(candles, timeframe, true),
      ...detectCandlestickPatterns(candles),
    ].filter(Boolean);
  }

  function remapPatternIndices(pattern, chartIndices) {
    if (!pattern || !Array.isArray(chartIndices) || !chartIndices.length) return pattern;
    const remapPoint = (value) => {
      if (!value || !Number.isFinite(Number(value.index))) return value;
      const sourceIndex = Math.max(0, Math.min(chartIndices.length - 1, Math.round(Number(value.index))));
      return { ...value, index: chartIndices[sourceIndex] };
    };
    return {
      ...pattern,
      label: remapPoint(pattern.label),
      points: (pattern.points || []).map(remapPoint),
      lines: (pattern.lines || []).map((item) => ({
        ...item,
        from: remapPoint(item.from),
        to: remapPoint(item.to),
      })),
      projection: pattern.projection
        ? { ...pattern.projection, breakout: remapPoint(pattern.projection.breakout) }
        : pattern.projection,
    };
  }

  return {
    SUPPORTED_PATTERNS,
    detectAdditionalPatterns,
    convergenceCandidates,
    detectPennant,
    detectCupAndHandle,
    detectRounded,
    detectRectangle,
    detectChannel,
    detectTriple,
    detectCandlestickPatterns,
    remapPatternIndices,
  };
});
