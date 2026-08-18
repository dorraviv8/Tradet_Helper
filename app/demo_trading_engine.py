import hashlib
import csv
import io
import json
import math
import sqlite3
import time


VERSION = "2.0.0"
SCHEMA_VERSION = 4
ACCOUNT_ID = "primary"
STARTING_CASH_CENTS = 2_000_000
COMMISSION_CENTS = 500
TAX_RATE = 0.25
SHORT_BORROW_ANNUAL_RATE = 0.03
DAY_MS = 86_400_000
MINIMUM_DAY_TRADES_24H = 2
ACTIVE_DAY_MINIMUM_SCORE = 50
MINIMUM_GROSS_STOP_CENTS = COMMISSION_CENTS * 2 * 3

STOP_POLICY = {
  "day": {"minimum_atr": 0.60, "minimum_pct": 0.0030, "maximum_pct": 0.0080, "minimum_target_r": 1.15},
  "swing": {"minimum_atr": 0.80, "minimum_pct": 0.0080, "maximum_pct": 0.0600, "minimum_target_r": 1.20},
  "long": {"minimum_atr": 1.20, "minimum_pct": 0.0200, "maximum_pct": 0.1200, "minimum_target_r": 1.35},
}

HORIZON_POLICY = {
  "day": {
    "minimum_score": 58,
    "risk_pct": 0.75,
    "max_position_pct": 40.0,
    "entry_expiry_ms": 35 * 60_000,
    "max_holding_ms": 4 * 60 * 60_000,
  },
  "swing": {
    "minimum_score": 62,
    "risk_pct": 0.75,
    "max_position_pct": 25.0,
    "entry_expiry_ms": 3 * DAY_MS,
    "max_holding_ms": 21 * DAY_MS,
  },
  "long": {
    "minimum_score": 68,
    "risk_pct": 1.0,
    "max_position_pct": 30.0,
    "entry_expiry_ms": 7 * DAY_MS,
    "max_holding_ms": 112 * DAY_MS,
  },
}

SYMBOL_POLICY = {
  "QQQ": {"execution_symbol": "QQQ", "currency": "USD", "fractional": False, "slippage_bps": 1.0},
  "SPY": {"execution_symbol": "SPY", "currency": "USD", "fractional": False, "slippage_bps": 1.0},
  "BTC-USD": {"execution_symbol": "BTC-USD", "currency": "USD", "fractional": True, "slippage_bps": 4.0},
  "TA125": {"execution_symbol": "IBI-F42.TA", "currency": "ILS", "fractional": False, "slippage_bps": 8.0},
}


def now_ms():
  return int(time.time() * 1000)


def init_schema(connection, timestamp=None):
  timestamp = int(timestamp or now_ms())
  connection.executescript("""
    CREATE TABLE IF NOT EXISTS demo_accounts (
      id TEXT PRIMARY KEY,
      started_at INTEGER NOT NULL,
      starting_cash_cents INTEGER NOT NULL,
      cash_cents INTEGER NOT NULL,
      high_watermark_cents INTEGER NOT NULL,
      max_drawdown_bps INTEGER NOT NULL DEFAULT 0,
      policy_version TEXT NOT NULL,
      updated_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS demo_orders (
      id TEXT PRIMARY KEY,
      idempotency_key TEXT NOT NULL UNIQUE,
      account_id TEXT NOT NULL,
      position_id TEXT,
      symbol TEXT NOT NULL,
      execution_symbol TEXT NOT NULL,
      currency TEXT NOT NULL,
      horizon TEXT NOT NULL,
      timeframe INTEGER NOT NULL,
      direction TEXT NOT NULL,
      action TEXT NOT NULL,
      quantity REAL,
      status TEXT NOT NULL,
      signal_at INTEGER NOT NULL,
      eligible_at INTEGER NOT NULL,
      expires_at INTEGER,
      reference_price REAL,
      planned_risk_cents INTEGER NOT NULL DEFAULT 0,
      max_notional_cents INTEGER NOT NULL DEFAULT 0,
      fill_price REAL,
      fill_fx_rate REAL,
      filled_at INTEGER,
      commission_cents INTEGER NOT NULL DEFAULT 0,
      reason TEXT,
      details_json TEXT,
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL,
      FOREIGN KEY (account_id) REFERENCES demo_accounts(id)
    );
    CREATE INDEX IF NOT EXISTS idx_demo_orders_pending ON demo_orders(status, symbol, horizon, eligible_at);
    CREATE INDEX IF NOT EXISTS idx_demo_orders_recent ON demo_orders(created_at DESC);
    CREATE TABLE IF NOT EXISTS demo_positions (
      id TEXT PRIMARY KEY,
      account_id TEXT NOT NULL,
      entry_order_id TEXT NOT NULL,
      symbol TEXT NOT NULL,
      execution_symbol TEXT NOT NULL,
      currency TEXT NOT NULL,
      horizon TEXT NOT NULL,
      timeframe INTEGER NOT NULL,
      direction TEXT NOT NULL,
      setup TEXT NOT NULL,
      setup_type TEXT,
      score INTEGER NOT NULL,
      signal_at INTEGER NOT NULL,
      opened_at INTEGER NOT NULL,
      closed_at INTEGER,
      status TEXT NOT NULL,
      quantity REAL NOT NULL,
      remaining_quantity REAL NOT NULL,
      entry_price REAL NOT NULL,
      entry_fx_rate REAL NOT NULL,
      entry_value_cents INTEGER NOT NULL,
      remaining_basis_cents INTEGER NOT NULL,
      stop_price REAL NOT NULL,
      target1_price REAL NOT NULL,
      target2_price REAL NOT NULL,
      target1_hit_at INTEGER,
      last_price REAL NOT NULL,
      last_fx_rate REAL NOT NULL,
      last_valued_at INTEGER NOT NULL,
      last_bar_at INTEGER NOT NULL,
      max_favorable_cents INTEGER NOT NULL DEFAULT 0,
      max_adverse_cents INTEGER NOT NULL DEFAULT 0,
      realized_gross_cents INTEGER NOT NULL DEFAULT 0,
      commission_cents INTEGER NOT NULL DEFAULT 0,
      tax_cents INTEGER NOT NULL DEFAULT 0,
      net_pnl_cents INTEGER NOT NULL DEFAULT 0,
      close_reason TEXT,
      strategy_version TEXT NOT NULL,
      details_json TEXT,
      FOREIGN KEY (account_id) REFERENCES demo_accounts(id),
      FOREIGN KEY (entry_order_id) REFERENCES demo_orders(id)
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_demo_one_open_position
      ON demo_positions(symbol, horizon) WHERE status = 'open';
    CREATE INDEX IF NOT EXISTS idx_demo_positions_history ON demo_positions(opened_at DESC);
    CREATE TABLE IF NOT EXISTS demo_fills (
      id TEXT PRIMARY KEY,
      order_id TEXT NOT NULL UNIQUE,
      position_id TEXT NOT NULL,
      symbol TEXT NOT NULL,
      horizon TEXT NOT NULL,
      direction TEXT NOT NULL,
      action TEXT NOT NULL,
      quantity REAL NOT NULL,
      price REAL NOT NULL,
      fx_rate REAL NOT NULL,
      notional_cents INTEGER NOT NULL,
      commission_cents INTEGER NOT NULL,
      filled_at INTEGER NOT NULL,
      reason TEXT,
      FOREIGN KEY (order_id) REFERENCES demo_orders(id),
      FOREIGN KEY (position_id) REFERENCES demo_positions(id)
    );
    CREATE INDEX IF NOT EXISTS idx_demo_fills_time ON demo_fills(filled_at DESC);
    CREATE TABLE IF NOT EXISTS demo_ledger (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      account_id TEXT NOT NULL,
      event_key TEXT NOT NULL UNIQUE,
      event_at INTEGER NOT NULL,
      event_type TEXT NOT NULL,
      order_id TEXT,
      position_id TEXT,
      amount_cents INTEGER NOT NULL,
      cash_after_cents INTEGER NOT NULL,
      details_json TEXT,
      FOREIGN KEY (account_id) REFERENCES demo_accounts(id)
    );
    CREATE INDEX IF NOT EXISTS idx_demo_ledger_time ON demo_ledger(event_at DESC);
    CREATE TABLE IF NOT EXISTS demo_equity_snapshots (
      account_id TEXT NOT NULL,
      snapshot_at INTEGER NOT NULL,
      cash_cents INTEGER NOT NULL,
      invested_cents INTEGER NOT NULL,
      collateral_cents INTEGER NOT NULL,
      unrealized_cents INTEGER NOT NULL,
      equity_cents INTEGER NOT NULL,
      PRIMARY KEY (account_id, snapshot_at)
    );
    CREATE INDEX IF NOT EXISTS idx_demo_equity_time ON demo_equity_snapshots(snapshot_at DESC);
    CREATE TABLE IF NOT EXISTS demo_schema_meta (
      id INTEGER PRIMARY KEY CHECK (id = 1),
      schema_version INTEGER NOT NULL,
      updated_at INTEGER NOT NULL
    );
  """)
  migrations = {
    "demo_orders": {
      "triggered_at": "INTEGER",
      "fill_eligible_at": "INTEGER",
    },
    "demo_positions": {
      "initial_risk_cents": "INTEGER NOT NULL DEFAULT 0",
      "original_stop_price": "REAL",
      "original_target1_price": "REAL",
      "original_target2_price": "REAL",
      "trailing_stop_price": "REAL",
      "stop_confirmation": "TEXT NOT NULL DEFAULT 'touch'",
      "selection_mode": "TEXT NOT NULL DEFAULT 'legacy'",
      "policy_version": "TEXT NOT NULL DEFAULT 'legacy'",
      "exit_policy_json": "TEXT NOT NULL DEFAULT '{}'",
      "last_intraday_bar_at": "INTEGER NOT NULL DEFAULT 0",
      "last_daily_bar_at": "INTEGER NOT NULL DEFAULT 0",
      "borrow_cents": "INTEGER NOT NULL DEFAULT 0",
    },
    "demo_fills": {
      "fill_model": "TEXT NOT NULL DEFAULT 'legacy'",
      "ambiguous": "INTEGER NOT NULL DEFAULT 0",
    },
  }
  for table, columns in migrations.items():
    existing_columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, definition in columns.items():
      if name not in existing_columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
  connection.execute("""
    INSERT INTO demo_schema_meta (id, schema_version, updated_at)
    VALUES (1, ?, ?)
    ON CONFLICT(id) DO UPDATE SET schema_version = excluded.schema_version, updated_at = excluded.updated_at
  """, (SCHEMA_VERSION, timestamp))
  connection.execute("""
    UPDATE demo_positions
    SET initial_risk_cents = CASE
          WHEN initial_risk_cents > 0 THEN initial_risk_cents
          WHEN entry_price > 0 THEN ROUND(entry_value_cents * ABS(entry_price - stop_price) / entry_price)
          ELSE 0 END,
        original_stop_price = COALESCE(original_stop_price, stop_price),
        original_target1_price = COALESCE(original_target1_price, target1_price),
        original_target2_price = COALESCE(original_target2_price, target2_price),
        last_intraday_bar_at = CASE WHEN last_intraday_bar_at > 0 THEN last_intraday_bar_at ELSE last_bar_at END,
        last_daily_bar_at = CASE WHEN last_daily_bar_at > 0 THEN last_daily_bar_at ELSE last_bar_at END
  """)
  existing = connection.execute("SELECT id FROM demo_accounts WHERE id = ?", (ACCOUNT_ID,)).fetchone()
  if not existing:
    connection.execute("""
      INSERT INTO demo_accounts (
        id, started_at, starting_cash_cents, cash_cents, high_watermark_cents,
        max_drawdown_bps, policy_version, updated_at
      ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)
    """, (ACCOUNT_ID, timestamp, STARTING_CASH_CENTS, STARTING_CASH_CENTS, STARTING_CASH_CENTS, VERSION, timestamp))
    connection.execute("""
      INSERT INTO demo_ledger (
        account_id, event_key, event_at, event_type, amount_cents,
        cash_after_cents, details_json
      ) VALUES (?, ?, ?, 'opening_balance', ?, ?, ?)
    """, (
      ACCOUNT_ID, f"account:{ACCOUNT_ID}:opening", timestamp, STARTING_CASH_CENTS,
      STARTING_CASH_CENTS, json.dumps({"policyVersion": VERSION}),
    ))
  else:
    connection.execute(
      "UPDATE demo_accounts SET policy_version = ?, updated_at = ? WHERE id = ?",
      (VERSION, timestamp, ACCOUNT_ID),
    )


