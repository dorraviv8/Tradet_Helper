import math
import statistics
from bisect import bisect_left
from collections import defaultdict

import strategy_engine


MINUTE_MS = strategy_engine.MINUTE_MS
RESOLVED_OUTCOMES = {"target2", "target1_stop", "stopped", "time_exit"}


def _hit_map(signal, candle):
  direction = signal["direction"]
  entry = float(signal["entry"])
  stop = float(signal["stop"])
  target1 = float(signal["target"])
  target2 = float(signal["target2"])
  close_confirmation = (signal.get("executionQuality") or {}).get("entryConfirmation") == "close"
  if direction == "long":
    return {
      "entry": candle["close"] >= entry if close_confirmation else candle["high"] >= entry,
      "stop": candle["low"] <= stop,
      "target1": candle["high"] >= target1,
      "target2": candle["high"] >= target2,
      "favorable": max(0, candle["high"] - entry),
      "adverse": max(0, entry - candle["low"]),
    }
  return {
    "entry": candle["close"] <= entry if close_confirmation else candle["low"] <= entry,
    "stop": candle["high"] >= stop,
    "target1": candle["low"] <= target1,
    "target2": candle["low"] <= target2,
    "favorable": max(0, entry - candle["low"]),
    "adverse": max(0, candle["high"] - entry),
  }


def _net_r(gross_r, entry, risk, slippage_bps, commission_per_share):
  if risk <= 0:
    return None
  execution_cost = entry * (float(slippage_bps) / 10_000) * 2 + float(commission_per_share) * 2
  return gross_r - execution_cost / risk


def execution_slippage_bps(signal, timeframe, base_slippage_bps, symbol):
  phase = signal.get("marketPhase") or strategy_engine.market_phase(int(signal.get("signalCandleTime") or 0), symbol)
  extra = 0.0
  if phase in {"open", "premarket", "after_hours"}:
    extra += 1.0
  elif phase == "midday":
    extra += 0.35
  if strategy_engine.is_continuous_market(symbol):
    extra += 1.0
  if timeframe == strategy_engine.DAILY_TIMEFRAME:
    extra += 0.5
  return float(base_slippage_bps) + extra


def gap_adjusted_stop_r(signal, candle):
  entry = float(signal["entry"])
  stop = float(signal["stop"])
  risk = abs(entry - stop)
  if risk <= 0:
    return -1.0
  if signal["direction"] == "long":
    exit_price = min(stop, float(candle["open"]))
    return (exit_price - entry) / risk
  exit_price = max(stop, float(candle["open"]))
  return (entry - exit_price) / risk


