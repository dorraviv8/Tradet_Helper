import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


MINUTE_MS = 60_000
MARKET_TIME_ZONE = ZoneInfo("America/New_York")
TEL_AVIV_TIME_ZONE = ZoneInfo("Asia/Jerusalem")
TIMEFRAMES = (1, 5, 15)
DAILY_TIMEFRAME = 1440
DEFAULT_SYMBOL = "QQQ"
CRYPTO_SYMBOLS = {"BTC-USD"}
TEL_AVIV_SYMBOLS = {"TA125"}
US_REGULAR_OPEN_MINUTE = 9 * 60 + 30
US_REGULAR_CLOSE_MINUTE = 16 * 60
TEL_AVIV_REGULAR_OPEN_MINUTE = 10 * 60
TEL_AVIV_REGULAR_CLOSE_MINUTE = 17 * 60 + 30
MARKET_PROFILES = {
  "QQQ": {
    "label": "US technology ETF",
    "reliableVolume": True,
    "relativeVolumeFloor": 1.10,
    "intradayScale": 1.0,
    "dailyTargetMinPct": 0.012,
    "dailyTargetMaxPct": 0.025,
    "dailyTarget2MaxPct": 0.04,
    "dailyRiskAtr": 1.45,
    "dailyRiskPct": 0.022,
  },
  "SPY": {
    "label": "US broad-market ETF",
    "reliableVolume": True,
    "relativeVolumeFloor": 1.05,
    "intradayScale": 0.82,
    "dailyTargetMinPct": 0.008,
    "dailyTargetMaxPct": 0.018,
    "dailyTarget2MaxPct": 0.03,
    "dailyRiskAtr": 1.4,
    "dailyRiskPct": 0.018,
  },
  "BTC-USD": {
    "label": "Continuous cryptocurrency",
    "reliableVolume": True,
    "relativeVolumeFloor": 1.15,
    "intradayScale": 1.0,
    "dailyTargetMinPct": 0.02,
    "dailyTargetMaxPct": 0.05,
    "dailyTarget2MaxPct": 0.08,
    "dailyRiskAtr": 1.65,
    "dailyRiskPct": 0.045,
  },
  "TA125": {
    "label": "Tel Aviv broad-market index",
    "reliableVolume": False,
    "relativeVolumeFloor": None,
    "intradayScale": 0.78,
    "dailyTargetMinPct": 0.007,
    "dailyTargetMaxPct": 0.018,
    "dailyTarget2MaxPct": 0.028,
    "dailyRiskAtr": 1.4,
    "dailyRiskPct": 0.018,
  },
}


def asset_profile(symbol=DEFAULT_SYMBOL):
  return MARKET_PROFILES.get(str(symbol or DEFAULT_SYMBOL).upper(), MARKET_PROFILES[DEFAULT_SYMBOL])


def is_continuous_market(symbol=DEFAULT_SYMBOL):
  return str(symbol or DEFAULT_SYMBOL).upper() in CRYPTO_SYMBOLS


def is_tel_aviv_market(symbol=DEFAULT_SYMBOL):
  return str(symbol or DEFAULT_SYMBOL).upper() in TEL_AVIV_SYMBOLS


def market_timezone(symbol=DEFAULT_SYMBOL):
  if is_continuous_market(symbol):
    return timezone.utc
  return TEL_AVIV_TIME_ZONE if is_tel_aviv_market(symbol) else MARKET_TIME_ZONE


def regular_session_minutes(symbol=DEFAULT_SYMBOL):
  if is_tel_aviv_market(symbol):
    return TEL_AVIV_REGULAR_OPEN_MINUTE, TEL_AVIV_REGULAR_CLOSE_MINUTE
  return US_REGULAR_OPEN_MINUTE, US_REGULAR_CLOSE_MINUTE


def clamp(value, minimum, maximum):
  return max(minimum, min(maximum, value))


def market_parts(timestamp, symbol=DEFAULT_SYMBOL):
  zone = market_timezone(symbol)
  value = datetime.fromtimestamp(timestamp / 1000, zone)
  return value.strftime("%Y-%m-%d"), value.hour * 60 + value.minute


def market_session(timestamp, symbol=DEFAULT_SYMBOL):
  zone = market_timezone(symbol)
  value = datetime.fromtimestamp(timestamp / 1000, zone)
  day, minute = market_parts(timestamp, symbol)
  if is_continuous_market(symbol):
    return {"date": day, "minute": minute, "phase": "continuous", "regular": True}
  if value.weekday() >= 5 or (is_tel_aviv_market(symbol) and value.weekday() == 6):
    return {"date": day, "minute": minute, "phase": "closed", "regular": False}
  regular_open, regular_close = regular_session_minutes(symbol)
  if minute < regular_open:
    return {"date": day, "minute": minute, "phase": "premarket", "regular": False}
  if minute < regular_close:
    return {"date": day, "minute": minute, "phase": "regular", "regular": True}
  return {"date": day, "minute": minute, "phase": "after_hours", "regular": False}


def market_phase(timestamp, symbol=DEFAULT_SYMBOL):
  if is_continuous_market(symbol):
    return "continuous"
  session = market_session(timestamp, symbol)
  if session["phase"] == "closed":
    return "closed"
  minute = session["minute"]
  regular_open, regular_close = regular_session_minutes(symbol)
  if minute < regular_open:
    return "premarket"
  if minute < regular_open + 15:
    return "open"
  if minute < regular_open + 90:
    return "morning"
  if minute < regular_open + (regular_close - regular_open) * 0.55:
    return "midday"
  if minute < regular_close - 60:
    return "afternoon"
  if minute < regular_close:
    return "power_hour"
  return "after_hours"