def _hash_id(prefix, *parts):
  digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:24]
  return f"{prefix}-{digest}"


def _json(value):
  try:
    return json.loads(value or "{}")
  except (TypeError, json.JSONDecodeError):
    return {}


def _candidate_levels_are_valid(candidate):
  try:
    entry = float(candidate.get("entry") or 0)
    stop = float(candidate.get("stop") or 0)
    target1 = float(candidate.get("target") or candidate.get("target1") or 0)
    target2 = float(candidate.get("target2") or 0)
  except (TypeError, ValueError):
    return False
  if min(entry, stop, target1, target2) <= 0:
    return False
  if candidate.get("direction") == "long":
    return stop < entry < target1 <= target2
  if candidate.get("direction") == "short":
    return stop > entry > target1 >= target2
  return False


def _aggressive_day_candidate_is_safe(candidate):
  if not _candidate_levels_are_valid(candidate):
    return False
  if int(candidate.get("score") or 0) < ACTIVE_DAY_MINIMUM_SCORE:
    return False
  if float(candidate.get("riskReward") or 0) < 0.8:
    return False
  data_health = candidate.get("dataHealth") or {}
  if data_health.get("tradeAllowed") is False:
    return False
  data_quality = str(candidate.get("dataQuality") or "clean").lower()
  if data_quality != "clean":
    return False
  if candidate.get("watchOnly"):
    return False
  if (candidate.get("executionQuality") or {}).get("status") == "blocked":
    return False
  if (candidate.get("qualityGate") or {}).get("status") == "Blocked":
    return False
  if (candidate.get("calibrationDrift") or {}).get("status") == "blocked":
    return False
  if (candidate.get("contextRouting") or {}).get("status") == "block":
    return False
  entry = float(candidate["entry"])
  stop_pct = abs(entry - float(candidate["stop"])) / entry
  return 0.0005 <= stop_pct <= 0.06


def _candidate_subject(signal, aggressive_day=False):
  if not isinstance(signal, dict):
    return None
  if any("outside regular market hours" in str(reason).lower() for reason in signal.get("reasons") or []):
    return None
  direct = signal if signal.get("direction") in {"long", "short"} else None
  candidates = [item for item in (direct, signal.get("bestLong"), signal.get("bestShort")) if isinstance(item, dict)]
  eligible = [
    item for item in candidates
    if item.get("direction") in {"long", "short"}
    and not item.get("watchOnly")
    and _candidate_levels_are_valid(item)
    and (not aggressive_day or _aggressive_day_candidate_is_safe(item))
  ]
  return max(eligible, key=lambda item: (int(item.get("score") or 0), float(item.get("riskReward") or 0)), default=None)


def candidates_from_recommendations(symbol, recommendations, timestamp, aggressive_day=False):
  rows = []
  for timeframe in (1, 5, 15):
    signal = recommendations.get(timeframe) or recommendations.get(str(timeframe)) or {}
    candidate = _candidate_subject(signal, aggressive_day)
    if not candidate:
      continue
    score = int(candidate.get("score") or 0)
    threshold = ACTIVE_DAY_MINIMUM_SCORE if aggressive_day else HORIZON_POLICY["day"]["minimum_score"]
    if score < threshold:
      continue
    row = _candidate_row(symbol, "day", timeframe, signal, candidate, timestamp)
    row["selection_mode"] = "activity_target" if aggressive_day and score < HORIZON_POLICY["day"]["minimum_score"] else "qualified"
    rows.append(row)
  if rows:
    rows = [max(rows, key=lambda row: (row["score"] + (4 if row["timeframe"] == 5 else 1 if row["timeframe"] == 15 else 0), row["risk_reward"]))]

  daily = recommendations.get(1440) or recommendations.get("1440") or {}
  daily_candidate = _candidate_subject(daily)
  if daily_candidate:
    daily_score = int(daily_candidate.get("score") or 0)
    if daily_score >= HORIZON_POLICY["swing"]["minimum_score"]:
      rows.append(_candidate_row(symbol, "swing", 1440, daily, daily_candidate, timestamp))
    trend = daily.get("selectedTrend") or {}
    direction_tone = "positive" if daily_candidate.get("direction") == "long" else "negative"
    if daily_score >= HORIZON_POLICY["long"]["minimum_score"] and trend.get("tone") == direction_tone:
      long_row = _candidate_row(symbol, "long", 1440, daily, daily_candidate, timestamp)
      entry = long_row["reference_price"]
      stop_distance = abs(entry - long_row["stop_reference"])
      wider_risk = max(stop_distance * 1.55, entry * 0.025)
      long_row["stop_reference"] = entry - wider_risk if long_row["direction"] == "long" else entry + wider_risk
      long_row["target1_reference"] = entry + wider_risk * 2.2 if long_row["direction"] == "long" else entry - wider_risk * 2.2
      long_row["target2_reference"] = entry + wider_risk * 3.6 if long_row["direction"] == "long" else entry - wider_risk * 3.6
      long_row["setup"] = f"Long-horizon {long_row['setup']}"
      rows.append(long_row)
  return rows


def _candidate_row(symbol, horizon, timeframe, signal, candidate, timestamp):
  signal_at = int(signal.get("signalCandleTime") or candidate.get("signalCandleTime") or timestamp)
  actionable_at = int(signal.get("actionableAt") or candidate.get("actionableAt") or signal_at + max(1, timeframe) * 60_000)
  return {
    "symbol": symbol,
    "horizon": horizon,
    "timeframe": timeframe,
    "direction": candidate.get("direction"),
    "setup": str(candidate.get("setup") or "Momentum setup")[:160],
    "setup_type": str(candidate.get("setupType") or "momentum")[:80],
    "score": int(candidate.get("score") or 0),
    "risk_reward": float(candidate.get("riskReward") or 0),
    "signal_at": signal_at,
    "actionable_at": actionable_at,
    "reference_price": float(candidate.get("entry") or 0),
    "stop_reference": float(candidate.get("stop") or 0),
    "target1_reference": float(candidate.get("target") or candidate.get("target1") or 0),
    "target2_reference": float(candidate.get("target2") or 0),
    "atr": float(candidate.get("atr") or 0),
    "entry_confirmation": str((candidate.get("executionQuality") or {}).get("entryConfirmation") or "close"),
    "exit_rules": list(candidate.get("exitRules") or [])[:6],
    "market_phase": str(candidate.get("marketPhase") or "unknown"),
    "market_regime": str((candidate.get("regime") or {}).get("type") or "unknown"),
    "strategy_version": str(candidate.get("strategyVersion") or "unknown"),
    "reasons": list(candidate.get("reasons") or [])[:8],
  }


