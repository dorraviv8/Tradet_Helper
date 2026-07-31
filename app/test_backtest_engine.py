import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import backtest_engine as backtest


def candle(time, open_price, high, low, close, volume=1_000):
  return {
    "time": time,
    "open": open_price,
    "high": high,
    "low": low,
    "close": close,
    "volume": volume,
  }


def signal(**overrides):
  value = {
    "timeframe": 1,
    "direction": "long",
    "setup": "Long 1m breakout",
    "setupType": "breakout",
    "marketPhase": "morning",
    "score": 78,
    "signalCandleTime": 60_000,
    "entry": 100.0,
    "stop": 99.0,
    "target": 101.0,
    "target2": 102.0,
    "watchOnly": False,
  }
  value.update(overrides)
  return value


class BacktestEngineTests(unittest.TestCase):
  def test_entry_bar_cannot_receive_same_bar_target_credit(self):
    result = backtest.simulate_trade(signal(), [
      candle(120_000, 99.8, 101.2, 99.7, 100.8),
      candle(180_000, 100.1, 100.3, 98.8, 99.0),
    ], 1, slippage_bps=0)
    self.assertEqual(result["outcome"], "stopped")
    self.assertFalse(result["target1Hit"])
    self.assertEqual(result["realizedR"], -1.0)

  def test_target_then_stop_applies_partial_exit_and_costs(self):
    result = backtest.simulate_trade(signal(), [
      candle(120_000, 99.8, 100.3, 99.7, 100.1),
      candle(180_000, 100.1, 101.2, 100.0, 101.0),
      candle(240_000, 101.0, 101.1, 98.8, 99.0),
    ], 1, slippage_bps=0.5)
    self.assertEqual(result["outcome"], "target1_stop")
    self.assertTrue(result["target1Hit"])
    self.assertLess(result["realizedR"], 0)

  def test_gap_through_stop_uses_worse_opening_price(self):
    result = backtest.simulate_trade(signal(), [
      candle(120_000, 99.8, 100.3, 99.7, 100.1),
      candle(180_000, 98.5, 99.1, 98.2, 98.8),
    ], 1, slippage_bps=0)
    self.assertEqual(result["outcome"], "stopped")
    self.assertEqual(result["realizedR"], -1.5)

  def test_open_and_continuous_markets_use_more_conservative_slippage(self):
    base = backtest.execution_slippage_bps(signal(marketPhase="morning"), 5, 0.5, "QQQ")
    opening = backtest.execution_slippage_bps(signal(marketPhase="open"), 5, 0.5, "QQQ")
    crypto = backtest.execution_slippage_bps(signal(marketPhase="continuous"), 5, 0.5, "BTC-USD")
    self.assertGreater(opening, base)
    self.assertGreater(crypto, base)

  def test_calibration_reports_probability_expectancy_and_interval(self):
    trades = []
    for index in range(20):
      trades.append({
        "timeframe": 1,
        "direction": "long",
        "setupType": "breakout",
        "marketPhase": "morning",
        "enteredAt": 120_000,
        "outcome": "target2" if index < 12 else "stopped",
        "target1Hit": index < 12,
        "realizedR": 1.5 if index < 12 else -1.0,
        "mfeR": 1.8 if index < 12 else 0.3,
        "maeR": 0.2 if index < 12 else 1.0,
        "timeToTarget1Ms": 300_000 if index < 12 else None,
      })
    result = backtest.calibration_for_signal(trades, signal())
    self.assertTrue(result["calibrated"])
    self.assertEqual(result["sampleSize"], 20)
    self.assertAlmostEqual(result["probabilityT1"], 17 / 30)
    self.assertLess(result["confidenceLow"], 0.6)
    self.assertGreater(result["confidenceHigh"], 0.6)
    self.assertGreater(result["expectedR"], 0)

  def test_calibration_never_borrows_samples_from_another_timeframe(self):
    trades = [{
      "timeframe": 1440,
      "direction": "long",
      "setupType": "breakout",
      "marketPhase": "swing",
      "enteredAt": 120_000,
      "outcome": "target2",
      "target1Hit": True,
      "realizedR": 1.5,
      "mfeR": 1.8,
      "maeR": 0.2,
      "timeToTarget1Ms": 86_400_000,
    } for _ in range(30)]
    result = backtest.calibration_for_signal(trades, signal(timeframe=5, setup="Long 5m breakout"))
    self.assertEqual(result["sampleSize"], 0)
    self.assertIsNone(result["probabilityT1"])

  def test_timeframe_summaries_keep_five_minute_results_separate(self):
    trades = [
      {"timeframe": 1, "enteredAt": 1, "outcome": "target2", "realizedR": 1.0, "target1Hit": True, "mfeR": 1.2, "maeR": 0.2, "timeToTarget1Ms": 60_000},
      {"timeframe": 5, "enteredAt": 1, "outcome": "stopped", "realizedR": -1.0, "target1Hit": False, "mfeR": 0.2, "maeR": 1.0, "timeToTarget1Ms": None},
    ]
    summary = backtest.timeframe_summaries(trades)
    self.assertEqual(summary["1"]["resolved"], 1)
    self.assertEqual(summary["5"]["resolved"], 1)
    self.assertEqual(summary["5"]["expectedR"], -1.0)

  def test_summary_reports_drawdown_profit_factor_and_losing_streak(self):
    values = [1.5, -1.0, -1.0, 2.0]
    trades = [{
      "timeframe": 5,
      "enteredAt": index + 1,
      "outcome": "target2" if value > 0 else "stopped",
      "realizedR": value,
      "target1Hit": value > 0,
      "mfeR": max(value, 0),
      "maeR": abs(min(value, 0)),
      "timeToTarget1Ms": 60_000 if value > 0 else None,
    } for index, value in enumerate(values)]
    summary = backtest.summarize(trades)
    self.assertAlmostEqual(summary["profitFactor"], 1.75)
    self.assertEqual(summary["maxDrawdownR"], 2.0)
    self.assertEqual(summary["maxConsecutiveLosses"], 2)

  def test_chronological_validation_keeps_later_trades_in_holdout(self):
    trades = []
    for index in range(20):
      trades.append({
        "timeframe": 5,
        "direction": "long",
        "setupType": "breakout",
        "marketPhase": "morning",
        "signalTime": index,
        "enteredAt": index + 1,
        "outcome": "target2" if index % 2 == 0 else "stopped",
        "target1Hit": index % 2 == 0,
        "realizedR": 1.5 if index % 2 == 0 else -1.0,
        "mfeR": 1.5 if index % 2 == 0 else 0.2,
        "maeR": 0.2 if index % 2 == 0 else 1.0,
        "timeToTarget1Ms": 60_000 if index % 2 == 0 else None,
      })
    result = backtest.chronological_validation(trades)
    self.assertEqual(result["sampleSize"], 20)
    self.assertEqual(result["inSample"]["resolved"], 12)
    self.assertEqual(result["outOfSample"]["resolved"], 8)
    self.assertTrue(result["folds"])


if __name__ == "__main__":
  unittest.main()
