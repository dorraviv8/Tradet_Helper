import base64
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))

import server


def candle(time, open_price, high, low, close, volume=100):
  return {
    "time": time,
    "open": open_price,
    "high": high,
    "low": low,
    "close": close,
    "volume": volume,
  }


def option_signal(direction="long", timeframe=5):
  long = direction == "long"
  return {
    "timeframe": timeframe,
    "direction": direction,
    "watchOnly": False,
    "score": 88,
    "setup": "Momentum continuation",
    "setupType": "momentum",
    "dataQuality": "clean",
    "riskReward": 1.5,
    "entry": 600,
    "stop": 598 if long else 602,
    "target": 603 if long else 597,
    "target2": 605 if long else 595,
    "signalCandleTime": 1_780_000_000_000,
    "actionableAt": 1_780_000_300_000,
    "trend5": {"tone": "positive" if long else "negative"},
    "trend15": {"tone": "positive" if long else "negative"},
    "regime": {"type": "trend_up" if long else "trend_down"},
  }


class ServerTests(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.old_db_path = server.DB_PATH
    self.old_legacy_path = server.LEGACY_DB_PATH
    self.old_app_password = server.APP_PASSWORD
    server.DB_PATH = os.path.join(self.tmp.name, "journal.sqlite3")
    server.LEGACY_DB_PATH = os.path.join(self.tmp.name, "missing.sqlite3")
    server.init_db()

  def tearDown(self):
    server.DB_PATH = self.old_db_path
    server.LEGACY_DB_PATH = self.old_legacy_path
    server.APP_PASSWORD = self.old_app_password
    self.tmp.cleanup()

  def insert_plan(self, plan_id, **overrides):
    row = {
      "id": plan_id,
      "created_at": 60_000,
      "updated_at": 60_000,
      "symbol": "QQQ",
      "provider": "test",
      "timeframe": 1,
      "direction": "long",
      "setup": "test setup",
      "setup_type": "test",
      "market_phase": "morning",
      "status": "alert",
      "score": 80,
      "entry": 100.0,
      "stop": 99.0,
      "target1": 101.0,
      "target2": 102.0,
      "risk_reward": 2.0,
      "price_at_plan": 100.0,
      "strategy_version": server.STRATEGY_VERSION,
      "eligible_for_learning": 1,
      "outcome_status": "open",
      "lifecycle_status": "waiting",
      "realized_r": None,
      "closed_at": None,
      "signal_candle_time": None,
      "entry_confirmation": "touch",
    }
    row.update(overrides)
    with server.db() as connection:
      connection.execute("""
        INSERT INTO plans (
          id, created_at, updated_at, symbol, provider, timeframe, direction, setup, setup_type,
          market_phase, status, score, entry, stop, target1, target2, risk_reward, price_at_plan,
          strategy_version, eligible_for_learning, outcome_status, lifecycle_status, realized_r, closed_at,
          signal_candle_time, entry_confirmation
        ) VALUES (
          :id, :created_at, :updated_at, :symbol, :provider, :timeframe, :direction, :setup, :setup_type,
          :market_phase, :status, :score, :entry, :stop, :target1, :target2, :risk_reward, :price_at_plan,
          :strategy_version, :eligible_for_learning, :outcome_status, :lifecycle_status, :realized_r, :closed_at,
          :signal_candle_time, :entry_confirmation
        )
      """, row)

  def test_native_five_minute_storage_rejects_non_boundary_quote(self):
    boundary = 1_780_000_100_000
    boundary -= boundary % (5 * server.MINUTE_MS)
    malformed = boundary + 4 * server.MINUTE_MS
    saved = server.save_market_bars("QQQ", 5, "yahoo", [
      candle(boundary, 100, 101, 99, 100.5, 1_000),
      candle(malformed, 100.6, 100.6, 100.6, 100.6, 0),
    ])
    self.assertEqual(saved, 1)
    rows = server.load_market_bars("QQQ", 5)
    self.assertEqual([row["time"] for row in rows], [boundary])

  def fetch_plan(self, plan_id):
    with server.db() as connection:
      return dict(connection.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone())

  def test_yahoo_synthetic_latest_quote_is_dropped_and_bucketed(self):
    minute = 1_800_000
    payload = {
      "chart": {
        "result": [{
          "timestamp": [minute // 1000, (minute + 37_000) // 1000],
          "indicators": {
            "quote": [{
              "open": [100, 101],
              "high": [101, 101],
              "low": [99, 101],
              "close": [100.5, 101],
              "volume": [1000, 0],
            }]
          },
        }]
      }
    }
    candles = server.normalize_yahoo_chart(payload)
    self.assertEqual(len(candles), 1)
    self.assertEqual(candles[0]["time"], minute)
    self.assertEqual(candles[0]["close"], 100.5)

  def test_pattern_observation_tracks_breakout_then_target(self):
    detected = int(datetime(2026, 7, 31, 14, 0, tzinfo=timezone.utc).timestamp() * 1000)
    pattern = server.validate_pattern_payload({
      "symbol": "QQQ",
      "timeframe": 1,
      "name": "Bull Flag",
      "direction": "up",
      "detectedAt": detected,
      "breakout": 100,
      "target": 102,
      "invalidation": 99,
      "measuredMove": 2,
    })
    with server.db() as connection:
      self.assertTrue(server.save_pattern_observation(connection, pattern))
      server.evaluate_pattern_observations(connection, "QQQ", [
        candle(detected + 60_000, 99.8, 100.2, 99.7, 100.1),
        candle(detected + 120_000, 100.2, 102.1, 100.1, 102.0),
      ])
      row = connection.execute("SELECT * FROM pattern_observations WHERE id = ?", (pattern["id"],)).fetchone()
      stats = server.pattern_validation_stats(connection, "QQQ")
    self.assertEqual(row["status"], "target")
    self.assertEqual(row["eligible_for_learning"], 1)
    self.assertEqual(stats[0]["targets"], 1)
    self.assertFalse(stats[0]["validated"])

  def test_database_backup_is_integrity_checked(self):
    old_backup_dir = server.BACKUP_DIR
    old_persistent_dir = server.PERSISTENT_DATA_DIR
    try:
      server.PERSISTENT_DATA_DIR = self.tmp.name
      server.BACKUP_DIR = os.path.join(self.tmp.name, "backups")
      path = server.backup_database(1_800_000_000_000)
      self.assertTrue(os.path.isfile(path))
      self.assertEqual(server.BACKUP_STATE["integrity"], "ok")
    finally:
      server.BACKUP_DIR = old_backup_dir
      server.PERSISTENT_DATA_DIR = old_persistent_dir

  def test_concurrent_writes_are_serialized_without_database_lock_errors(self):
    def write(index):
      with server.db() as connection:
        connection.execute("""
          INSERT INTO system_incidents (
            incident_key, severity, message, status, first_seen_at, last_seen_at, occurrences
          ) VALUES (?, 'warning', 'test', 'resolved', ?, ?, 1)
        """, (f"concurrent:{index}", index, index))
      return index

    with ThreadPoolExecutor(max_workers=12) as executor:
      completed = list(executor.map(write, range(40)))
    self.assertEqual(completed, list(range(40)))
    with server.db() as connection:
      total = connection.execute("SELECT COUNT(*) total FROM system_incidents WHERE incident_key LIKE 'concurrent:%'").fetchone()["total"]
    self.assertEqual(total, 40)

  def test_ta125_uses_yahoo_tel_aviv_index_symbol(self):
    payload = {
      "chart": {
        "result": [{
          "timestamp": [1_800],
          "indicators": {"quote": [{
            "open": [4_000], "high": [4_010], "low": [3_995], "close": [4_005], "volume": [0],
          }]},
        }],
      },
    }
    with patch.object(server, "yahoo_get", return_value=payload) as yahoo_get:
      candle = server.fetch_latest_candle("yahoo", "TA125")
    self.assertEqual(candle["close"], 4_005)
    self.assertEqual(yahoo_get.call_args.args[0], "/v8/finance/chart/^TA125.TA")
    self.assertEqual(server.active_provider("TA125"), "yahoo")

  def test_zero_volume_quote_outlier_is_rejected(self):
    self.assertIsNone(server.normalized_candle(
      candle(120_000, 100.0, 100.1, 92.0, 100.05, volume=0)
    ))
    self.assertIsNotNone(server.normalized_candle(
      candle(120_000, 100.0, 100.1, 99.9, 100.05, volume=0)
    ))

  def test_daily_history_is_persisted_separately(self):
    candles = [
      candle(86_400_000, 100, 102, 99, 101, 1_000),
      candle(172_800_000, 101, 103, 100, 102, 2_000),
    ]
    self.assertEqual(server.save_daily_candles("QQQ", "yahoo", candles, fetched_at=123_456), 2)
    loaded, fetched_at = server.load_daily_candles("QQQ")
    self.assertEqual(loaded, candles)
    self.assertEqual(fetched_at, 123_456)

  def test_history_uses_persisted_cache_when_provider_fetch_fails(self):
    cached = [candle(60_000, 100, 101, 99, 100.5, 1_000)]
    with server.db() as connection:
      server.save_candles(connection, "BTC-USD", "yahoo", cached)
    with patch.object(server, "fetch_history_candles", side_effect=server.URLError("temporary outage")):
      candles, degraded = server.history_candles_with_fallback("yahoo", "BTC-USD", {"history": []})
    self.assertEqual(candles, cached)
    self.assertTrue(degraded)

  def test_secondary_quote_requires_two_mismatches_before_blocking_status(self):
    now = 1_780_000_000_000
    profile = {
      "provider": "test",
      "name": "Independent test feed",
      "configured": True,
      "tolerancePct": 0.5,
      "freshnessMs": 180_000,
    }
    primary = candle(now, 100, 101, 99, 100, 1_000)
    with patch.object(server, "secondary_provider_profile", return_value=profile), patch.object(
      server, "fetch_secondary_quote", return_value={"price": 102, "time": now}
    ):
      first = server.validate_secondary_quote("QQQ", primary, timestamp=now)
      second = server.validate_secondary_quote("QQQ", primary, first, timestamp=now + 60_000)
    self.assertEqual(first["status"], "checking")
    self.assertEqual(first["mismatchCount"], 1)
    self.assertEqual(second["status"], "mismatch")
    self.assertEqual(second["mismatchCount"], 2)
    self.assertGreater(second["driftPct"], 1.9)

  def test_secondary_quote_verifies_close_prices_within_tolerance(self):
    now = 1_780_000_000_000
    profile = {
      "provider": "test",
      "name": "Independent test feed",
      "configured": True,
      "tolerancePct": 0.5,
      "freshnessMs": 180_000,
    }
    with patch.object(server, "secondary_provider_profile", return_value=profile), patch.object(
      server, "fetch_secondary_quote", return_value={"price": 100.1, "time": now - 10_000}
    ):
      result = server.validate_secondary_quote(
        "QQQ", candle(now, 100, 101, 99, 100, 1_000), timestamp=now
      )
    self.assertEqual(result["status"], "verified")
    self.assertEqual(result["failures"], 0)
    self.assertLess(result["driftPct"], result["tolerancePct"])

  def test_secondary_quote_waits_for_three_failures_before_unavailable(self):
    profile = {
      "provider": "test",
      "name": "Independent test feed",
      "configured": True,
      "tolerancePct": 0.5,
      "freshnessMs": 180_000,
    }
    primary = candle(1_780_000_000_000, 100, 101, 99, 100, 1_000)
    result = None
    with patch.object(server, "secondary_provider_profile", return_value=profile), patch.object(
      server, "fetch_secondary_quote", side_effect=server.URLError("offline")
    ):
      for index in range(3):
        result = server.validate_secondary_quote("QQQ", primary, result, 1_780_000_000_000 + index * 60_000)
    self.assertEqual(result["status"], "unavailable")
    self.assertEqual(result["failures"], 3)

  def test_monitoring_incidents_open_update_and_resolve_without_repeat_alerts(self):
    notifications = []
    notifier = lambda event, incident: notifications.append((event, incident["incident_key"])) or True
    findings = {"QQQ:provider_errors": ("warning", "QQQ: provider has errors")}
    with server.db() as connection:
      opened = server.reconcile_monitoring_incidents(connection, findings, timestamp=1_000, notifier=notifier)
      updated = server.reconcile_monitoring_incidents(connection, findings, timestamp=2_000, notifier=notifier)
      resolved = server.reconcile_monitoring_incidents(connection, {}, timestamp=3_000, notifier=notifier)
      row = connection.execute("SELECT status, occurrences, resolved_at FROM system_incidents WHERE incident_key = ?", ("QQQ:provider_errors",)).fetchone()
    self.assertEqual(opened[0]["event"], "opened")
    self.assertEqual(updated, [])
    self.assertEqual(resolved[0]["event"], "resolved")
    self.assertEqual(notifications, [("INCIDENT", "QQQ:provider_errors"), ("RECOVERED", "QQQ:provider_errors")])
    self.assertEqual(row["status"], "resolved")
    self.assertEqual(row["occurrences"], 2)
    self.assertEqual(row["resolved_at"], 3_000)

  def test_prometheus_metrics_expose_symbol_health_and_incidents(self):
    metrics = server.prometheus_metrics()
    self.assertIn("trader_helper_up 1", metrics)
    self.assertIn('trader_helper_provider_errors{symbol="QQQ"}', metrics)
    self.assertIn('trader_helper_trade_alerts_allowed{symbol="BTC-USD"}', metrics)
    self.assertIn('trader_helper_secondary_price_drift_pct{symbol="BTC-USD"}', metrics)
    self.assertIn('trader_helper_secondary_price_verified{symbol="QQQ"}', metrics)
    self.assertIn("trader_helper_demo_worker_healthy", metrics)
    self.assertIn("trader_helper_demo_invariant_findings", metrics)

  def test_demo_execution_bundle_excludes_forming_candles(self):
    closed_time = 1_780_000_800_000
    closed_time -= closed_time % (5 * server.MINUTE_MS)
    forming_time = closed_time + 5 * server.MINUTE_MS
    timestamp = forming_time + 30_000
    runtime = server.new_market_runtime()
    runtime["history"] = [
      candle(closed_time, 100, 101, 99, 100.5),
      candle(forming_time, 100.5, 102, 100, 101.5),
    ]
    bundle = server.demo_execution_bundle("QQQ", runtime, timestamp)
    self.assertEqual(bundle["intraday"][5][-1]["time"], closed_time)
    self.assertNotIn(forming_time, [bar["time"] for bar in bundle["intraday"][1]])

  def test_supported_symbols_include_bitcoin_and_spy(self):
    self.assertEqual(server.validate_symbol("btc-usd"), "BTC-USD")
    self.assertEqual(server.validate_symbol("spy"), "SPY")
    with self.assertRaises(ValueError):
      server.validate_symbol("IWM")

  def test_market_runtimes_are_isolated_by_symbol(self):
    with server.MARKET_RUNTIME_LOCK:
      old_qqq = server.MARKET_RUNTIMES["QQQ"]
      old_btc = server.MARKET_RUNTIMES["BTC-USD"]
      server.MARKET_RUNTIMES["QQQ"] = server.new_market_runtime()
      server.MARKET_RUNTIMES["BTC-USD"] = server.new_market_runtime()
      server.MARKET_RUNTIMES["QQQ"]["candle"] = candle(60_000, 100, 101, 99, 100.5)
      server.MARKET_RUNTIMES["BTC-USD"]["candle"] = candle(60_000, 60_000, 60_100, 59_900, 60_050)
    try:
      self.assertEqual(server.market_runtime_snapshot("QQQ")["candle"]["close"], 100.5)
      self.assertEqual(server.market_runtime_snapshot("BTC-USD")["candle"]["close"], 60_050)
    finally:
      with server.MARKET_RUNTIME_LOCK:
        server.MARKET_RUNTIMES["QQQ"] = old_qqq
        server.MARKET_RUNTIMES["BTC-USD"] = old_btc

  def test_backtest_result_round_trips_separately_from_journal(self):
    result = {"generatedAt": 123_456, "summary": {"resolved": 20}, "groups": [], "trades": []}
    with server.db() as connection:
      server.save_backtest_result(connection, "signature", result)
    with server.db() as connection:
      loaded = server.load_latest_backtest(connection)
      plan_count = connection.execute("SELECT COUNT(*) AS total FROM plans").fetchone()["total"]
    self.assertEqual(loaded["summary"]["resolved"], 20)
    self.assertEqual(loaded["sourceSignature"], "signature")
    self.assertEqual(plan_count, 0)

  def test_duplicate_trade_theses_are_quarantined_from_learning(self):
    signal_time = 1_780_000_000_000
    self.insert_plan(
      "revision-a", signal_candle_time=signal_time, setup="Long 1D EMA 20 rejection",
      timeframe=1440, realized_r=-1.0, outcome_status="stopped", lifecycle_status="closed", closed_at=signal_time + 1,
    )
    self.insert_plan(
      "revision-b", signal_candle_time=signal_time, setup="Long 1D EMA 20 rejection",
      timeframe=1440, entry=100.2, realized_r=-1.0, outcome_status="stopped", lifecycle_status="closed", closed_at=signal_time + 2,
    )
    with server.db() as connection:
      self.assertEqual(server.repair_duplicate_plan_learning(connection), 1)
      rows = connection.execute("SELECT id, eligible_for_learning, duplicate_of FROM plans ORDER BY id").fetchall()
      snapshot = server.build_learning_snapshot(connection, "QQQ")
      scoreboard = {row["symbol"]: row for row in server.recommendation_scoreboard(connection)}
    self.assertEqual(sum(int(row["eligible_for_learning"]) for row in rows), 1)
    self.assertEqual(sum(row["duplicate_of"] is not None for row in rows), 1)
    self.assertEqual(snapshot["resolvedSamples"], 1)
    self.assertEqual(scoreboard["QQQ"]["recommended"], 1)

  def test_same_signal_candle_revises_one_waiting_plan(self):
    base = {
      "direction": "long", "watchOnly": False, "score": 82,
      "setup": "Long 5m momentum continuation", "setupType": "momentum",
      "entry": 100.0, "stop": 99.0, "target": 101.2, "target2": 102.0,
      "riskReward": 1.2, "signalCandleTime": 1_780_000_000_000,
      "actionableAt": 1_780_000_300_000, "marketPhase": "morning",
      "regime": {"type": "trend_up"}, "reasons": [], "exitRules": [],
      "latestIndicator": {"close": 99.8},
      "executionQuality": {"status": "passed", "entryConfirmation": "close"},
    }
    with server.db() as connection:
      with patch.object(server, "now_ms", return_value=base["actionableAt"] + 60_000):
        first = server.persist_generated_signal(connection, "test", 5, base, {"activeTradeThreshold": 62}, "QQQ")
        revised = {**base, "entry": 100.25, "target": 101.45, "target2": 102.25, "actionableAt": base["actionableAt"] + 60_000}
        second = server.persist_generated_signal(connection, "test", 5, revised, {"activeTradeThreshold": 62}, "QQQ")
      rows = connection.execute("SELECT * FROM plans").fetchall()
      events = connection.execute("SELECT event_type FROM plan_events WHERE plan_id = ? ORDER BY id", (first,)).fetchall()
    self.assertEqual(first, second)
    self.assertEqual(len(rows), 1)
    self.assertEqual(rows[0]["entry"], 100.25)
    self.assertEqual(rows[0]["revision_count"], 1)
    self.assertEqual([row["event_type"] for row in events], ["created", "revised"])

  def test_close_confirmation_does_not_enter_on_intrabar_touch(self):
    self.insert_plan("close-confirm", entry_confirmation="close", entry=101, stop=99, target1=102, target2=103)
    with server.db() as connection:
      server.evaluate_plans(connection, "QQQ", [candle(120_000, 100, 101.5, 99.5, 100.5)])
    self.assertEqual(self.fetch_plan("close-confirm")["lifecycle_status"], "waiting")

  def test_shadow_candidates_are_deduplicated_and_isolated_from_live_learning(self):
    signal_time = int(datetime(2026, 7, 31, 14, 0, tzinfo=timezone.utc).timestamp() * 1000)
    candidate = {
      "direction": "long", "watchOnly": True, "score": 58,
      "setup": "Long 5m momentum continuation", "setupType": "momentum",
      "entry": 101.0, "stop": 100.0, "target": 102.0, "target2": 103.0,
      "riskReward": 1.0, "marketPhase": "morning", "reasons": [], "exitRules": [],
      "executionQuality": {"status": "passed", "entryConfirmation": "close", "riskBps": 99, "estimatedRoundTripCostBps": 1},
    }
    signal = {
      "direction": "neutral", "signalCandleTime": signal_time, "actionableAt": signal_time + 5 * server.MINUTE_MS,
      "latestIndicator": {"close": 100.8, "atr": 0.5}, "regime": {"type": "range"},
      "_shadowCandidates": [candidate],
    }
    with server.db() as connection:
      with patch.object(server, "now_ms", return_value=signal["actionableAt"] + 1):
        first = server.persist_shadow_candidate_pool(connection, "test", 5, signal, {"activeTradeThreshold": 62, "mode": "normal"}, None, "QQQ", {"tradeAllowed": True})
        second = server.persist_shadow_candidate_pool(connection, "test", 5, signal, {"activeTradeThreshold": 62, "mode": "normal"}, None, "QQQ", {"tradeAllowed": True})
      rows = connection.execute("SELECT * FROM plans WHERE status = 'shadow'").fetchall()
      snapshot = server.shadow_learning_snapshot(connection, "QQQ")
      cached_snapshot = server.shadow_learning_snapshot(connection, "QQQ")
      cache_rows = connection.execute("SELECT COUNT(*) FROM shadow_candidate_snapshots").fetchone()[0]
      scoreboard = {row["symbol"]: row for row in server.recommendation_scoreboard(connection)}
    self.assertEqual((first, second), (1, 0))
    self.assertEqual(len(rows), 1)
    self.assertEqual(rows[0]["eligible_for_learning"], 0)
    self.assertEqual(rows[0]["strategy_version"], server.SHADOW_CANDIDATE_VERSION)
    self.assertEqual(snapshot["tracked"], 1)
    self.assertEqual(cached_snapshot["generatedAt"], snapshot["generatedAt"])
    self.assertEqual(cache_rows, 1)
    self.assertEqual(scoreboard["QQQ"]["recommended"], 0)

  def test_shadow_entry_uses_close_confirmation_and_time_exit(self):
    self.insert_plan(
      "shadow-close", status="shadow", strategy_version=server.SHADOW_CANDIDATE_VERSION,
      eligible_for_learning=0, entry_confirmation="close", entry=101, stop=99,
      target1=102, target2=103, lifecycle_status="waiting",
    )
    with patch.object(server.notification_engine, "send_async") as notify:
      with server.db() as connection:
        server.evaluate_plans(connection, "QQQ", [candle(120_000, 100, 101.5, 99.5, 100.5)])
        waiting = dict(connection.execute("SELECT * FROM plans WHERE id = 'shadow-close'").fetchone())
        server.evaluate_plans(connection, "QQQ", [candle(180_000, 100.5, 101.3, 100.4, 101.1)])
        entered = dict(connection.execute("SELECT * FROM plans WHERE id = 'shadow-close'").fetchone())
        server.evaluate_plans(connection, "QQQ", [candle(60_000 + 4 * 60 * server.MINUTE_MS + server.MINUTE_MS, 101.2, 101.4, 101.0, 101.2)])
        closed = dict(connection.execute("SELECT * FROM plans WHERE id = 'shadow-close'").fetchone())
    self.assertEqual(waiting["lifecycle_status"], "waiting")
    self.assertEqual(entered["lifecycle_status"], "entered")
    self.assertEqual(closed["outcome_status"], "time_exit")
    self.assertAlmostEqual(closed["realized_r"], 0.1)
    notify.assert_not_called()

  def test_backtest_results_are_scoped_by_symbol(self):
    with server.db() as connection:
      server.save_backtest_result(connection, "qqq-signature", {"generatedAt": 1, "summary": {"resolved": 10}}, "QQQ")
      server.save_backtest_result(connection, "btc-signature", {"generatedAt": 2, "summary": {"resolved": 20}}, "BTC-USD")
    with server.db() as connection:
      self.assertEqual(server.load_latest_backtest(connection, "QQQ")["summary"]["resolved"], 10)
      self.assertEqual(server.load_latest_backtest(connection, "BTC-USD")["summary"]["resolved"], 20)

  def test_shadow_experiment_persists_deduplicated_trade_outcomes(self):
    variant = {
      "id": "quality-threshold-v1",
      "version": f"{server.STRATEGY_VERSION}-shadow-quality-threshold-v1",
      "settings": {"activeTradeThreshold": 66, "mode": "normal"},
    }
    result = {
      "generatedAt": 123_456,
      "symbol": "QQQ",
      "summary": {"resolved": 1, "expectedR": 0.4},
      "byTimeframe": {"5": {"resolved": 1}},
      "groups": [],
      "validation": {"status": "building", "outOfSample": {"resolved": 0}},
      "method": {"lookAheadSafe": True},
      "contextPolicy": {"version": "test-router", "blocked": [], "preferred": []},
      "trades": [{
        "timeframe": 5,
        "direction": "long",
        "setup": "Long 5m breakout",
        "setupType": "breakout",
        "marketPhase": "morning",
        "marketRegime": "trend_up",
        "qualityScore": 78,
        "signalTime": 60_000,
        "entry": 100.0,
        "stop": 99.0,
        "target1": 101.0,
        "target2": 102.0,
        "enteredAt": 120_000,
        "closedAt": 180_000,
        "outcome": "target2",
        "target1Hit": True,
        "realizedR": 1.9,
        "mfeR": 2.1,
        "maeR": 0.2,
      }],
    }
    with server.db() as connection:
      server.save_shadow_experiment_result(connection, "source-a", variant, result, "QQQ")
      result["trades"][0]["mfeR"] = 2.2
      server.save_shadow_experiment_result(connection, "source-a", variant, result, "QQQ")
    with server.db() as connection:
      experiments = server.load_latest_shadow_results(connection, "QQQ")
      trade = connection.execute("SELECT * FROM shadow_trade_results").fetchone()
      run_count = connection.execute("SELECT COUNT(*) AS total FROM shadow_experiment_runs").fetchone()["total"]
    self.assertEqual(run_count, 1)
    self.assertEqual(len(experiments), 1)
    self.assertEqual(experiments[0]["result"]["contextPolicy"]["version"], "test-router")
    self.assertEqual(trade["market_regime"], "trend_up")
    self.assertEqual(trade["realized_r"], 1.9)
    self.assertEqual(trade["mfe_r"], 2.2)

  def test_shadow_experiments_can_be_scoped_to_champion_source_signature(self):
    def save(signature, generated_at):
      variant = {
        "id": "quality-threshold-v1",
        "version": f"{server.STRATEGY_VERSION}-shadow-quality-threshold-v1",
        "settings": {"activeTradeThreshold": 66},
      }
      result = {
        "generatedAt": generated_at,
        "summary": {"resolved": generated_at},
        "trades": [],
      }
      server.save_shadow_experiment_result(connection, signature, variant, result, "QQQ")

    with server.db() as connection:
      save("source-old", 100)
      save("source-current", 200)
      current = server.load_latest_shadow_results(connection, "QQQ", "source-current")
      old = server.load_latest_shadow_results(connection, "QQQ", "source-old")
    self.assertEqual(current[0]["sourceSignature"], "source-current")
    self.assertEqual(current[0]["result"]["summary"]["resolved"], 200)
    self.assertEqual(old[0]["sourceSignature"], "source-old")
    self.assertEqual(old[0]["result"]["summary"]["resolved"], 100)

  def test_shadow_snapshot_ranks_review_eligible_variant_first(self):
    def replay(expected_r):
      return {
        "summary": {"resolved": 300, "expectedR": expected_r},
        "groups": [],
        "validation": {
          "outOfSample": {"resolved": 140, "expectedR": expected_r, "profitFactor": 1.5, "maxDrawdownR": 4.0},
          "folds": [{"test": {"resolved": 40, "expectedR": 0.1}} for _ in range(3)],
        },
      }
    champion = replay(0.10)
    definitions = server.shadow_engine.variants(server.load_strategy_settings(), server.STRATEGY_VERSION)
    experiments = [
      {"id": definitions[0]["id"], "version": definitions[0]["version"], "generatedAt": 100, "result": replay(0.18)},
      {"id": definitions[1]["id"], "version": definitions[1]["version"], "generatedAt": 100, "result": replay(0.05)},
    ]
    snapshot = server.build_shadow_experiment_snapshot(champion, experiments, server.load_strategy_settings())
    self.assertEqual(snapshot["bestVariantId"], "quality-threshold-v1")
    self.assertEqual(snapshot["variants"][0]["comparison"]["status"], "eligible_for_review")
    self.assertFalse(snapshot["autoPromote"])

  def test_context_routing_attaches_shadow_decision_without_blocking_production(self):
    candidate = {
      "direction": "long", "setupType": "breakout", "timeframe": 5,
      "marketPhase": "midday", "watchOnly": False,
    }
    signal = {**candidate, "regime": {"type": "chop"}, "bestLong": candidate, "bestShort": None}
    policy_row = {
      "key": "breakout|5|long|chop|midday", "samples": 22,
      "calibratedExpectedR": -0.4, "winRate": 0.3,
    }
    snapshot = {"variants": [{
      "id": server.context_router.VERSION,
      "contextPolicy": {"blocked": [policy_row], "preferred": []},
    }]}
    server.attach_context_routing(signal, snapshot)
    self.assertEqual(signal["contextRouting"]["status"], "block")
    self.assertEqual(candidate["contextRouting"]["status"], "block")
    self.assertFalse(signal["contextRouting"]["appliedToProduction"])
    self.assertFalse(signal["watchOnly"])

  def test_shadow_comparison_filters_champion_to_same_window_and_timeframes(self):
    def trade(timeframe, signal_time, realized_r):
      return {
        "timeframe": timeframe, "signalTime": signal_time, "enteredAt": signal_time + 1,
        "closedAt": signal_time + 2, "outcome": "target2" if realized_r > 0 else "stopped",
        "realizedR": realized_r, "target1Hit": realized_r > 0, "mfeR": 1.2,
        "maeR": 0.3, "timeToTarget1Ms": 1 if realized_r > 0 else None,
        "setupType": "breakout", "marketPhase": "morning", "marketRegime": "trend_up",
        "direction": "long",
      }
    champion = {"trades": [trade(1, 150, -1.0), trade(5, 50, -1.0), trade(5, 150, 1.0), trade(1440, 180, 0.5), trade(5, 250, -1.0)]}
    challenger = {"evaluationWindow": {"start": 100, "end": 200, "timeframes": [5, 1440]}}
    comparable = server.champion_for_shadow_window(champion, challenger)
    self.assertEqual(comparable["summary"]["resolved"], 2)
    self.assertEqual(comparable["summary"]["totalR"], 1.5)
    self.assertEqual(set(comparable["byTimeframe"]), {"5", "1440"})

  def test_historical_replay_is_throttled_after_starting(self):
    runtime = server.new_market_runtime()
    runtime["five_minute_history"] = [candle(index * 300_000, 100, 101, 99, 100) for index in range(160)]
    runtime["backtest_last_started_at"] = 1_000_000
    with server.MARKET_RUNTIME_LOCK:
      original = server.MARKET_RUNTIMES["QQQ"]
      server.MARKET_RUNTIMES["QQQ"] = runtime
    try:
      with patch.object(server, "now_ms", return_value=1_000_000 + server.BACKTEST_MIN_REPLAY_INTERVAL_MS - 1):
        self.assertFalse(server.schedule_historical_replay("QQQ"))
    finally:
      with server.MARKET_RUNTIME_LOCK:
        server.MARKET_RUNTIMES["QQQ"] = original

  def test_matching_champion_replay_is_refreshed_when_shadow_results_are_missing(self):
    runtime = {"backtest": {"sourceSignature": "same"}, "shadow_experiments": None}
    self.assertFalse(server.replay_snapshot_is_current(runtime, "same"))
    runtime["shadow_experiments"] = {"variants": []}
    self.assertFalse(server.replay_snapshot_is_current(runtime, "same"))
    runtime["shadow_experiments"] = {"variants": [{"id": server.context_router.VERSION}]}
    self.assertTrue(server.replay_snapshot_is_current(runtime, "same"))

  def test_data_health_blocks_missing_intraday_bars_during_market_hours(self):
    now = int(datetime(2026, 7, 27, 15, 0, tzinfo=timezone.utc).timestamp() * 1000)
    runtime = server.new_market_runtime()
    minute = 60_000
    runtime["history"] = [
      candle(now - (24 - index) * minute, 100, 101, 99, 100.5, 1_000)
      for index in range(24)
      if index != 12
    ]
    runtime["candle"] = candle(now, 100, 101, 99, 100.5, 1_000)
    runtime["five_minute_history"] = [
      candle(now - (36 - index) * 5 * minute, 100, 101, 99, 100.5, 2_000)
      for index in range(36)
    ]
    runtime["daily_history"] = [
      candle(now - (220 - index) * 86_400_000, 100, 101, 99, 100.5, 2_000)
      for index in range(220)
    ]
    runtime["last_success_at"] = now
    health = server.evaluate_data_health("QQQ", runtime, now)
    self.assertEqual(health["status"], "Blocked")
    self.assertFalse(health["tradeAllowed"])
    self.assertIn("missing-bar gap", " ".join(health["blockers"]))

  def test_data_health_scopes_higher_timeframe_bootstrap_to_that_timeframe(self):
    now = int(datetime(2026, 7, 27, 15, 0, tzinfo=timezone.utc).timestamp() * 1000)
    runtime = server.new_market_runtime()
    minute = 60_000
    runtime["history"] = [
      candle(now - (70 - index) * minute, 100, 101, 99, 100.5, 1_000)
      for index in range(70)
    ]
    runtime["candle"] = candle(now, 100, 101, 99, 100.5, 1_000)
    runtime["five_minute_history"] = [
      candle(now - (65 - index * 5) * minute, 100, 101, 99, 100.5, 2_000)
      for index in range(14)
    ]
    runtime["daily_history"] = [
      candle(now - (220 - index) * 86_400_000, 100, 101, 99, 100.5, 2_000)
      for index in range(220)
    ]
    runtime["last_success_at"] = now
    health = server.evaluate_data_health("QQQ", runtime, now)
    self.assertTrue(health["tradeAllowed"])
    self.assertEqual(health["status"], "Healthy")
    self.assertTrue(health["timeframes"]["1"]["tradeAllowed"])
    self.assertTrue(health["timeframes"]["5"]["tradeAllowed"])
    self.assertFalse(health["timeframes"]["15"]["tradeAllowed"])
    self.assertIn("15m not enough recent bars", health["warnings"])

  def test_data_health_blocks_confirmed_secondary_price_mismatch(self):
    now = int(datetime(2026, 7, 27, 15, 0, tzinfo=timezone.utc).timestamp() * 1000)
    runtime = server.new_market_runtime()
    runtime["history"] = [
      candle(now - (70 - index) * server.MINUTE_MS, 100, 101, 99, 100.5, 1_000)
      for index in range(70)
    ]
    runtime["candle"] = candle(now, 100, 101, 99, 100.5, 1_000)
    runtime["five_minute_history"] = [
      candle(now - (180 - index * 5) * server.MINUTE_MS, 100, 101, 99, 100.5, 2_000)
      for index in range(36)
    ]
    runtime["daily_history"] = [
      candle(now - (220 - index) * 86_400_000, 100, 101, 99, 100.5, 2_000)
      for index in range(220)
    ]
    runtime["last_success_at"] = now
    runtime["secondary_validation"] = {
      "status": "mismatch",
      "providerName": "Independent test feed",
      "configured": True,
      "driftPct": 1.2,
      "detail": "Primary and independent prices differ by 1.20%",
    }
    health = server.evaluate_data_health("QQQ", runtime, now)
    self.assertFalse(health["tradeAllowed"])
    self.assertIn("Primary and independent prices differ", " ".join(health["blockers"]))

  def test_data_health_marks_directional_candidates_watch_only(self):
    candidate = {"direction": "long", "watchOnly": False, "reasons": []}
    recommendations = {5: {**candidate, "bestLong": candidate, "bestShort": None}}
    health = {
      "tradeAllowed": False,
      "blockers": ["provider refresh is stale"],
      "timeframes": {"5": {"tradeAllowed": False, "detail": "bar is stale"}},
    }
    result = server.apply_data_health(recommendations, health)
    self.assertTrue(result[5]["watchOnly"])
    self.assertIn("provider refresh is stale", result[5]["dataQuality"])

  def test_learning_snapshot_persists_resolved_current_strategy_plans(self):
    for index in range(8):
      self.insert_plan(
        f"learn-{index}",
        setup_type="breakout",
        timeframe=5,
        market_phase="morning",
      )
    with server.db() as connection:
      connection.execute("""
        UPDATE plans
        SET realized_r = CASE WHEN id IN ('learn-0', 'learn-1', 'learn-2', 'learn-3', 'learn-4') THEN 1.2 ELSE -1.0 END,
            outcome_status = CASE WHEN id IN ('learn-0', 'learn-1', 'learn-2', 'learn-3', 'learn-4') THEN 'target2' ELSE 'stopped' END,
            lifecycle_status = 'closed',
            entry_hit_at = 60000,
            closed_at = 120000,
            max_favorable = 1.5,
            max_adverse = 0.5,
            updated_at = 120000
        WHERE id LIKE 'learn-%'
      """)
      snapshot = server.load_learning_snapshot(connection, "QQQ")
      stored = connection.execute("SELECT snapshot_json FROM learning_snapshots WHERE symbol = 'QQQ'").fetchone()
    self.assertEqual(snapshot["resolvedSamples"], 8)
    self.assertEqual(snapshot["groups"]["bySetup"]["breakout"]["winners"], 5)
    self.assertIn("breakout|5|morning|long|unknown", snapshot["groups"]["byComparable"])
    self.assertIsNotNone(stored)
    confidence = server.learning_confidence_for_signal(snapshot, {
      "direction": "long", "setupType": "breakout", "timeframe": 5, "marketPhase": "morning",
    })
    self.assertEqual(confidence["status"], "Preliminary")
    self.assertEqual(confidence["sampleSize"], 8)
    self.assertEqual(confidence["scope"], "hierarchical through exact context")
    self.assertGreater(confidence["target1Rate"], 0.5)
    self.assertLess(confidence["target1Rate"], 5 / 8)
    self.assertLess(confidence["confidenceLow"], confidence["target1Rate"])
    self.assertGreater(confidence["confidenceHigh"], confidence["target1Rate"])
    self.assertAlmostEqual(confidence["avgMfeR"], 1.5)
    self.assertAlmostEqual(confidence["avgMaeR"], 0.5)
    self.assertEqual(confidence["avgHoldingMs"], 60_000)

  def test_learning_snapshot_excludes_unresolved_and_quarantined_plans(self):
    self.insert_plan("resolved", realized_r=1.0, outcome_status="target2", lifecycle_status="closed", closed_at=120000)
    self.insert_plan("open", realized_r=None, outcome_status="open", lifecycle_status="waiting")
    self.insert_plan(
      "old-version",
      strategy_version="4.0.0",
      eligible_for_learning=0,
      realized_r=1.0,
      outcome_status="target2",
      lifecycle_status="closed",
      closed_at=120000,
    )
    with server.db() as connection:
      snapshot = server.load_learning_snapshot(connection, "QQQ")
    self.assertEqual(snapshot["resolvedSamples"], 1)

  def test_setup_quality_gate_blocks_statistically_weak_comparable_setup(self):
    for index in range(20):
      self.insert_plan(
        f"weak-breakout-{index}", setup_type="breakout", timeframe=5, direction="long",
        realized_r=-1.0, outcome_status="stopped", lifecycle_status="closed", closed_at=100_000 + index,
      )
    with server.db() as connection:
      snapshot = server.build_learning_snapshot(connection, "QQQ")
    candidate = {"direction": "long", "setupType": "breakout", "timeframe": 5, "score": 82, "reasons": []}
    recommendations = {5: {**candidate, "bestLong": candidate, "bestShort": None}}
    result = server.apply_setup_quality_gate(recommendations, snapshot)
    self.assertEqual(result[5]["qualityGate"]["status"], "Blocked")
    self.assertTrue(result[5]["watchOnly"])
    self.assertIn("Blocked: 20 comparable breakout 5m long", result[5]["reasons"][-1])

  def test_setup_quality_gate_prefers_positive_comparable_setup(self):
    for index in range(30):
      self.insert_plan(
        f"strong-breakout-{index}", setup_type="breakout", timeframe=5, direction="long",
        realized_r=1.0, outcome_status="target2", lifecycle_status="closed", closed_at=100_000 + index,
      )
    with server.db() as connection:
      snapshot = server.build_learning_snapshot(connection, "QQQ")
    candidate = {"direction": "long", "setupType": "breakout", "timeframe": 5, "score": 82, "reasons": []}
    result = server.apply_setup_quality_gate({5: candidate}, snapshot)
    self.assertEqual(result[5]["qualityGate"]["status"], "Preferred")
    self.assertEqual(result[5]["score"], 85)

  def test_recommendation_scoreboard_reports_all_recorded_alert_outcomes_per_market(self):
    self.insert_plan("qqq-win", realized_r=1.3, outcome_status="target2", lifecycle_status="closed")
    self.insert_plan("qqq-loss", realized_r=-1.0, outcome_status="stopped", lifecycle_status="closed")
    self.insert_plan("qqq-open", realized_r=None, outcome_status="open", lifecycle_status="waiting")
    self.insert_plan("spy-win", symbol="SPY", realized_r=0.5, outcome_status="target1", lifecycle_status="closed")
    self.insert_plan(
      "older-qqq-win",
      strategy_version="5.0.0",
      realized_r=1.0,
      outcome_status="target2",
      lifecycle_status="closed",
    )
    with server.db() as connection:
      scoreboard = {row["symbol"]: row for row in server.recommendation_scoreboard(connection)}
    self.assertEqual(scoreboard["QQQ"], {
      "symbol": "QQQ", "recommended": 4, "resolved": 3, "successful": 2,
      "unsuccessful": 1, "active": 1, "successRate": 66.7,
    })
    self.assertEqual(scoreboard["SPY"], {
      "symbol": "SPY", "recommended": 1, "resolved": 1, "successful": 1,
      "unsuccessful": 0, "active": 0, "successRate": 100.0,
    })
    self.assertEqual(scoreboard["BTC-USD"]["successRate"], None)
    self.assertEqual(scoreboard["BTC-USD"]["unsuccessful"], 0)
    self.assertEqual(scoreboard["TA125"]["recommended"], 0)

  def test_model_validation_requires_forward_sample_and_quality_gates(self):
    for index in range(30):
      self.insert_plan(
        f"validation-{index}",
        realized_r=1.0 if index < 24 else -1.0,
        outcome_status="target2" if index < 24 else "stopped",
        lifecycle_status="closed",
        closed_at=100_000 + index,
      )
    with server.db() as connection:
      snapshot = server.model_validation_snapshot(connection, "QQQ")
    self.assertEqual(snapshot["status"], "Developing")
    self.assertEqual(snapshot["resolved"], 30)
    self.assertEqual(snapshot["winners"], 24)
    self.assertTrue(snapshot["criteria"]["minimumSamples"])
    self.assertTrue(snapshot["criteria"]["positiveExpectancy"])
    self.assertTrue(snapshot["criteria"]["winRateConfidence"])
    self.assertFalse(snapshot["criteria"]["outOfSample"])
    self.assertEqual(snapshot["byTimeframe"][0]["key"], "1")

  def test_cnn_fear_greed_payload_is_normalized(self):
    result = server.normalize_fear_greed({
      "fear_and_greed": {
        "score": 37.057,
        "rating": "fear",
        "timestamp": "2026-07-17T23:59:50+00:00",
        "previous_close": 41.68,
        "previous_1_week": 46.82,
        "previous_1_month": 32.94,
        "previous_1_year": 74.17,
      }
    })
    self.assertEqual(result["score"], 37.1)
    self.assertEqual(result["rating"], "Fear")
    self.assertEqual(result["previousClose"], 41.68)
    self.assertEqual(result["source"], "CNN")

  def test_cnn_fear_greed_rejects_out_of_range_score(self):
    with self.assertRaises(ValueError):
      server.normalize_fear_greed({"fear_and_greed": {"score": 101}})

  def test_entry_and_stop_same_bar_is_ambiguous(self):
    self.insert_plan("ambiguous")
    with server.db() as connection:
      updates = server.evaluate_plans(connection, "QQQ", [
        candle(120_000, 100, 100.5, 98.8, 99.4),
      ])
    row = self.fetch_plan("ambiguous")
    self.assertEqual(updates, 1)
    self.assertEqual(row["outcome_status"], "ambiguous")
    self.assertEqual(row["lifecycle_status"], "closed")

  def test_candles_inside_signal_window_are_not_evaluated(self):
    self.insert_plan("boundary", created_at=360_000, updated_at=360_000, timeframe=5)
    with server.db() as connection:
      updates = server.evaluate_plans(connection, "QQQ", [
        candle(120_000, 99.5, 101.5, 99.4, 101.0),
        candle(300_000, 99.5, 101.5, 99.4, 101.0),
      ])
    row = self.fetch_plan("boundary")
    self.assertEqual(updates, 0)
    self.assertEqual(row["lifecycle_status"], "waiting")
    self.assertIsNone(row["entry_hit_at"])

  def test_first_bar_at_actionable_boundary_is_evaluated_once(self):
    self.insert_plan("first_bar", created_at=360_000, updated_at=360_000, timeframe=5)
    boundary_candle = candle(360_000, 99.8, 100.5, 99.7, 100.2)
    with server.db() as connection:
      first_updates = server.evaluate_plans(connection, "QQQ", [boundary_candle])
      duplicate_updates = server.evaluate_plans(connection, "QQQ", [boundary_candle])
    row = self.fetch_plan("first_bar")
    self.assertEqual(first_updates, 1)
    self.assertEqual(duplicate_updates, 0)
    self.assertEqual(row["entry_hit_at"], 360_000)
    self.assertEqual(row["observations"], 1)

  def test_entry_bar_does_not_receive_same_bar_target_credit(self):
    self.insert_plan("same_bar_target")
    with server.db() as connection:
      server.evaluate_plans(connection, "QQQ", [
        candle(120_000, 99.8, 102.2, 99.7, 101.5),
      ])
    row = self.fetch_plan("same_bar_target")
    self.assertEqual(row["lifecycle_status"], "entered")
    self.assertEqual(row["outcome_status"], "open")
    self.assertIsNone(row["hit_target1_at"])
    self.assertIsNone(row["hit_target2_at"])

  def test_target1_then_stop_preserves_partial_outcome(self):
    self.insert_plan("target1_stop")
    with server.db() as connection:
      server.evaluate_plans(connection, "QQQ", [
        candle(120_000, 99.8, 100.4, 99.7, 100.2),
        candle(180_000, 100.2, 101.2, 100.1, 101.0),
        candle(240_000, 101.0, 101.1, 98.8, 99.0),
      ])
    row = self.fetch_plan("target1_stop")
    self.assertEqual(row["outcome_status"], "target1_stop")
    self.assertEqual(row["lifecycle_status"], "closed")
    self.assertEqual(row["hit_target1_at"], 180_000)
    self.assertEqual(row["hit_stop_at"], 240_000)
    self.assertEqual(row["realized_r"], 0.0)

  def test_waiting_plan_expires_without_entry(self):
    self.insert_plan("expired", entry=110.0, stop=105.0, target1=112.0, target2=114.0)
    with server.db() as connection:
      server.evaluate_plans(connection, "QQQ", [
        candle(60_000 + 4 * 60 * 60 * 1000 + 60_000, 100, 101, 99, 100.5),
      ])
    row = self.fetch_plan("expired")
    self.assertEqual(row["outcome_status"], "expired")
    self.assertEqual(row["lifecycle_status"], "expired")

  def test_option_idea_persists_and_requires_fresh_exit_quote_for_learning(self):
    quote_start = 1_780_000_000_000
    quote_exit = quote_start + 60_000
    self.insert_plan(
      "option-plan",
      timeframe=5,
      lifecycle_status="closed",
      outcome_status="target2",
      closed_at=quote_exit,
    )
    opportunity = {
      "status": "contract",
      "symbol": "QQQ",
      "signalKey": "option-signal",
      "generatedAt": quote_start,
      "planId": "option-plan",
      "timeframe": 5,
      "direction": "long",
      "side": "call",
      "score": 88,
      "provider": {"name": "Market Data"},
      "underlying": {"entry": 100, "stop": 99, "target1": 101, "target2": 102},
      "contract": {
        "optionSymbol": "QQQ260807C00100000",
        "expiration": 1_786_061_600_000,
        "strike": 100,
        "dte": 10,
        "bid": 2.0,
        "ask": 2.2,
        "mid": 2.1,
        "quoteAt": quote_start,
        "volume": 500,
        "openInterest": 2000,
        "iv": 0.2,
        "delta": 0.62,
        "gamma": 0.03,
        "theta": -0.05,
        "vega": 0.2,
        "deltaBucket": "0.60-0.65",
      },
    }
    with server.db() as connection:
      idea_id = server.persist_options_opportunity(connection, opportunity)
      connection.execute("""
        INSERT INTO option_quote_observations (
          idea_id, observed_at, quote_at, bid, ask, mid, volume, open_interest,
          iv, delta, gamma, theta, vega
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      """, (idea_id, quote_exit, quote_exit, 2.8, 3.0, 2.9, 700, 2200, 0.21, 0.64, 0.03, -0.04, 0.2))
      self.assertEqual(server.resolve_option_ideas(connection), 1)
      idea = connection.execute("SELECT * FROM option_ideas WHERE id = ?", (idea_id,)).fetchone()
    self.assertEqual(idea["eligible_for_learning"], 1)
    self.assertAlmostEqual(idea["realized_return"], (2.9 - 2.1) / 2.1)

  def test_options_provider_credit_ceiling_is_persistent(self):
    with server.db() as connection:
      connection.execute("""
        INSERT INTO options_provider_usage (usage_day, credits, updated_at)
        VALUES (?, ?, ?)
      """, (server.options_usage_day(), 78, server.now_ms()))
    reserved, used = server.reserve_options_provider_credits(4)
    self.assertFalse(reserved)
    self.assertEqual(used, 78)

  def test_options_chain_is_cached_before_spending_more_credits(self):
    guidance = server.options_engine.build_guidance(
      5,
      option_signal(),
      generated_at=1_780_000_300_000,
    )
    guidance["signalKey"] = "cache-test-signal"
    payload = {
      "s": "ok",
      "optionSymbol": ["QQQ260807C00600000"],
      "side": ["call"],
      "strike": [600],
    }
    with server.FETCH_CACHE_LOCK:
      server.FETCH_CACHE.pop(("options-chain", guidance["signalKey"]), None)
    with patch.object(server, "marketdata_get", return_value=payload) as request:
      first, first_cached, first_error = server.fetch_options_chain(guidance, 1_780_000_300_000)
      second, second_cached, second_error = server.fetch_options_chain(guidance, 1_780_000_300_000)
    with server.db() as connection:
      credits = server.options_provider_usage(connection, 1_780_000_300_000)
    self.assertEqual(first, second)
    self.assertFalse(first_cached)
    self.assertTrue(second_cached)
    self.assertIsNone(first_error)
    self.assertIsNone(second_error)
    self.assertEqual(request.call_count, 1)
    self.assertEqual(request.call_args.args[0], "/v1/options/chain/QQQ/")
    self.assertEqual(credits, server.OPTIONS_PROVIDER_REQUEST_CREDITS)

  def test_btc_options_chain_requests_ibit_contracts(self):
    guidance = server.options_engine.build_guidance(
      15,
      option_signal(timeframe=15),
      generated_at=1_780_000_300_000,
      underlying_price=100_000,
      option_price=70,
      symbol="BTC-USD",
    )
    guidance["signalKey"] = "btc-ibit-chain"
    payload = {"s": "ok", "optionSymbol": ["IBIT260807C00070000"], "side": ["call"], "strike": [70]}
    with server.FETCH_CACHE_LOCK:
      server.FETCH_CACHE.pop(("options-chain", guidance["signalKey"]), None)
    with patch.object(server, "marketdata_get", return_value=payload) as request:
      server.fetch_options_chain(guidance, 1_780_000_300_000)
    self.assertEqual(request.call_args.args[0], "/v1/options/chain/IBIT/")

  def test_qqq_spy_confirmation_rewards_alignment_and_relative_strength(self):
    step = 5 * 60_000
    qqq_runtime = server.new_market_runtime()
    spy_runtime = server.new_market_runtime()
    qqq_runtime["five_minute_history"] = [
      candle(index * step, 100 + index, 101 + index, 99 + index, 100 + index)
      for index in range(8)
    ]
    spy_runtime["five_minute_history"] = [
      candle(index * step, 100 + index * 0.3, 101 + index * 0.3, 99 + index * 0.3, 100 + index * 0.3)
      for index in range(8)
    ]
    spy_recommendations = {
      5: {"selectedTrend": {"label": "Up", "tone": "positive"}},
      15: {"selectedTrend": {"label": "Up", "tone": "positive"}},
      1440: {"selectedTrend": {"label": "Up", "tone": "positive"}},
    }
    confirmation = server.qqq_spy_confirmation(5, "long", qqq_runtime, spy_runtime, spy_recommendations)
    self.assertEqual(confirmation["label"], "Confirmed")
    self.assertGreater(confirmation["scoreAdjustment"], 0)
    self.assertEqual(confirmation["relativeStrength"]["label"], "Leading")

  def test_marketdata_get_accepts_delayed_http_203(self):
    class Response:
      status = 203

      def __enter__(self):
        return self

      def __exit__(self, *_args):
        return False

      def read(self):
        return b'{"s":"ok","optionSymbol":[]}'

    old_token = server.MARKETDATA_TOKEN
    server.MARKETDATA_TOKEN = "test-token"
    try:
      with patch.object(server, "urlopen", return_value=Response()):
        payload = server.marketdata_get("/v1/options/chain/QQQ/")
    finally:
      server.MARKETDATA_TOKEN = old_token
    self.assertEqual(payload["s"], "ok")

  def test_option_entry_quote_cannot_be_reused_as_exit_quote(self):
    quote_start = 1_780_000_000_000
    self.insert_plan(
      "same-option-quote",
      timeframe=5,
      lifecycle_status="closed",
      outcome_status="stopped",
      closed_at=quote_start + 60_000,
    )
    opportunity = {
      "status": "contract",
      "symbol": "QQQ",
      "signalKey": "same-option-signal",
      "generatedAt": quote_start,
      "planId": "same-option-quote",
      "timeframe": 5,
      "direction": "long",
      "side": "call",
      "score": 85,
      "provider": {"name": "Market Data"},
      "underlying": {"entry": 100, "stop": 99, "target1": 101, "target2": 102},
      "contract": {
        "optionSymbol": "QQQ260807C00100000",
        "expiration": 1_786_061_600_000,
        "strike": 100,
        "dte": 10,
        "bid": 2.0,
        "ask": 2.2,
        "mid": 2.1,
        "quoteAt": quote_start,
        "volume": 500,
        "openInterest": 2000,
        "iv": 0.2,
        "delta": 0.62,
        "gamma": 0.03,
        "theta": -0.05,
        "vega": 0.2,
        "deltaBucket": "0.60-0.65",
      },
    }
    with server.db() as connection:
      idea_id = server.persist_options_opportunity(connection, opportunity)
      server.resolve_option_ideas(connection)
      idea = connection.execute("SELECT * FROM option_ideas WHERE id = ?", (idea_id,)).fetchone()
    self.assertEqual(idea["eligible_for_learning"], 0)
    self.assertIsNone(idea["realized_return"])

  def test_non_health_routes_require_configured_basic_auth(self):
    server.APP_PASSWORD = "test-secret"
    handler = object.__new__(server.Handler)
    responses = []
    headers = []
    handler.send_response = responses.append
    handler.send_header = lambda key, value: headers.append((key, value))
    handler.end_headers = lambda: None

    token = base64.b64encode(b"trader:test-secret").decode("ascii")
    handler.headers = {"Authorization": f"Basic {token}"}
    self.assertTrue(handler.require_auth())

    handler.headers = {"Authorization": "Basic invalid"}
    self.assertFalse(handler.require_auth())
    self.assertEqual(responses[-1], 401)
    self.assertTrue(any(key == "WWW-Authenticate" for key, _ in headers))


if __name__ == "__main__":
  unittest.main()