def simulate_trade(signal, future_candles, timeframe, slippage_bps=0.5, commission_per_share=0.0, symbol=strategy_engine.DEFAULT_SYMBOL):
  entry = float(signal["entry"])
  stop = float(signal["stop"])
  target1 = float(signal["target"])
  target2 = float(signal["target2"])
  risk = abs(entry - stop)
  if risk <= 0:
    return None
  direction = signal["direction"]
  signal_time = int(signal["signalCandleTime"])
  signal_day = strategy_engine.market_parts(signal_time, symbol)[0]
  max_age = 14 * 24 * 60 * MINUTE_MS if timeframe == strategy_engine.DAILY_TIMEFRAME else 4 * 60 * MINUTE_MS
  entered_at = None
  working_signal = dict(signal)
  target1_at = None
  favorable = 0.0
  adverse = 0.0
  last = None

  for candle in future_candles:
    if candle["time"] <= signal_time:
      continue
    if timeframe != strategy_engine.DAILY_TIMEFRAME and strategy_engine.market_parts(candle["time"], symbol)[0] != signal_day:
      break
    if candle["time"] - signal_time > max_age:
      break
    last = candle
    hits = _hit_map(working_signal, candle)
    if entered_at is None:
      if not hits["entry"] and hits["stop"]:
        return _trade_record(signal, timeframe, "invalidated", None, candle["time"], 0, 0, None, None)
      if not hits["entry"]:
        continue
      if hits["stop"]:
        return _trade_record(working_signal, timeframe, "ambiguous", candle["time"], candle["time"], 0, 0, None, None)
      opening_fill = float(candle["open"])
      if direction == "long" and opening_fill > entry:
        working_signal["entry"] = opening_fill
      elif direction == "short" and opening_fill < entry:
        working_signal["entry"] = opening_fill
      entry = float(working_signal["entry"])
      risk = abs(entry - stop)
      if risk <= 0 or (direction == "long" and entry >= target1) or (direction == "short" and entry <= target1):
        return _trade_record(working_signal, timeframe, "ambiguous", candle["time"], candle["time"], 0, 0, None, None)
      entered_at = candle["time"]
      continue

    favorable = max(favorable, hits["favorable"])
    adverse = max(adverse, hits["adverse"])
    if target1_at is not None:
      if hits["target2"] and hits["stop"]:
        return _trade_record(working_signal, timeframe, "ambiguous", entered_at, candle["time"], favorable, adverse, None, target1_at)
      if hits["target2"]:
        gross_r = abs(target2 - entry) / risk
        net = _net_r(gross_r, entry, risk, execution_slippage_bps(signal, timeframe, slippage_bps, symbol), commission_per_share)
        return _trade_record(working_signal, timeframe, "target2", entered_at, candle["time"], favorable, adverse, net, target1_at)
      if hits["stop"]:
        gross_r = abs(target1 - entry) / risk * 0.5 + gap_adjusted_stop_r(working_signal, candle) * 0.5
        net = _net_r(gross_r, entry, risk, execution_slippage_bps(signal, timeframe, slippage_bps, symbol), commission_per_share)
        return _trade_record(working_signal, timeframe, "target1_stop", entered_at, candle["time"], favorable, adverse, net, target1_at)
      continue

    if hits["stop"] and (hits["target1"] or hits["target2"]):
      return _trade_record(working_signal, timeframe, "ambiguous", entered_at, candle["time"], favorable, adverse, None, None)
    if hits["target2"]:
      gross_r = abs(target2 - entry) / risk
      net = _net_r(gross_r, entry, risk, execution_slippage_bps(signal, timeframe, slippage_bps, symbol), commission_per_share)
      return _trade_record(working_signal, timeframe, "target2", entered_at, candle["time"], favorable, adverse, net, candle["time"])
    if hits["target1"]:
      target1_at = candle["time"]
      continue
    if hits["stop"]:
      gross_r = gap_adjusted_stop_r(working_signal, candle)
      net = _net_r(gross_r, entry, risk, execution_slippage_bps(signal, timeframe, slippage_bps, symbol), commission_per_share)
      return _trade_record(working_signal, timeframe, "stopped", entered_at, candle["time"], favorable, adverse, net, None)

  if entered_at is None:
    end_time = last["time"] if last else signal_time + max_age
    return _trade_record(signal, timeframe, "expired", None, end_time, 0, 0, None, None)
  if last is None:
    return _trade_record(working_signal, timeframe, "open", entered_at, None, favorable, adverse, None, target1_at)
  close_move = (last["close"] - entry) if direction == "long" else (entry - last["close"])
  gross_r = close_move / risk
  if target1_at is not None:
    gross_r = abs(target1 - entry) / risk * 0.5 + gross_r * 0.5
  net = _net_r(gross_r, entry, risk, execution_slippage_bps(signal, timeframe, slippage_bps, symbol), commission_per_share)
  return _trade_record(working_signal, timeframe, "time_exit", entered_at, last["time"], favorable, adverse, net, target1_at)


