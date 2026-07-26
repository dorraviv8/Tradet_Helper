"""Options-opportunity selection and contract ranking.

This module never places trades. It converts an already-confirmed underlying
plan into either strike/DTE guidance or a filtered contract candidate.
"""

import math
from datetime import datetime, timedelta, timezone


DAILY_TIMEFRAME = 1440
MIN_SCORE = 80
TARGET_DELTA = 0.62
MIN_DELTA = 0.55
MAX_DELTA = 0.70
MAX_SPREAD_PCT = 0.10
MIN_OPEN_INTEREST = 500
MIN_VOLUME = 100
MAX_QUOTE_AGE_MS = 30 * 60 * 1000

OPTION_PROFILES = {
  "QQQ": {
    "optionSymbol": "QQQ",
    "underlyingLabel": "QQQ",
    "requiresRegularSession": False,
    "dteProfiles": {
      5: {"min": 7, "max": 14, "target": 10},
      15: {"min": 10, "max": 21, "target": 14},
      DAILY_TIMEFRAME: {"min": 14, "max": 35, "target": 28},
    },
  },
  "SPY": {
    "optionSymbol": "SPY",
    "underlyingLabel": "SPY",
    "requiresRegularSession": False,
    "dteProfiles": {
      5: {"min": 7, "max": 14, "target": 10},
      15: {"min": 10, "max": 21, "target": 14},
      DAILY_TIMEFRAME: {"min": 14, "max": 35, "target": 28},
    },
  },
  "BTC-USD": {
    "optionSymbol": "IBIT",
    "underlyingLabel": "BTC-USD",
    "requiresRegularSession": True,
    "dteProfiles": {
      5: {"min": 10, "max": 21, "target": 14},
      15: {"min": 14, "max": 30, "target": 21},
      DAILY_TIMEFRAME: {"min": 21, "max": 45, "target": 35},
    },
  },
}


def option_profile(symbol):
  return OPTION_PROFILES.get(str(symbol or "QQQ").upper())


def option_symbol(symbol):
  profile = option_profile(symbol)
  return profile.get("optionSymbol") if profile else None


def finite_number(value):
  try:
    number = float(value)
  except (TypeError, ValueError):
    return None
  return number if math.isfinite(number) else None


def none_opportunity(detail=None, symbol="QQQ"):
  profile = option_profile(symbol)
  underlying = profile.get("underlyingLabel") if profile else symbol
  contract_symbol = profile.get("optionSymbol") if profile else None
  detail = detail or f"No strong {underlying} options opportunity is confirmed."
  return {
    "status": "none",
    "symbol": symbol,
    "underlyingSymbol": underlying,
    "optionSymbol": contract_symbol,
    "detail": detail,
    "generatedAt": None,
    "signalKey": None,
  }


def _direction_tone(direction):
  return "positive" if direction == "long" else "negative"


def _valid_plan_prices(signal):
  values = {
    key: finite_number(signal.get(key))
    for key in ("entry", "stop", "target", "target2")
  }
  if any(value is None or value <= 0 for value in values.values()):
    return False
  if signal.get("direction") == "long":
    return values["stop"] < values["entry"] < values["target"] <= values["target2"]
  return values["stop"] > values["entry"] > values["target"] >= values["target2"]


def signal_blockers(signal, timeframe, regular_session, symbol="QQQ"):
  profile = option_profile(symbol)
  blockers = []
  direction = str(signal.get("direction") or "")
  if not profile:
    blockers.append("options are not configured for this asset")
  elif timeframe not in profile["dteProfiles"]:
    blockers.append("unsupported timeframe")
  if direction not in {"long", "short"}:
    blockers.append("no directional signal")
  if signal.get("watchOnly"):
    blockers.append("watch-only underlying plan")
  if int(signal.get("score") or 0) < MIN_SCORE:
    blockers.append(f"score below {MIN_SCORE}")
  if str(signal.get("dataQuality") or "clean").lower() != "clean":
    blockers.append("underlying data quality is not clean")
  risk_reward = finite_number(signal.get("riskReward"))
  if risk_reward is None or risk_reward < 1.0:
    blockers.append("underlying reward relative to risk is too low")
  if direction in {"long", "short"} and not _valid_plan_prices(signal):
    blockers.append("underlying price levels are invalid")

  regime_type = str((signal.get("regime") or {}).get("type") or "mixed")
  if direction == "long" and regime_type == "trend_down":
    blockers.append("market regime opposes a CALL")
  if direction == "short" and regime_type == "trend_up":
    blockers.append("market regime opposes a PUT")
  setup_type = str(signal.get("setupType") or "")
  if setup_type in {"momentum", "breakout", "breakdown", "ema_pullback"} and regime_type in {"range", "chop"}:
    blockers.append("market regime does not support momentum follow-through")

  if profile and profile.get("requiresRegularSession") and not regular_session:
    blockers.append(f"{profile['optionSymbol']} options ideas require the US regular session")
  if timeframe in {5, 15}:
    if not regular_session:
      blockers.append("intraday options ideas require the regular session")
    expected_tone = _direction_tone(direction)
    if (signal.get("trend5") or {}).get("tone") != expected_tone:
      blockers.append("5m trend is not aligned")
    if (signal.get("trend15") or {}).get("tone") != expected_tone:
      blockers.append("15m trend is not aligned")
  return blockers


