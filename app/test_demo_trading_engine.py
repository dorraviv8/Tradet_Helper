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
    "watchOnly": False,
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
    engine.fill_pending_entries(self.connection, "QQQ", [candle(400_000, 100), candle(700_000, 100)], 1, 700_000, {"day"})
    position = self.connection.execute("SELECT * FROM demo_positions").fetchone()
    self.assertIsNotNone(position)
    self.assertEqual(position["commission_cents"], 500)
    self.assertLess(self.connection.execute("SELECT cash_cents FROM demo_accounts").fetchone()["cash_cents"], 2_000_000)

    engine.evaluate_open_positions(
      self.connection, "QQQ", [candle(1_000_000, 104, high=104.5, low=103.5)], 1, 1_000_000,
      horizons={"day"},
    )
    partial = self.connection.execute("SELECT * FROM demo_positions").fetchone()
    self.assertEqual(partial["status"], "open")
    self.assertEqual(partial["commission_cents"], 1_000)
    self.assertEqual(partial["tax_cents"], 0)

    engine.evaluate_open_positions(
      self.connection, "QQQ", [candle(1_300_000, 108, high=109, low=107.5)], 1, 1_300_000,
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
    engine.fill_pending_entries(self.connection, "QQQ", [candle(400_000, 100), candle(700_000, 100)], 1, 700_000, {"day"})
    engine.evaluate_open_positions(
      self.connection, "QQQ", [candle(1_000_000, 97.5, high=99, low=97.5, close=97.5)], 1, 1_000_000,
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
    engine.fill_pending_entries(self.connection, "QQQ", [candle(400_000, 100), candle(700_000, 100)], 1, 700_000, {"day"})

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
    engine.fill_pending_entries(self.connection, "QQQ", [candle(400_000, 100), candle(700_000, 100)], 1, 700_000, {"day"})
    position = self.connection.execute("SELECT * FROM demo_positions").fetchone()
    details = engine._json(position["details_json"])["executionStopPolicy"]

    self.assertAlmostEqual(position["stop_price"], 98.0, places=4)
    self.assertFalse(details["adjusted"])

  def test_short_trade_is_fully_cash_collateralized(self):
    recs = {5: recommendations("short")[5]}
    engine.create_entry_orders(self.connection, "SPY", recs, 500_000)
    engine.fill_pending_entries(self.connection, "SPY", [candle(400_000, 100), candle(700_000, 100)], 1, 700_000, {"day"})
    position = self.connection.execute("SELECT * FROM demo_positions").fetchone()
    account = engine.account_snapshot(self.connection)["account"]
    self.assertGreater(account["shortCollateral"], 0)
    self.assertEqual(account["investedValue"], 0)
    self.assertAlmostEqual(account["equity"], 19_995, delta=0.1)
    self.assertEqual(position["direction"], "short")

  def test_restart_reprocessing_does_not_duplicate_fills_or_ledger(self):
    recs = {5: recommendations()[5]}
    bars = {5: [candle(400_000, 100), candle(700_000, 100)]}
    engine.process_market(self.connection, "QQQ", recs, bars, [], 1, 700_000)
    first = tuple(self.connection.execute(
      "SELECT (SELECT COUNT(*) FROM demo_orders), (SELECT COUNT(*) FROM demo_fills), (SELECT COUNT(*) FROM demo_ledger)"
    ).fetchone())
    engine.process_market(self.connection, "QQQ", recs, bars, [], 1, 700_000)
    second = tuple(self.connection.execute(
      "SELECT (SELECT COUNT(*) FROM demo_orders), (SELECT COUNT(*) FROM demo_fills), (SELECT COUNT(*) FROM demo_ledger)"
    ).fetchone())
    self.assertEqual(first, second)

  def test_ta125_execution_uses_etf_and_usd_fx_conversion(self):
    recs = {5: recommendations()[5]}
    engine.create_entry_orders(self.connection, "TA125", recs, 500_000)
    engine.fill_pending_entries(self.connection, "TA125", [candle(400_000, 100), candle(700_000, 100)], 0.30, 700_000, {"day"})
    position = self.connection.execute("SELECT * FROM demo_positions").fetchone()
    self.assertEqual(position["execution_symbol"], "IBI-F42.TA")
    self.assertEqual(position["currency"], "ILS")
    self.assertAlmostEqual(position["entry_fx_rate"], 0.30)

  def test_ta125_uses_timestamp_aligned_fx_rate(self):
    recs = {5: recommendations()[5]}
    engine.create_entry_orders(self.connection, "TA125", recs, 500_000)
    fx = [{"time": 300_000, "rate": 0.25}, {"time": 900_000, "rate": 0.30}]
    engine.fill_pending_entries(self.connection, "TA125", [candle(400_000, 100), candle(700_000, 100)], fx, 700_000, {"day"})
    position = self.connection.execute("SELECT * FROM demo_positions").fetchone()
    self.assertAlmostEqual(position["entry_fx_rate"], 0.25)

  def test_simultaneous_horizons_recheck_symbol_and_portfolio_risk_at_fill(self):
    recs = recommendations()
    engine.create_entry_orders(self.connection, "QQQ", recs, 500_000)
    day_bar = [candle(400_000, 100), candle(700_000, 100)]
    daily_bar = [candle(86_500_000, 100), candle(172_900_000, 100)]
    engine.fill_pending_entries(self.connection, "QQQ", day_bar, 1, 700_000, {"day"})
    engine.fill_pending_entries(self.connection, "QQQ", daily_bar, 1, 172_900_000, {"swing", "long"})
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
      engine.fill_pending_entries(self.connection, symbol, [candle(400_000, 100), candle(700_000, 100)], 1, 700_000, {"day"})
    self.assertEqual(engine.day_trade_entries_last_24h(self.connection, 700_000), 2)
    created = engine.create_entry_orders(self.connection, "BTC-USD", activity_target_recommendations(), 700_000)
    self.assertEqual(created, 0)

  def test_entry_does_not_fill_until_native_timeframe_trigger_closes(self):
    recs = {5: recommendations()[5]}
    engine.create_entry_orders(self.connection, "QQQ", recs, 500_000)
    bars = {1: [candle(400_000, 101)], 5: [candle(400_000, 99, high=101, close=99)]}
    self.assertEqual(engine.fill_pending_entries(self.connection, "QQQ", bars, 1, 700_000, {"day"}), 0)
    self.assertEqual(self.connection.execute("SELECT status FROM demo_orders").fetchone()["status"], "pending")
    bars[5].extend([candle(700_000, 100, close=100.2), candle(1_000_000, 100.3)])
    self.assertEqual(engine.fill_pending_entries(self.connection, "QQQ", bars, 1, 1_000_000, {"day"}), 1)

  def test_gap_through_touch_stop_fills_at_worse_open(self):
    engine.create_entry_orders(self.connection, "QQQ", {5: recommendations()[5]}, 500_000)
    engine.fill_pending_entries(self.connection, "QQQ", [candle(400_000, 100), candle(700_000, 100)], 1, 700_000, {"day"})
    self.connection.execute("UPDATE demo_positions SET stop_confirmation = 'touch'")
    engine.evaluate_open_positions(
      self.connection, "QQQ", [candle(1_000_000, 95, high=96, low=94, close=95)],
      1, 1_000_000, horizons={"day"},
    )
    fill = self.connection.execute("SELECT * FROM demo_fills WHERE action = 'exit'").fetchone()
    self.assertLess(fill["price"], 95)
    self.assertEqual(fill["fill_model"], "gap_open")

  def test_closed_short_trade_deducts_borrow_cost_without_tax_credit(self):
    engine.create_entry_orders(self.connection, "SPY", {5: recommendations("short")[5]}, 500_000)
    engine.fill_pending_entries(self.connection, "SPY", [candle(400_000, 100), candle(700_000, 100)], 1, 700_000, {"day"})
    engine.evaluate_open_positions(
      self.connection, "SPY", [candle(1_000_000, 103, high=103, low=102.5, close=103)],
      1, 1_000_000, horizons={"day"},
    )
    position = self.connection.execute("SELECT * FROM demo_positions").fetchone()
    self.assertGreater(position["borrow_cents"], 0)
    self.assertEqual(position["tax_cents"], 0)

  def test_live_quote_revalues_same_forming_timestamp_without_advancing_cursor(self):
    engine.create_entry_orders(self.connection, "QQQ", {5: recommendations()[5]}, 500_000)
    engine.fill_pending_entries(self.connection, "QQQ", [candle(400_000, 100), candle(700_000, 100)], 1, 700_000, {"day"})
    engine.mark_open_positions(self.connection, "QQQ", 101.25, 1, 750_000)
    engine.mark_open_positions(self.connection, "QQQ", 102.25, 1, 750_000)
    position = self.connection.execute("SELECT * FROM demo_positions").fetchone()
    self.assertEqual(position["last_price"], 102.25)
    self.assertEqual(position["last_intraday_bar_at"], 699_999)

  def test_cash_ledger_mismatch_is_a_critical_invariant(self):
    self.connection.execute("UPDATE demo_accounts SET cash_cents = cash_cents - 1")
    findings = engine.invariant_findings(self.connection, 500_000)
    self.assertTrue(any(severity == "critical" and "reconcile" in message for severity, message in findings))

  def test_learning_separates_policy_cohorts_and_uses_actual_risk(self):
    for policy, opened_at in (("legacy", 10_000), (engine.VERSION, 20_000)):
      self.connection.execute("""
        INSERT INTO demo_orders (id, idempotency_key, account_id, symbol, execution_symbol, currency,
          horizon, timeframe, direction, action, status, signal_at, eligible_at, planned_risk_cents,
          max_notional_cents, created_at, updated_at)
        VALUES (?, ?, 'primary', 'QQQ', 'QQQ', 'USD', 'day', 5, 'long', 'entry', 'filled', ?, ?, 99999, 100000, ?, ?)
      """, (f"o-{policy}", f"k-{policy}", opened_at, opened_at, opened_at, opened_at))
      self.connection.execute("""
        INSERT INTO demo_positions (id, account_id, entry_order_id, symbol, execution_symbol, currency,
          horizon, timeframe, direction, setup, setup_type, score, signal_at, opened_at, closed_at,
          status, quantity, remaining_quantity, entry_price, entry_fx_rate, entry_value_cents,
          remaining_basis_cents, stop_price, target1_price, target2_price, last_price, last_fx_rate,
          last_valued_at, last_bar_at, net_pnl_cents, strategy_version, initial_risk_cents, policy_version)
        VALUES (?, 'primary', ?, 'QQQ', 'QQQ', 'USD', 'day', 5, 'long', 'test', 'momentum', 70,
          ?, ?, ?, 'closed', 1, 0, 100, 1, 10000, 0, 98, 104, 108, 104, 1, ?, ?, 1000,
          'test', 2000, ?)
      """, (f"p-{policy}", f"o-{policy}", opened_at, opened_at, opened_at + 1, opened_at + 1, opened_at + 1, policy))
    snapshot = engine.learning_snapshot(self.connection)
    self.assertEqual(len(snapshot["cohorts"]), 2)
    self.assertTrue(all(row["expectedR"] == 0.5 for row in snapshot["cohorts"]))


if __name__ == "__main__":
  unittest.main()
