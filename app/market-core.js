(function attachMarketCore(root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.MarketCore = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function buildMarketCore() {
  const MINUTE_MS = 60_000;
  const MARKET_TIME_ZONE = "America/New_York";
  const TEL_AVIV_TIME_ZONE = "Asia/Jerusalem";
  const US_REGULAR_OPEN_MINUTE = 9 * 60 + 30;
  const US_REGULAR_CLOSE_MINUTE = 16 * 60;
  const TEL_AVIV_REGULAR_OPEN_MINUTE = 10 * 60;
  const TEL_AVIV_REGULAR_CLOSE_MINUTE = 17 * 60 + 30;

  function finite(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function minuteStart(timestamp) {
    return Math.floor(Number(timestamp) / MINUTE_MS) * MINUTE_MS;
  }

  function normalizeChartWindow(totalBars, requestedCount, requestedEnd, options = {}) {
    const total = Math.max(0, Math.floor(Number(totalBars) || 0));
    if (!total) return { total: 0, start: 0, end: 0, count: 0, live: true };
    const minimum = Math.min(total, Math.max(2, Math.floor(Number(options.minCount) || 24)));
    const maximum = Math.max(minimum, Math.min(total, Math.floor(Number(options.maxCount) || 600)));
    const fallback = Math.min(maximum, Math.max(minimum, Math.floor(Number(options.defaultCount) || 120)));
    const countValue = Number.isFinite(Number(requestedCount)) ? Math.round(Number(requestedCount)) : fallback;
    const count = Math.max(minimum, Math.min(maximum, countValue));
    const futureRatio = Math.max(0, Math.min(0.75, Number(options.maxFutureRatio) || 0));
    const maxFutureBars = Math.floor(count * futureRatio);
    const endValue = Number.isFinite(Number(requestedEnd)) ? Math.round(Number(requestedEnd)) : total;
    const end = Math.max(count, Math.min(total + maxFutureBars, endValue));
    return { total, start: end - count, end, count, live: end >= total };
  }

  function zoomChartWindow(windowState, factor, anchorRatio = 1, options = {}) {
    const current = normalizeChartWindow(
      windowState?.total,
      windowState?.count,
      windowState?.end,
      options,
    );
    if (!current.total) return current;
    const ratio = Math.max(0, Math.min(1, Number(anchorRatio) || 0));
    const scale = Math.max(0.2, Math.min(5, Number(factor) || 1));
    const nextCount = Math.round(current.count * scale);
    const anchor = current.start + ratio * Math.max(0, current.count - 1);
    const nextStart = Math.round(anchor - ratio * Math.max(0, nextCount - 1));
    return normalizeChartWindow(current.total, nextCount, nextStart + nextCount, options);
  }

  function panChartWindow(windowState, bars, options = {}) {
    const current = normalizeChartWindow(
      windowState?.total,
      windowState?.count,
      windowState?.end,
      options,
    );
    return normalizeChartWindow(current.total, current.count, current.end - Math.round(Number(bars) || 0), options);
  }

  function normalizeCandle(candle) {
    const time = finite(candle?.time);
    const open = finite(candle?.open);
    const high = finite(candle?.high);
    const low = finite(candle?.low);
    const close = finite(candle?.close);
    const volume = Math.max(0, finite(candle?.volume) || 0);
    if ([time, open, high, low, close].some((value) => value === null)) return null;
    if (Math.min(open, high, low, close) <= 0) return null;
    if (high < Math.max(open, close) || low > Math.min(open, close) || high < low) return null;
    if (volume === 0 && (high - low) / ((open + close) / 2) > 0.02) return null;
    return {
      time: minuteStart(time),
      open,
      high,
      low,
      close,
      volume,
      sourceTime: time,
    };
  }

  function mergeCandles(candles) {
    const buckets = new Map();
    for (const raw of candles || []) {
      const candle = normalizeCandle(raw);
      if (!candle) continue;
      const existing = buckets.get(candle.time);
      if (!existing) {
        buckets.set(candle.time, { ...candle });
        continue;
      }
      const newer = candle.sourceTime >= existing.sourceTime;
      existing.high = Math.max(existing.high, candle.high);
      existing.low = Math.min(existing.low, candle.low);
      existing.volume = Math.max(existing.volume, candle.volume);
      if (newer) {
        existing.close = candle.close;
        existing.sourceTime = candle.sourceTime;
      }
    }
    return [...buckets.values()]
      .sort((a, b) => a.time - b.time)
      .map(({ sourceTime, ...candle }) => candle);
  }

  function mergeCandle(candles, incoming, limit = 2500) {
    return mergeCandles([...(candles || []), incoming]).slice(-limit);
  }

  function isCandleClosed(candle, timeframeMinutes = 1, now = Date.now(), graceMs = 2_000) {
    return Number(candle?.time) + timeframeMinutes * MINUTE_MS + graceMs <= now;
  }

  function resample(candles, minutes) {
    if (minutes === 1) return mergeCandles(candles);
    const size = minutes * MINUTE_MS;
    const buckets = new Map();
    for (const candle of mergeCandles(candles)) {
      const key = Math.floor(candle.time / size) * size;
      const existing = buckets.get(key);
      if (!existing) {
        buckets.set(key, { ...candle, time: key });
        continue;
      }
      existing.high = Math.max(existing.high, candle.high);
      existing.low = Math.min(existing.low, candle.low);
      existing.close = candle.close;
      existing.volume += candle.volume;
    }
    return [...buckets.values()].sort((a, b) => a.time - b.time);
  }

  function resampleDaily(candles, options = {}) {
    const buckets = new Map();
    for (const candle of mergeCandles(candles)) {
      const parts = marketParts(candle.time, options);
      const session = marketSession(candle.time, options);
      const existing = buckets.get(parts.date);
      if (!existing) {
        buckets.set(parts.date, {
          ...candle,
          sessionDate: parts.date,
          hasExtended: !session.regular,
          sourceTime: candle.time,
        });
        continue;
      }
      existing.high = Math.max(existing.high, candle.high);
      existing.low = Math.min(existing.low, candle.low);
      existing.volume += candle.volume;
      existing.hasExtended = existing.hasExtended || !session.regular;
      if (candle.time >= existing.sourceTime) {
        existing.close = candle.close;
        existing.sourceTime = candle.time;
      }
    }
    return [...buckets.values()]
      .sort((a, b) => a.time - b.time)
      .map(({ sourceTime, ...candle }) => candle);
  }

  const dateFormatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: MARKET_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  const timeFormatter = new Intl.DateTimeFormat("en-US", {
    timeZone: MARKET_TIME_ZONE,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const weekdayFormatter = new Intl.DateTimeFormat("en-US", {
    timeZone: MARKET_TIME_ZONE,
    weekday: "short",
  });
  const utcDateFormatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: "UTC", year: "numeric", month: "2-digit", day: "2-digit",
  });
  const utcTimeFormatter = new Intl.DateTimeFormat("en-US", {
    timeZone: "UTC", hour: "2-digit", minute: "2-digit", hour12: false,
  });
  const utcWeekdayFormatter = new Intl.DateTimeFormat("en-US", { timeZone: "UTC", weekday: "short" });
  const telAvivDateFormatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: TEL_AVIV_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  const telAvivTimeFormatter = new Intl.DateTimeFormat("en-US", {
    timeZone: TEL_AVIV_TIME_ZONE,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const telAvivWeekdayFormatter = new Intl.DateTimeFormat("en-US", { timeZone: TEL_AVIV_TIME_ZONE, weekday: "short" });

  function isTelAvivMarket(options = {}) {
    return options.market === "tase";
  }

  function regularSessionMinutes(options = {}) {
    return isTelAvivMarket(options)
      ? { open: TEL_AVIV_REGULAR_OPEN_MINUTE, close: TEL_AVIV_REGULAR_CLOSE_MINUTE }
      : { open: US_REGULAR_OPEN_MINUTE, close: US_REGULAR_CLOSE_MINUTE };
  }

  function marketParts(timestamp, options = {}) {
    const date = new Date(Number(timestamp));
    const selectedTimeFormatter = options.continuous ? utcTimeFormatter : isTelAvivMarket(options) ? telAvivTimeFormatter : timeFormatter;
    const selectedDateFormatter = options.continuous ? utcDateFormatter : isTelAvivMarket(options) ? telAvivDateFormatter : dateFormatter;
    const selectedWeekdayFormatter = options.continuous ? utcWeekdayFormatter : isTelAvivMarket(options) ? telAvivWeekdayFormatter : weekdayFormatter;
    const parts = selectedTimeFormatter.formatToParts(date);
    const hour = Number(parts.find((part) => part.type === "hour")?.value || 0);
    const minute = Number(parts.find((part) => part.type === "minute")?.value || 0);
    return {
      date: selectedDateFormatter.format(date),
      minuteOfDay: hour * 60 + minute,
      hour,
      minute,
      weekday: selectedWeekdayFormatter.format(date),
    };
  }

  function marketSession(timestamp, options = {}) {
    const parts = marketParts(timestamp, options);
    if (options.continuous) return { ...parts, phase: "continuous", regular: true };
    if (["Sat", "Sun"].includes(parts.weekday)) return { ...parts, phase: "closed", regular: false };
    const { open, close } = regularSessionMinutes(options);
    if (parts.minuteOfDay < open) return { ...parts, phase: "premarket", regular: false };
    if (parts.minuteOfDay < close) return { ...parts, phase: "regular", regular: true };
    return { ...parts, phase: "after_hours", regular: false };
  }

  function todayCandles(candles, latestTime, options = {}) {
    if (!candles?.length) return [];
    const latest = latestTime || candles[candles.length - 1].time;
    const day = marketParts(latest, options).date;
    return candles.filter((candle) => marketParts(candle.time, options).date === day);
  }

  function regularSessionCandles(candles, latestTime, options = {}) {
    return todayCandles(candles, latestTime, options).filter((candle) => marketSession(candle.time, options).regular);
  }

  function ema(values, period) {
    const result = Array(values.length).fill(null);
    let previous = null;
    const k = 2 / (period + 1);
    values.forEach((value, index) => {
      if (!Number.isFinite(value)) return;
      previous = previous === null ? value : value * k + previous * (1 - k);
      result[index] = previous;
    });
    return result;
  }

  function sma(values, period) {
    const result = Array(values.length).fill(null);
    let sum = 0;
    for (let index = 0; index < values.length; index += 1) {
      sum += values[index];
      if (index >= period) sum -= values[index - period];
      if (index >= period - 1) result[index] = sum / period;
    }
    return result;
  }

  function wilder(values, period) {
    const result = Array(values.length).fill(null);
    if (values.length < period) return result;
    let average = values.slice(0, period).reduce((sum, value) => sum + value, 0) / period;
    result[period - 1] = average;
    for (let index = period; index < values.length; index += 1) {
      average = (average * (period - 1) + values[index]) / period;
      result[index] = average;
    }
    return result;
  }

  function calculateIndicators(rawCandles, options = {}) {
    const candles = mergeCandles(rawCandles);
    if (!candles.length) return [];
    const closes = candles.map((candle) => candle.close);
    const ema9 = ema(closes, 9);
    const ema21 = ema(closes, 21);
    const ema20 = ema(closes, 20);
    const ema50 = ema(closes, 50);
    const ema150 = ema(closes, 150);
    const sma20 = sma(closes, 20);
    const sma50 = sma(closes, 50);
    const sma150 = sma(closes, 150);
    const gains = [];
    const losses = [];
    const trueRanges = [];
    const volumeHistory = new Map();
    const relativeVolumes = [];

    candles.forEach((candle, index) => {
      const previous = candles[index - 1];
      const change = previous ? candle.close - previous.close : 0;
      gains.push(Math.max(0, change));
      losses.push(Math.max(0, -change));
      trueRanges.push(previous
        ? Math.max(candle.high - candle.low, Math.abs(candle.high - previous.close), Math.abs(candle.low - previous.close))
        : candle.high - candle.low);

      const parts = marketParts(candle.time, options);
      const samples = volumeHistory.get(parts.minuteOfDay) || [];
      const average = samples.length ? samples.reduce((sum, value) => sum + value, 0) / samples.length : null;
      relativeVolumes.push(average && candle.volume > 0 ? candle.volume / average : null);
      if (candle.volume > 0) {
        samples.push(candle.volume);
        if (samples.length > 10) samples.shift();
        volumeHistory.set(parts.minuteOfDay, samples);
      }
    });

    const averageGains = wilder(gains, 14);
    const averageLosses = wilder(losses, 14);
    const atrs = wilder(trueRanges, 14);
    let vwapKey = "";
    let cumulativePV = 0;
    let cumulativeVolume = 0;

    return candles.map((candle, index) => {
      const parts = marketParts(candle.time, options);
      const { open } = regularSessionMinutes(options);
      const segment = options.continuous ? "continuous" : parts.minuteOfDay < open ? "pre" : "regular";
      const key = `${parts.date}:${segment}`;
      if (key !== vwapKey) {
        vwapKey = key;
        cumulativePV = 0;
        cumulativeVolume = 0;
      }
      const typical = (candle.high + candle.low + candle.close) / 3;
      if (candle.volume > 0) {
        cumulativePV += typical * candle.volume;
        cumulativeVolume += candle.volume;
      }
      const averageGain = averageGains[index];
      const averageLoss = averageLosses[index];
      let rsi = null;
      if (Number.isFinite(averageGain) && Number.isFinite(averageLoss)) {
        if (averageLoss === 0) rsi = averageGain === 0 ? 50 : 100;
        else rsi = 100 - 100 / (1 + averageGain / averageLoss);
      }
      return {
        ...candle,
        ema9: ema9[index],
        ema21: ema21[index],
        ema20: ema20[index],
        ema50: ema50[index],
        ema150: ema150[index],
        sma20: sma20[index],
        sma50: sma50[index],
        sma150: sma150[index],
        vwap: cumulativeVolume ? cumulativePV / cumulativeVolume : null,
        rsi,
        atr: atrs[index],
        relativeVolume: relativeVolumes[index],
      };
    });
  }

  function previousRegularClose(candles, latestTime, options = {}) {
    if (!candles?.length) return null;
    const currentDay = marketParts(latestTime || candles[candles.length - 1].time, options).date;
    const prior = candles.filter((candle) => {
      const parts = marketParts(candle.time, options);
      const { open, close } = regularSessionMinutes(options);
      return parts.date < currentDay && (options.continuous || (parts.minuteOfDay >= open && parts.minuteOfDay < close));
    });
    return prior.length ? prior[prior.length - 1].close : null;
  }

  return {
    MINUTE_MS,
    MARKET_TIME_ZONE,
    TEL_AVIV_TIME_ZONE,
    minuteStart,
    normalizeChartWindow,
    zoomChartWindow,
    panChartWindow,
    normalizeCandle,
    mergeCandles,
    mergeCandle,
    isCandleClosed,
    resample,
    resampleDaily,
    marketParts,
    marketSession,
    todayCandles,
    regularSessionCandles,
    calculateIndicators,
    previousRegularClose,
  };
});