def _account(connection):
  return connection.execute("SELECT * FROM demo_accounts WHERE id = ?", (ACCOUNT_ID,)).fetchone()


def _cash_event(connection, event_key, timestamp, event_type, amount_cents, order_id=None, position_id=None, details=None):
  account = _account(connection)
  new_cash = int(account["cash_cents"]) + int(amount_cents)
  if new_cash < 0:
    raise ValueError("demo account cash invariant would be negative")
  connection.execute("UPDATE demo_accounts SET cash_cents = ?, updated_at = ? WHERE id = ?", (new_cash, timestamp, ACCOUNT_ID))
  connection.execute("""
    INSERT INTO demo_ledger (
      account_id, event_key, event_at, event_type, order_id, position_id,
      amount_cents, cash_after_cents, details_json
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
  """, (ACCOUNT_ID, event_key, timestamp, event_type, order_id, position_id, int(amount_cents), new_cash, json.dumps(details or {})))
  return new_cash


def _open_exposure_cents(connection, symbol=None):
  where = "WHERE status = 'open'"
  params = ()
  if symbol:
    where += " AND symbol = ?"
    params = (symbol,)
  row = connection.execute(f"SELECT COALESCE(SUM(remaining_basis_cents), 0) total FROM demo_positions {where}", params).fetchone()
  return int(row["total"] or 0)


def _open_risk_cents(connection):
  risk = 0
  for row in connection.execute("""
    SELECT remaining_basis_cents, entry_price, stop_price
    FROM demo_positions WHERE status = 'open'
  """).fetchall():
    entry = float(row["entry_price"] or 0)
    if entry > 0:
      risk += round(int(row["remaining_basis_cents"] or 0) * abs(entry - float(row["stop_price"])) / entry)
  return risk


def day_trade_entries_last_24h(connection, timestamp=None):
  timestamp = int(timestamp or now_ms())
  row = connection.execute("""
    SELECT COUNT(*) total FROM demo_positions
    WHERE horizon = 'day' AND opened_at >= ? AND opened_at <= ?
  """, (timestamp - DAY_MS, timestamp)).fetchone()
  return int(row["total"] or 0)


