import sqlite3
import unittest

import demo_trading_engine as engine


def candle(timestamp, price, high=None, low=None, close=None):
  return {
    "time": timestamp,
    "open": price,
    "high": price if high is None else high,
    "low": price if low is None else low,
    "close": price if close is None else close,
    "volume": 10_000,
  }


def recommendations(direction="long", signal_at=100_000, score=80):
  long = direction == "long"
  candidate = {
    "direction": direction,
    "watchOnly": False,
    "score": score,
    "riskReward": 2,
    "setup": "Test momentum",
    "setupType": "momentum",
    "entry": 100,
    "stop": 98 if long else 102,
    "target": 104 if long else 96,
    "target2": 108 if long else 92,
    "strategyVersion": "test",
  }
  return {
    5: {**candidate, "signalCandleTime": signal_at, "actionableAt": signal_at + 300_000},
    1440: {
      **candidate,
      "signalCandleTime": signal_at,
      "actionableAt": signal_at + 86_400_000,
      "selectedTrend": {"tone": "positive" if long else "negative"},
    },
  }


def activity_target_recommendations(signal_at=100_000, blocked=False):
  signal = recommendations(signal_at=signal_at, score=52)[5]
  signal.update({
    "watchOnly": True,
    "riskReward": 1.0,
    "dataQuality": "provider blocked" if blocked else "clean",
    "dataHealth": {"tradeAllowed": not blocked},
  })
  return {5: signal}