def _trade_record(signal, timeframe, outcome, entered_at, closed_at, favorable, adverse, realized_r, target1_at):
  risk = abs(float(signal["entry"]) - float(signal["stop"]))
  return {
    "timeframe": int(timeframe),
    "direction": signal["direction"],
    "setup": signal["setup"],
    "setupType": signal.get("setupType", strategy_engine.setup_type(signal["setup"])),
    "marketPhase": signal.get("marketPhase", "swing" if timeframe == strategy_engine.DAILY_TIMEFRAME else "unknown"),
    "marketRegime": (signal.get("regime") or {}).get("type") or signal.get("marketRegime") or "unknown",
    "qualityScore": int(signal.get("score") or 0),
    "signalTime": int(signal["signalCandleTime"]),
    "entry": float(signal["entry"]),
    "stop": float(signal["stop"]),
    "target1": float(signal["target"]),
    "target2": float(signal["target2"]),
    "enteredAt": entered_at,
    "closedAt": closed_at,
    "outcome": outcome,
    "target1Hit": target1_at is not None,
    "timeToTarget1Ms": target1_at - entered_at if target1_at is not None and entered_at is not None else None,
    "realizedR": realized_r,
    "mfeR": favorable / risk if risk else None,
    "maeR": adverse / risk if risk else None,
  }


def _signal_is_actionable(signal):
  return signal.get("direction") in {"long", "short"} and not signal.get("watchOnly") and signal.get("entry") is not None


def replay_intraday(raw_candles, timeframe, source_timeframe, settings=None, max_bars=None, symbol=strategy_engine.DEFAULT_SYMBOL):
  settings = settings or {}
  source = strategy_engine.merge_candles(raw_candles)
  sampled = source if timeframe == source_timeframe else strategy_engine.resample(source, timeframe)
  generation_start = sampled[0]["time"] if sampled else 0
  if max_bars and len(sampled) > max_bars:
    generation_start = sampled[-max_bars]["time"]
    warmup_start = generation_start - 180 * timeframe * MINUTE_MS
    source = [candle for candle in source if candle["time"] >= warmup_start]
    sampled = source if timeframe == source_timeframe else strategy_engine.resample(source, timeframe)
  selected_values = strategy_engine.indicators(sampled, symbol)
  source_by_day = defaultdict(list)
  for candle in source:
    source_by_day[strategy_engine.market_parts(candle["time"], symbol)[0]].append(candle)
  day_context = {}
  for day, day_source in source_by_day.items():
    series = {
      1: strategy_engine.indicators(day_source, symbol) if source_timeframe == 1 else [],
      5: strategy_engine.indicators(day_source if source_timeframe == 5 else strategy_engine.resample(day_source, 5), symbol),
      15: strategy_engine.indicators(strategy_engine.resample(day_source, 15), symbol),
    }
    regular = [item for item in day_source if strategy_engine.market_session(item["time"], symbol)["regular"]]
    prefix_highs = []
    prefix_lows = []
    for item in regular:
      prefix_highs.append(max(item["high"], prefix_highs[-1] if prefix_highs else item["high"]))
      prefix_lows.append(min(item["low"], prefix_lows[-1] if prefix_lows else item["low"]))
    day_context[day] = {
      "source": day_source,
      "sourceTimes": [item["time"] for item in day_source],
      "series": series,
      "times": {key: [item["time"] for item in values] for key, values in series.items()},
      "regular": regular,
      "regularTimes": [item["time"] for item in regular],
      "regularHighs": prefix_highs,
      "regularLows": prefix_lows,
    }
  slippage = float(settings.get("backtestSlippageBps", 0.5))
  commission = float(settings.get("backtestCommissionPerShare", 0.0))
  cooldown = int(settings.get("alertCooldownMinutes", 15)) * MINUTE_MS
  trades = []
  last_signal = {}
  for index, candle in enumerate(sampled):
    if index < 25 or candle["time"] < generation_start or not strategy_engine.market_session(candle["time"], symbol)["regular"]:
      continue
    cutoff = candle["time"] + timeframe * MINUTE_MS
    day = strategy_engine.market_parts(candle["time"], symbol)[0]
    context = day_context[day]
    trend_values = {
      key: values[:bisect_left(context["times"][key], cutoff)]
      for key, values in context["series"].items()
    }
    trends = {key: strategy_engine.classify_trend(values) for key, values in trend_values.items()}
    regime_values = trend_values[1] if trend_values[1] else trend_values[5]
    regular_count = bisect_left(context["regularTimes"], cutoff)
    opening_count = min(regular_count, max(1, math.ceil(30 / max(1, source_timeframe))))
    session = {} if not regular_count else {
      "openingHigh": context["regularHighs"][opening_count - 1],
      "openingLow": context["regularLows"][opening_count - 1],
      "sessionHigh": context["regularHighs"][regular_count - 1],
      "sessionLow": context["regularLows"][regular_count - 1],
    }
    signal = strategy_engine.build_intraday_signal(
      selected_values[:index + 1],
      timeframe,
      trends,
      strategy_engine.classify_market_regime(regime_values),
      session,
      settings,
      {},
      [],
      symbol,
    )
    if not _signal_is_actionable(signal):
      continue
    key = (signal.get("setupType"), signal["direction"])
    if candle["time"] - last_signal.get(key, -10**18) < cooldown:
      continue
    last_signal[key] = candle["time"]
    trade = simulate_trade(signal, sampled[index + 1:], timeframe, slippage, commission, symbol)
    if trade:
      trades.append(trade)
  return trades