def select_underlying_signal(recommendations, regular_session, symbol="QQQ"):
  candidates = []
  diagnostics = {}
  for timeframe in (5, 15, DAILY_TIMEFRAME):
    signal = (recommendations or {}).get(timeframe)
    if signal is None:
      signal = (recommendations or {}).get(str(timeframe))
    if not isinstance(signal, dict):
      diagnostics[str(timeframe)] = ["analysis unavailable"]
      continue
    blockers = signal_blockers(signal, timeframe, regular_session, symbol)
    diagnostics[str(timeframe)] = blockers
    if blockers:
      continue
    candidates.append((timeframe, signal))

  if not candidates:
    result = none_opportunity(symbol=symbol)
    result["diagnostics"] = diagnostics
    return None, result

  candidates.sort(
    key=lambda item: (
      int(item[1].get("score") or 0),
      finite_number(item[1].get("riskReward")) or 0,
      1 if item[0] == 15 else 0,
    ),
    reverse=True,
  )
  timeframe, signal = candidates[0]
  return (timeframe, signal), None


def _expiration_date(generated_at, dte):
  moment = datetime.fromtimestamp(generated_at / 1000, tz=timezone.utc)
  expiration = moment.date() + timedelta(days=int(dte))
  if expiration.weekday() == 5:
    expiration -= timedelta(days=1)
  elif expiration.weekday() == 6:
    expiration -= timedelta(days=2)
  return expiration.isoformat()


def _signal_key(timeframe, signal, symbol):
  entry = finite_number(signal.get("entry")) or 0
  signal_time = int(signal.get("signalCandleTime") or signal.get("actionableAt") or 0)
  setup = str(signal.get("setupType") or signal.get("setup") or "setup").replace("|", "-")
  return "|".join((
    f"{symbol}-option",
    str(timeframe),
    str(signal.get("direction")),
    setup,
    str(signal_time),
    str(round(entry * 20)),
  ))


def build_guidance(timeframe, signal, plan_id=None, generated_at=None, underlying_price=None, option_price=None, symbol="QQQ"):
  generated_at = int(generated_at or datetime.now(tz=timezone.utc).timestamp() * 1000)
  asset = option_profile(symbol)
  if not asset or timeframe not in asset["dteProfiles"]:
    raise ValueError(f"options are not configured for {symbol} timeframe {timeframe}")
  profile = dict(asset["dteProfiles"][timeframe])
  direction = signal["direction"]
  side = "call" if direction == "long" else "put"
  entry = finite_number(signal.get("entry"))
  underlying_spot = finite_number(underlying_price) or entry
  contract_spot = finite_number(option_price) or underlying_spot
  strike_low = contract_spot * (0.99 if side == "call" else 1.0)
  strike_high = contract_spot * (1.0 if side == "call" else 1.01)
  target1 = finite_number(signal.get("target"))
  target2 = finite_number(signal.get("target2"))
  stop = finite_number(signal.get("stop"))
  return {
    "status": "guidance",
    "symbol": symbol,
    "underlyingSymbol": asset["underlyingLabel"],
    "optionSymbol": asset["optionSymbol"],
    "signalKey": _signal_key(timeframe, signal, symbol),
    "generatedAt": generated_at,
    "planId": plan_id,
    "timeframe": timeframe,
    "direction": direction,
    "side": side,
    "sideLabel": side.upper(),
    "score": int(signal.get("score") or 0),
    "setup": str(signal.get("setup") or "Momentum setup"),
    "setupType": str(signal.get("setupType") or "unknown"),
    "detail": (
      f"{asset['optionSymbol']} {side.upper()} guidance for a confirmed {asset['underlyingLabel']} "
      f"{timeframe if timeframe != DAILY_TIMEFRAME else '1D'}{'m' if timeframe != DAILY_TIMEFRAME else ''} {direction} momentum plan."
    ),
    "dte": {
      **profile,
      "earliestExpiration": _expiration_date(generated_at, profile["min"]),
      "targetExpiration": _expiration_date(generated_at, profile["target"]),
      "latestExpiration": _expiration_date(generated_at, profile["max"]),
    },
    "delta": {"min": MIN_DELTA, "target": TARGET_DELTA, "max": MAX_DELTA},
    "strikeGuidance": {
      "min": round(min(strike_low, strike_high), 2),
      "max": round(max(strike_low, strike_high), 2),
      "label": "ATM to about 1% ITM",
    },
    "underlying": {
      "price": underlying_spot,
      "entry": entry,
      "stop": stop,
      "target1": target1,
      "target2": target2,
      "riskReward": finite_number(signal.get("riskReward")),
    },
    "exitPlan": {
      "invalidation": f"Exit if {asset['underlyingLabel']} invalidates at {stop:.2f}.",
      "target1": f"Consider partial profit when {asset['underlyingLabel']} reaches {target1:.2f}.",
      "target2": f"Exit the remainder or trail risk near {asset['underlyingLabel']} {target2:.2f}.",
      "time": "Exit early if momentum fails; expiration is not the planned holding period.",
    },
    "contract": None,
    "provider": {
      "name": "Market Data",
      "mode": "guidance",
      "configured": False,
      "delayed": False,
      "quoteAt": None,
      "detail": f"Exact {asset['optionSymbol']} contract quotes require MARKETDATA_TOKEN.",
    },
  }


