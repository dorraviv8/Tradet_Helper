import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import strategy_engine as strategy


NEW_YORK = ZoneInfo("America/New_York")
TEL_AVIV = ZoneInfo("Asia/Jerusalem")


def timestamp(year, month, day, hour, minute):
  return int(datetime(year, month, day, hour, minute, tzinfo=NEW_YORK).timestamp() * 1000)


def tel_aviv_timestamp(year, month, day, hour, minute):
  return int(datetime(year, month, day, hour, minute, tzinfo=TEL_AVIV).timestamp() * 1000)


def candle(time, open_price, high, low, close, volume=1000):
  return {
    "time": time,
    "open": open_price,
    "high": high,
    "low": low,
    "close": close,
    "volume": volume,
  }


class StrategyEngineTests(unittest.TestCase):
  def test_asset_profiles_use_distinct_market_targets(self):
    qqq = strategy.bounds(5, "normal", "QQQ")
    spy = strategy.bounds(5, "normal", "SPY")
    ta125 = strategy.bounds(5, "normal", "TA125")
    btc = strategy.bounds(5, "normal", "BTC-USD")
    self.assertLess(spy["target1MaxPct"], qqq["target1MaxPct"])
    self.assertLess(ta125["target1MaxPct"], qqq["target1MaxPct"])
    self.assertGreater(btc["target1MaxPct"], qqq["target1MaxPct"])
    self.assertFalse(strategy.asset_profile("TA125")["reliableVolume"])

  def test_execution_quality_blocks_stop_inside_cost_and_candle_noise(self):
    blocked = strategy.execution_quality(64_742.5, 64_746.1, 12.0, 1, {"backtestSlippageBps": 0.5}, "BTC-USD")
    passed = strategy.execution_quality(64_742.5, 64_600.0, 120.0, 5, {"backtestSlippageBps": 0.5}, "BTC-USD")
    self.assertEqual(blocked["status"], "blocked")
    self.assertEqual(blocked["entryConfirmation"], "close")
    self.assertTrue(blocked["blockers"])
    self.assertEqual(passed["status"], "passed")

  def test_resample_preserves_ohlcv_order(self):
    start = timestamp(2026, 7, 17, 9, 30)
    sampled = strategy.resample([
      candle(start, 100, 101, 99.8, 100.5, 10),
      candle(start + strategy.MINUTE_MS, 100.5, 102, 100.2, 101.5, 20),
    ], 5)
    self.assertEqual(len(sampled), 1)
    self.assertEqual(sampled[0]["open"], 100)
    self.assertEqual(sampled[0]["high"], 102)
    self.assertEqual(sampled[0]["low"], 99.8)
    self.assertEqual(sampled[0]["close"], 101.5)
    self.assertEqual(sampled[0]["volume"], 30)

  def test_zero_volume_quote_outlier_is_rejected(self):
    merged = strategy.merge_candles([
      candle(timestamp(2026, 7, 17, 17, 0), 100, 100.1, 92, 100.05, 0),
      candle(timestamp(2026, 7, 17, 17, 1), 100, 100.1, 99.9, 100.05, 0),
    ])
    self.assertEqual(len(merged), 1)
    self.assertEqual(merged[0]["low"], 99.9)

  def test_adaptive_adjustment_requires_thirty_resolved_examples(self):
    reasons = []
    below_minimum = {"bySetup": {"momentum": {"winners": 25, "stopped": 4}}}
    self.assertEqual(strategy.adaptive_adjustment("momentum", 5, "morning", below_minimum, reasons), 0)
    enough = {"bySetup": {"momentum": {"winners": 26, "stopped": 4}}}
    self.assertGreater(strategy.adaptive_adjustment("momentum", 5, "morning", enough, []), 0)

  def test_shadow_learning_does_not_change_production_candidate_score(self):
    latest = {
      "time": timestamp(2026, 7, 17, 10, 30), "open": 100.0, "high": 100.2, "low": 99.9, "close": 100.1,
      "volume": 2_000, "ema20": 100.0, "ema50": 99.8, "sma20": 100.0, "sma50": 99.8,
      "vwap": 99.9, "rsi": 60.0, "atr": 1.0, "relativeVolume": 1.3,
    }
    context = {
      "latest": latest,
      "previous": {**latest, "time": latest["time"] - 5 * strategy.MINUTE_MS, "close": 99.95},
      "direction": "long",
      "shape": strategy.candle_shape(latest),
      "levels": {"support": 99.7, "resistance": 100.15, "supportTouches": 2, "resistanceTouches": 2},
      "timeframe": 5,
      "trend5": {"tone": "positive"},
      "trend15": {"tone": "positive"},
      "selectedTrend": {"tone": "positive"},
      "trends": {1: {"tone": "positive"}, 5: {"tone": "positive"}, 15: {"tone": "positive"}},
      "regime": {"type": "trend_up", "label": "Trend Up"},
      "execution": {"available": True, "aligned": True, "detail": "1m confirms"},
    }
    setup = {"setup": "Long 5m momentum continuation", "baseScore": 45, "reasons": ["test"]}
    performance = {"bySetup": {"momentum": {"winners": 30, "stopped": 0}}}
    baseline = strategy.score_candidate(setup, context, {"mode": "normal", "learning": {"mode": "shadow"}}, {})
    shadow = strategy.score_candidate(setup, context, {"mode": "normal", "learning": {"mode": "shadow"}}, performance)
    approved = strategy.score_candidate(setup, context, {"mode": "normal", "learning": {"mode": "approved_live"}}, performance)
    self.assertGreater(shadow["shadowModel"]["suggestedScoreAdjustment"], 0)
    self.assertEqual(shadow["score"], baseline["score"])
    self.assertFalse(shadow["shadowModel"]["appliedToProduction"])
    self.assertGreater(approved["score"], shadow["score"])

  def test_analysis_returns_every_timeframe_with_actionable_boundaries(self):
    start = timestamp(2026, 7, 17, 9, 30)
    candles = []
    price = 600.0
    for index in range(390):
      close = price + 0.025 + (0.03 if index % 17 == 0 else 0)
      candles.append(candle(start + index * strategy.MINUTE_MS, price, close + 0.04, price - 0.03, close, 1000 + index * 3))
      price = close
    now = start + 391 * strategy.MINUTE_MS
    result = strategy.analyze_all(candles, {"sessionMode": "extended", "mode": "normal"}, now=now)
    self.assertEqual(set(result), {1, 5, 15})
    for timeframe, signal in result.items():
      self.assertEqual(signal["timeframe"], timeframe)
      self.assertEqual(signal["actionableAt"], signal["signalCandleTime"] + timeframe * strategy.MINUTE_MS)
      self.assertIn(signal["direction"], {"long", "short", "neutral"})

  def test_recent_gap_pauses_otherwise_current_analysis(self):
    start = timestamp(2026, 7, 17, 10, 0)
    candles = []
    price = 600.0
    for index in range(80):
      offset = index + (2 if index >= 60 else 0)
      close = price + 0.03
      candles.append(candle(start + offset * strategy.MINUTE_MS, price, close + 0.04, price - 0.02, close, 1500))
      price = close
    now = candles[-1]["time"] + 2 * strategy.MINUTE_MS
    result = strategy.analyze_all(candles, {"sessionMode": "extended"}, now=now)
    self.assertEqual(result[1]["direction"], "neutral")
    self.assertIn("data quality", result[1]["reasons"][0])

  def test_weekend_is_closed(self):
    saturday = timestamp(2026, 7, 18, 11, 0)
    self.assertEqual(strategy.market_session(saturday)["phase"], "closed")
    self.assertEqual(strategy.market_phase(saturday), "closed")

  def test_bitcoin_market_is_continuous_on_weekends(self):
    saturday = timestamp(2026, 7, 18, 11, 0)
    session = strategy.market_session(saturday, "BTC-USD")
    self.assertTrue(session["regular"])
    self.assertEqual(session["phase"], "continuous")
    self.assertEqual(strategy.market_phase(saturday, "BTC-USD"), "continuous")

  def test_tel_aviv_market_uses_local_weekday_and_regular_session(self):
    sunday = tel_aviv_timestamp(2026, 7, 26, 11, 0)
    monday_open = tel_aviv_timestamp(2026, 7, 27, 10, 0)
    monday_close = tel_aviv_timestamp(2026, 7, 27, 17, 31)
    self.assertEqual(strategy.market_session(sunday, "TA125")["phase"], "closed")
    self.assertEqual(strategy.market_session(monday_open, "TA125")["phase"], "regular")
    self.assertEqual(strategy.market_session(monday_close, "TA125")["phase"], "after_hours")
    self.assertEqual(strategy.market_parts(monday_open, "TA125")[0], "2026-07-27")

  def test_bitcoin_risk_bounds_are_asset_specific(self):
    qqq = strategy.bounds(5, "normal", "QQQ")
    bitcoin = strategy.bounds(5, "normal", "BTC-USD")
    self.assertGreater(bitcoin["target1MaxPct"], qqq["target1MaxPct"])
    self.assertGreater(bitcoin["maxRiskPct"], qqq["maxRiskPct"])

  def test_trend_confirmation_requires_two_timeframes_for_continuation(self):
    trends = {
      1: {"tone": "positive"},
      5: {"tone": "neutral"},
      15: {"tone": "positive"},
    }
    confirmation = strategy.trend_confirmation(trends, 1, "long")
    self.assertEqual(confirmation["aligned"], 2)
    self.assertEqual(confirmation["opposed"], 0)
    self.assertEqual(strategy.trend_confirmation(trends, 1, "short")["opposed"], 2)

  def test_atr_extension_measures_price_distance_on_trade_side(self):
    latest = {"close": 603.0, "ema20": 600.0, "atr": 2.0}
    self.assertAlmostEqual(strategy.atr_extension(latest, "long"), 1.5)
    self.assertAlmostEqual(strategy.atr_extension(latest, "short"), -1.5)

  def test_market_regime_identifies_aligned_uptrend(self):
    start = timestamp(2026, 7, 16, 9, 30)
    candles = []
    for index in range(45):
      price = 600 + index * 0.18
      candles.append(candle(start + index * strategy.MINUTE_MS, price, price + 0.22, price - 0.04, price + 0.16, 2_000 + index * 10))
    regime = strategy.classify_market_regime(strategy.indicators(candles))
    self.assertEqual(regime["type"], "trend_up")
    self.assertEqual(regime["tone"], "positive")

  def test_daily_analysis_builds_separate_swing_plan(self):
    day = datetime(2025, 8, 1, 9, 30, tzinfo=NEW_YORK)
    candles = []
    price = 500.0
    while len(candles) < 220:
      if day.weekday() < 5:
        close = price + 0.45
        candles.append(candle(
          int(day.timestamp() * 1000),
          price,
          close + 0.22,
          price - 0.18,
          close,
          30_000_000 + len(candles) * 10_000,
        ))
        price = close
      day += timedelta(days=1)
    now = int(day.timestamp() * 1000)
    signal = strategy.analyze_daily(candles, {"mode": "normal"}, now=now)
    self.assertEqual(signal["timeframe"], strategy.DAILY_TIMEFRAME)
    self.assertEqual(signal["direction"], "long")
    self.assertEqual(signal["holdingPeriod"], "multi-day swing")
    self.assertLess(signal["stop"], signal["entry"])
    self.assertLess(signal["entry"], signal["target"])
    self.assertLess(signal["target"], signal["target2"])

  def test_intraday_analysis_prefers_native_five_minute_history(self):
    start = timestamp(2026, 7, 16, 9, 30)
    one_minute = []
    five_minute = []
    for index in range(210):
      one_price = 600 + index * 0.01
      five_price = 590 + index * 0.04
      one_minute.append(candle(start + index * strategy.MINUTE_MS, one_price, one_price + 0.08, one_price - 0.04, one_price + 0.03))
      five_minute.append(candle(start + index * 5 * strategy.MINUTE_MS, five_price, five_price + 0.12, five_price - 0.05, five_price + 0.08))
    now = five_minute[-1]["time"] + 6 * strategy.MINUTE_MS
    result = strategy.analyze_all(one_minute, {"sessionMode": "extended"}, now=now, five_minute_candles=five_minute)
    self.assertEqual(result[5]["latestIndicator"]["time"], five_minute[-1]["time"])
    self.assertAlmostEqual(result[5]["latestIndicator"]["close"], five_minute[-1]["close"])

  def test_session_levels_only_expose_completed_opening_ranges(self):
    start = timestamp(2026, 7, 17, 9, 30)
    candles = [
      candle(start + index * strategy.MINUTE_MS, 100 + index * 0.1, 100.2 + index * 0.1, 99.9 + index * 0.1, 100.1 + index * 0.1)
      for index in range(20)
    ]
    levels = strategy.session_levels(candles)
    self.assertIn("opening5High", levels)
    self.assertIn("opening15High", levels)
    self.assertNotIn("opening30High", levels)
    self.assertAlmostEqual(levels["opening15High"], candles[14]["high"])
    self.assertAlmostEqual(levels["sessionHigh"], candles[-1]["high"])

  def test_relative_volume_uses_rolling_baseline_when_time_of_day_history_is_short(self):
    start = timestamp(2026, 7, 17, 9, 30)
    candles = [
      candle(start + index * 5 * strategy.MINUTE_MS, 100, 100.2, 99.8, 100.1, 1_000)
      for index in range(21)
    ]
    candles[-1]["volume"] = 2_000
    values = strategy.indicators(candles)
    self.assertIsNone(values[-1]["timeRelativeVolume"])
    self.assertAlmostEqual(values[-1]["rollingRelativeVolume"], 2.0)
    self.assertAlmostEqual(values[-1]["relativeVolume"], 2.0)

  def test_five_minute_continuation_requires_available_one_minute_execution_alignment(self):
    latest = {
      "time": timestamp(2026, 7, 17, 10, 30), "open": 100.0, "high": 100.2, "low": 99.9, "close": 100.1,
      "volume": 2_000, "ema20": 100.0, "ema50": 99.8, "sma20": 100.0, "sma50": 99.8,
      "vwap": 99.9, "rsi": 60.0, "atr": 1.0, "relativeVolume": 1.3,
    }
    previous = {**latest, "time": latest["time"] - 5 * strategy.MINUTE_MS, "close": 99.95, "high": 100.0, "low": 99.8}
    context = {
      "latest": latest,
      "previous": previous,
      "direction": "long",
      "shape": strategy.candle_shape(latest),
      "levels": {"support": 99.7, "resistance": 100.15, "supportTouches": 2, "resistanceTouches": 2},
      "timeframe": 5,
      "trend5": {"tone": "positive"},
      "trend15": {"tone": "positive"},
      "selectedTrend": {"tone": "positive"},
      "trends": {1: {"tone": "positive"}, 5: {"tone": "positive"}, 15: {"tone": "positive"}},
      "regime": {"type": "trend_up", "label": "Trend Up"},
      "execution": {"available": True, "aligned": False, "detail": "1m execution does not yet confirm the 5m direction"},
    }
    candidate = strategy.score_candidate({
      "setup": "Long 5m momentum continuation", "baseScore": 45, "reasons": ["test"],
    }, context, {"mode": "normal"}, {})
    self.assertTrue(candidate["watchOnly"])
    self.assertIn("1m execution does not yet confirm", " ".join(candidate["reasons"]))

  def test_prior_session_levels_use_the_last_completed_regular_session(self):
    previous = timestamp(2026, 7, 16, 15, 55)
    current = timestamp(2026, 7, 17, 10, 0)
    levels = strategy.prior_session_levels([
      candle(previous - 5 * strategy.MINUTE_MS, 100, 102, 99, 101),
      candle(previous, 101, 103, 100, 102),
      candle(current, 104, 105, 103, 104.5),
    ])
    self.assertEqual(levels, {"priorDayHigh": 103, "priorDayLow": 99})

  def test_compression_breakout_requires_a_compact_range_then_close_outside_it(self):
    start = timestamp(2026, 7, 17, 11, 0)
    values = []
    for index in range(8):
      base = 100 + (0.03 if index % 2 else 0)
      values.append({
        "time": start + index * 5 * strategy.MINUTE_MS,
        "open": base,
        "high": base + 0.12,
        "low": base - 0.12,
        "close": base + 0.01,
        "atr": 0.5,
      })
    values[-1]["close"] = 100.45
    values[-1]["high"] = 100.5
    self.assertTrue(strategy.compression_breakout(values, "long"))
    self.assertFalse(strategy.compression_breakout(values, "short"))

  def test_five_minute_no_trade_filters_cover_open_low_volatility_and_midday_volume(self):
    open_candle = {"time": timestamp(2026, 7, 17, 9, 35), "close": 600, "atr": 0.4, "vwap": 600, "relativeVolume": 1.0}
    open_filters = strategy.five_minute_no_trade_filters(open_candle, {"type": "mixed"})
    self.assertIn("Wait for the 15-minute opening range to complete", open_filters)
    midday_candle = {"time": timestamp(2026, 7, 17, 12, 0), "close": 600, "atr": 0.1, "vwap": 600, "relativeVolume": 0.5}
    midday_filters = strategy.five_minute_no_trade_filters(midday_candle, {"type": "chop"})
    self.assertIn("5m volatility is too compressed for a reliable target", midday_filters)
    self.assertIn("Midday volume is too light for a momentum trade", midday_filters)
    self.assertIn("Choppy price action is too close to VWAP", midday_filters)

  def test_new_five_minute_setup_types_remain_distinct_for_learning_and_replay(self):
    self.assertEqual(strategy.setup_type("Long 5m failed breakout reversal"), "failed_breakout")
    self.assertEqual(strategy.setup_type("Long 5m compression breakout"), "compression")
    self.assertEqual(strategy.setup_type("Long 5m 15m opening range breakout"), "opening_range")
    self.assertEqual(strategy.setup_type("Long 5m premarket high breakout"), "premarket")


if __name__ == "__main__":
  unittest.main()