def replay_daily(raw_candles, settings=None, max_bars=None, symbol=strategy_engine.DEFAULT_SYMBOL):
  settings = settings or {}
  candles = strategy_engine.merge_candles(raw_candles)
  if max_bars and len(candles) > max_bars:
    candles = candles[-max_bars:]
  values = strategy_engine.indicators(candles, symbol)
  trades = []
  last_signal = {}
  slippage = float(settings.get("backtestSlippageBps", 0.5))
  commission = float(settings.get("backtestCommissionPerShare", 0.0))
  for index in range(160, len(candles) - 1):
    candle = candles[index]
    signal = strategy_engine.build_daily_signal(values[:index + 1], settings, {}, symbol=symbol)
    if not _signal_is_actionable(signal):
      continue
    key = (signal.get("setupType"), signal["direction"])
    if candle["time"] - last_signal.get(key, -10**18) < 7 * 24 * 60 * MINUTE_MS:
      continue
    last_signal[key] = candle["time"]
    trade = simulate_trade(signal, candles[index + 1:], strategy_engine.DAILY_TIMEFRAME, slippage, commission, symbol)
    if trade:
      trades.append(trade)
  return trades


def run_replay(
  one_minute=None, five_minute=None, daily=None, settings=None,
  symbol=strategy_engine.DEFAULT_SYMBOL, five_minute_max_bars=50_000,
  daily_max_bars=3_000,
):
  settings = settings or {}
  trades = []
  if one_minute:
    trades.extend(replay_intraday(one_minute, 1, 1, settings, max_bars=25_000, symbol=symbol))
  if five_minute:
    trades.extend(replay_intraday(five_minute, 5, 5, settings, max_bars=five_minute_max_bars, symbol=symbol))
    trades.extend(replay_intraday(five_minute, 15, 5, settings, max_bars=five_minute_max_bars, symbol=symbol))
  if daily:
    trades.extend(replay_daily(daily, settings, max_bars=daily_max_bars, symbol=symbol))
  validation = chronological_validation(trades)
  return {
    "symbol": symbol,
    "summary": summarize(trades),
    "byTimeframe": timeframe_summaries(trades),
    "groups": grouped_summaries(trades),
    "trades": trades,
    "validation": validation,
    "method": {
      "lookAheadSafe": True,
      "sameBarTargetsExcluded": True,
      "ambiguousBarsExcludedFromCalibration": True,
      "slippageBpsPerSide": float(settings.get("backtestSlippageBps", 0.5)),
      "commissionPerSharePerSide": float(settings.get("backtestCommissionPerShare", 0.0)),
      "validation": "Fixed-rule chronological holdout and rolling forward folds; no replay result changes production parameters",
    },
  }