def normalize_marketdata_chain(payload):
  if not isinstance(payload, dict) or payload.get("s") not in {"ok", "success"}:
    return []
  symbols = payload.get("optionSymbol") or []
  if not isinstance(symbols, list):
    return []
  fields = (
    "optionSymbol", "underlying", "expiration", "side", "strike", "dte",
    "bid", "ask", "mid", "last", "volume", "openInterest",
    "underlyingPrice", "updated", "iv", "delta", "gamma", "theta", "vega",
  )
  output = []
  for index in range(len(symbols)):
    row = {}
    for field in fields:
      values = payload.get(field)
      row[field] = values[index] if isinstance(values, list) and index < len(values) else None
    output.append(row)
  return output


def timestamp_ms(value):
  number = finite_number(value)
  if number is None:
    return None
  return int(number * 1000 if number < 10_000_000_000 else number)


def _delta_bucket(delta):
  value = abs(finite_number(delta) or 0)
  if value < 0.60:
    return "0.55-0.60"
  if value < 0.65:
    return "0.60-0.65"
  return "0.65-0.70"


def contract_blockers(contract, guidance, now_ms, require_fresh=True):
  blockers = []
  side = str(contract.get("side") or "").lower()
  bid = finite_number(contract.get("bid"))
  ask = finite_number(contract.get("ask"))
  mid = finite_number(contract.get("mid"))
  if mid is None and bid is not None and ask is not None:
    mid = (bid + ask) / 2
  delta = abs(finite_number(contract.get("delta")) or 0)
  dte = finite_number(contract.get("dte"))
  if side != guidance["side"]:
    blockers.append("wrong side")
  if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid or mid is None or mid <= 0:
    blockers.append("invalid bid/ask")
  elif (ask - bid) / mid > MAX_SPREAD_PCT:
    blockers.append("bid/ask spread above 10%")
  if int(finite_number(contract.get("openInterest")) or 0) < MIN_OPEN_INTEREST:
    blockers.append("open interest below 500")
  if int(finite_number(contract.get("volume")) or 0) < MIN_VOLUME:
    blockers.append("volume below 100")
  if not MIN_DELTA <= delta <= MAX_DELTA:
    blockers.append("delta outside target range")
  profile = guidance["dte"]
  if dte is None or not profile["min"] <= dte <= profile["max"]:
    blockers.append("expiration outside DTE range")
  for field in ("iv", "delta", "gamma", "theta", "vega"):
    if finite_number(contract.get(field)) is None:
      blockers.append(f"missing {field}")
  quote_at = timestamp_ms(contract.get("updated"))
  if require_fresh and (quote_at is None or now_ms - quote_at > MAX_QUOTE_AGE_MS or quote_at > now_ms + 60_000):
    blockers.append("quote is older than 30 minutes")
  return blockers


def option_learning_adjustment(learning, delta):
  bucket = _delta_bucket(delta)
  row = (learning or {}).get(bucket) or {}
  sample_size = int(row.get("sampleSize") or 0)
  if sample_size < 30:
    return 0
  expected_return = finite_number(row.get("averageReturn")) or 0
  win_rate = finite_number(row.get("winRate"))
  if win_rate is None:
    win_rate = 0.5
  raw = (expected_return * 12) + ((win_rate - 0.5) * 10)
  return max(-5, min(5, round(raw, 1)))