class DemoTradingEngineTests(unittest.TestCase):
  def setUp(self):
    self.connection = sqlite3.connect(":memory:")
    self.connection.row_factory = sqlite3.Row
    self.connection.execute("PRAGMA foreign_keys=ON")
    engine.init_schema(self.connection, 1_000)

  def tearDown(self):
    self.connection.close()

  def test_account_is_initialized_once_and_never_reset(self):
    engine.init_schema(self.connection, 9_999)
    account = self.connection.execute("SELECT * FROM demo_accounts").fetchone()
    ledger = self.connection.execute("SELECT COUNT(*) total FROM demo_ledger").fetchone()
    self.assertEqual(account["started_at"], 1_000)
    self.assertEqual(account["cash_cents"], 2_000_000)
    self.assertEqual(account["policy_version"], engine.VERSION)
    self.assertEqual(ledger["total"], 1)

  def test_forward_only_signal_and_idempotent_entry_order(self):
    old = recommendations(signal_at=-300_000)
    self.assertEqual(engine.create_entry_orders(self.connection, "QQQ", old, 500_000), 0)
    current = recommendations(signal_at=100_000)
    self.assertEqual(engine.create_entry_orders(self.connection, "QQQ", current, 500_000), 3)
    self.assertEqual(engine.create_entry_orders(self.connection, "QQQ", current, 500_000), 0)
    total = self.connection.execute("SELECT COUNT(*) total FROM demo_orders").fetchone()["total"]
    self.assertEqual(total, 3)

  def test_long_trade_charges_commissions_and_tax_only_on_final_profit(self):
    recs = {5: recommendations()[5]}
    engine.create_entry_orders(self.connection, "QQQ", recs, 500_000)
    engine.fill_pending_entries(self.connection, "QQQ", [candle(400_000, 100)], 1, 500_000, {"day"})
    position = self.connection.execute("SELECT * FROM demo_positions").fetchone()
    self.assertIsNotNone(position)
    self.assertEqual(position["commission_cents"], 500)
    self.assertLess(self.connection.execute("SELECT cash_cents FROM demo_accounts").fetchone()["cash_cents"], 2_000_000)

    engine.evaluate_open_positions(
      self.connection, "QQQ", [candle(700_000, 104, high=104.5, low=103.5)], 1, 700_000,
      horizons={"day"},
    )
    partial = self.connection.execute("SELECT * FROM demo_positions").fetchone()
    self.assertEqual(partial["status"], "open")
    self.assertEqual(partial["commission_cents"], 1_000)
    self.assertEqual(partial["tax_cents"], 0)

    engine.evaluate_open_positions(
      self.connection, "QQQ", [candle(1_000_000, 108, high=109, low=107.5)], 1, 1_000_000,
      horizons={"day"},
    )
    closed = self.connection.execute("SELECT * FROM demo_positions").fetchone()
    self.assertEqual(closed["status"], "closed")
    self.assertEqual(closed["commission_cents"], 1_500)
    self.assertGreater(closed["realized_gross_cents"], 0)
    self.assertEqual(closed["tax_cents"], round(max(0, closed["realized_gross_cents"] - 1_500) * 0.25))
    self.assertEqual(closed["net_pnl_cents"], closed["realized_gross_cents"] - closed["commission_cents"] - closed["tax_cents"])

  def test_losing_trade_has_no_tax_credit(self):
    recs = {5: recommendations()[5]}
    engine.create_entry_orders(self.connection, "QQQ", recs, 500_000)
    engine.fill_pending_entries(self.connection, "QQQ", [candle(400_000, 100)], 1, 500_000, {"day"})
    engine.evaluate_open_positions(
      self.connection, "QQQ", [candle(700_000, 98, high=99, low=97.5)], 1, 700_000,
      horizons={"day"},
    )
    closed = self.connection.execute("SELECT * FROM demo_positions").fetchone()
    self.assertEqual(closed["status"], "closed")
    self.assertEqual(closed["tax_cents"], 0)
    self.assertLess(closed["net_pnl_cents"], 0)
    learning = engine.learning_snapshot(self.connection)
    self.assertEqual(learning["resolvedSamples"], 1)
    self.assertFalse(learning["automaticChangesApplied"])

  def test_narrow_stop_is_widened_beyond_fee_dominated_noise(self):
    signal = recommendations()[5]
    signal.update({"stop": 99.90, "target": 100.30, "target2": 100.60, "atr": 0.25})
    engine.create_entry_orders(self.connection, "QQQ", {5: signal}, 500_000)
    engine.fill_pending_entries(self.connection, "QQQ", [candle(400_000, 100)], 1, 500_000, {"day"})

    position = self.connection.execute("SELECT * FROM demo_positions").fetchone()
    self.assertIsNotNone(position)
    stop_pct = abs(position["entry_price"] - position["stop_price"]) / position["entry_price"]
    gross_stop_cents = round(position["entry_value_cents"] * stop_pct)
    target_r = abs(position["target1_price"] - position["entry_price"]) / abs(position["entry_price"] - position["stop_price"])
    details = engine._json(position["details_json"])["executionStopPolicy"]

    self.assertGreaterEqual(gross_stop_cents, engine.MINIMUM_GROSS_STOP_CENTS)
    self.assertGreaterEqual(stop_pct, engine.STOP_POLICY["day"]["minimum_pct"])
    self.assertGreaterEqual(target_r, engine.STOP_POLICY["day"]["minimum_target_r"] - 1e-9)
    self.assertTrue(details["adjusted"])
    self.assertEqual(details["roundTripCommission"], 10.0)

  def test_valid_wider_structural_stop_is_preserved(self):
    recs = {5: recommendations()[5]}
    engine.create_entry_orders(self.connection, "QQQ", recs, 500_000)
    engine.fill_pending_entries(self.connection, "QQQ", [candle(400_000, 100)], 1, 500_000, {"day"})
    position = self.connection.execute("SELECT * FROM demo_positions").fetchone()
    details = engine._json(position["details_json"])["executionStopPolicy"]

    self.assertAlmostEqual(position["stop_price"], 98.0098, places=4)
    self.assertFalse(details["adjusted"])

  def test_short_trade_is_fully_cash_collateralized(self):
    recs = {5: recommendations("short")[5]}
    engine.create_entry_orders(self.connection, "SPY", recs, 500_000)
    engine.fill_pending_entries(self.connection, "SPY", [candle(400_000, 100)], 1, 500_000, {"day"})
    position = self.connection.execute("SELECT * FROM demo_positions").fetchone()
    account = engine.account_snapshot(self.connection)["account"]
    self.assertGreater(account["shortCollateral"], 0)
    self.assertEqual(account["investedValue"], 0)
    self.assertAlmostEqual(account["equity"], 19_995, delta=0.1)
    self.assertEqual(position["direction"], "short")

  def test_restart_reprocessing_does_not_duplicate_fills_or_ledger(self):
    recs = {5: recommendations()[5]}
    bars = [candle(400_000, 100)]
    engine.process_market(self.connection, "QQQ", recs, bars, [], 1, 500_000)
    first = tuple(self.connection.execute(
      "SELECT (SELECT COUNT(*) FROM demo_orders), (SELECT COUNT(*) FROM demo_fills), (SELECT COUNT(*) FROM demo_ledger)"
    ).fetchone())
    engine.process_market(self.connection, "QQQ", recs, bars, [], 1, 500_000)
    second = tuple(self.connection.execute(
      "SELECT (SELECT COUNT(*) FROM demo_orders), (SELECT COUNT(*) FROM demo_fills), (SELECT COUNT(*) FROM demo_ledger)"
    ).fetchone())
    self.assertEqual(first, second)

  def test_ta125_execution_uses_etf_and_usd_fx_conversion(self):
    recs = {5: recommendations()[5]}
    engine.create_entry_orders(self.connection, "TA125", recs, 500_000)
    engine.fill_pending_entries(self.connection, "TA125", [candle(400_000, 42)], 0.30, 500_000, {"day"})
    position = self.connection.execute("SELECT * FROM demo_positions").fetchone()
    self.assertEqual(position["execution_symbol"], "IBI-F42.TA")
    self.assertEqual(position["currency"], "ILS")
    self.assertAlmostEqual(position["entry_fx_rate"], 0.30)

  def test_simultaneous_horizons_recheck_symbol_and_portfolio_risk_at_fill(self):
    recs = recommendations()
    engine.create_entry_orders(self.connection, "QQQ", recs, 500_000)
    day_bar = [candle(400_000, 100)]
    daily_bar = [candle(86_500_000, 100)]
    engine.fill_pending_entries(self.connection, "QQQ", day_bar, 1, 500_000, {"day"})
    engine.fill_pending_entries(self.connection, "QQQ", daily_bar, 1, 90_000_000, {"swing", "long"})
    exposure = self.connection.execute("SELECT SUM(remaining_basis_cents) total FROM demo_positions WHERE status = 'open'").fetchone()["total"]
    stop_risk = engine._open_risk_cents(self.connection)
    self.assertLessEqual(exposure, 800_000)
    self.assertLessEqual(stop_risk, 80_000)

  def test_activity_target_accepts_safe_watch_candidate_below_normal_threshold(self):
    created = engine.create_entry_orders(self.connection, "QQQ", activity_target_recommendations(), 500_000)
    order = self.connection.execute("SELECT reason, details_json FROM demo_orders").fetchone()
    self.assertEqual(created, 1)
    self.assertEqual(order["reason"], "daily_activity_target")
    self.assertIn('"selectionMode": "activity_target"', order["details_json"])

  def test_activity_target_never_bypasses_blocked_data(self):
    created = engine.create_entry_orders(self.connection, "QQQ", activity_target_recommendations(blocked=True), 500_000)
    self.assertEqual(created, 0)

  def test_activity_target_stops_after_two_recent_day_entries(self):
    for symbol in ("QQQ", "SPY"):
      engine.create_entry_orders(self.connection, symbol, {5: recommendations()[5]}, 500_000)
      engine.fill_pending_entries(self.connection, symbol, [candle(400_000, 100)], 1, 500_000, {"day"})
    self.assertEqual(engine.day_trade_entries_last_24h(self.connection, 500_000), 2)
    created = engine.create_entry_orders(self.connection, "BTC-USD", activity_target_recommendations(), 500_000)
    self.assertEqual(created, 0)


if __name__ == "__main__":
  unittest.main()
