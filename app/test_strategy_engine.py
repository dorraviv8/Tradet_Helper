import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import strategy_engine as strategy


NEW_YORK = ZoneInfo("America/New_York")


def timestamp(year, month, day, hour, minute):
  return int(datetime(year, month, day, hour, minute, tzinfo=NEW_YORK).timestamp() * 1000)


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

  def test_bitcoin_risk_bounds_are_asset_specific(self):
    qqq = strategy.bounds(5, "normal", "QQQ")
    bitcoin = strategy.bounds(5, "normal", "BTC-USD")
    self.assertGreater(bitcoin["target1MaxPct"], qqq["target1MaxPct"])
    self.assertGreater(bitcoin["maxRiskPct"], qqq["maxRiskPct"])

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


if __name__ == "__main__":
  unittest.main()