def create_entry_orders(connection, symbol, recommendations, timestamp=None):
  timestamp = int(timestamp or now_ms())
  account = _account(connection)
  if not account or timestamp < int(account["started_at"]):
    return 0
  created = 0
  aggressive_day = day_trade_entries_last_24h(connection, timestamp) < MINIMUM_DAY_TRADES_24H
  for candidate in candidates_from_recommendations(symbol, recommendations, timestamp, aggressive_day):
    policy = HORIZON_POLICY[candidate["horizon"]]
    if min(candidate["reference_price"], candidate["stop_reference"], candidate["target1_reference"], candidate["target2_reference"]) <= 0:
      continue
    if candidate["signal_at"] < int(account["started_at"]):
      continue
    existing = connection.execute("""
      SELECT 1 FROM demo_positions WHERE symbol = ? AND horizon = ? AND status = 'open'
      UNION ALL
      SELECT 1 FROM demo_orders WHERE symbol = ? AND horizon = ? AND action = 'entry' AND status IN ('pending', 'triggered')
      LIMIT 1
    """, (symbol, candidate["horizon"], symbol, candidate["horizon"])).fetchone()
    if existing:
      continue
    identity = f"{VERSION}|{symbol}|{candidate['horizon']}|{candidate['timeframe']}|{candidate['direction']}|{candidate['signal_at']}"
    idempotency_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    order_id = _hash_id("demo-order", idempotency_key)
    equity = calculate_account_values(connection)["equity_cents"]
    risk_cents = max(0, round(equity * policy["risk_pct"] / 100))
    position_cap = max(0, round(equity * policy["max_position_pct"] / 100))
    portfolio_room = max(0, round(equity * 0.90) - _open_exposure_cents(connection))
    symbol_room = max(0, round(equity * 0.40) - _open_exposure_cents(connection, symbol))
    max_notional = min(position_cap, portfolio_room, symbol_room, max(0, int(account["cash_cents"]) - COMMISSION_CENTS))
    if max_notional < 2_500:
      continue
    details = {
      "setup": candidate["setup"],
      "setupType": candidate["setup_type"],
      "score": candidate["score"],
      "riskReward": candidate["risk_reward"],
      "referenceEntry": candidate["reference_price"],
      "referenceStop": candidate["stop_reference"],
      "referenceTarget1": candidate["target1_reference"],
      "referenceTarget2": candidate["target2_reference"],
      "atrAtSignal": candidate["atr"],
      "entryConfirmation": candidate["entry_confirmation"],
      "stopConfirmation": "close",
      "exitRules": candidate["exit_rules"],
      "marketPhase": candidate["market_phase"],
      "marketRegime": candidate["market_regime"],
      "strategyVersion": candidate["strategy_version"],
      "reasons": candidate["reasons"],
      "selectionMode": candidate.get("selection_mode") or "qualified",
    }
    instrument = SYMBOL_POLICY[symbol]
    cursor = connection.execute("""
      INSERT OR IGNORE INTO demo_orders (
        id, idempotency_key, account_id, symbol, execution_symbol, currency,
        horizon, timeframe, direction, action, status, signal_at, eligible_at,
        expires_at, reference_price, planned_risk_cents, max_notional_cents,
        reason, details_json, created_at, updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'entry', 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
      order_id, idempotency_key, ACCOUNT_ID, symbol, instrument["execution_symbol"], instrument["currency"],
      candidate["horizon"], candidate["timeframe"], candidate["direction"], candidate["signal_at"],
      candidate["actionable_at"], candidate["actionable_at"] + policy["entry_expiry_ms"], candidate["reference_price"],
      risk_cents, max_notional,
      "daily_activity_target" if candidate.get("selection_mode") == "activity_target" else "qualified_system_signal",
      json.dumps(details), timestamp, timestamp,
    ))
    created += int(cursor.rowcount > 0)
  return created


def _usd_value_cents(price, quantity, fx_rate):
  return max(0, round(float(price) * float(quantity) * float(fx_rate) * 100))


def _fx_rate_at(source, timestamp):
  if isinstance(source, (int, float)):
    rate = float(source)
    return rate if math.isfinite(rate) and rate > 0 else None
  if isinstance(source, (list, tuple)):
    selected = None
    for item in source:
      item_time = int(item.get("time") or 0)
      if item_time > int(timestamp):
        break
      rate = float(item.get("rate") or 0)
      if math.isfinite(rate) and rate > 0:
        selected = rate
    return selected
  return None


def _adverse_fill(price, direction, action, bps):
  entry = action == "entry"
  buying = (direction == "long" and entry) or (direction == "short" and not entry)
  factor = 1 + float(bps) / 10_000 if buying else 1 - float(bps) / 10_000
  return float(price) * factor


def _first_bar_after(bars, eligible_at, expires_at=None):
  return next((bar for bar in bars if int(bar.get("time") or 0) >= eligible_at and (expires_at is None or int(bar.get("time") or 0) <= expires_at)), None)


def _timeframe_bars(bars, timeframe):
  if isinstance(bars, dict):
    return list(bars.get(timeframe) or bars.get(str(timeframe)) or [])
  return list(bars or [])


def _entry_hit(details, direction, bar):
  trigger = float(details.get("referenceEntry") or 0)
  confirmation = str(details.get("entryConfirmation") or "close")
  if direction == "long":
    return float(bar["close"] if confirmation == "close" else bar["high"]) >= trigger
  return float(bar["close"] if confirmation == "close" else bar["low"]) <= trigger


def _entry_invalidated(details, direction, bar):
  stop = float(details.get("referenceStop") or 0)
  return float(bar["low"]) <= stop if direction == "long" else float(bar["high"]) >= stop


def _cost_aware_fill_levels(details, direction, horizon, fill_price, max_notional_cents):
  reference_entry = float(details.get("referenceEntry") or 0)
  if reference_entry <= 0 or fill_price <= 0 or max_notional_cents <= 0:
    return None
  original_stop = float(details.get("referenceStop") or 0)
  original_target1 = float(details.get("referenceTarget1") or 0)
  original_target2 = float(details.get("referenceTarget2") or 0)
  if min(original_stop, original_target1, original_target2) <= 0:
    return None
  if direction == "long" and not (original_stop < fill_price < original_target1 <= original_target2):
    return None
  if direction == "short" and not (original_stop > fill_price > original_target1 >= original_target2):
    return None

  policy = STOP_POLICY[horizon]
  original_stop_distance = abs(fill_price - original_stop)
  atr_distance = max(0.0, float(details.get("atrAtSignal") or 0)) * policy["minimum_atr"]
  percentage_distance = fill_price * policy["minimum_pct"]
  economic_distance = fill_price * MINIMUM_GROSS_STOP_CENTS / max_notional_cents
  stop_distance = max(original_stop_distance, atr_distance, percentage_distance, economic_distance)
  stop_was_widened = stop_distance > original_stop_distance + 1e-9
  if stop_was_widened and stop_distance / fill_price > policy["maximum_pct"]:
    return None

  target1_distance = max(abs(original_target1 - fill_price), stop_distance * policy["minimum_target_r"])
  target2_distance = max(abs(original_target2 - fill_price), target1_distance * 1.35, stop_distance * 1.70)
  sign = 1 if direction == "long" else -1
  stop_price = fill_price - sign * stop_distance
  target1_price = fill_price + sign * target1_distance
  target2_price = fill_price + sign * target2_distance
  if min(stop_price, target1_price, target2_price) <= 0:
    return None
  return {
    "stop": stop_price,
    "target1": target1_price,
    "target2": target2_price,
    "stopDistancePct": stop_distance / fill_price,
    "stopAdjusted": stop_was_widened,
    "minimumGrossStopCents": MINIMUM_GROSS_STOP_CENTS,
  }


def fill_pending_entries(connection, symbol, bars, fx_rate=1.0, timestamp=None, horizons=None, session_regular=None, fill_bars=None):
  timestamp = int(timestamp or now_ms())
  rows = connection.execute("""
    SELECT * FROM demo_orders
    WHERE symbol = ? AND action = 'entry' AND status IN ('pending', 'triggered')
    ORDER BY eligible_at, created_at
  """, (symbol,)).fetchall()
  if horizons:
    rows = [row for row in rows if row["horizon"] in horizons]
  filled = 0
  for order in rows:
    details = _json(order["details_json"])
    eligible_bars = _timeframe_bars(bars, int(order["timeframe"]))
    if order["horizon"] == "day" and session_regular is not None:
      eligible_bars = [bar for bar in eligible_bars if session_regular(int(bar.get("time") or 0), symbol)]
    status = order["status"]
    fill_eligible_at = order["fill_eligible_at"]
    if status == "pending" and order["expires_at"] and timestamp > int(order["expires_at"]):
      connection.execute("UPDATE demo_orders SET status = 'cancelled', reason = 'entry_expired', updated_at = ? WHERE id = ?", (timestamp, order["id"]))
      continue
    if status == "pending":
      trigger_bar = None
      for candidate_bar in eligible_bars:
        bar_time = int(candidate_bar.get("time") or 0)
        if bar_time < int(order["eligible_at"]):
          continue
        if order["expires_at"] and bar_time > int(order["expires_at"]):
          break
        hit = _entry_hit(details, order["direction"], candidate_bar)
        invalidated = _entry_invalidated(details, order["direction"], candidate_bar)
        if invalidated and not hit:
          connection.execute("UPDATE demo_orders SET status = 'cancelled', reason = 'invalidated_before_entry', updated_at = ? WHERE id = ?", (timestamp, order["id"]))
          trigger_bar = None
          status = "cancelled"
          break
        if hit and invalidated:
          connection.execute("UPDATE demo_orders SET status = 'cancelled', reason = 'ambiguous_entry_bar', updated_at = ? WHERE id = ?", (timestamp, order["id"]))
          trigger_bar = None
          status = "cancelled"
          break
        if hit:
          trigger_bar = candidate_bar
          break
      if status == "cancelled" or trigger_bar is None:
        continue
      triggered_at = int(trigger_bar["time"])
      confirmation = str(details.get("entryConfirmation") or "close")
      fill_eligible_at = triggered_at + (max(1, int(order["timeframe"])) * 60_000 if confirmation == "close" else 0)
      details["triggeredAt"] = triggered_at
      details["fillEligibleAt"] = fill_eligible_at
      connection.execute("""
        UPDATE demo_orders SET status = 'triggered', triggered_at = ?, fill_eligible_at = ?,
          details_json = ?, reason = 'entry_trigger_confirmed', updated_at = ? WHERE id = ?
      """, (triggered_at, fill_eligible_at, json.dumps(details), timestamp, order["id"]))
      status = "triggered"
    execution_bars = _timeframe_bars(fill_bars, int(order["timeframe"])) if fill_bars is not None else eligible_bars
    if order["horizon"] == "day" and session_regular is not None:
      execution_bars = [bar for bar in execution_bars if session_regular(int(bar.get("time") or 0), symbol)]
    fill_deadline = int(order["expires_at"]) + max(1, int(order["timeframe"])) * 60_000 if order["expires_at"] else None
    bar = _first_bar_after(execution_bars, int(fill_eligible_at or order["eligible_at"]), fill_deadline)
    if not bar:
      if status == "triggered" and fill_deadline and timestamp > fill_deadline:
        connection.execute("UPDATE demo_orders SET status = 'cancelled', reason = 'triggered_fill_expired', updated_at = ? WHERE id = ?", (timestamp, order["id"]))
      continue
    event_at = int(bar["time"])
    bar_fx_rate = _fx_rate_at(fx_rate, event_at)
    if bar_fx_rate is None:
      continue
    account = _account(connection)
    instrument = SYMBOL_POLICY[symbol]
    reference_entry = float(details.get("referenceEntry") or 0)
    confirmation = str(details.get("entryConfirmation") or "close")
    raw_fill = float(bar["open"])
    if confirmation != "close":
      raw_fill = max(raw_fill, reference_entry) if order["direction"] == "long" else min(raw_fill, reference_entry)
    adverse_gap = (raw_fill - reference_entry) if order["direction"] == "long" else (reference_entry - raw_fill)
    maximum_gap = max(float(details.get("atrAtSignal") or 0) * 0.5, reference_entry * (0.004 if order["horizon"] == "day" else 0.015 if order["horizon"] == "swing" else 0.025))
    if adverse_gap > maximum_gap:
      connection.execute("UPDATE demo_orders SET status = 'rejected', reason = 'entry_gap_too_large', updated_at = ? WHERE id = ?", (timestamp, order["id"]))
      continue
    fill_price = _adverse_fill(raw_fill, order["direction"], "entry", instrument["slippage_bps"])
    equity = calculate_account_values(connection)["equity_cents"]
    policy = HORIZON_POLICY[order["horizon"]]
    max_notional = min(
      int(order["max_notional_cents"]),
      max(0, int(account["cash_cents"]) - COMMISSION_CENTS),
      max(0, round(equity * policy["max_position_pct"] / 100)),
      max(0, round(equity * 0.90) - _open_exposure_cents(connection)),
      max(0, round(equity * 0.40) - _open_exposure_cents(connection, symbol)),
    )
    levels = _cost_aware_fill_levels(details, order["direction"], order["horizon"], fill_price, max_notional)
    if not levels:
      connection.execute("UPDATE demo_orders SET status = 'rejected', reason = 'invalid_or_uneconomic_fill_levels', updated_at = ? WHERE id = ?", (timestamp, order["id"]))
      continue
    stop_pct = levels["stopDistancePct"]
    portfolio_risk_room = max(0, round(equity * 0.04) - _open_risk_cents(connection))
    risk_notional = int(min(int(order["planned_risk_cents"]), portfolio_risk_room) / stop_pct)
    notional_budget = min(max_notional, risk_notional)
    unit_usd = fill_price * bar_fx_rate
    if unit_usd <= 0:
      continue
    raw_quantity = (notional_budget / 100) / unit_usd
    quantity = math.floor(raw_quantity * 100_000_000) / 100_000_000 if instrument["fractional"] else math.floor(raw_quantity)
    notional_cents = _usd_value_cents(fill_price, quantity, bar_fx_rate)
    if quantity <= 0 or notional_cents + COMMISSION_CENTS > int(account["cash_cents"]):
      connection.execute("UPDATE demo_orders SET status = 'rejected', reason = 'insufficient_cash', updated_at = ? WHERE id = ?", (timestamp, order["id"]))
      continue
    levels = _cost_aware_fill_levels(details, order["direction"], order["horizon"], fill_price, notional_cents)
    if not levels:
      connection.execute("UPDATE demo_orders SET status = 'rejected', reason = 'uneconomic_stop_distance', updated_at = ? WHERE id = ?", (timestamp, order["id"]))
      continue
    stop_pct = levels["stopDistancePct"]
    stop_price = levels["stop"]
    target1_price = levels["target1"]
    target2_price = levels["target2"]
    details["executionStopPolicy"] = {
      "version": VERSION,
      "adjusted": levels["stopAdjusted"],
      "stopDistancePct": round(stop_pct, 6),
      "minimumGrossStopRisk": _money(levels["minimumGrossStopCents"]),
      "roundTripCommission": _money(COMMISSION_CENTS * 2),
    }
    position_details_json = json.dumps(details)
    initial_risk_cents = round(notional_cents * stop_pct)
    stop_confirmation = str(details.get("stopConfirmation") or "close")
    selection_mode = str(details.get("selectionMode") or "qualified")
    exit_policy_json = json.dumps({
      "stopConfirmation": stop_confirmation,
      "rules": list(details.get("exitRules") or []),
      "trailAfterTarget1": True,
    })
    position_id = _hash_id("demo-position", order["id"])
    fill_id = _hash_id("demo-fill", order["id"])
    _cash_event(connection, f"{order['id']}:entry_notional", event_at, "entry_notional", -notional_cents, order["id"], position_id)
    _cash_event(connection, f"{order['id']}:commission", event_at, "commission", -COMMISSION_CENTS, order["id"], position_id)
    connection.execute("""
      INSERT INTO demo_positions (
        id, account_id, entry_order_id, symbol, execution_symbol, currency,
        horizon, timeframe, direction, setup, setup_type, score, signal_at,
        opened_at, status, quantity, remaining_quantity, entry_price, entry_fx_rate,
        entry_value_cents, remaining_basis_cents, stop_price, target1_price,
        target2_price, last_price, last_fx_rate, last_valued_at, last_bar_at,
        commission_cents, strategy_version, details_json, initial_risk_cents,
        original_stop_price, original_target1_price, original_target2_price,
        trailing_stop_price, stop_confirmation, selection_mode, policy_version, exit_policy_json,
        last_intraday_bar_at, last_daily_bar_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
      position_id, ACCOUNT_ID, order["id"], symbol, order["execution_symbol"], order["currency"],
      order["horizon"], order["timeframe"], order["direction"], str(details.get("setup") or "Momentum setup"),
      str(details.get("setupType") or "momentum"), int(details.get("score") or 0), order["signal_at"], event_at,
      quantity, quantity, fill_price, bar_fx_rate, notional_cents, notional_cents, stop_price, target1_price,
      target2_price, fill_price, bar_fx_rate, event_at, event_at - 1, COMMISSION_CENTS,
      str(details.get("strategyVersion") or "unknown"), position_details_json, initial_risk_cents,
      float(details.get("referenceStop") or stop_price), float(details.get("referenceTarget1") or target1_price),
      float(details.get("referenceTarget2") or target2_price), None, stop_confirmation, selection_mode, VERSION, exit_policy_json,
      event_at - 1, event_at - 1,
    ))
    connection.execute("""
      INSERT INTO demo_fills (
        id, order_id, position_id, symbol, horizon, direction, action, quantity,
        price, fx_rate, notional_cents, commission_cents, filled_at, reason, fill_model
      ) VALUES (?, ?, ?, ?, ?, ?, 'entry', ?, ?, ?, ?, ?, ?, ?, ?)
    """, (fill_id, order["id"], position_id, symbol, order["horizon"], order["direction"], quantity, fill_price, bar_fx_rate, notional_cents, COMMISSION_CENTS, event_at, "entry_trigger_confirmed", "next_bar_open" if confirmation == "close" else "trigger_touch"))
    connection.execute("""
      UPDATE demo_orders SET position_id = ?, quantity = ?, status = 'filled', fill_price = ?,
        fill_fx_rate = ?, filled_at = ?, commission_cents = ?, details_json = ?, updated_at = ? WHERE id = ?
    """, (position_id, quantity, fill_price, bar_fx_rate, event_at, COMMISSION_CENTS, position_details_json, event_at, order["id"]))
    filled += 1
  return filled