def summarize(trades):
  entered = [trade for trade in trades if trade["enteredAt"] is not None]
  resolved = [trade for trade in entered if trade["outcome"] in RESOLVED_OUTCOMES and trade["realizedR"] is not None]
  target_hits = [trade for trade in resolved if trade["target1Hit"]]
  realized = [trade["realizedR"] for trade in resolved]
  favorable = [trade["mfeR"] for trade in resolved if trade["mfeR"] is not None]
  adverse = [trade["maeR"] for trade in resolved if trade["maeR"] is not None]
  target_times = [trade["timeToTarget1Ms"] for trade in resolved if trade["timeToTarget1Ms"] is not None]
  wins = [value for value in realized if value > 0]
  losses = [value for value in realized if value <= 0]
  equity = 0.0
  peak = 0.0
  max_drawdown = 0.0
  consecutive_losses = 0
  max_consecutive_losses = 0
  for value in realized:
    equity += value
    peak = max(peak, equity)
    max_drawdown = max(max_drawdown, peak - equity)
    if value <= 0:
      consecutive_losses += 1
      max_consecutive_losses = max(max_consecutive_losses, consecutive_losses)
    else:
      consecutive_losses = 0
  gross_profit = sum(wins)
  gross_loss = abs(sum(losses))
  average_win = statistics.fmean(wins) if wins else None
  average_loss = statistics.fmean(losses) if losses else None
  return {
    "signals": len(trades),
    "entries": len(entered),
    "resolved": len(resolved),
    "target1Hits": len(target_hits),
    "stops": sum(trade["outcome"] == "stopped" for trade in resolved),
    "expired": sum(trade["outcome"] in {"expired", "invalidated"} for trade in trades),
    "ambiguous": sum(trade["outcome"] == "ambiguous" for trade in trades),
    "probabilityT1": len(target_hits) / len(resolved) if resolved else None,
    "expectedR": statistics.fmean(realized) if realized else None,
    "totalR": sum(realized) if realized else None,
    "winRate": len(wins) / len(resolved) if resolved else None,
    "profitFactor": gross_profit / gross_loss if gross_loss > 0 else None,
    "avgWinR": average_win,
    "avgLossR": average_loss,
    "payoffRatio": average_win / abs(average_loss) if average_win is not None and average_loss not in {None, 0} else None,
    "maxDrawdownR": max_drawdown if resolved else None,
    "maxConsecutiveLosses": max_consecutive_losses,
    "avgFavorableR": statistics.fmean(favorable) if favorable else None,
    "avgAdverseR": statistics.fmean(adverse) if adverse else None,
    "medianTimeToTarget1Ms": statistics.median(target_times) if target_times else None,
  }