def rank_contracts(contracts, guidance, now_ms, realized_vol=None, learning=None, require_fresh=True):
  ranked = []
  realized_vol = finite_number(realized_vol)
  for contract in contracts or []:
    blockers = contract_blockers(contract, guidance, now_ms, require_fresh=require_fresh)
    if blockers:
      continue
    item = dict(contract)
    bid = finite_number(item["bid"])
    ask = finite_number(item["ask"])
    mid = finite_number(item.get("mid")) or (bid + ask) / 2
    delta = abs(finite_number(item["delta"]))
    dte = finite_number(item["dte"])
    spread_pct = (ask - bid) / mid
    open_interest = int(finite_number(item["openInterest"]) or 0)
    volume = int(finite_number(item["volume"]) or 0)
    iv = finite_number(item["iv"])

    score = 100.0
    score -= min(20, abs(delta - TARGET_DELTA) / (MAX_DELTA - MIN_DELTA) * 20)
    score -= min(20, spread_pct / MAX_SPREAD_PCT * 20)
    score -= min(12, abs(dte - guidance["dte"]["target"]) / max(1, guidance["dte"]["max"] - guidance["dte"]["min"]) * 12)
    score += min(5, math.log10(max(MIN_OPEN_INTEREST, open_interest) / MIN_OPEN_INTEREST) * 4)
    score += min(3, math.log10(max(MIN_VOLUME, volume) / MIN_VOLUME) * 3)
    if realized_vol and realized_vol > 0:
      volatility_ratio = iv / realized_vol
      score -= min(10, max(0, volatility_ratio - 1.15) * 8)
      item["ivToRealizedVol"] = round(volatility_ratio, 3)
    learning_adjustment = option_learning_adjustment(learning, delta)
    score += learning_adjustment
    item.update({
      "mid": round(mid, 4),
      "spreadPct": round(spread_pct, 4),
      "rankScore": round(max(0, min(100, score)), 1),
      "learningAdjustment": learning_adjustment,
      "quoteAt": timestamp_ms(item.get("updated")),
      "deltaBucket": _delta_bucket(delta),
    })
    ranked.append(item)
  ranked.sort(key=lambda item: (item["rankScore"], item["openInterest"], item["volume"]), reverse=True)
  return ranked


def option_scenarios(contract, guidance):
  mid = finite_number(contract.get("mid"))
  delta = finite_number(contract.get("delta"))
  gamma = finite_number(contract.get("gamma"))
  theta = finite_number(contract.get("theta"))
  vega = finite_number(contract.get("vega"))
  bid = finite_number(contract.get("bid"))
  ask = finite_number(contract.get("ask"))
  spot = finite_number(contract.get("underlyingPrice")) or guidance["underlying"]["price"]
  if None in (mid, delta, gamma, theta, vega, bid, ask, spot):
    return None

  hold_days = max(1, min(5, int(guidance["timeframe"] / 5)))
  uncertainty = abs(ask - bid) / 2 + abs(vega) * 0.05

  def scenario(label, underlying_target):
    change = finite_number(underlying_target) - spot
    estimate = max(0.01, mid + delta * change + 0.5 * gamma * change * change + theta * hold_days)
    return {
      "label": label,
      "underlyingPrice": round(float(underlying_target), 2),
      "estimatedOptionMid": round(estimate, 2),
      "estimatedReturnPct": round((estimate / mid - 1) * 100, 1),
      "rangeLow": round(max(0.01, estimate - uncertainty), 2),
      "rangeHigh": round(estimate + uncertainty, 2),
    }

  return {
    "method": "Delta/gamma/theta estimate; IV and market conditions can materially change the result.",
    "target1": scenario(f"{guidance['underlyingSymbol']} target 1", guidance["underlying"]["target1"]),
    "target2": scenario(f"{guidance['underlyingSymbol']} target 2", guidance["underlying"]["target2"]),
  }


def attach_contract(guidance, contract, provider_detail="15-minute delayed options quote"):
  result = dict(guidance)
  selected = dict(contract)
  selected["costPerContract"] = round(float(selected["mid"]) * 100, 2)
  selected["expiration"] = timestamp_ms(selected.get("expiration"))
  selected["scenarios"] = option_scenarios(selected, guidance)
  result["status"] = "contract"
  result["contract"] = selected
  result["provider"] = {
    "name": "Market Data",
    "mode": "delayed",
    "configured": True,
    "delayed": True,
    "quoteAt": selected.get("quoteAt"),
    "detail": provider_detail,
  }
  result["detail"] = (
    f"{result['sideLabel']} contract candidate selected for liquidity, spread, delta, and expiration fit. "
    "The quote is delayed; verify it in your broker before acting."
  )
  return result