def _unrealized_cents(position, price, fx_rate):
  current = _usd_value_cents(price, position["remaining_quantity"], fx_rate)
  basis = int(position["remaining_basis_cents"])
  return current - basis if position["direction"] == "long" else basis - current


def _exit_trigger(
  position, bar, timestamp, session_is_regular=True, allow_stop=True, allow_targets=True,
  allow_time_exit=True, indicators=None, allow_momentum=True,
):
  long = position["direction"] == "long"
  if position["horizon"] == "day" and not session_is_regular:
    return "session_close", float(position["last_price"]), 1.0
  stop = float(position["trailing_stop_price"] or position["stop_price"])
  close_confirmation = str(position["stop_confirmation"] or "touch") == "close"
  stop_hit = allow_stop and ((float(bar["close"]) <= stop if long else float(bar["close"]) >= stop) if close_confirmation else (float(bar["low"]) <= stop if long else float(bar["high"]) >= stop))
  entry_bar = int(bar["time"]) == int(position["opened_at"])
  target2_hit = allow_targets and not entry_bar and (float(bar["high"]) >= position["target2_price"] if long else float(bar["low"]) <= position["target2_price"])
  target1_hit = allow_targets and not entry_bar and (float(bar["high"]) >= position["target1_price"] if long else float(bar["low"]) <= position["target1_price"])
  if stop_hit:
    if close_confirmation:
      raw_price = float(bar["close"])
    else:
      raw_price = min(stop, float(bar["open"])) if long else max(stop, float(bar["open"]))
    return ("ambiguous_stop" if target1_hit or target2_hit else "stop"), raw_price, 1.0
  if target2_hit:
    raw_price = max(float(position["target2_price"]), float(bar["open"])) if long else min(float(position["target2_price"]), float(bar["open"]))
    return "target2", raw_price, 1.0
  if target1_hit and not position["target1_hit_at"]:
    raw_price = max(float(position["target1_price"]), float(bar["open"])) if long else min(float(position["target1_price"]), float(bar["open"]))
    return "target1", raw_price, 0.5
  if allow_momentum and isinstance(indicators, dict):
    ema20 = indicators.get("ema20")
    rsi = indicators.get("rsi")
    if ema20 is not None and rsi is not None:
      momentum_failed = (
        (long and float(bar["close"]) < float(ema20) and float(rsi) < 45)
        or (not long and float(bar["close"]) > float(ema20) and float(rsi) > 55)
      )
      if momentum_failed:
        return "momentum_exit", float(bar["close"]), 1.0
  max_holding = HORIZON_POLICY[position["horizon"]]["max_holding_ms"]
  if allow_time_exit and timestamp - int(position["opened_at"]) >= max_holding:
    return "time_exit", float(bar["close"]), 1.0
  return None


def _close_quantity(connection, position, quantity, raw_price, fx_rate, event_at, reason):
  instrument = SYMBOL_POLICY[position["symbol"]]
  fill_price = _adverse_fill(raw_price, position["direction"], "exit", instrument["slippage_bps"])
  remaining_before = float(position["remaining_quantity"])
  quantity = min(remaining_before, quantity)
  is_final = quantity >= remaining_before - 1e-9
  basis_cents = int(position["remaining_basis_cents"]) if is_final else round(int(position["remaining_basis_cents"]) * quantity / remaining_before)
  exit_notional_cents = _usd_value_cents(fill_price, quantity, fx_rate)
  gross_cents = exit_notional_cents - basis_cents if position["direction"] == "long" else basis_cents - exit_notional_cents
  sequence = connection.execute("SELECT COUNT(*) total FROM demo_fills WHERE position_id = ?", (position["id"],)).fetchone()["total"]
  order_id = _hash_id("demo-order", position["id"], "exit", sequence, reason, event_at)
  fill_id = _hash_id("demo-fill", order_id)
  idempotency_key = hashlib.sha256(f"{position['id']}|exit|{sequence}|{reason}|{event_at}".encode("utf-8")).hexdigest()
  if reason in {"stop", "ambiguous_stop"} and str(position["stop_confirmation"] or "touch") == "close":
    fill_model = "close_confirmation"
  elif reason in {"stop", "ambiguous_stop"} and abs(float(raw_price) - float(position["stop_price"])) > 1e-9:
    fill_model = "gap_open"
  elif reason in {"momentum_exit", "time_exit", "session_close"}:
    fill_model = "bar_close"
  else:
    fill_model = "bar_level"
  connection.execute("""
    INSERT INTO demo_orders (
      id, idempotency_key, account_id, position_id, symbol, execution_symbol,
      currency, horizon, timeframe, direction, action, quantity, status,
      signal_at, eligible_at, reference_price, fill_price, fill_fx_rate,
      filled_at, commission_cents, reason, details_json, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'exit', ?, 'filled', ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)
  """, (order_id, idempotency_key, ACCOUNT_ID, position["id"], position["symbol"], position["execution_symbol"], position["currency"], position["horizon"], position["timeframe"], position["direction"], quantity, event_at, event_at, raw_price, fill_price, fx_rate, event_at, COMMISSION_CENTS, reason, event_at, event_at))
  connection.execute("""
    INSERT INTO demo_fills (
      id, order_id, position_id, symbol, horizon, direction, action, quantity,
        price, fx_rate, notional_cents, commission_cents, filled_at, reason,
        fill_model, ambiguous
      ) VALUES (?, ?, ?, ?, ?, ?, 'exit', ?, ?, ?, ?, ?, ?, ?, ?, ?)
  """, (fill_id, order_id, position["id"], position["symbol"], position["horizon"], position["direction"], quantity, fill_price, fx_rate, exit_notional_cents, COMMISSION_CENTS, event_at, reason, fill_model, 1 if reason == "ambiguous_stop" else 0))
  if position["direction"] == "long":
    _cash_event(connection, f"{order_id}:exit_value", event_at, "exit_value", exit_notional_cents, order_id, position["id"])
  else:
    _cash_event(connection, f"{order_id}:collateral_release", event_at, "collateral_release", basis_cents + gross_cents, order_id, position["id"])
  _cash_event(connection, f"{order_id}:commission", event_at, "commission", -COMMISSION_CENTS, order_id, position["id"])
  total_gross = int(position["realized_gross_cents"]) + gross_cents
  total_commission = int(position["commission_cents"]) + COMMISSION_CENTS
  borrow_cents = int(position["borrow_cents"] or 0)
  if is_final and position["direction"] == "short":
    holding_days = max(1.0, (event_at - int(position["opened_at"])) / DAY_MS)
    borrow_cents += round(int(position["entry_value_cents"]) * SHORT_BORROW_ANNUAL_RATE * holding_days / 365)
    if borrow_cents:
      _cash_event(connection, f"{position['id']}:borrow", event_at, "borrow_fee", -borrow_cents, order_id, position["id"], {"annualRate": SHORT_BORROW_ANNUAL_RATE, "holdingDays": holding_days})
  tax_cents = 0
  if is_final:
    taxable_cents = max(0, total_gross - total_commission - borrow_cents)
    tax_cents = round(taxable_cents * TAX_RATE)
    if tax_cents:
      _cash_event(connection, f"{position['id']}:tax", event_at, "tax", -tax_cents, order_id, position["id"], {"rate": TAX_RATE})
  remaining_quantity = 0 if is_final else remaining_before - quantity
  remaining_basis = 0 if is_final else int(position["remaining_basis_cents"]) - basis_cents
  net_pnl = total_gross - total_commission - borrow_cents - tax_cents if is_final else total_gross - total_commission
  connection.execute("""
    UPDATE demo_positions SET remaining_quantity = ?, remaining_basis_cents = ?,
      realized_gross_cents = ?, commission_cents = ?, tax_cents = tax_cents + ?,
      net_pnl_cents = ?, borrow_cents = ?, target1_hit_at = CASE WHEN ? = 'target1' THEN ? ELSE target1_hit_at END,
      status = CASE WHEN ? THEN 'closed' ELSE status END,
      closed_at = CASE WHEN ? THEN ? ELSE closed_at END,
      close_reason = CASE WHEN ? THEN ? ELSE close_reason END,
      last_price = ?, last_fx_rate = ?, last_valued_at = ?, last_bar_at = ?
    WHERE id = ?
  """, (remaining_quantity, remaining_basis, total_gross, total_commission, tax_cents, net_pnl, borrow_cents, reason, event_at, 1 if is_final else 0, 1 if is_final else 0, event_at, 1 if is_final else 0, reason, fill_price, fx_rate, event_at, event_at, position["id"]))