def chronological_validation(trades, holdout_fraction=0.4, folds=3):
  resolved = sorted(
    [trade for trade in trades if trade.get("enteredAt") is not None and trade.get("outcome") in RESOLVED_OUTCOMES and trade.get("realizedR") is not None],
    key=lambda trade: (int(trade.get("signalTime") or 0), int(trade.get("timeframe") or 0)),
  )
  if len(resolved) < 10:
    return {
      "status": "building",
      "detail": "At least 10 resolved replay trades are required for a chronological holdout",
      "sampleSize": len(resolved),
      "inSample": summarize([]),
      "outOfSample": summarize([]),
      "folds": [],
    }
  split = max(1, min(len(resolved) - 1, round(len(resolved) * (1 - holdout_fraction))))
  in_sample = resolved[:split]
  out_of_sample = resolved[split:]
  fold_rows = []
  fold_size = max(1, len(resolved) // (folds + 1))
  for index in range(folds):
    test_start = min(len(resolved), fold_size * (index + 1))
    test_end = len(resolved) if index == folds - 1 else min(len(resolved), test_start + fold_size)
    test_rows = resolved[test_start:test_end]
    if not test_rows:
      continue
    fold_rows.append({
      "fold": index + 1,
      "trainingSamples": test_start,
      "testStart": test_rows[0]["signalTime"],
      "testEnd": test_rows[-1]["signalTime"],
      "test": summarize(test_rows),
    })
  holdout = summarize(out_of_sample)
  status = "validated" if holdout["resolved"] >= 30 and (holdout.get("expectedR") or 0) > 0 and (holdout.get("profitFactor") or 0) > 1 else "provisional"
  return {
    "status": status,
    "detail": "Chronological fixed-rule holdout; production scoring is not fitted on the test period",
    "sampleSize": len(resolved),
    "splitIndex": split,
    "inSample": summarize(in_sample),
    "outOfSample": holdout,
    "folds": fold_rows,
  }


def grouped_summaries(trades):
  groups = defaultdict(list)
  for trade in trades:
    groups[(trade["timeframe"], trade["setupType"], trade["marketPhase"], trade.get("marketRegime", "unknown"), trade["direction"])].append(trade)
  output = []
  for (timeframe, setup_type, phase, regime, direction), rows in groups.items():
    output.append({
      "timeframe": timeframe,
      "setupType": setup_type,
      "marketPhase": phase,
      "marketRegime": regime,
      "direction": direction,
      **summarize(rows),
    })
  return sorted(output, key=lambda row: (row["timeframe"], row["setupType"], row["marketPhase"], row["marketRegime"], row["direction"]))


def timeframe_summaries(trades):
  return {
    str(timeframe): summarize([trade for trade in trades if int(trade["timeframe"]) == timeframe])
    for timeframe in sorted({int(trade["timeframe"]) for trade in trades})
  }


def wilson_interval(successes, total, z=1.96):
  if total <= 0:
    return None, None
  rate = successes / total
  denominator = 1 + z * z / total
  center = (rate + z * z / (2 * total)) / denominator
  margin = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / denominator
  return max(0, center - margin), min(1, center + margin)


def calibration_for_signal(trades, signal, minimum_group=8, calibrated_minimum=20):
  if not signal or signal.get("direction") not in {"long", "short"}:
    return empty_calibration()
  timeframe = int(signal.get("timeframe") or 0)
  setup_kind = signal.get("setupType") or strategy_engine.setup_type(signal.get("setup", ""))
  direction = signal["direction"]
  candidates = (
    ("setup + timeframe + side", lambda row: row["timeframe"] == timeframe and row["setupType"] == setup_kind and row["direction"] == direction),
    ("setup + timeframe", lambda row: row["timeframe"] == timeframe and row["setupType"] == setup_kind),
    ("timeframe + side", lambda row: row["timeframe"] == timeframe and row["direction"] == direction),
    ("timeframe", lambda row: row["timeframe"] == timeframe),
  )
  selected = []
  scope = "no comparable replay sample"
  for label, predicate in candidates:
    rows = [row for row in trades if predicate(row) and row["enteredAt"] is not None and row["outcome"] in RESOLVED_OUTCOMES and row["realizedR"] is not None]
    if len(rows) >= minimum_group:
      selected = rows
      scope = label
      break
  if not selected:
    selected = [
      row for row in trades
      if row["timeframe"] == timeframe and row["enteredAt"] is not None
      and row["outcome"] in RESOLVED_OUTCOMES and row["realizedR"] is not None
    ]
    scope = "timeframe (small sample)" if selected else scope
  if not selected:
    return empty_calibration()
  successes = sum(bool(row["target1Hit"]) for row in selected)
  total = len(selected)
  low, high = wilson_interval(successes, total)
  posterior_probability = (successes + 5) / (total + 10)
  target_times = [row["timeToTarget1Ms"] for row in selected if row["timeToTarget1Ms"] is not None]
  return {
    "sampleSize": total,
    "target1Hits": successes,
    "probabilityT1": posterior_probability,
    "observedProbabilityT1": successes / total,
    "confidenceLow": low,
    "confidenceHigh": high,
    "expectedR": statistics.fmean(row["realizedR"] for row in selected),
    "avgMfeR": statistics.fmean(row["mfeR"] for row in selected if row["mfeR"] is not None),
    "avgMaeR": statistics.fmean(row["maeR"] for row in selected if row["maeR"] is not None),
    "medianTimeToTarget1Ms": statistics.median(target_times) if target_times else None,
    "scope": scope,
    "calibrated": total >= calibrated_minimum,
  }


def empty_calibration():
  return {
    "sampleSize": 0,
    "target1Hits": 0,
    "probabilityT1": None,
    "observedProbabilityT1": None,
    "confidenceLow": None,
    "confidenceHigh": None,
    "expectedR": None,
    "avgMfeR": None,
    "avgMaeR": None,
    "medianTimeToTarget1Ms": None,
    "scope": "no comparable replay sample",
    "calibrated": False,
  }
