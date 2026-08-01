import base64
import os
import sys
import tempfile
import unittest
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
    }
    row.update(overrides)
    with server.db() as connection:
      connection.execute("""
        INSERT INTO plans (
          id, created_at, updated_at, symbol, provider, timeframe, direction, setup, setup_type,
          market_phase, status, score, entry, stop, target1, target2, risk_reward, price_at_plan,
          strategy_version, eligible_for_learning, outcome_status, lifecycle_status, realized_r, closed_at
        ) VALUES (
          :id, :created_at, :updated_at, :symbol, :provider, :timeframe, :direction, :setup, :setup_type,
          :market_phase, :status, :score, :entry, :stop, :target1, :target2, :risk_reward, :price_at_plan,
          :strategy_version, :eligible_for_learning, :outcome_status, :lifecycle_status, :realized_r, :closed_at
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

  def test_backtest_results_are_scoped_by_symbol(self):
    with server.db() as connection:
      server.save_backtest_result(connection, "qqq-signature", {"generatedAt": 1, "summary": {"resolved": 10}}, "QQQ")
      server.save_backtest_result(connection, "btc-signature", {"generatedAt": 2, "summary": {"resolved": 20}}, "BTC-USD")
    with server.db() as connection:
      self.assertEqual(server.load_latest_backtest(connection, "QQQ")["summary"]["resolved"], 10)
      self.assertEqual(server.load_latest_backtest(connection, "BTC-USD")["summary"]["resolved"], 20)

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
    self.assertEqual(confidence["scope"], "comparable setup, timeframe, phase, direction, and regime")
    self.assertAlmostEqual(confidence["target1Rate"], 15 / 28)
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