def _update_trailing_stop(connection, position, indicators):
  if not position["target1_hit_at"] or not isinstance(indicators, dict):
    return position
  atr = max(0.0, float(indicators.get("atr") or 0))
  ema20 = indicators.get("ema20")
  vwap = indicators.get("vwap") if position["horizon"] == "day" else None
  anchors = [float(value) for value in (ema20, vwap) if value is not None and math.isfinite(float(value))]
  if not anchors:
    return position
  buffer = atr * 0.20
  current = float(position["trailing_stop_price"] or position["stop_price"])
  if position["direction"] == "long":
    candidate = max(anchors) - buffer
    candidate = min(candidate, float(position["last_price"]) - max(buffer, float(position["last_price"]) * 0.0002))
    trailing = max(current, candidate)
  else:
    candidate = min(anchors) + buffer
    candidate = max(candidate, float(position["last_price"]) + max(buffer, float(position["last_price"]) * 0.0002))
    trailing = min(current, candidate)
  if abs(trailing - current) <= 1e-9:
    return position
  connection.execute("UPDATE demo_positions SET trailing_stop_price = ?, stop_price = ? WHERE id = ?", (trailing, trailing, position["id"]))
  return connection.execute("SELECT * FROM demo_positions WHERE id = ?", (position["id"],)).fetchone()


def evaluate_open_positions(
  connection, symbol, bars, fx_rate=1.0, timestamp=None, session_regular=None,
  horizons=None, indicator_context=None, stream="intraday", allow_stop=True,
  allow_targets=True, allow_time_exit=True, allow_momentum=True,
):
  timestamp = int(timestamp or now_ms())
  rows = connection.execute("SELECT * FROM demo_positions WHERE symbol = ? AND status = 'open' ORDER BY opened_at", (symbol,)).fetchall()
  if horizons:
    rows = [row for row in rows if row["horizon"] in horizons]
  exits = 0
  for original in rows:
    position = original
    relevant_bars = _timeframe_bars(bars, int(position["timeframe"])) if isinstance(bars, dict) else list(bars or [])
    cursor_column = "last_daily_bar_at" if stream == "daily" else "last_intraday_bar_at"
    relevant = [bar for bar in relevant_bars if int(bar.get("time") or 0) > int(position[cursor_column])]
    for bar in relevant:
      bar_fx_rate = _fx_rate_at(fx_rate, int(bar["time"]))
      if bar_fx_rate is None:
        continue
      indicators = {}
      if bar is relevant[-1]:
        indicators = (indicator_context or {}).get(int(position["timeframe"])) or (indicator_context or {}).get(str(position["timeframe"])) or {}
      position = _update_trailing_stop(connection, position, indicators)
      regular = True if session_regular is None else bool(session_regular(int(bar["time"]), symbol))
      trigger = _exit_trigger(
        position, bar, int(bar["time"]), regular, allow_stop, allow_targets,
        allow_time_exit, indicators, allow_momentum,
      )
      if trigger:
        reason, price, fraction = trigger
        quantity = float(position["remaining_quantity"]) * fraction
        if not SYMBOL_POLICY[symbol]["fractional"] and fraction < 1:
          quantity = max(1, math.floor(quantity))
        _close_quantity(connection, position, quantity, price, bar_fx_rate, int(bar["time"]), reason)
        exits += 1
        position = connection.execute("SELECT * FROM demo_positions WHERE id = ?", (position["id"],)).fetchone()
        connection.execute(f"UPDATE demo_positions SET {cursor_column} = ?, last_bar_at = MAX(last_bar_at, ?) WHERE id = ?", (int(bar["time"]), int(bar["time"]), position["id"]))
        if position["status"] != "open":
          break
      else:
        unrealized = _unrealized_cents(position, float(bar["close"]), bar_fx_rate)
        favorable = max(int(position["max_favorable_cents"]), unrealized)
        adverse = min(int(position["max_adverse_cents"]), unrealized)
        connection.execute(f"""
          UPDATE demo_positions SET last_price = ?, last_fx_rate = ?, last_valued_at = ?,
            last_bar_at = MAX(last_bar_at, ?), max_favorable_cents = ?, max_adverse_cents = ?,
            {cursor_column} = ? WHERE id = ?
        """, (float(bar["close"]), bar_fx_rate, int(bar["time"]), int(bar["time"]), favorable, adverse, int(bar["time"]), position["id"]))
        position = connection.execute("SELECT * FROM demo_positions WHERE id = ?", (position["id"],)).fetchone()
  return exits


def mark_open_positions(connection, symbol, price, fx_rate=1.0, valued_at=None):
  valued_at = int(valued_at or now_ms())
  if price is None or not math.isfinite(float(price)) or float(price) <= 0:
    return 0
  rows = connection.execute("SELECT * FROM demo_positions WHERE symbol = ? AND status = 'open'", (symbol,)).fetchall()
  for position in rows:
    unrealized = _unrealized_cents(position, float(price), fx_rate)
    connection.execute("""
      UPDATE demo_positions SET last_price = ?, last_fx_rate = ?, last_valued_at = ?,
        max_favorable_cents = MAX(max_favorable_cents, ?),
        max_adverse_cents = MIN(max_adverse_cents, ?) WHERE id = ?
    """, (float(price), fx_rate, valued_at, unrealized, unrealized, position["id"]))
  return len(rows)


def process_market(
  connection, symbol, recommendations, intraday_bars, daily_bars, fx_rate=1.0,
  timestamp=None, session_regular=None, latest_quote=None, indicator_context=None,
):
  timestamp = int(timestamp or now_ms())
  current_fx_rate = _fx_rate_at(fx_rate, timestamp)
  if symbol not in SYMBOL_POLICY or current_fx_rate is None:
    return {"created": 0, "filled": 0, "exits": 0}
  created = create_entry_orders(connection, symbol, recommendations or {}, timestamp)
  filled = fill_pending_entries(connection, symbol, intraday_bars, fx_rate, timestamp, {"day"}, session_regular)
  intraday_fill_bars = _timeframe_bars(intraday_bars, 5) or _timeframe_bars(intraday_bars, 1)
  filled += fill_pending_entries(connection, symbol, daily_bars, fx_rate, timestamp, {"swing", "long"}, fill_bars=intraday_fill_bars)
  exits = 0
  exits += evaluate_open_positions(connection, symbol, intraday_bars, fx_rate, timestamp, session_regular, {"day"}, indicator_context)
  exits += evaluate_open_positions(
    connection, symbol, intraday_fill_bars, fx_rate, timestamp, session_regular,
    {"swing", "long"}, indicator_context, "intraday", False, True, False, False,
  )
  exits += evaluate_open_positions(
    connection, symbol, daily_bars, fx_rate, timestamp, session_regular,
    {"swing", "long"}, indicator_context, "daily", True, False, True,
  )
  if isinstance(latest_quote, dict):
    quote_at = latest_quote.get("time") or timestamp
    quote_fx_rate = _fx_rate_at(fx_rate, quote_at) or current_fx_rate
    mark_open_positions(connection, symbol, latest_quote.get("price"), quote_fx_rate, quote_at)
  record_equity_snapshot(connection, timestamp)
  return {"created": created, "filled": filled, "exits": exits}