def merge_candles(raw_candles):
  buckets = {}
  for raw in raw_candles or []:
    try:
      values = {key: float(raw[key]) for key in ("open", "high", "low", "close")}
      timestamp = int(raw["time"] // MINUTE_MS) * MINUTE_MS
      volume = max(0, int(raw.get("volume") or 0))
    except (KeyError, TypeError, ValueError):
      continue
    if not all(math.isfinite(value) and value > 0 for value in values.values()):
      continue
    if values["high"] < max(values["open"], values["close"]) or values["low"] > min(values["open"], values["close"]):
      continue
    reference_price = (values["open"] + values["close"]) / 2
    if volume == 0 and (values["high"] - values["low"]) / reference_price > 0.02:
      continue
    existing = buckets.get(timestamp)
    candle = {"time": timestamp, **values, "volume": volume}
    if not existing:
      buckets[timestamp] = candle
    else:
      existing["high"] = max(existing["high"], candle["high"])
      existing["low"] = min(existing["low"], candle["low"])
      existing["close"] = candle["close"]
      existing["volume"] = max(existing["volume"], candle["volume"])
  return [buckets[key] for key in sorted(buckets)]


def resample(candles, minutes):
  size = minutes * MINUTE_MS
  buckets = {}
  for candle in merge_candles(candles):
    key = candle["time"] // size * size
    existing = buckets.get(key)
    if not existing:
      buckets[key] = {**candle, "time": key}
    else:
      existing["high"] = max(existing["high"], candle["high"])
      existing["low"] = min(existing["low"], candle["low"])
      existing["close"] = candle["close"]
      existing["volume"] += candle["volume"]
  return [buckets[key] for key in sorted(buckets)]


def ema(values, period):
  output = []
  previous = None
  weight = 2 / (period + 1)
  for value in values:
    previous = value if previous is None else value * weight + previous * (1 - weight)
    output.append(previous)
  return output


def sma(values, period):
  output = [None] * len(values)
  total = 0
  for index, value in enumerate(values):
    total += value
    if index >= period:
      total -= values[index - period]
    if index >= period - 1:
      output[index] = total / period
  return output


def wilder(values, period):
  output = [None] * len(values)
  if len(values) < period:
    return output
  average = sum(values[:period]) / period
  output[period - 1] = average
  for index in range(period, len(values)):
    average = (average * (period - 1) + values[index]) / period
    output[index] = average
  return output


def indicators(raw_candles, symbol=DEFAULT_SYMBOL):
  candles = merge_candles(raw_candles)
  if not candles:
    return []
  closes = [candle["close"] for candle in candles]
  averages = {
    "ema20": ema(closes, 20),
    "ema50": ema(closes, 50),
    "ema150": ema(closes, 150),
    "sma20": sma(closes, 20),
    "sma50": sma(closes, 50),
    "sma150": sma(closes, 150),
  }
  gains = []
  losses = []
  ranges = []
  volume_history = {}
  relative_volumes = []
  rolling_relative_volumes = []
  rolling_volumes = []
  for index, candle in enumerate(candles):
    previous = candles[index - 1] if index else None
    change = candle["close"] - previous["close"] if previous else 0
    gains.append(max(0, change))
    losses.append(max(0, -change))
    ranges.append(
      max(candle["high"] - candle["low"], abs(candle["high"] - previous["close"]), abs(candle["low"] - previous["close"]))
      if previous else candle["high"] - candle["low"]
    )
    minute = market_parts(candle["time"], symbol)[1]
    samples = volume_history.setdefault(minute, [])
    average = sum(samples) / len(samples) if samples else None
    relative_volumes.append(candle["volume"] / average if average and candle["volume"] else None)
    rolling_average = sum(rolling_volumes) / len(rolling_volumes) if rolling_volumes else None
    rolling_relative_volumes.append(candle["volume"] / rolling_average if rolling_average and candle["volume"] else None)
    if candle["volume"]:
      samples.append(candle["volume"])
      del samples[:-10]
      rolling_volumes.append(candle["volume"])
      del rolling_volumes[:-20]

  average_gains = wilder(gains, 14)
  average_losses = wilder(losses, 14)
  atrs = wilder(ranges, 14)
  output = []
  vwap_key = None
  cumulative_pv = 0
  cumulative_volume = 0
  for index, candle in enumerate(candles):
    day, minute = market_parts(candle["time"], symbol)
    regular_open, _ = regular_session_minutes(symbol)
    segment = "continuous" if is_continuous_market(symbol) else "pre" if minute < regular_open else "regular"
    key = (day, segment)
    if key != vwap_key:
      vwap_key = key
      cumulative_pv = 0
      cumulative_volume = 0
    typical = (candle["high"] + candle["low"] + candle["close"]) / 3
    cumulative_pv += typical * candle["volume"]
    cumulative_volume += candle["volume"]
    average_gain = average_gains[index]
    average_loss = average_losses[index]
    rsi = None
    if average_gain is not None and average_loss is not None:
      rsi = 50 if average_gain == average_loss == 0 else 100 if average_loss == 0 else 100 - 100 / (1 + average_gain / average_loss)
    enriched = {
      **candle,
      "vwap": cumulative_pv / cumulative_volume if cumulative_volume else None,
      "rsi": rsi,
      "atr": atrs[index],
      "timeRelativeVolume": relative_volumes[index],
      "rollingRelativeVolume": rolling_relative_volumes[index],
      "relativeVolume": relative_volumes[index] or rolling_relative_volumes[index],
    }
    for name, values in averages.items():
      enriched[name] = values[index]
    output.append(enriched)
  return output


def today_candles(candles, symbol=DEFAULT_SYMBOL):
  if not candles:
    return []
  day = market_parts(candles[-1]["time"], symbol)[0]
  return [candle for candle in candles if market_parts(candle["time"], symbol)[0] == day]


def closed_for_timeframe(candles, timeframe, now):
  sampled = merge_candles(candles) if timeframe == 1 else resample(candles, timeframe)
  return [candle for candle in sampled if candle["time"] + timeframe * MINUTE_MS + 2_000 <= now]


def classify_trend(values):
  if len(values) < 8:
    return {"label": "Building", "tone": "neutral"}
  latest = values[-1]
  prior = values[-min(6, len(values) - 1)]
  required = (latest.get("ema20"), latest.get("ema50"), latest.get("vwap"), latest.get("rsi"), prior.get("ema20"))
  if any(value is None for value in required):
    return {"label": "Building", "tone": "neutral"}
  score = 0
  score += 1 if latest["close"] > latest["ema20"] else -1
  score += 1 if latest["close"] > latest["ema50"] else -1
  score += 1 if latest["close"] > latest["vwap"] else -1
  score += 1 if latest["ema20"] > prior["ema20"] else -1
  score += 1 if latest["rsi"] >= 55 else -1 if latest["rsi"] <= 45 else 0
  score += 1 if latest["close"] > prior["close"] else -1
  if score >= 4:
    return {"label": "Strong up", "tone": "positive"}
  if score >= 2:
    return {"label": "Weak up", "tone": "positive"}
  if score <= -4:
    return {"label": "Strong down", "tone": "negative"}
  if score <= -2:
    return {"label": "Weak down", "tone": "negative"}
  return {"label": "Range", "tone": "neutral"}


def classify_market_regime(values):
  if len(values) < 30:
    return {
      "label": "Building",
      "tone": "neutral",
      "type": "building",
      "detail": "Waiting for enough current-session candles",
    }
  latest = values[-1]
  recent = values[-30:]
  prior = values[-min(18, len(values) - 1)]
  required = (latest.get("atr"), latest.get("ema20"), latest.get("ema50"), latest.get("vwap"), prior.get("ema20"))
  if any(value is None for value in required):
    return {
      "label": "Building",
      "tone": "neutral",
      "type": "building",
      "detail": "Waiting for complete regime indicators",
    }
  high = max(candle["high"] for candle in recent)
  low = min(candle["low"] for candle in recent)
  atr_values = [candle["atr"] for candle in recent if candle.get("atr") is not None]
  average_atr = sum(atr_values) / len(atr_values) if atr_values else 0
  atr_expansion = latest["atr"] / average_atr if average_atr else 1
  trend_score = (
    (1 if latest["ema20"] > latest["ema50"] else -1)
    + (1 if latest["close"] > latest["vwap"] else -1)
    + (1 if latest["close"] > prior["close"] else -1)
    + (1 if latest["ema20"] > prior["ema20"] else -1)
  )
  range_atr = (high - low) / average_atr if average_atr else 0
  if atr_expansion > 1.45 and abs(trend_score) <= 1:
    return {"label": "Chop", "tone": "neutral", "type": "chop", "detail": f"High volatility without clean direction ({range_atr:.1f} ATR range)"}
  if trend_score >= 3 and range_atr >= 3:
    return {"label": "Trend Up", "tone": "positive", "type": "trend_up", "detail": "Current session has upside alignment across EMA, VWAP, and price slope"}
  if trend_score <= -3 and range_atr >= 3:
    return {"label": "Trend Down", "tone": "negative", "type": "trend_down", "detail": "Current session has downside alignment across EMA, VWAP, and price slope"}
  if range_atr < 2.2:
    return {"label": "Range", "tone": "neutral", "type": "range", "detail": "Price is compressed versus current ATR; prefer fades or wait for expansion"}
  return {"label": "Mixed", "tone": "neutral", "type": "mixed", "detail": "Momentum is not fully aligned; require cleaner confirmation"}


def recent_levels(values, lookback):
  prior = values[-lookback:-1]
  highs = [item["high"] for item in prior]
  lows = [item["low"] for item in prior]
  if not highs or not lows:
    return None
  resistance = max(highs)
  support = min(lows)
  tolerance = (values[-1].get("atr") or 0.25) * 0.35
  return {
    "resistance": resistance,
    "support": support,
    "resistanceTouches": sum(abs(value - resistance) <= tolerance for value in highs),
    "supportTouches": sum(abs(value - support) <= tolerance for value in lows),
  }


def candle_shape(candle):
  value_range = max(0.01, candle["high"] - candle["low"])
  body = abs(candle["close"] - candle["open"])
  return {
    "body": body,
    "bodyPct": body / value_range,
    "upperWickPct": (candle["high"] - max(candle["open"], candle["close"])) / value_range,
    "lowerWickPct": (min(candle["open"], candle["close"]) - candle["low"]) / value_range,
    "bullish": candle["close"] > candle["open"],
    "bearish": candle["close"] < candle["open"],
  }


def bounds(timeframe, mode, symbol=DEFAULT_SYMBOL):
  equity_values = {
    1: {"maxRiskAtr": 1.2, "maxRiskPct": 0.0028, "target1MinPct": 0.0025, "target1MaxPct": 0.0038, "target2MaxPct": 0.0055, "lookback": 24},
    5: {"maxRiskAtr": 1.35, "maxRiskPct": 0.0035, "target1MinPct": 0.003, "target1MaxPct": 0.0045, "target2MaxPct": 0.0065, "lookback": 18},
    15: {"maxRiskAtr": 1.5, "maxRiskPct": 0.0042, "target1MinPct": 0.0032, "target1MaxPct": 0.005, "target2MaxPct": 0.007, "lookback": 14},
  }
  crypto_values = {
    1: {"maxRiskAtr": 1.35, "maxRiskPct": 0.0045, "target1MinPct": 0.003, "target1MaxPct": 0.006, "target2MaxPct": 0.009, "lookback": 30},
    5: {"maxRiskAtr": 1.5, "maxRiskPct": 0.0075, "target1MinPct": 0.005, "target1MaxPct": 0.012, "target2MaxPct": 0.018, "lookback": 24},
    15: {"maxRiskAtr": 1.65, "maxRiskPct": 0.012, "target1MinPct": 0.008, "target1MaxPct": 0.02, "target2MaxPct": 0.03, "lookback": 18},
  }
  values = dict((crypto_values if is_continuous_market(symbol) else equity_values)[timeframe])
  profile = asset_profile(symbol)
  if not is_continuous_market(symbol):
    for key in ("maxRiskPct", "target1MinPct", "target1MaxPct", "target2MaxPct"):
      values[key] *= profile["intradayScale"]
  scale = {"scalp": 0.82, "normal": 1, "strict": 1.08}.get(mode, 1)
  for key in ("target1MinPct", "target1MaxPct", "target2MaxPct"):
    values[key] *= scale
  return values


def execution_quality(entry, stop, atr, timeframe, settings=None, symbol=DEFAULT_SYMBOL):
  settings = settings or {}
  risk = abs(float(entry) - float(stop))
  price = max(abs(float(entry)), 1e-9)
  atr_value = max(float(atr or 0), 1e-9)
  risk_bps = risk / price * 10_000
  risk_atr = risk / atr_value
  base_slippage = max(0, float(settings.get("backtestSlippageBps", 0.5)))
  estimated_slippage = base_slippage + (1.0 if is_continuous_market(symbol) else 0.0)
  round_trip_cost_bps = estimated_slippage * 2
  minimum_risk_bps = max(3.0 if is_continuous_market(symbol) else 2.0, round_trip_cost_bps / 0.25)
  blockers = []
  if timeframe != DAILY_TIMEFRAME:
    if risk_bps < minimum_risk_bps:
      blockers.append(f"Stop distance {risk_bps:.1f} bps is too small for estimated execution cost")
    if risk_atr < 0.25:
      blockers.append(f"Stop distance {risk_atr:.2f} ATR is inside normal candle noise")
  return {
    "status": "blocked" if blockers else "passed",
    "riskBps": round(risk_bps, 3),
    "riskAtr": round(risk_atr, 3),
    "estimatedRoundTripCostBps": round(round_trip_cost_bps, 3),
    "minimumRiskBps": round(minimum_risk_bps, 3),
    "minimumRiskAtr": 0.25,
    "entryConfirmation": "close" if timeframe != DAILY_TIMEFRAME else "touch",
    "blockers": blockers,
  }


def session_levels(candles, bar_minutes=1, symbol=DEFAULT_SYMBOL):
  current = today_candles(candles, symbol)
  regular = [candle for candle in current if market_session(candle["time"], symbol)["regular"]]
  premarket = [candle for candle in current if market_session(candle["time"], symbol)["phase"] == "premarket"]
  if not regular:
    return {}
  result = {
    "sessionHigh": max(candle["high"] for candle in regular),
    "sessionLow": min(candle["low"] for candle in regular),
  }
  for minutes in (5, 15, 30):
    count = math.ceil(minutes / max(1, bar_minutes))
    opening = regular[:count]
    if len(opening) >= count:
      result[f"opening{minutes}High"] = max(candle["high"] for candle in opening)
      result[f"opening{minutes}Low"] = min(candle["low"] for candle in opening)
  if premarket:
    result["premarketHigh"] = max(candle["high"] for candle in premarket)
    result["premarketLow"] = min(candle["low"] for candle in premarket)
  return result


def prior_session_levels(candles, symbol=DEFAULT_SYMBOL):
  values = merge_candles(candles)
  if not values:
    return {}
  current_day = market_parts(values[-1]["time"], symbol)[0]
  sessions = {}
  for candle in values:
    session = market_session(candle["time"], symbol)
    if session["regular"] and session["date"] != current_day:
      sessions.setdefault(session["date"], []).append(candle)
  if not sessions:
    return {}
  previous = sessions[sorted(sessions)[-1]]
  return {
    "priorDayHigh": max(candle["high"] for candle in previous),
    "priorDayLow": min(candle["low"] for candle in previous),
  }


def compression_breakout(values, direction):
  """Identify a compact six-bar 5m range that has just expanded through its boundary."""
  if len(values) < 8:
    return False
  prior = values[-7:-1]
  latest = values[-1]
  atr = latest.get("atr") or 0
  if atr <= 0:
    return False
  high = max(candle["high"] for candle in prior)
  low = min(candle["low"] for candle in prior)
  compressed = high - low <= atr * 2.2
  return compressed and (latest["close"] > high if direction == "long" else latest["close"] < low)


def five_minute_no_trade_filters(latest, regime, symbol=DEFAULT_SYMBOL):
  phase = market_phase(latest["time"], symbol)
  reasons = []
  atr = latest.get("atr") or 0
  close = latest.get("close") or 0
  relative_volume = latest.get("relativeVolume")
  if not is_continuous_market(symbol) and phase == "open":
    reasons.append("Wait for the 15-minute opening range to complete")
  if atr > 0 and close > 0 and atr / close < 0.00035:
    reasons.append("5m volatility is too compressed for a reliable target")
  if phase == "midday" and asset_profile(symbol)["reliableVolume"] and relative_volume is not None and relative_volume < 0.6:
    reasons.append("Midday volume is too light for a momentum trade")
  if regime.get("type") == "chop" and atr > 0 and abs(latest["close"] - (latest.get("vwap") or latest["close"])) < atr * 0.35:
    reasons.append("Choppy price action is too close to VWAP")
  return reasons


def execution_confirmation(values, direction):
  """Use closed 1m bars to validate that a 5m idea has an execution trigger."""
  if len(values or []) < 8:
    return {"available": False, "aligned": None, "detail": "1m execution bars are still building"}
  latest = values[-1]
  previous = values[-2]
  anchor = values[-4]
  required = (latest.get("ema20"), latest.get("vwap"), latest.get("rsi"), previous.get("ema20"))
  if any(value is None for value in required):
    return {"available": False, "aligned": None, "detail": "1m execution indicators are still building"}
  shape = candle_shape(latest)
  if direction == "long":
    aligned = (
      latest["close"] > latest["ema20"]
      and latest["close"] > latest["vwap"]
      and latest["rsi"] >= 50
      and latest["close"] >= previous["close"]
      and (shape["bullish"] or latest["low"] <= latest["ema20"])
      and latest["close"] > anchor["close"]
      and latest["rsi"] >= (anchor.get("rsi") or latest["rsi"])
    )
  else:
    aligned = (
      latest["close"] < latest["ema20"]
      and latest["close"] < latest["vwap"]
      and latest["rsi"] <= 50
      and latest["close"] <= previous["close"]
      and (shape["bearish"] or latest["high"] >= latest["ema20"])
      and latest["close"] < anchor["close"]
      and latest["rsi"] <= (anchor.get("rsi") or latest["rsi"])
    )
  return {
    "available": True,
    "aligned": aligned,
    "detail": "1m execution confirms price, EMA/VWAP, and three-bar momentum" if aligned else "1m price, EMA/VWAP, and three-bar momentum are not fully aligned",
  }


def setup_type(setup):
  value = setup.lower()
  for needle, label in (("failed", "failed_breakout"), ("compression", "compression"), ("opening range", "opening_range"), ("premarket", "premarket"), ("momentum", "momentum"), ("pullback", "ema_pullback"), ("vwap", "vwap"), ("breakout", "breakout"), ("breakdown", "breakdown"), ("reversal", "reversal")):
    if needle in value:
      return label
  return "other"


def trend_confirmation(trends, timeframe, direction):
  """Return aligned and opposing trend counts without double-counting a timeframe."""
  tone = "positive" if direction == "long" else "negative"
  opposing_tone = "negative" if tone == "positive" else "positive"
  timeframes = (1, 5, 15) if timeframe == 1 else (5, 15)
  selected = [trends.get(item, {"tone": "neutral"}).get("tone") for item in timeframes]
  return {
    "aligned": sum(value == tone for value in selected),
    "opposed": sum(value == opposing_tone for value in selected),
    "available": len(selected),
  }


def atr_extension(latest, direction):
  """Measure how far price has already moved away from EMA 20 in ATR units."""
  atr = latest.get("atr") or 0
  ema20 = latest.get("ema20")
  if atr <= 0 or ema20 is None:
    return 0
  move = latest["close"] - ema20 if direction == "long" else ema20 - latest["close"]
  return move / atr


def adaptive_adjustment(kind, timeframe, phase, performance, reasons):
  adjustment = 0
  groups = (
    ((performance.get("bySetup") or {}), kind, 1),
    ((performance.get("byTimeframe") or {}), str(timeframe), 0.8),
    ((performance.get("byPhase") or {}), phase, 0.7),
  )
  for rows, key, weight in groups:
    row = rows.get(key)
    winners = int((row or {}).get("winners") or 0)
    losses = int((row or {}).get("stopped") or 0)
    resolved = winners + losses
    if resolved < 30:
      continue
    posterior = (winners + 10) / (resolved + 20)
    delta = int(clamp(round((posterior - 0.5) * 14 * weight), -4, 4))
    if delta:
      adjustment += delta
      reasons.append(f"{key} historical adjustment {delta:+d}")
  return clamp(adjustment, -6, 6)


def score_candidate(candidate, context, settings, performance, symbol=DEFAULT_SYMBOL):
  latest = context["latest"]
  previous = context["previous"]
  direction = context["direction"]
  long = direction == "long"
  shape = context["shape"]
  local = context["levels"]
  timeframe = context["timeframe"]
  reasons = list(candidate["reasons"])
  score = candidate["baseScore"]
  phase = market_phase(latest["time"], symbol)
  tone = "positive" if long else "negative"
  regime = context.get("regime") or {"label": "Mixed", "type": "mixed"}
  kind = setup_type(candidate["setup"])
  confirmation = trend_confirmation(context["trends"], timeframe, direction)
  extension = atr_extension(latest, direction)
  continuation = kind in {"momentum", "breakout", "breakdown", "ema_pullback"}
  execution = context.get("execution") or {"available": False, "aligned": None}
  relative_volume = latest.get("relativeVolume") or 0
  profile = asset_profile(symbol)
  contribution_rows = [{"label": "Setup structure", "points": int(candidate["baseScore"])}]

  def adjust(points, label):
    nonlocal score
    score += points
    contribution_rows.append({"label": label, "points": int(points)})

  if (regime["type"] == "trend_up" and not long) or (regime["type"] == "trend_down" and long):
    adjust(-16, "Regime opposition")
    reasons.append(f"Market regime opposes {direction} setup")
  if regime["type"] in {"range", "chop"} and setup_type(candidate["setup"]) == "momentum":
    adjust(-10, "Momentum in range/chop")
    reasons.append(f"{regime['label']} regime reduces momentum follow-through quality")
  if setup_type(candidate["setup"]) in {"reversal", "vwap"} and regime["type"] in {"range", "mixed"}:
    adjust(5, "Reversion-friendly regime")
    reasons.append(f"{regime['label']} regime can favor tactical reversion setups")
  if continuation and confirmation["aligned"] < 2:
    adjust(-18, "Missing trend alignment")
    reasons.append("Higher-timeframe momentum is not sufficiently aligned")
  elif continuation and confirmation["opposed"]:
    adjust(-12, "Opposing monitored trend")
    reasons.append("A monitored timeframe opposes the setup direction")
  if continuation and extension > 1.35:
    adjust(-20, "Overextended entry")
    reasons.append(f"Price is already {extension:.1f} ATR beyond EMA 20; avoid chasing")
  if timeframe == 5 and execution["available"]:
    if execution["aligned"]:
      adjust(10, "One-minute execution confirmation")
      reasons.append(execution["detail"])
    elif continuation:
      adjust(-18, "One-minute execution conflict")
      reasons.append(execution["detail"])

  checks = (
    (context["selectedTrend"]["tone"] == tone, 16, f"{timeframe}m trend agrees"),
    (context["trend5"]["tone"] == tone, 12, "5m trend confirms"),
    (context["trend15"]["tone"] == tone, 12, "15m trend confirms"),
    ((latest["ema20"] > latest["ema50"]) if long else (latest["ema20"] < latest["ema50"]), 12, "EMA 20/50 structure agrees"),
    (((latest.get("sma20") or latest["ema20"]) > (latest.get("sma50") or latest["ema50"])) if long else ((latest.get("sma20") or latest["ema20"]) < (latest.get("sma50") or latest["ema50"])), 8, "SMA 20/50 structure agrees"),
    ((latest["close"] > latest["vwap"]) if long else (latest["close"] < latest["vwap"]), 8, "VWAP is on the correct side"),
    ((45 <= latest["rsi"] <= 68) if long else (32 <= latest["rsi"] <= 55), 10, "RSI is in a tradable momentum zone"),
    ((shape["bullish"] if long else shape["bearish"]) and shape["bodyPct"] >= 0.35, 10, "Confirmation candle has a real body"),
    ((relative_volume >= (profile["relativeVolumeFloor"] or 99) if profile["reliableVolume"] else False) or shape["body"] >= latest["atr"] * 0.35, 8, "Relative volume or candle expansion supports the move"),
    ((local["supportTouches"] if long else local["resistanceTouches"]) >= 2, 4, "Nearby level has repeated touches"),
  )
  if phase in {"morning", "afternoon", "power_hour"}:
    adjust(6, f"{phase.replace('_', ' ').title()} follow-through window")
    reasons.append(f"Market phase supports intraday follow-through: {phase}")
  elif phase == "midday":
    adjust(-6, "Midday liquidity penalty")
    reasons.append("Midday session can be choppy")
  for condition, points, reason in checks:
    if condition:
      adjust(points, reason)
      reasons.append(reason)

  five_minute_model = None
  if timeframe == 5:
    if kind == "opening_range":
      five_minute_model = "opening_breakout"
      if phase == "morning":
        adjust(5, "Opening breakout timing")
    elif kind in {"ema_pullback", "vwap"}:
      five_minute_model = "trend_pullback"
      if regime["type"] in {"trend_up", "trend_down"}:
        adjust(5, "Trend pullback regime")
    elif kind in {"failed_breakout", "reversal"}:
      five_minute_model = "failed_break_reversal"
      if regime["type"] in {"range", "mixed"}:
        adjust(4, "Reversal-friendly regime")
    elif kind in {"breakout", "breakdown", "compression"}:
      five_minute_model = "range_expansion"
    else:
      five_minute_model = "momentum_continuation"
    if phase == "midday" and continuation:
      adjust(-6, "Midday continuation requires exceptional volume")
    if phase == "power_hour" and continuation:
      adjust(4, "Power-hour continuation window")

  current_bounds = bounds(timeframe, settings.get("mode", "normal"), symbol)
  buffer = max(0.03, latest["atr"] * (0.1 if timeframe == 5 else 0.08))
  if long:
    entry = max(latest["high"] + buffer, latest["close"] + 0.01)
    stop = min(latest["low"], latest["ema20"], local["support"]) - latest["atr"] * 0.2
  else:
    entry = min(latest["low"] - buffer, latest["close"] - 0.01)
    stop = max(latest["high"], latest["ema20"], local["resistance"]) + latest["atr"] * 0.2
  risk = abs(entry - stop)
  structural_risk_too_wide = risk > min(latest["atr"] * current_bounds["maxRiskAtr"], entry * current_bounds["maxRiskPct"])
  if structural_risk_too_wide:
    adjust(-14, "Structural risk too wide")
    reasons.append("Structural invalidation is wider than this timeframe risk limit")

  minimum = entry * current_bounds["target1MinPct"]
  maximum = entry * current_bounds["target1MaxPct"]
  maximum2 = entry * current_bounds["target2MaxPct"]
  if timeframe == 5:
    # Keep 5m targets tied to current volatility while retaining the configured QQQ move limits.
    target_move = clamp(max(risk * 1.15, latest["atr"] * 0.75, minimum), minimum, maximum)
    target2_move = clamp(max(risk * 1.7, latest["atr"] * 1.15, target_move * 1.35), target_move, maximum2)
  else:
    target_move = clamp(max(risk * 1.05, minimum), minimum, maximum)
    target2_move = clamp(max(risk * 1.5, maximum), maximum, maximum2)
  target = entry + target_move if long else entry - target_move
  target2 = entry + target2_move if long else entry - target2_move
  risk_reward = target_move / risk if risk else 0
  if risk_reward >= 1.05:
    adjust(8, "Acceptable reward/risk")
    reasons.append("Target 1 offers acceptable reward/risk")
  if risk_reward < 0.85:
    adjust(-22, "Weak reward/risk")
    reasons.append("Reward/risk is weak")
  elif risk_reward < 1.05:
    adjust(-8, "Marginal reward/risk")
    reasons.append("Reward/risk is marginal")
  shadow_adjustment = adaptive_adjustment(kind, timeframe, phase, performance, [])
  learning_mode = (settings.get("learning") or {}).get("mode", "shadow")
  if shadow_adjustment and learning_mode == "approved_live":
    adjust(shadow_adjustment, "Approved forward outcome calibration")
  execution_quality_state = execution_quality(entry, stop, latest["atr"], timeframe, settings, symbol)
  if execution_quality_state["blockers"]:
    score -= 20
    reasons.extend(execution_quality_state["blockers"])
    contribution_rows.append({"label": "Execution quality block", "points": -20})
  normalized_score = int(clamp(round(50 + (score - 50) * 0.68), 0, 95))
  exit_rules = [
    "Take partial profit near Target 1",
    f"Exit if price closes {'below' if long else 'above'} invalidation",
    f"Trail remainder {'below' if long else 'above'} EMA 20 or VWAP after Target 1",
  ]
  return {
    "setup": candidate["setup"],
    "setupType": kind,
    "direction": direction,
    "score": normalized_score,
    "rawScore": round(score),
    "scoreContributions": contribution_rows,
    "reasons": reasons,
    "entry": entry,
    "stop": stop,
    "target": target,
    "target2": target2,
    "riskReward": risk_reward,
    "watchOnly": structural_risk_too_wide or risk_reward < 0.85 or bool(execution_quality_state["blockers"]) or (continuation and extension > 1.8) or (timeframe == 5 and continuation and execution["available"] and not execution["aligned"]),
    "marketPhase": phase,
    "executionConfirmation": execution,
    "executionQuality": execution_quality_state,
    "fiveMinuteModel": five_minute_model,
    "shadowModel": {
      "status": "shadow" if learning_mode != "approved_live" else "approved_live",
      "suggestedScoreAdjustment": shadow_adjustment,
      "appliedToProduction": learning_mode == "approved_live",
    },
    "exitWarning": f"For {direction}: scale at T1, trail {'below' if long else 'above'} EMA 20/VWAP",
    "exitRules": exit_rules,
  }


def neutral(reason, timeframe, trends):
  return {
    "setup": "No high-probability trade",
    "direction": "neutral",
    "score": 0,
    "reasons": [reason],
    "entry": None,
    "stop": None,
    "target": None,
    "target2": None,
    "riskReward": None,
    "watchOnly": True,
    "exitWarning": "No active trade plan",
    "exitRules": ["Wait for a confirmed setup with clean execution quality"],
    "timeframe": timeframe,
    **trends,
    "bestLong": None,
    "bestShort": None,
    "biasScore": 0,
  }


def daily_candle_is_closed(candle, now, symbol=DEFAULT_SYMBOL):
  candle_date = market_parts(candle["time"], symbol)[0]
  if is_continuous_market(symbol):
    return candle_date < datetime.fromtimestamp(now / 1000, timezone.utc).strftime("%Y-%m-%d")
  current = datetime.fromtimestamp(now / 1000, market_timezone(symbol))
  current_date = current.strftime("%Y-%m-%d")
  if candle_date < current_date:
    return True
  _, regular_close = regular_session_minutes(symbol)
  return candle_date == current_date and market_session(now, symbol)["regular"] is False and current.hour * 60 + current.minute >= regular_close + 5


def classify_daily_trend(values):
  if len(values) < 160:
    return {"label": "Building", "tone": "neutral"}
  latest = values[-1]
  prior_week = values[-6]
  prior_month = values[-21]
  required = (latest.get("ema20"), latest.get("ema50"), latest.get("sma150"), latest.get("rsi"), prior_week.get("ema20"))
  if any(value is None for value in required):
    return {"label": "Building", "tone": "neutral"}
  score = 0
  score += 1 if latest["close"] > latest["ema20"] else -1
  score += 1 if latest["close"] > latest["ema50"] else -1
  score += 1 if latest["close"] > latest["sma150"] else -1
  score += 1 if latest["ema20"] > prior_week["ema20"] else -1
  score += 1 if latest["ema50"] > prior_month["ema50"] else -1
  score += 1 if latest["rsi"] >= 55 else -1 if latest["rsi"] <= 45 else 0
  score += 1 if latest["close"] > prior_week["close"] else -1
  score += 1 if latest["close"] > prior_month["close"] else -1
  if score >= 5:
    return {"label": "Strong up", "tone": "positive"}
  if score >= 2:
    return {"label": "Up", "tone": "positive"}
  if score <= -5:
    return {"label": "Strong down", "tone": "negative"}
  if score <= -2:
    return {"label": "Down", "tone": "negative"}
  return {"label": "Mixed", "tone": "neutral"}


def score_daily_candidate(candidate, values, levels, trend, settings, performance, symbol=DEFAULT_SYMBOL):
  latest = values[-1]
  previous = values[-2]
  prior_week = values[-6]
  prior_month = values[-21]
  long = candidate["direction"] == "long"
  tone = "positive" if long else "negative"
  reasons = list(candidate["reasons"])
  score = candidate["baseScore"]
  contribution_rows = [{"label": "Daily setup structure", "points": int(candidate["baseScore"])}]
  shape = candle_shape(latest)
  kind = setup_type(candidate["setup"])
  profile = asset_profile(symbol)
  extension = atr_extension(latest, candidate["direction"])
  ema20_rising = latest["ema20"] > prior_week["ema20"]
  five_day_return = latest["close"] / prior_week["close"] - 1
  twenty_day_return = latest["close"] / prior_month["close"] - 1
  checks = (
    (trend["tone"] == tone, 16, "Daily trend agrees with the trade direction"),
    ((latest["ema20"] > latest["ema50"]) if long else (latest["ema20"] < latest["ema50"]), 12, "Daily EMA 20/50 structure agrees"),
    ((latest["close"] > latest["sma150"]) if long else (latest["close"] < latest["sma150"]), 10, "Price is on the momentum side of SMA 150"),
    ((52 <= latest["rsi"] <= 74) if long else (26 <= latest["rsi"] <= 48), 10, "Daily RSI is in a sustainable momentum zone"),
    ((ema20_rising and long) or (not ema20_rising and not long), 10, "EMA 20 slope supports continuation"),
    ((five_day_return > 0) if long else (five_day_return < 0), 8, "Five-day price momentum agrees"),
    ((twenty_day_return > 0) if long else (twenty_day_return < 0), 8, "Twenty-day price momentum agrees"),
    ((shape["bullish"] if long else shape["bearish"]) and shape["bodyPct"] >= 0.35, 8, "Daily confirmation candle has directional body"),
    (profile["reliableVolume"] and (latest.get("relativeVolume") or 0) >= 1.0, 6, "Daily volume is at or above its recent average"),
  )
  for condition, points, reason in checks:
    if condition:
      score += points
      reasons.append(reason)
      contribution_rows.append({"label": reason, "points": int(points)})
  if kind in {"momentum", "breakout", "breakdown", "ema_pullback"} and extension > 1.75:
    score -= 8
    reasons.append(f"Daily close is already {extension:.1f} ATR beyond EMA 20; wait for a better location")
    contribution_rows.append({"label": "Daily extension penalty", "points": -8})

  buffer = max(0.05, latest["atr"] * 0.08)
  if long:
    entry = latest["high"] + buffer
    structural = max(latest["low"], latest["ema20"], levels["support"])
    stop = structural - latest["atr"] * 0.18
  else:
    entry = latest["low"] - buffer
    structural = min(latest["high"], latest["ema20"], levels["resistance"])
    stop = structural + latest["atr"] * 0.18
  risk = abs(entry - stop)
  risk_limit = min(latest["atr"] * profile["dailyRiskAtr"], entry * profile["dailyRiskPct"])
  structural_risk_too_wide = risk <= 0 or risk > risk_limit
  if structural_risk_too_wide:
    score -= 16
    reasons.append("Daily invalidation is wider than the swing risk limit")
    contribution_rows.append({"label": "Swing risk too wide", "points": -16})

  scale = {"scalp": 0.9, "normal": 1, "strict": 1.1}.get(settings.get("mode", "normal"), 1)
  minimum = entry * profile["dailyTargetMinPct"] * scale
  maximum = entry * profile["dailyTargetMaxPct"] * scale
  maximum2 = entry * profile["dailyTarget2MaxPct"] * scale
  target_move = clamp(max(risk * 1.2, minimum), minimum, maximum)
  target2_move = clamp(max(risk * 1.8, target_move * 1.45), target_move, maximum2)
  target = entry + target_move if long else entry - target_move
  target2 = entry + target2_move if long else entry - target2_move
  risk_reward = target_move / risk if risk > 0 else 0
  if risk_reward >= 1.2:
    score += 10
    reasons.append("Swing Target 1 offers at least 1.2R")
    contribution_rows.append({"label": "Swing reward/risk", "points": 10})
  elif risk_reward < 1:
    score -= 18
    reasons.append("Swing reward/risk is below 1R")
    contribution_rows.append({"label": "Weak swing reward/risk", "points": -18})

  shadow_adjustment = adaptive_adjustment(kind, DAILY_TIMEFRAME, "swing", performance, [])
  learning_mode = (settings.get("learning") or {}).get("mode", "shadow")
  if shadow_adjustment and learning_mode == "approved_live":
    score += shadow_adjustment
    contribution_rows.append({"label": "Approved forward outcome calibration", "points": int(shadow_adjustment)})
  normalized_score = int(clamp(round(50 + (score - 50) * 0.68), 0, 95))
  execution_quality_state = execution_quality(entry, stop, latest["atr"], DAILY_TIMEFRAME, settings, symbol)
  return {
    "setup": candidate["setup"],
    "setupType": kind,
    "direction": candidate["direction"],
    "score": normalized_score,
    "rawScore": round(score),
    "scoreContributions": contribution_rows,
    "shadowModel": {
      "status": "shadow" if learning_mode != "approved_live" else "approved_live",
      "suggestedScoreAdjustment": shadow_adjustment,
      "appliedToProduction": learning_mode == "approved_live",
    },
    "reasons": reasons,
    "entry": entry,
    "stop": stop,
    "target": target,
    "target2": target2,
    "riskReward": risk_reward,
    "executionQuality": execution_quality_state,
    "watchOnly": structural_risk_too_wide or risk_reward < 1 or (kind in {"momentum", "breakout", "breakdown", "ema_pullback"} and extension > 5.5),
    "marketPhase": "swing",
    "holdingPeriod": "multi-day swing",
    "exitWarning": f"For {'long' if long else 'short'} swing: reduce at T1 and trail against daily EMA 20",
    "exitRules": [
      "Take partial profit near swing Target 1",
      f"Exit on a daily close {'below' if long else 'above'} invalidation",
      f"Trail the remainder {'below' if long else 'above'} daily EMA 20 after Target 1",
      "Reassess if momentum has not followed through within five trading days",
    ],
  }


def analyze_daily(raw_candles, settings=None, performance=None, now=None, intraday_context=None, symbol=DEFAULT_SYMBOL):
  settings = settings or {}
  performance = performance or {}
  now = int(now or datetime.now().timestamp() * 1000)
  closed = [candle for candle in merge_candles(raw_candles) if daily_candle_is_closed(candle, now, symbol)]
  values = indicators(closed, symbol)
  return build_daily_signal(values, settings, performance, intraday_context, symbol)


def build_daily_signal(values, settings=None, performance=None, intraday_context=None, symbol=DEFAULT_SYMBOL):
  settings = settings or {}
  performance = performance or {}
  intraday_context = intraday_context or {}
  fallback_trend = {"label": "Building", "tone": "neutral"}
  trend_context = {
    "trend1": intraday_context.get("trend1", fallback_trend),
    "trend5": intraday_context.get("trend5", fallback_trend),
    "trend15": intraday_context.get("trend15", fallback_trend),
  }
  selected_trend = classify_daily_trend(values)
  context = {
    **trend_context,
    "selectedTrend": selected_trend,
    "regime": {
      "label": "Daily momentum",
      "tone": selected_trend["tone"],
      "type": "swing",
      "detail": "Closed daily candles with EMA 20/50, SMA 150, RSI, ATR, volume, and 5/20-day momentum",
    },
  }
  if len(values) < 160:
    return neutral("Waiting for at least 160 closed daily candles to score a swing setup.", DAILY_TIMEFRAME, context)
  latest = values[-1]
  previous = values[-2]
  if any(latest.get(key) is None for key in ("ema20", "ema50", "sma150", "rsi", "atr")):
    return neutral("Daily swing indicators are still building.", DAILY_TIMEFRAME, context)
  levels = recent_levels(values, 21)
  if not levels:
    return neutral("Daily support and resistance are unavailable.", DAILY_TIMEFRAME, context)

  prior = values[-21:-1]
  resistance = max(item["high"] for item in prior)
  support = min(item["low"] for item in prior)
  shape = candle_shape(latest)
  ema20_rising = latest["ema20"] > values[-6]["ema20"]
  bullish_structure = latest["close"] > latest["ema20"] > latest["ema50"] and latest["close"] > latest["sma150"]
  bearish_structure = latest["close"] < latest["ema20"] < latest["ema50"] and latest["close"] < latest["sma150"]
  bullish_momentum = latest["close"] > latest["ema20"] and ema20_rising and latest["close"] > previous["close"] and 52 <= latest["rsi"] <= 74
  bearish_momentum = latest["close"] < latest["ema20"] and not ema20_rising and latest["close"] < previous["close"] and 26 <= latest["rsi"] <= 48
  conditions = (
    (latest["close"] > latest["ema20"] and latest["close"] > resistance, "long", "20-day breakout", 30, "Daily close broke above 20-day resistance"),
    (bullish_structure and latest["low"] <= latest["ema20"] < latest["close"] and shape["bullish"], "long", "EMA 20 pullback", 27, "Daily pullback held a rising EMA 20"),
    (bullish_momentum, "long", "momentum continuation", 23, "Bullish daily structure continues with positive price momentum"),
    (latest["low"] <= support + latest["atr"] * 0.35 and shape["lowerWickPct"] >= 0.35 and latest["close"] > previous["high"], "long", "support reversal", 20, "Daily candle rejected 20-day support"),
    (latest["close"] < latest["ema20"] and latest["close"] < support, "short", "20-day breakdown", 30, "Daily close broke below 20-day support"),
    (bearish_structure and latest["high"] >= latest["ema20"] > latest["close"] and shape["bearish"], "short", "EMA 20 rejection", 27, "Daily rebound rejected a falling EMA 20"),
    (bearish_momentum, "short", "momentum continuation", 23, "Bearish daily structure continues with negative price momentum"),
    (latest["high"] >= resistance - latest["atr"] * 0.35 and shape["upperWickPct"] >= 0.35 and latest["close"] < previous["low"], "short", "resistance reversal", 20, "Daily candle rejected 20-day resistance"),
  )
  candidates = []
  for enabled, direction, name, base_score, reason in conditions:
    if enabled:
      candidates.append(score_daily_candidate({
        "setup": f"{direction.title()} 1D {name}",
        "direction": direction,
        "baseScore": base_score,
        "reasons": [reason],
      }, values, levels, selected_trend, settings, performance, symbol))
  candidates.sort(key=lambda item: (item["score"], item["riskReward"]), reverse=True)
  best_long = next((item for item in candidates if item["direction"] == "long"), None)
  best_short = next((item for item in candidates if item["direction"] == "short"), None)
  best = candidates[0] if candidates else None
  threshold = int(settings.get("activeTradeThreshold", 62)) + {"scalp": -6, "normal": 0, "strict": 8}.get(settings.get("mode", "normal"), 0)
  if not best or best["watchOnly"] or best["score"] < threshold:
    signal = neutral("No daily long or short momentum setup is confirmed right now.", DAILY_TIMEFRAME, context)
  else:
    signal = {**best, "timeframe": DAILY_TIMEFRAME, **context}
  signal["bestLong"] = best_long
  signal["bestShort"] = best_short
  signal["biasScore"] = (best_long["score"] - best_short["score"]) if best_long and best_short else round(best_long["score"] * 0.5) if best_long else -round(best_short["score"] * 0.5) if best_short else 0
  signal["signalCandleTime"] = latest["time"]
  signal["actionableAt"] = latest["time"] + DAILY_TIMEFRAME * MINUTE_MS
  signal["latestIndicator"] = latest
  signal["dataQuality"] = "clean"
  return signal


def analyze_all(raw_candles, settings=None, performance=None, now=None, five_minute_candles=None, symbol=DEFAULT_SYMBOL):
  settings = settings or {}
  performance = performance or {}
  now = int(now or datetime.now().timestamp() * 1000)
  candles = merge_candles(raw_candles)
  closed_one = closed_for_timeframe(candles, 1, now)
  current_day = today_candles(closed_one, symbol)
  recent_regular = [candle for candle in current_day if market_session(candle["time"], symbol)["regular"]][-45:]
  gap_limit = 3 * MINUTE_MS if is_continuous_market(symbol) else 90_000
  recent_gaps = sum(
    recent_regular[index]["time"] - recent_regular[index - 1]["time"] > gap_limit
    for index in range(1, len(recent_regular))
  )
  gap_is_material = recent_gaps >= 2 if is_continuous_market(symbol) or is_tel_aviv_market(symbol) else recent_gaps > 0
  quality_issues = [f"{recent_gaps} recent data gap{'s' if recent_gaps != 1 else ''}"] if gap_is_material else []
  if market_session(now, symbol)["regular"] and (not closed_one or now - closed_one[-1]["time"] > 4 * MINUTE_MS):
    quality_issues.append("market data is stale")
  trend_values = {}
  trends = {}
  for timeframe in TIMEFRAMES:
    values = indicators(closed_for_timeframe(current_day, timeframe, now), symbol)
    trend_values[timeframe] = values
    trends[timeframe] = classify_trend(values)
  session = session_levels(closed_one, symbol=symbol)
  regime = classify_market_regime(trend_values[1])
  output = {}

  for timeframe in TIMEFRAMES:
    source = five_minute_candles if timeframe in {5, 15} and five_minute_candles else candles
    selected = indicators(closed_for_timeframe(source, timeframe, now), symbol)
    output[timeframe] = build_intraday_signal(
      selected, timeframe, trends, regime, session, settings, performance, quality_issues, symbol,
      execution_values=trend_values[1],
    )
  return output


def build_intraday_signal(selected, timeframe, trends, regime, session, settings=None, performance=None, quality_issues=None, symbol=DEFAULT_SYMBOL, execution_values=None):
  settings = settings or {}
  performance = performance or {}
  quality_issues = quality_issues or []
  trend_context = {
    "trend1": trends.get(1, {"label": "Building", "tone": "neutral"}),
    "trend5": trends.get(5, {"label": "Building", "tone": "neutral"}),
    "trend15": trends.get(15, {"label": "Building", "tone": "neutral"}),
    "selectedTrend": trends.get(timeframe, {"label": "Building", "tone": "neutral"}),
    "regime": regime,
  }
  if len(selected) < 25:
    return neutral("Waiting for enough closed candles to score an intraday setup.", timeframe, trend_context)
  latest = selected[-1]
  previous = selected[-2]
  if any(latest.get(key) is None for key in ("ema20", "ema50", "vwap", "rsi", "atr")):
    return neutral("Indicators are still building.", timeframe, trend_context)
  current_bounds = bounds(timeframe, settings.get("mode", "normal"), symbol)
  levels = recent_levels(selected, current_bounds["lookback"])
  if not levels:
    return neutral("Recent support and resistance are unavailable.", timeframe, trend_context)
  shape = candle_shape(latest)
  reference_levels = prior_session_levels(selected, symbol) if timeframe == 5 else {}
  session = {**session, **reference_levels}
  five_minute_filters = five_minute_no_trade_filters(latest, regime, symbol) if timeframe == 5 else []
  execution_long = execution_confirmation(execution_values, "long") if timeframe == 5 else {"available": False, "aligned": None}
  execution_short = execution_confirmation(execution_values, "short") if timeframe == 5 else {"available": False, "aligned": None}
  long_confirmation = trend_confirmation(trends, timeframe, "long")
  short_confirmation = trend_confirmation(trends, timeframe, "short")
  bullish_context = long_confirmation["aligned"] >= 1
  bearish_context = short_confirmation["aligned"] >= 1
  bullish_continuation = long_confirmation["aligned"] >= 2
  bearish_continuation = short_confirmation["aligned"] >= 2
  near_support = latest["low"] <= levels["support"] + latest["atr"] * 0.45
  near_resistance = latest["high"] >= levels["resistance"] - latest["atr"] * 0.45
  reclaim_vwap = previous.get("vwap") is not None and previous["close"] <= previous["vwap"] and latest["close"] > latest["vwap"]
  lose_vwap = previous.get("vwap") is not None and previous["close"] >= previous["vwap"] and latest["close"] < latest["vwap"]
  opening_high = session.get("opening15High")
  opening_low = session.get("opening15Low")
  opening_range_long = timeframe == 5 and opening_high is not None and previous["close"] <= opening_high < latest["close"]
  opening_range_short = timeframe == 5 and opening_low is not None and previous["close"] >= opening_low > latest["close"]
  prior_day_high = session.get("priorDayHigh")
  prior_day_low = session.get("priorDayLow")
  premarket_high = session.get("premarketHigh")
  premarket_low = session.get("premarketLow")
  failed_breakout_short = timeframe == 5 and latest["high"] > levels["resistance"] and latest["close"] < levels["resistance"] and shape["upperWickPct"] >= 0.35
  failed_breakdown_long = timeframe == 5 and latest["low"] < levels["support"] and latest["close"] > levels["support"] and shape["lowerWickPct"] >= 0.35
  conditions = (
    (opening_range_long and bullish_continuation, "long", "15m opening range breakout", 30, "Price closed above the completed 15-minute opening range with aligned momentum"),
    (timeframe == 5 and prior_day_high is not None and previous["close"] <= prior_day_high < latest["close"] and bullish_continuation, "long", "prior day high breakout", 28, "Price closed above prior-day resistance with aligned momentum"),
    (timeframe == 5 and premarket_high is not None and previous["close"] <= premarket_high < latest["close"] and bullish_continuation, "long", "premarket high breakout", 26, "Price closed above the premarket high with aligned momentum"),
    (compression_breakout(selected, "long") and bullish_continuation, "long", "compression breakout", 26, "A compact 5m range expanded upward with aligned momentum"),
    (failed_breakdown_long and bullish_context, "long", "failed breakdown reversal", 24, "Price reclaimed broken support after a failed downside break"),
    (bullish_continuation and latest["close"] > latest["vwap"] and latest["low"] <= latest["ema20"] < latest["close"], "long", "EMA 20 pullback", 24, "Pullback held the EMA 20/VWAP area"),
    (latest["close"] > levels["resistance"] and bullish_continuation, "long", "breakout", 28, "Price broke above recent resistance with multi-timeframe confirmation"),
    (reclaim_vwap and latest["close"] > latest["ema20"], "long", "VWAP reclaim", 20, "Price reclaimed VWAP and closed above EMA 20"),
    (near_support and shape["lowerWickPct"] >= 0.35 and latest["close"] > previous["high"] and latest["rsi"] > previous["rsi"], "long", "support reversal", 18, "Price rejected support with improving RSI"),
    (bullish_continuation and trends[timeframe]["tone"] == "positive" and latest["close"] > latest["ema20"] and 50 <= latest["rsi"] <= 78, "long", "momentum continuation", 18, "Current momentum is aligned across timeframes for a small upside continuation"),
    (opening_range_short and bearish_continuation, "short", "15m opening range breakdown", 30, "Price closed below the completed 15-minute opening range with aligned momentum"),
    (timeframe == 5 and prior_day_low is not None and previous["close"] >= prior_day_low > latest["close"] and bearish_continuation, "short", "prior day low breakdown", 28, "Price closed below prior-day support with aligned momentum"),
    (timeframe == 5 and premarket_low is not None and previous["close"] >= premarket_low > latest["close"] and bearish_continuation, "short", "premarket low breakdown", 26, "Price closed below the premarket low with aligned momentum"),
    (compression_breakout(selected, "short") and bearish_continuation, "short", "compression breakdown", 26, "A compact 5m range expanded downward with aligned momentum"),
    (failed_breakout_short and bearish_context, "short", "failed breakout reversal", 24, "Price rejected broken resistance after a failed upside break"),
    (bearish_continuation and latest["close"] < latest["vwap"] and latest["high"] >= latest["ema20"] > latest["close"], "short", "EMA 20 pullback", 24, "Pullback rejected the EMA 20/VWAP area"),
    (latest["close"] < levels["support"] and bearish_continuation, "short", "breakdown", 28, "Price broke below recent support with multi-timeframe confirmation"),
    (lose_vwap and latest["close"] < latest["ema20"], "short", "VWAP loss", 20, "Price lost VWAP and closed below EMA 20"),
    (near_resistance and shape["upperWickPct"] >= 0.35 and latest["close"] < previous["low"] and latest["rsi"] < previous["rsi"], "short", "resistance reversal", 18, "Price rejected resistance with weakening RSI"),
    (bearish_continuation and trends[timeframe]["tone"] == "negative" and latest["close"] < latest["ema20"] and 18 <= latest["rsi"] <= 50, "short", "momentum continuation", 18, "Current momentum is aligned across timeframes for a small downside continuation"),
  )
  candidates = []
  for enabled, direction, name, base_score, reason in conditions:
    if not enabled:
      continue
    candidate = {"setup": f"{direction.title()} {timeframe}m {name}", "baseScore": base_score, "reasons": [reason]}
    context = {
      "latest": latest,
      "previous": previous,
      "direction": direction,
      "shape": shape,
      "levels": levels,
      "timeframe": timeframe,
      "trend5": trends[5],
      "trend15": trends[15],
      "selectedTrend": trends[timeframe],
      "trends": trends,
      "regime": regime,
      "session": session,
      "execution": execution_long if direction == "long" else execution_short,
    }
    candidates.append(score_candidate(candidate, context, settings, performance, symbol))
  if five_minute_filters:
    for candidate in candidates:
      candidate["watchOnly"] = True
      candidate["reasons"].extend(five_minute_filters)
  candidates.sort(key=lambda item: (item["score"], item["riskReward"]), reverse=True)
  best_long = next((item for item in candidates if item["direction"] == "long"), None)
  best_short = next((item for item in candidates if item["direction"] == "short"), None)
  best = candidates[0] if candidates else None
  threshold = int(settings.get("activeTradeThreshold", 62)) + {"scalp": -6, "normal": 0, "strict": 8}.get(settings.get("mode", "normal"), 0)
  market = market_session(latest["time"], symbol)
  outside_session = settings.get("sessionMode", "regular") == "regular" and not market["regular"]
  if not best or best["watchOnly"] or best["score"] < threshold or outside_session or quality_issues:
    reason = "Alerts are paused outside regular market hours" if outside_session else f"Alerts are paused until data quality is clean: {', '.join(quality_issues)}" if quality_issues else "; ".join(five_minute_filters) if five_minute_filters else "No long or short setup is confirmed right now"
    signal = neutral(reason, timeframe, trend_context)
  else:
    signal = {**best, "timeframe": timeframe, **trend_context}
  signal["bestLong"] = best_long
  signal["bestShort"] = best_short
  signal["biasScore"] = (best_long["score"] - best_short["score"]) if best_long and best_short else round(best_long["score"] * 0.5) if best_long else -round(best_short["score"] * 0.5) if best_short else 0
  signal["signalCandleTime"] = latest["time"]
  signal["actionableAt"] = latest["time"] + timeframe * MINUTE_MS
  signal["latestIndicator"] = latest
  signal["dataQuality"] = ",".join(quality_issues) if quality_issues else "clean"
  return signal


def analyze_intraday_timeframe(raw_candles, timeframe, settings=None, performance=None, now=None, source_timeframe=1, symbol=DEFAULT_SYMBOL):
  if timeframe not in TIMEFRAMES or source_timeframe not in {1, 5}:
    raise ValueError("unsupported replay timeframe")
  settings = settings or {}
  now = int(now or datetime.now().timestamp() * 1000)
  source = merge_candles(raw_candles)
  closed_source = [candle for candle in source if candle["time"] + source_timeframe * MINUTE_MS + 2_000 <= now]
  current_day = today_candles(closed_source, symbol)
  trend_values = {
    1: indicators(current_day, symbol) if source_timeframe == 1 else [],
    5: indicators(current_day if source_timeframe == 5 else resample(current_day, 5), symbol),
    15: indicators(resample(current_day, 15), symbol),
  }
  trends = {key: classify_trend(values) for key, values in trend_values.items()}
  selected_source = current_day if timeframe == source_timeframe else resample(current_day, timeframe)
  selected = indicators(selected_source, symbol)
  regime_source = trend_values[1] if trend_values[1] else trend_values[5]
  regime = classify_market_regime(regime_source)
  return build_intraday_signal(
    selected,
    timeframe,
    trends,
    regime,
    session_levels(closed_source, source_timeframe, symbol),
    settings,
    performance,
    [],
    symbol,
    execution_values=trend_values[1],
  )