def calculate_account_values(connection):
  account = _account(connection)
  positions = connection.execute("SELECT * FROM demo_positions WHERE status = 'open'").fetchall()
  invested = 0
  collateral = 0
  unrealized = 0
  for position in positions:
    value = _usd_value_cents(position["last_price"], position["remaining_quantity"], position["last_fx_rate"])
    if position["direction"] == "long":
      invested += value
    else:
      collateral += int(position["remaining_basis_cents"])
    unrealized += _unrealized_cents(position, position["last_price"], position["last_fx_rate"])
  equity = int(account["cash_cents"]) + invested + collateral + (unrealized if collateral else 0)
  # Long market value already contains its unrealized P&L. Only short P&L is additive.
  short_unrealized = sum(
    _unrealized_cents(position, position["last_price"], position["last_fx_rate"])
    for position in positions if position["direction"] == "short"
  )
  equity = int(account["cash_cents"]) + invested + collateral + short_unrealized
  return {
    "cash_cents": int(account["cash_cents"]),
    "invested_cents": invested,
    "collateral_cents": collateral,
    "unrealized_cents": unrealized,
    "equity_cents": equity,
  }


def record_equity_snapshot(connection, timestamp=None):
  timestamp = int(timestamp or now_ms())
  bucket = timestamp - timestamp % (5 * 60_000)
  values = calculate_account_values(connection)
  account = _account(connection)
  high = max(int(account["high_watermark_cents"]), values["equity_cents"])
  drawdown_bps = round(max(0, high - values["equity_cents"]) / high * 10_000) if high > 0 else 0
  max_drawdown = max(int(account["max_drawdown_bps"]), drawdown_bps)
  connection.execute("UPDATE demo_accounts SET high_watermark_cents = ?, max_drawdown_bps = ?, updated_at = ? WHERE id = ?", (high, max_drawdown, timestamp, ACCOUNT_ID))
  connection.execute("""
    INSERT INTO demo_equity_snapshots (
      account_id, snapshot_at, cash_cents, invested_cents, collateral_cents,
      unrealized_cents, equity_cents
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(account_id, snapshot_at) DO UPDATE SET
      cash_cents = excluded.cash_cents, invested_cents = excluded.invested_cents,
      collateral_cents = excluded.collateral_cents, unrealized_cents = excluded.unrealized_cents,
      equity_cents = excluded.equity_cents
  """, (ACCOUNT_ID, bucket, values["cash_cents"], values["invested_cents"], values["collateral_cents"], values["unrealized_cents"], values["equity_cents"]))
  return values


def _money(cents):
  return round(int(cents or 0) / 100, 2)


def _position_json(row):
  remaining = float(row["remaining_quantity"])
  unrealized = _unrealized_cents(row, row["last_price"], row["last_fx_rate"]) if row["status"] == "open" else 0
  details = _json(row["details_json"])
  return {
    "id": row["id"], "symbol": row["symbol"], "executionSymbol": row["execution_symbol"],
    "currency": row["currency"], "horizon": row["horizon"], "timeframe": int(row["timeframe"]),
    "direction": row["direction"], "setup": row["setup"], "setupType": row["setup_type"],
    "score": int(row["score"]), "signalAt": int(row["signal_at"]), "openedAt": int(row["opened_at"]),
    "closedAt": row["closed_at"], "status": row["status"], "quantity": float(row["quantity"]),
    "remainingQuantity": remaining, "entryPrice": row["entry_price"], "lastPrice": row["last_price"],
    "stop": row["stop_price"], "target1": row["target1_price"], "target2": row["target2_price"],
    "originalStop": row["original_stop_price"], "originalTarget1": row["original_target1_price"],
    "originalTarget2": row["original_target2_price"], "trailingStop": row["trailing_stop_price"],
    "target1HitAt": row["target1_hit_at"], "entryValue": _money(row["entry_value_cents"]),
    "remainingValue": _money(_usd_value_cents(row["last_price"], remaining, row["last_fx_rate"])),
    "initialRisk": _money(row["initial_risk_cents"]),
    "unrealizedPnl": _money(unrealized), "realizedGrossPnl": _money(row["realized_gross_cents"]),
    "commissions": _money(row["commission_cents"]), "taxes": _money(row["tax_cents"]),
    "borrowFees": _money(row["borrow_cents"]),
    "netPnl": _money(row["net_pnl_cents"]), "closeReason": row["close_reason"],
    "lastValuedAt": int(row["last_valued_at"]), "strategyVersion": row["strategy_version"],
    "policyVersion": row["policy_version"], "selectionMode": row["selection_mode"],
    "stopConfirmation": row["stop_confirmation"],
    "stopAdjusted": bool((details.get("executionStopPolicy") or {}).get("adjusted")),
  }


def _wilson_lower_bound(wins, samples, z=1.96):
  if samples <= 0:
    return None
  rate = wins / samples
  denominator = 1 + z * z / samples
  center = rate + z * z / (2 * samples)
  margin = z * math.sqrt((rate * (1 - rate) + z * z / (4 * samples)) / samples)
  return max(0, (center - margin) / denominator)


def learning_snapshot(connection):
  rows = connection.execute("""
    SELECT p.symbol, p.horizon, p.timeframe, p.direction, p.setup_type,
      p.policy_version, p.selection_mode, p.stop_confirmation,
      COUNT(*) samples,
      SUM(CASE WHEN p.net_pnl_cents > 0 THEN 1 ELSE 0 END) wins,
      SUM(p.net_pnl_cents) net_cents,
      AVG(p.net_pnl_cents) average_net_cents,
      SUM(CASE WHEN p.initial_risk_cents > 0 THEN p.initial_risk_cents ELSE 0 END) total_risk_cents,
      AVG(CASE WHEN p.initial_risk_cents > 0 THEN p.initial_risk_cents END) average_risk_cents
    FROM demo_positions p
    WHERE p.status = 'closed'
    GROUP BY p.symbol, p.horizon, p.timeframe, p.direction, p.setup_type,
      p.policy_version, p.selection_mode, p.stop_confirmation
    ORDER BY samples DESC, net_cents DESC
  """).fetchall()
  cohorts = []
  proposals = []
  for row in rows:
    samples = int(row["samples"] or 0)
    wins = int(row["wins"] or 0)
    average_net = int(row["average_net_cents"] or 0)
    total_risk = int(row["total_risk_cents"] or 0)
    average_risk = int(row["average_risk_cents"] or 0)
    expected_r = int(row["net_cents"] or 0) / total_risk if total_risk > 0 else None
    lower_bound = _wilson_lower_bound(wins, samples)
    cohort = {
      "symbol": row["symbol"], "horizon": row["horizon"], "direction": row["direction"],
      "timeframe": int(row["timeframe"]), "setupType": row["setup_type"],
      "policyVersion": row["policy_version"], "selectionMode": row["selection_mode"],
      "stopConfirmation": row["stop_confirmation"], "samples": samples, "wins": wins,
      "winRate": round(wins / samples * 100, 1) if samples else None,
      "winRateLower95": round(lower_bound * 100, 1) if lower_bound is not None else None,
      "netPnl": _money(row["net_cents"]), "averageActualRisk": _money(average_risk),
      "expectedR": round(expected_r, 3) if expected_r is not None else None,
      "validationStatus": "eligible" if samples >= 50 and expected_r is not None else "building",
    }
    cohorts.append(cohort)
    if samples >= 50 and expected_r is not None and expected_r < -0.10 and lower_bound < 0.40:
      proposals.append({
        "cohort": cohort, "action": "tighten",
        "detail": "Shadow-test a higher score threshold and 25% lower risk allocation for this cohort.",
        "applied": False,
      })
    elif samples >= 50 and expected_r is not None and expected_r > 0.15 and lower_bound >= 0.45:
      proposals.append({
        "cohort": cohort, "action": "expand",
        "detail": "Shadow-test a modest priority increase without changing the portfolio risk ceiling.",
        "applied": False,
      })
  total = sum(row["samples"] for row in cohorts)
  return {
    "mode": "shadow_validation",
    "resolvedSamples": total,
    "minimumCohortSamples": 50,
    "cohorts": cohorts,
    "proposals": proposals,
    "automaticChangesApplied": False,
    "detail": "Completed trades are separated by policy, selection mode, timeframe, and exit model. Expected R uses actual filled risk. Changes remain unapplied until a cohort has at least 50 forward outcomes and passes statistical review.",
  }


def account_snapshot(connection, limit=200, offset=0):
  account = _account(connection)
  values = calculate_account_values(connection)
  totals = connection.execute("""
    SELECT COALESCE(SUM(realized_gross_cents), 0) gross,
           COALESCE(SUM(commission_cents), 0) commissions,
           COALESCE(SUM(tax_cents), 0) taxes,
           COALESCE(SUM(borrow_cents), 0) borrow,
           COALESCE(SUM(net_pnl_cents), 0) net,
           SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) closed,
           SUM(CASE WHEN status = 'closed' AND net_pnl_cents > 0 THEN 1 ELSE 0 END) wins,
           SUM(CASE WHEN status = 'closed' AND net_pnl_cents <= 0 THEN 1 ELSE 0 END) losses
    FROM demo_positions
  """).fetchone()
  open_rows = connection.execute("SELECT * FROM demo_positions WHERE status = 'open' ORDER BY opened_at DESC").fetchall()
  history_rows = connection.execute("SELECT * FROM demo_positions WHERE status = 'closed' ORDER BY closed_at DESC LIMIT ? OFFSET ?", (int(limit), int(offset))).fetchall()
  pending_rows = connection.execute("""
    SELECT id, symbol, execution_symbol, horizon, timeframe, direction, status, eligible_at,
           expires_at, reference_price, planned_risk_cents, max_notional_cents, reason, details_json,
           triggered_at, fill_eligible_at
    FROM demo_orders WHERE status IN ('pending', 'triggered') ORDER BY eligible_at
  """).fetchall()
  breakdown = []
  for row in connection.execute("""
    SELECT symbol, horizon, COUNT(*) trades,
      SUM(CASE WHEN status = 'closed' AND net_pnl_cents > 0 THEN 1 ELSE 0 END) wins,
      SUM(CASE WHEN status = 'closed' AND net_pnl_cents <= 0 THEN 1 ELSE 0 END) losses,
      COALESCE(SUM(net_pnl_cents), 0) net_pnl_cents
    FROM demo_positions WHERE status = 'closed' GROUP BY symbol, horizon ORDER BY symbol, horizon
  """).fetchall():
    closed = int(row["trades"] or 0)
    wins = int(row["wins"] or 0)
    breakdown.append({"symbol": row["symbol"], "horizon": row["horizon"], "trades": closed, "wins": wins, "losses": int(row["losses"] or 0), "winRate": round(wins / closed * 100, 1) if closed else None, "netPnl": _money(row["net_pnl_cents"])})
  curve = [{"time": int(row["snapshot_at"]), "equity": _money(row["equity_cents"])} for row in connection.execute("SELECT snapshot_at, equity_cents FROM demo_equity_snapshots ORDER BY snapshot_at DESC LIMIT 10000").fetchall()][::-1]
  closed = int(totals["closed"] or 0)
  net_total = int(totals["net"] or 0)
  net_pnl = values["equity_cents"] - int(account["starting_cash_cents"])
  day_entries = day_trade_entries_last_24h(connection)
  position_ids = [row["id"] for row in [*open_rows, *history_rows]]
  fills_by_position = {position_id: [] for position_id in position_ids}
  if position_ids:
    placeholders = ",".join("?" for _ in position_ids)
    for fill in connection.execute(f"SELECT * FROM demo_fills WHERE position_id IN ({placeholders}) ORDER BY filled_at", position_ids).fetchall():
      fills_by_position[fill["position_id"]].append({
        "action": fill["action"], "quantity": float(fill["quantity"]), "price": float(fill["price"]),
        "fxRate": float(fill["fx_rate"]), "notional": _money(fill["notional_cents"]),
        "commission": _money(fill["commission_cents"]), "filledAt": int(fill["filled_at"]),
        "reason": fill["reason"], "fillModel": fill["fill_model"], "ambiguous": bool(fill["ambiguous"]),
      })
  open_positions = [{**_position_json(row), "fills": fills_by_position.get(row["id"], [])} for row in open_rows]
  trade_history = [{**_position_json(row), "fills": fills_by_position.get(row["id"], [])} for row in history_rows]
  return {
    "account": {
      "id": account["id"], "mode": "demo", "startedAt": int(account["started_at"]),
      "startingCash": _money(account["starting_cash_cents"]), "cash": _money(values["cash_cents"]),
      "investedValue": _money(values["invested_cents"]), "shortCollateral": _money(values["collateral_cents"]),
      "unrealizedPnl": _money(values["unrealized_cents"]), "realizedGrossPnl": _money(totals["gross"]),
      "commissions": _money(totals["commissions"]), "taxes": _money(totals["taxes"]),
      "borrowFees": _money(totals["borrow"]),
      "realizedNetPnl": _money(net_total), "netPnl": _money(net_pnl), "equity": _money(values["equity_cents"]),
      "returnPct": round(net_pnl / int(account["starting_cash_cents"]) * 100, 2),
      "maxDrawdownPct": round(int(account["max_drawdown_bps"]) / 100, 2),
      "closedTrades": closed, "wins": int(totals["wins"] or 0), "losses": int(totals["losses"] or 0),
      "winRate": round(int(totals["wins"] or 0) / closed * 100, 1) if closed else None,
      "dayTradesLast24h": day_entries, "minimumDayTradesTarget": MINIMUM_DAY_TRADES_24H,
      "policyVersion": account["policy_version"], "updatedAt": int(account["updated_at"]),
    },
    "openPositions": open_positions,
    "pendingOrders": [{
      "id": row["id"], "symbol": row["symbol"], "executionSymbol": row["execution_symbol"],
      "horizon": row["horizon"], "timeframe": int(row["timeframe"]), "direction": row["direction"],
      "status": row["status"], "triggeredAt": row["triggered_at"], "fillEligibleAt": row["fill_eligible_at"],
      "eligibleAt": int(row["eligible_at"]), "expiresAt": row["expires_at"], "referencePrice": row["reference_price"],
      "plannedRisk": _money(row["planned_risk_cents"]), "maxNotional": _money(row["max_notional_cents"]),
      "setup": _json(row["details_json"]).get("setup"),
    } for row in pending_rows],
    "tradeHistory": trade_history, "historyTotal": closed, "historyOffset": int(offset), "historyLimit": int(limit),
    "breakdown": breakdown, "equityCurve": curve, "learning": learning_snapshot(connection),
    "rules": {
      "commissionPerOrder": 5, "profitableTradeTaxPct": 25, "leverage": False,
      "reset": False, "focus": "day", "minimumDayTrades24h": MINIMUM_DAY_TRADES_24H,
      "activityTargetMinimumScore": ACTIVE_DAY_MINIMUM_SCORE,
    },
  }


def trade_export_csv(connection):
  output = io.StringIO()
  writer = csv.writer(output)
  writer.writerow([
    "position_id", "symbol", "horizon", "timeframe", "direction", "setup", "score",
    "opened_at", "closed_at", "entry_price", "final_exit_price", "quantity",
    "initial_risk_usd", "gross_pnl_usd", "commissions_usd", "borrow_fees_usd", "tax_usd", "net_pnl_usd",
    "close_reason", "policy_version", "selection_mode", "stop_confirmation",
  ])
  rows = connection.execute("""
    SELECT p.*, (
      SELECT f.price FROM demo_fills f
      WHERE f.position_id = p.id AND f.action = 'exit'
      ORDER BY f.filled_at DESC LIMIT 1
    ) final_exit_price
    FROM demo_positions p ORDER BY p.opened_at
  """).fetchall()
  for row in rows:
    writer.writerow([
      row["id"], row["symbol"], row["horizon"], row["timeframe"], row["direction"],
      row["setup"], row["score"], row["opened_at"], row["closed_at"], row["entry_price"],
      row["final_exit_price"], row["quantity"], _money(row["initial_risk_cents"]),
      _money(row["realized_gross_cents"]), _money(row["commission_cents"]),
      _money(row["borrow_cents"]), _money(row["tax_cents"]), _money(row["net_pnl_cents"]), row["close_reason"],
      row["policy_version"], row["selection_mode"], row["stop_confirmation"],
    ])
  return output.getvalue()


def invariant_findings(connection, timestamp=None):
  timestamp = int(timestamp or now_ms())
  findings = []
  account = _account(connection)
  if int(account["cash_cents"]) < 0:
    findings.append(("critical", "Demo account cash is negative"))
  ledger = connection.execute("SELECT COALESCE(SUM(amount_cents), 0) total FROM demo_ledger WHERE account_id = ?", (ACCOUNT_ID,)).fetchone()
  if int(ledger["total"]) != int(account["cash_cents"]):
    findings.append(("critical", f"Demo cash does not reconcile to the immutable ledger ({account['cash_cents']} vs {ledger['total']} cents)"))
  duplicate = connection.execute("""
    SELECT symbol, horizon, COUNT(*) total FROM demo_positions WHERE status = 'open'
    GROUP BY symbol, horizon HAVING COUNT(*) > 1 LIMIT 1
  """).fetchone()
  if duplicate:
    findings.append(("critical", f"Duplicate open demo positions for {duplicate['symbol']} {duplicate['horizon']}"))
  broken_fill = connection.execute("""
    SELECT o.id FROM demo_orders o
    LEFT JOIN demo_fills f ON f.order_id = o.id
    WHERE o.status = 'filled' AND f.id IS NULL LIMIT 1
  """).fetchone()
  if broken_fill:
    findings.append(("critical", f"Filled demo order {broken_fill['id']} has no fill record"))
  invalid_position = connection.execute("""
    SELECT id, symbol FROM demo_positions
    WHERE quantity <= 0 OR remaining_quantity < 0 OR remaining_quantity > quantity + 0.00000001
      OR entry_price <= 0 OR stop_price <= 0 OR target1_price <= 0 OR target2_price <= 0
      OR (direction = 'long' AND NOT (stop_price < entry_price AND target1_price > entry_price AND target2_price >= target1_price))
      OR (direction = 'short' AND NOT (stop_price > entry_price AND target1_price < entry_price AND target2_price <= target1_price))
    LIMIT 1
  """).fetchone()
  if invalid_position:
    findings.append(("critical", f"Demo position {invalid_position['id']} has invalid quantity or price geometry"))
  stale_trigger = connection.execute("""
    SELECT id FROM demo_orders
    WHERE status = 'triggered' AND expires_at IS NOT NULL AND expires_at < ? LIMIT 1
  """, (timestamp,)).fetchone()
  if stale_trigger:
    findings.append(("warning", f"Triggered demo order {stale_trigger['id']} is past its expiry"))
  stale_crypto = connection.execute("""
    SELECT id FROM demo_positions
    WHERE status = 'open' AND symbol = 'BTC-USD' AND last_valued_at < ? LIMIT 1
  """, (timestamp - 10 * 60_000,)).fetchone()
  if stale_crypto:
    findings.append(("critical", f"Open BTC demo position {stale_crypto['id']} has stale valuation data"))
  return findings
