#!/usr/bin/env python3
import base64
import binascii
from contextlib import contextmanager
import hmac
import json
import math
import mimetypes
import os
import shutil
import sqlite3
import sys
import threading
import time
from http.cookiejar import CookieJar
from datetime import datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen
from zoneinfo import ZoneInfo

import strategy_engine
import backtest_engine
import ibkr_provider
import options_engine


HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "5173"))
DATA_PROVIDER = os.environ.get("DATA_PROVIDER", "auto").lower()
APP_USERNAME = os.environ.get("APP_USERNAME", "trader")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
DEBUG_ERRORS = os.environ.get("DEBUG_ERRORS", "").lower() in {"1", "true", "yes"}
POLYGON_API_KEY = os.environ.get("POLYGON_API_KEY", "")
POLYGON_BASE = os.environ.get("POLYGON_BASE_URL", "https://api.massive.com")
ALPACA_API_KEY = os.environ.get("ALPACA_API_KEY", "") or os.environ.get("APCA_API_KEY_ID", "")
ALPACA_API_SECRET = os.environ.get("ALPACA_API_SECRET", "") or os.environ.get("APCA_API_SECRET_KEY", "")
ALPACA_BASE = os.environ.get("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets")
ALPACA_FEED = os.environ.get("ALPACA_FEED", "iex")
YAHOO_BASE = os.environ.get("YAHOO_BASE_URL", "https://query2.finance.yahoo.com")
YAHOO_FALLBACK_BASE = os.environ.get("YAHOO_FALLBACK_BASE_URL", "https://query1.finance.yahoo.com")
CNN_FEAR_GREED_PAGE = "https://edition.cnn.com/markets/fear-and-greed"
CNN_FEAR_GREED_API = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
MARKETDATA_TOKEN = os.environ.get("MARKETDATA_TOKEN", "")
MARKETDATA_BASE = os.environ.get("MARKETDATA_BASE_URL", "https://api.marketdata.app")
IBKR_HOST = os.environ.get("IBKR_HOST", "127.0.0.1")
IBKR_PORT = int(os.environ.get("IBKR_PORT", "7496"))
IBKR_CLIENT_ID = int(os.environ.get("IBKR_CLIENT_ID", "17"))
IBKR_REQUIRE_LIVE = os.environ.get("IBKR_REQUIRE_LIVE", "true").lower() in {"1", "true", "yes"}
IBKR_HISTORY_DURATION = os.environ.get("IBKR_HISTORY_DURATION", "2 D")
SYMBOL = "QQQ"
SUPPORTED_SYMBOLS = ("QQQ", "SPY", "BTC-USD")
STRATEGY_VERSION = "5.2.0"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
LEGACY_DB_PATH = os.path.join(APP_DIR, "trader_journal.sqlite3")
DB_PATH = os.environ.get("JOURNAL_DB_PATH", os.path.join(DATA_DIR, "trader_journal.sqlite3"))
STATIC_FILES = {
  "/": "index.html",
  "/index.html": "index.html",
  "/styles.css": "styles.css",
  "/app.js": "app.js",
  "/market-core.js": "market-core.js",
  "/pattern-engine.js": "pattern-engine.js",
  "/settings.json": "settings.json",
}
MINUTE_MS = 60_000
DAILY_CACHE_TTL_MS = 6 * 60 * 60 * 1000
SENTIMENT_CACHE_TTL_SECONDS = 5 * 60
OPTIONS_CACHE_TTL_SECONDS = 30 * 60
OPTIONS_PROVIDER_DAILY_LIMIT = 80
OPTIONS_PROVIDER_REQUEST_CREDITS = 4
FETCH_CACHE = {}
FETCH_CACHE_LOCK = threading.Lock()
MARKET_TIME_ZONE = ZoneInfo("America/New_York")
MARKET_RUNTIME_LOCK = threading.Lock()
def new_market_runtime():
  return {
    "candle": None,
    "history": [],
    "five_minute_history": [],
    "daily_history": [],
    "last_success_at": None,
    "last_history_at": None,
    "error_count": 0,
    "last_error": None,
    "recommendations": {},
    "recommendations_at": None,
    "options_opportunity": options_engine.none_opportunity(),
    "options_opportunity_at": None,
    "backtest": None,
    "backtest_status": "not_started",
    "backtest_error": None,
  }


MARKET_RUNTIMES = {symbol: new_market_runtime() for symbol in SUPPORTED_SYMBOLS}
MARKET_STOP_EVENT = threading.Event()
BACKTEST_JOB_LOCK = threading.Lock()
BACKTEST_JOBS_ACTIVE = set()
IBKR_CLIENT = None
IBKR_CLIENT_LOCK = threading.Lock()


def ensure_data_dir():
  os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
  if DB_PATH == LEGACY_DB_PATH:
    return
  if not os.path.exists(DB_PATH) and os.path.exists(LEGACY_DB_PATH):
    shutil.copy2(LEGACY_DB_PATH, DB_PATH)


@contextmanager
def db():
  ensure_data_dir()
  connection = sqlite3.connect(DB_PATH, timeout=10)
  connection.row_factory = sqlite3.Row
  connection.execute("PRAGMA journal_mode=WAL")
  connection.execute("PRAGMA busy_timeout=10000")
  connection.execute("PRAGMA foreign_keys=ON")
  try:
    yield connection
    connection.commit()
  except Exception:
    connection.rollback()
    raise
  finally:
    connection.close()


def add_column(connection, existing, name, definition):
  if name not in existing:
    connection.execute(f"ALTER TABLE plans ADD COLUMN {name} {definition}")
    existing.add(name)


def init_db():
  with db() as connection:
    connection.execute("""
      CREATE TABLE IF NOT EXISTS plans (
        id TEXT PRIMARY KEY,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        symbol TEXT NOT NULL,
        provider TEXT,
        timeframe INTEGER NOT NULL,
        direction TEXT NOT NULL,
        setup TEXT NOT NULL,
        setup_type TEXT,
        market_phase TEXT,
        status TEXT NOT NULL,
        score INTEGER NOT NULL,
        entry REAL NOT NULL,
        stop REAL NOT NULL,
        target1 REAL NOT NULL,
        target2 REAL NOT NULL,
        risk_reward REAL,
        price_at_plan REAL NOT NULL,
        rsi REAL,
        atr REAL,
        vwap REAL,
        ema20 REAL,
        ema50 REAL,
        ema150 REAL,
        sma20 REAL,
        sma50 REAL,
        sma150 REAL,
        selected_trend TEXT,
        trend_5 TEXT,
        trend_15 TEXT,
        reasons_json TEXT,
        exit_rules_json TEXT,
        outcome_status TEXT NOT NULL DEFAULT 'open',
        hit_target1_at INTEGER,
        hit_target2_at INTEGER,
        hit_stop_at INTEGER,
        max_favorable REAL NOT NULL DEFAULT 0,
        max_adverse REAL NOT NULL DEFAULT 0,
        last_price REAL,
        observations INTEGER NOT NULL DEFAULT 0,
        user_feedback TEXT,
        lifecycle_status TEXT NOT NULL DEFAULT 'waiting',
        entry_hit_at INTEGER,
        expired_at INTEGER,
        time_to_target1_ms INTEGER,
        time_to_stop_ms INTEGER,
        strategy_version TEXT,
        signal_candle_time INTEGER,
        settings_json TEXT,
        data_quality TEXT,
        eligible_for_learning INTEGER NOT NULL DEFAULT 0,
        realized_r REAL,
        closed_at INTEGER,
        last_observed_at INTEGER
      )
    """)
    existing = {row["name"] for row in connection.execute("PRAGMA table_info(plans)").fetchall()}
    for column, definition in {
      "setup_type": "TEXT",
      "market_phase": "TEXT",
      "user_feedback": "TEXT",
      "lifecycle_status": "TEXT NOT NULL DEFAULT 'waiting'",
      "entry_hit_at": "INTEGER",
      "expired_at": "INTEGER",
      "time_to_target1_ms": "INTEGER",
      "time_to_stop_ms": "INTEGER",
      "strategy_version": "TEXT",
      "signal_candle_time": "INTEGER",
      "settings_json": "TEXT",
      "data_quality": "TEXT",
      "eligible_for_learning": "INTEGER NOT NULL DEFAULT 0",
      "realized_r": "REAL",
      "closed_at": "INTEGER",
      "last_observed_at": "INTEGER",
      "calibration_json": "TEXT",
      "feature_snapshot_json": "TEXT",
    }.items():
      add_column(connection, existing, column, definition)

    connection.execute("""
      CREATE TABLE IF NOT EXISTS candles (
        symbol TEXT NOT NULL,
        time INTEGER NOT NULL,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL,
        volume INTEGER NOT NULL DEFAULT 0,
        provider TEXT,
        is_closed INTEGER NOT NULL DEFAULT 1,
        created_at INTEGER NOT NULL,
        PRIMARY KEY (symbol, time)
      )
    """)
    connection.execute("""
      CREATE TABLE IF NOT EXISTS daily_candles (
        symbol TEXT NOT NULL,
        time INTEGER NOT NULL,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL,
        volume INTEGER NOT NULL DEFAULT 0,
        provider TEXT NOT NULL,
        fetched_at INTEGER NOT NULL,
        PRIMARY KEY (symbol, time)
      )
    """)
    connection.execute("""
      CREATE TABLE IF NOT EXISTS plan_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        plan_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        event_at INTEGER NOT NULL,
        price REAL,
        details_json TEXT,
        FOREIGN KEY (plan_id) REFERENCES plans(id) ON DELETE CASCADE
      )
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_plans_created_at ON plans(created_at)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_plans_outcome ON plans(outcome_status)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_plans_learning ON plans(eligible_for_learning, strategy_version)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_candles_symbol_time ON candles(symbol, time)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_daily_candles_symbol_time ON daily_candles(symbol, time)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_events_plan ON plan_events(plan_id, event_at)")
    connection.execute("""
      CREATE TABLE IF NOT EXISTS backtest_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        strategy_version TEXT NOT NULL,
        source_signature TEXT NOT NULL UNIQUE,
        generated_at INTEGER NOT NULL,
        result_json TEXT NOT NULL
      )
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_backtest_version_time ON backtest_runs(strategy_version, generated_at DESC)")
    backtest_columns = {row["name"] for row in connection.execute("PRAGMA table_info(backtest_runs)").fetchall()}
    if "symbol" not in backtest_columns:
      connection.execute("ALTER TABLE backtest_runs ADD COLUMN symbol TEXT NOT NULL DEFAULT 'QQQ'")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_backtest_symbol_version_time ON backtest_runs(symbol, strategy_version, generated_at DESC)")
    connection.execute("""
      CREATE TABLE IF NOT EXISTS learning_snapshots (
        symbol TEXT NOT NULL,
        strategy_version TEXT NOT NULL,
        source_signature TEXT NOT NULL,
        updated_at INTEGER NOT NULL,
        snapshot_json TEXT NOT NULL,
        PRIMARY KEY (symbol, strategy_version)
      )
    """)
    connection.execute("""
      CREATE TABLE IF NOT EXISTS option_ideas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_key TEXT NOT NULL UNIQUE,
        plan_id TEXT,
        symbol TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        timeframe INTEGER NOT NULL,
        direction TEXT NOT NULL,
        side TEXT NOT NULL,
        score INTEGER NOT NULL,
        status TEXT NOT NULL,
        provider TEXT,
        contract_symbol TEXT,
        expiration INTEGER,
        strike REAL,
        dte INTEGER,
        entry_bid REAL,
        entry_ask REAL,
        entry_mid REAL,
        entry_quote_at INTEGER,
        delta REAL,
        delta_bucket TEXT,
        underlying_entry REAL,
        underlying_stop REAL,
        underlying_target1 REAL,
        underlying_target2 REAL,
        underlying_outcome TEXT,
        exit_mid REAL,
        exit_quote_at INTEGER,
        realized_return REAL,
        eligible_for_learning INTEGER NOT NULL DEFAULT 0,
        resolved_at INTEGER,
        payload_json TEXT NOT NULL,
        FOREIGN KEY (plan_id) REFERENCES plans(id) ON DELETE SET NULL
      )
    """)
    connection.execute("""
      CREATE TABLE IF NOT EXISTS option_quote_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        idea_id INTEGER NOT NULL,
        observed_at INTEGER NOT NULL,
        quote_at INTEGER,
        bid REAL,
        ask REAL,
        mid REAL,
        volume INTEGER,
        open_interest INTEGER,
        iv REAL,
        delta REAL,
        gamma REAL,
        theta REAL,
        vega REAL,
        FOREIGN KEY (idea_id) REFERENCES option_ideas(id) ON DELETE CASCADE
      )
    """)
    connection.execute("""
      CREATE TABLE IF NOT EXISTS options_provider_usage (
        usage_day TEXT PRIMARY KEY,
        credits INTEGER NOT NULL DEFAULT 0,
        updated_at INTEGER NOT NULL
      )
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_option_ideas_plan ON option_ideas(plan_id, resolved_at)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_option_ideas_learning ON option_ideas(eligible_for_learning, delta_bucket)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_option_quotes_idea_time ON option_quote_observations(idea_id, observed_at DESC)")
    connection.execute("""
      UPDATE plans
      SET eligible_for_learning = 0
      WHERE strategy_version IS NULL OR strategy_version <> ?
    """, (STRATEGY_VERSION,))


def now_ms():
  return int(time.time() * 1000)


def minute_start(timestamp):
  return int(timestamp // MINUTE_MS) * MINUTE_MS


def finite_number(value):
  try:
    number = float(value)
  except (TypeError, ValueError):
    return None
  return number if math.isfinite(number) else None


def finite_or_none(value):
  number = finite_number(value)
  return number if number is not None else None


def normalized_candle(raw, allow_source_time=False):
  if not isinstance(raw, dict):
    return None
  time_value = finite_number(raw.get("time"))
  open_price = finite_number(raw.get("open"))
  high = finite_number(raw.get("high"))
  low = finite_number(raw.get("low"))
  close = finite_number(raw.get("close"))
  if None in (time_value, open_price, high, low, close):
    return None
  if min(open_price, high, low, close) <= 0:
    return None
  if high < max(open_price, close) or low > min(open_price, close) or high < low:
    return None
  volume = finite_number(raw.get("volume"))
  normalized_volume = max(0, int(volume or 0))
  reference_price = (open_price + close) / 2
  if normalized_volume == 0 and (high - low) / reference_price > 0.02:
    return None
  candle = {
    "time": minute_start(int(time_value)),
    "open": float(open_price),
    "high": float(high),
    "low": float(low),
    "close": float(close),
    "volume": normalized_volume,
  }
  if allow_source_time:
    candle["source_time"] = int(time_value)
  return candle


def merge_candle_series(raw_candles):
  buckets = {}
  for raw in raw_candles or []:
    candle = normalized_candle(raw, allow_source_time=True)
    if not candle:
      continue
    existing = buckets.get(candle["time"])
    if not existing:
      buckets[candle["time"]] = dict(candle)
      continue
    existing["high"] = max(existing["high"], candle["high"])
    existing["low"] = min(existing["low"], candle["low"])
    existing["volume"] = max(existing["volume"], candle["volume"])
    if candle["source_time"] >= existing["source_time"]:
      existing["close"] = candle["close"]
      existing["source_time"] = candle["source_time"]
  output = []
  for candle in sorted(buckets.values(), key=lambda item: item["time"]):
    candle.pop("source_time", None)
    output.append(candle)
  return output


def active_provider(symbol=SYMBOL):
  if str(symbol).upper() in {"SPY", "BTC-USD"}:
    return "yahoo"
  if DATA_PROVIDER == "demo":
    return ""
  if DATA_PROVIDER == "yahoo":
    return "yahoo"
  if DATA_PROVIDER == "ibkr":
    return "ibkr" if ibkr_provider.available() else ""
  if DATA_PROVIDER == "alpaca":
    return "alpaca" if ALPACA_API_KEY and ALPACA_API_SECRET else ""
  if DATA_PROVIDER == "polygon":
    return "polygon" if POLYGON_API_KEY else ""
  if ALPACA_API_KEY and ALPACA_API_SECRET:
    return "alpaca"
  if POLYGON_API_KEY:
    return "polygon"
  return "yahoo"


def ibkr_client():
  global IBKR_CLIENT
  if not ibkr_provider.available():
    raise RuntimeError("IBKR Python API is not installed; run the server from the project .venv")
  with IBKR_CLIENT_LOCK:
    if IBKR_CLIENT is None:
      IBKR_CLIENT = ibkr_provider.IBKRMarketDataClient(
        host=IBKR_HOST,
        port=IBKR_PORT,
        client_id=IBKR_CLIENT_ID,
        require_live=IBKR_REQUIRE_LIVE,
      )
    return IBKR_CLIENT


def validate_symbol(symbol):
  value = str(symbol or SYMBOL).upper()
  if value not in SUPPORTED_SYMBOLS:
    raise ValueError(f"Supported symbols are {', '.join(SUPPORTED_SYMBOLS)}")
  return value


def polygon_get(path, params=None):
  if not POLYGON_API_KEY:
    raise RuntimeError("POLYGON_API_KEY is not set")
  query = dict(params or {})
  query["apiKey"] = POLYGON_API_KEY
  url = f"{POLYGON_BASE}{path}?{urlencode(query)}"
  request = Request(url, headers={"Accept": "application/json", "User-Agent": "qqq-alert-helper/2.0"})
  with urlopen(request, timeout=12) as response:
    return json.loads(response.read().decode("utf-8"))


def alpaca_get(path, params=None):
  if not ALPACA_API_KEY or not ALPACA_API_SECRET:
    raise RuntimeError("ALPACA_API_KEY and ALPACA_API_SECRET are not set")
  query = urlencode(params or {})
  url = f"{ALPACA_BASE}{path}"
  if query:
    url = f"{url}?{query}"
  request = Request(url, headers={
    "Accept": "application/json",
    "User-Agent": "qqq-alert-helper/2.0",
    "APCA-API-KEY-ID": ALPACA_API_KEY,
    "APCA-API-SECRET-KEY": ALPACA_API_SECRET,
  })
  with urlopen(request, timeout=12) as response:
    return json.loads(response.read().decode("utf-8"))


def yahoo_get(path, params=None):
  query = urlencode(params or {})
  url = f"{YAHOO_BASE}{path}"
  if query:
    url = f"{url}?{query}"
  request = Request(url, headers={
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://finance.yahoo.com",
    "Referer": f"https://finance.yahoo.com/quote/{SYMBOL}/chart/",
    "User-Agent": "Mozilla/5.0",
  })
  try:
    with urlopen(request, timeout=12) as response:
      return json.loads(response.read().decode("utf-8"))
  except HTTPError as error:
    if error.code != 429 or YAHOO_FALLBACK_BASE == YAHOO_BASE:
      raise
  fallback_url = f"{YAHOO_FALLBACK_BASE}{path}"
  if query:
    fallback_url = f"{fallback_url}?{query}"
  fallback_request = Request(fallback_url, headers={
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": f"https://finance.yahoo.com/quote/{SYMBOL}/chart/",
    "User-Agent": "Mozilla/5.0",
  })
  with urlopen(fallback_request, timeout=12) as response:
    return json.loads(response.read().decode("utf-8"))


def fear_greed_rating(score):
  if score < 25:
    return "Extreme Fear"
  if score < 45:
    return "Fear"
  if score <= 55:
    return "Neutral"
  if score <= 75:
    return "Greed"
  return "Extreme Greed"


def normalize_fear_greed(payload):
  current = payload.get("fear_and_greed") if isinstance(payload, dict) else None
  if not isinstance(current, dict):
    raise ValueError("CNN Fear & Greed payload is missing the current index")
  score = float(current.get("score"))
  if not math.isfinite(score) or score < 0 or score > 100:
    raise ValueError("CNN Fear & Greed score is invalid")

  def optional_score(key):
    value = current.get(key)
    if value is None:
      return None
    number = float(value)
    return number if math.isfinite(number) and 0 <= number <= 100 else None

  rating = str(current.get("rating") or fear_greed_rating(score)).replace("_", " ").strip().title()
  return {
    "score": round(score, 1),
    "rating": rating,
    "timestamp": str(current.get("timestamp") or ""),
    "previousClose": optional_score("previous_close"),
    "previousWeek": optional_score("previous_1_week"),
    "previousMonth": optional_score("previous_1_month"),
    "previousYear": optional_score("previous_1_year"),
    "source": "CNN",
    "sourceUrl": CNN_FEAR_GREED_PAGE,
  }


def fetch_cnn_fear_greed():
  cookies = CookieJar()
  opener = build_opener(HTTPCookieProcessor(cookies))
  user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
  page_request = Request(CNN_FEAR_GREED_PAGE, headers={
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": user_agent,
  })
  with opener.open(page_request, timeout=12) as response:
    response.read(1)
  api_request = Request(CNN_FEAR_GREED_API, headers={
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://edition.cnn.com",
    "Referer": CNN_FEAR_GREED_PAGE,
    "User-Agent": user_agent,
  })
  with opener.open(api_request, timeout=12) as response:
    payload = json.loads(response.read().decode("utf-8"))
  return normalize_fear_greed(payload)


def cnn_fear_greed():
  key = ("sentiment", "cnn-fear-greed")
  current = time.time()
  with FETCH_CACHE_LOCK:
    cached = FETCH_CACHE.get(key)
    if cached and current - cached["time"] < SENTIMENT_CACHE_TTL_SECONDS:
      return {**cached["value"], "cached": True, "stale": False}
  try:
    value = fetch_cnn_fear_greed()
  except Exception:
    if cached:
      return {**cached["value"], "cached": True, "stale": True}
    raise
  with FETCH_CACHE_LOCK:
    FETCH_CACHE[key] = {"time": current, "value": value}
  return {**value, "cached": False, "stale": False}


def parse_rfc3339_millis(value):
  if isinstance(value, (int, float)):
    return int(value)
  normalized = str(value).replace("Z", "+00:00")
  from datetime import datetime
  return int(datetime.fromisoformat(normalized).timestamp() * 1000)


def normalize_aggregate(item):
  return normalized_candle({
    "time": item.get("t"),
    "open": item.get("o"),
    "high": item.get("h"),
    "low": item.get("l"),
    "close": item.get("c"),
    "volume": item.get("v", 0),
  })


def normalize_alpaca_bar(item):
  if not item:
    return None
  return normalized_candle({
    "time": parse_rfc3339_millis(item.get("t")),
    "open": item.get("o"),
    "high": item.get("h"),
    "low": item.get("l"),
    "close": item.get("c"),
    "volume": item.get("v", 0),
  })


def normalize_yahoo_chart(payload):
  chart = payload.get("chart") or {}
  results = chart.get("result") or []
  if not results:
    return []
  result = results[0]
  timestamps = result.get("timestamp") or []
  quote_sets = ((result.get("indicators") or {}).get("quote") or [])
  if not quote_sets:
    return []

  quote = quote_sets[0]
  opens = quote.get("open") or []
  highs = quote.get("high") or []
  lows = quote.get("low") or []
  closes = quote.get("close") or []
  volumes = quote.get("volume") or []
  raw = []
  for index, timestamp in enumerate(timestamps):
    try:
      open_price = opens[index]
      high = highs[index]
      low = lows[index]
      close = closes[index]
    except IndexError:
      continue
    if None in (open_price, high, low, close):
      continue
    volume = int(volumes[index] or 0) if index < len(volumes) else 0
    source_time = int(timestamp) * 1000
    synthetic_quote = (
      source_time % MINUTE_MS != 0
      and volume == 0
      and float(open_price) == float(high) == float(low) == float(close)
    )
    if synthetic_quote:
      continue
    raw.append({
      "time": source_time,
      "open": open_price,
      "high": high,
      "low": low,
      "close": close,
      "volume": volume,
    })
  return merge_candle_series(raw)


def normalize_snapshot_minute(payload):
  ticker = payload.get("ticker") or {}
  minute = ticker.get("min") or {}
  if not minute:
    return None
  timestamp = minute.get("t")
  if timestamp is None:
    updated = ticker.get("updated")
    timestamp = int(updated / 1_000_000) if updated else now_ms()
  return normalize_aggregate({
    "t": timestamp,
    "o": minute.get("o"),
    "h": minute.get("h"),
    "l": minute.get("l"),
    "c": minute.get("c"),
    "v": minute.get("v", 0),
  })


def fetch_latest_candle(provider, symbol):
  if provider == "ibkr":
    return ibkr_client().latest_candle()
  if provider == "yahoo":
    data = yahoo_get(f"/v8/finance/chart/{symbol}", {
      "range": "1d",
      "interval": "1m",
      "includePrePost": "true",
    })
    candles = normalize_yahoo_chart(data)
    return candles[-1] if candles else None
  if provider == "alpaca":
    data = alpaca_get("/v2/stocks/bars/latest", {"symbols": symbol, "feed": ALPACA_FEED})
    raw_bar = (data.get("bars") or {}).get(symbol)
    return normalize_alpaca_bar(raw_bar)
  data = polygon_get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{symbol}")
  return normalize_snapshot_minute(data)


def latest_candle(provider, symbol):
  ttl = 10 if provider == "yahoo" else 3
  key = ("latest", provider, symbol)
  current = time.time()
  with FETCH_CACHE_LOCK:
    cached = FETCH_CACHE.get(key)
    if cached and current - cached["time"] < ttl:
      return cached["value"]
  value = fetch_latest_candle(provider, symbol)
  with FETCH_CACHE_LOCK:
    FETCH_CACHE[key] = {"time": current, "value": value}
  return value


def market_date():
  return datetime.now(MARKET_TIME_ZONE).date()


def fetch_history_candles(provider, symbol):
  today = market_date()
  start = today - timedelta(days=7)
  if provider == "ibkr":
    candles = ibkr_client().request_history(IBKR_HISTORY_DURATION)
  elif provider == "yahoo":
    data = yahoo_get(f"/v8/finance/chart/{symbol}", {
      "range": "5d",
      "interval": "1m",
      "includePrePost": "true",
    })
    candles = normalize_yahoo_chart(data)
  elif provider == "alpaca":
    data = alpaca_get("/v2/stocks/bars", {
      "symbols": symbol,
      "timeframe": "1Min",
      "start": start.isoformat(),
      "limit": "10000",
      "adjustment": "raw",
      "feed": ALPACA_FEED,
      "sort": "asc",
    })
    candles = [
      candle for candle in (
        normalize_alpaca_bar(item) for item in (data.get("bars") or {}).get(symbol, [])
      ) if candle
    ]
  else:
    data = polygon_get(
      f"/v2/aggs/ticker/{symbol}/range/1/minute/{start.isoformat()}/{today.isoformat()}",
      {"adjusted": "true", "sort": "asc", "limit": "50000"},
    )
    candles = [candle for candle in (normalize_aggregate(item) for item in data.get("results", [])) if candle]
  return merge_candle_series(candles)


def fetch_five_minute_candles(provider, symbol):
  if provider == "yahoo":
    data = yahoo_get(f"/v8/finance/chart/{symbol}", {
      "range": "60d",
      "interval": "5m",
      "includePrePost": "true",
    })
    return merge_candle_series(normalize_yahoo_chart(data))
  history = market_runtime_snapshot(symbol)["history"] or fetch_history_candles(provider, symbol)
  return strategy_engine.resample(history, 5)


def fetch_daily_candles(symbol):
  data = yahoo_get(f"/v8/finance/chart/{symbol}", {
    "range": "2y",
    "interval": "1d",
    "includePrePost": "false",
  })
  candles = normalize_yahoo_chart(data)
  if len(candles) < 160:
    raise ValueError("Daily provider history is incomplete")
  return candles


def record_market_candles(symbol, provider, candles):
  normalized = merge_candle_series(candles)
  if not normalized:
    return 0
  boundary = now_ms() - 2_000
  closed = [candle for candle in normalized if candle["time"] + MINUTE_MS <= boundary]
  forming = [candle for candle in normalized if candle["time"] + MINUTE_MS > boundary]
  with db() as connection:
    if closed:
      save_candles(connection, symbol, provider, closed, is_closed=1)
      evaluate_plans(connection, symbol, closed)
      resolve_option_ideas(connection)
    if forming:
      save_candles(connection, symbol, provider, forming, is_closed=0)
  return len(normalized)


def load_cached_candles(symbol, limit=2500):
  with db() as connection:
    rows = connection.execute("""
      SELECT time, open, high, low, close, volume
      FROM candles
      WHERE symbol = ?
      ORDER BY time DESC
      LIMIT ?
    """, (symbol, int(limit))).fetchall()
  return merge_candle_series(dict(row) for row in reversed(rows))


def save_daily_candles(symbol, provider, candles, fetched_at=None):
  normalized = merge_candle_series(candles)
  if not normalized:
    return 0
  timestamp = int(fetched_at or now_ms())
  with db() as connection:
    for candle in normalized:
      connection.execute("""
        INSERT INTO daily_candles (
          symbol, time, open, high, low, close, volume, provider, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, time) DO UPDATE SET
          open = excluded.open,
          high = excluded.high,
          low = excluded.low,
          close = excluded.close,
          volume = excluded.volume,
          provider = excluded.provider,
          fetched_at = excluded.fetched_at
      """, (
        symbol, candle["time"], candle["open"], candle["high"], candle["low"],
        candle["close"], candle["volume"], provider, timestamp,
      ))
  return len(normalized)


def load_daily_candles(symbol, limit=520):
  with db() as connection:
    rows = connection.execute("""
      SELECT time, open, high, low, close, volume
      FROM daily_candles
      WHERE symbol = ?
      ORDER BY time DESC
      LIMIT ?
    """, (symbol, int(limit))).fetchall()
    fetched_at = connection.execute("""
      SELECT MAX(fetched_at) AS fetched_at
      FROM daily_candles
      WHERE symbol = ?
    """, (symbol,)).fetchone()["fetched_at"]
  return merge_candle_series(dict(row) for row in reversed(rows)), fetched_at


def load_strategy_settings():
  try:
    with open(os.path.join(APP_DIR, "settings.json"), encoding="utf-8") as handle:
      return json.load(handle)
  except (OSError, json.JSONDecodeError):
    return {"activeTradeThreshold": 62, "mode": "normal", "sessionMode": "regular"}


def learning_source_signature(connection, symbol=SYMBOL):
  row = connection.execute("""
    SELECT COUNT(*) AS resolved,
           COALESCE(MAX(closed_at), 0) AS last_closed_at,
           COALESCE(MAX(updated_at), 0) AS last_updated_at
    FROM plans
    WHERE symbol = ? AND eligible_for_learning = 1 AND strategy_version = ? AND realized_r IS NOT NULL
  """, (symbol, STRATEGY_VERSION)).fetchone()
  return f"{int(row['resolved'])}:{int(row['last_closed_at'])}:{int(row['last_updated_at'])}"


def learning_group_rows(connection, symbol, group_name, column):
  rows = connection.execute(f"""
    SELECT {column} AS group_key,
           COUNT(*) AS sample_size,
           SUM(CASE WHEN realized_r > 0 THEN 1 ELSE 0 END) AS winners,
           SUM(CASE WHEN realized_r <= 0 THEN 1 ELSE 0 END) AS stopped,
           SUM(CASE WHEN outcome_status IN ('target1_stop', 'target2') THEN 1 ELSE 0 END) AS target1_hits,
           AVG(realized_r) AS expected_r,
           MAX(closed_at) AS last_closed_at
    FROM plans
    WHERE symbol = ? AND eligible_for_learning = 1 AND strategy_version = ? AND realized_r IS NOT NULL
    GROUP BY {column}
  """, (symbol, STRATEGY_VERSION)).fetchall()
  groups = {}
  for row in rows:
    value = dict(row)
    sample_size = int(value["sample_size"] or 0)
    winners = int(value["winners"] or 0)
    target1_hits = int(value["target1_hits"] or 0)
    # The neutral prior prevents a small run of outcomes from producing a large score change.
    value["win_rate"] = (winners + 10) / (sample_size + 20) if sample_size else 0.5
    value["target1_rate"] = (target1_hits + 10) / (sample_size + 20) if sample_size else 0.5
    value["expected_r"] = float(value["expected_r"] or 0)
    value["group"] = group_name
    groups[str(value["group_key"])] = value
  return groups


def build_learning_snapshot(connection, symbol=SYMBOL):
  group_definitions = (
    ("bySetup", "setup", "COALESCE(setup_type, 'unknown')"),
    ("byTimeframe", "timeframe", "CAST(timeframe AS TEXT)"),
    ("byPhase", "phase", "COALESCE(market_phase, 'unknown')"),
  )
  groups = {key: learning_group_rows(connection, symbol, label, column) for key, label, column in group_definitions}
  total = sum(int(item["sample_size"]) for item in groups["byTimeframe"].values())
  return {
    "symbol": symbol,
    "strategyVersion": STRATEGY_VERSION,
    "resolvedSamples": total,
    "performance": {
      key: {
        group_key: {
          "winners": item["winners"],
          "stopped": item["stopped"],
          "sampleSize": item["sample_size"],
          "expectedR": item["expected_r"],
        }
        for group_key, item in values.items()
      }
      for key, values in groups.items()
    },
    "groups": groups,
  }


def load_learning_snapshot(connection, symbol=SYMBOL):
  signature = learning_source_signature(connection, symbol)
  row = connection.execute("""
    SELECT source_signature, snapshot_json
    FROM learning_snapshots
    WHERE symbol = ? AND strategy_version = ?
  """, (symbol, STRATEGY_VERSION)).fetchone()
  if row and row["source_signature"] == signature:
    try:
      return json.loads(row["snapshot_json"])
    except (TypeError, ValueError):
      pass
  snapshot = build_learning_snapshot(connection, symbol)
  connection.execute("""
    INSERT INTO learning_snapshots (symbol, strategy_version, source_signature, updated_at, snapshot_json)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(symbol, strategy_version) DO UPDATE SET
      source_signature = excluded.source_signature,
      updated_at = excluded.updated_at,
      snapshot_json = excluded.snapshot_json
  """, (symbol, STRATEGY_VERSION, signature, now_ms(), json.dumps(snapshot, separators=(",", ":"))))
  return snapshot


def load_strategy_performance(connection, symbol=SYMBOL):
  return load_learning_snapshot(connection, symbol).get("performance") or {}


def load_latest_backtest(connection, symbol=SYMBOL):
  row = connection.execute("""
    SELECT source_signature, generated_at, result_json
    FROM backtest_runs
    WHERE symbol = ? AND strategy_version = ?
    ORDER BY generated_at DESC
    LIMIT 1
  """, (symbol, STRATEGY_VERSION)).fetchone()
  if not row:
    return None
  try:
    result = json.loads(row["result_json"])
  except (TypeError, ValueError):
    return None
  result["sourceSignature"] = row["source_signature"]
  result["generatedAt"] = row["generated_at"]
  return result


def save_backtest_result(connection, source_signature, result, symbol=SYMBOL):
  generated_at = int(result.get("generatedAt") or now_ms())
  connection.execute("""
    INSERT INTO backtest_runs (strategy_version, source_signature, generated_at, result_json, symbol)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(source_signature) DO UPDATE SET
      strategy_version = excluded.strategy_version,
      generated_at = excluded.generated_at,
      result_json = excluded.result_json,
      symbol = excluded.symbol
  """, (STRATEGY_VERSION, source_signature, generated_at, json.dumps(result, separators=(",", ":")), symbol))
  connection.execute("""
    DELETE FROM backtest_runs
    WHERE id NOT IN (
      SELECT id FROM backtest_runs WHERE symbol = ? AND strategy_version = ? ORDER BY generated_at DESC LIMIT 3
    )
      AND symbol = ?
  """, (symbol, STRATEGY_VERSION, symbol))


def backtest_source_signature(runtime, settings, symbol=SYMBOL):
  series = (runtime.get("history") or [], runtime.get("five_minute_history") or [], runtime.get("daily_history") or [])
  replay_intervals = (15 * MINUTE_MS, 15 * MINUTE_MS, 24 * 60 * MINUTE_MS)
  source = {
    "version": STRATEGY_VERSION,
    "symbol": symbol,
    "series": [
      [(values[-1]["time"] // replay_intervals[index]) * replay_intervals[index] if values else None]
      for index, values in enumerate(series)
    ],
    "settings": {
      "mode": settings.get("mode", "normal"),
      "activeTradeThreshold": settings.get("activeTradeThreshold", 62),
      "sessionMode": settings.get("sessionMode", "regular"),
      "backtestSlippageBps": settings.get("backtestSlippageBps", 0.5),
      "backtestCommissionPerShare": settings.get("backtestCommissionPerShare", 0.0),
    },
  }
  return json.dumps(source, sort_keys=True, separators=(",", ":"))


def attach_signal_calibration(signal, trades):
  if not isinstance(signal, dict):
    return signal
  for key in ("bestLong", "bestShort"):
    candidate = signal.get(key)
    if isinstance(candidate, dict):
      candidate["timeframe"] = signal.get("timeframe")
      candidate["calibration"] = backtest_engine.calibration_for_signal(trades, candidate)
  signal["calibration"] = backtest_engine.calibration_for_signal(trades, signal)
  return signal


def learning_confidence_for_signal(snapshot, signal):
  if not isinstance(signal, dict) or signal.get("direction") not in {"long", "short"}:
    return {
      "status": "Building",
      "sampleSize": 0,
      "scope": "no actionable setup",
      "expectedR": None,
      "target1Rate": None,
      "lastUpdated": None,
    }
  setup_type = signal.get("setupType") or strategy_engine.setup_type(signal.get("setup", ""))
  candidates = (
    ("setup", setup_type, "setup type"),
    ("timeframe", str(signal.get("timeframe") or ""), "timeframe"),
    ("phase", signal.get("marketPhase") or "unknown", "market phase"),
  )
  groups = snapshot.get("groups") or {}
  selected = None
  scope = "no comparable resolved plans"
  for group_name, key, label in candidates:
    item = (groups.get(f"by{group_name.title()}") or {}).get(str(key))
    if item and int(item.get("sample_size") or 0) >= 8:
      selected = item
      scope = label
      break
  if selected is None:
    return {
      "status": "Building",
      "sampleSize": 0,
      "scope": scope,
      "expectedR": None,
      "target1Rate": None,
      "lastUpdated": None,
    }
  sample_size = int(selected["sample_size"])
  return {
    "status": "Established" if sample_size >= 60 else "Developing" if sample_size >= 20 else "Preliminary",
    "sampleSize": sample_size,
    "scope": scope,
    "expectedR": finite_or_none(selected.get("expected_r")),
    "target1Rate": finite_or_none(selected.get("target1_rate")),
    "lastUpdated": selected.get("last_closed_at"),
  }


def attach_signal_learning_confidence(signal, snapshot):
  if not isinstance(signal, dict):
    return signal
  for key in ("bestLong", "bestShort"):
    candidate = signal.get(key)
    if isinstance(candidate, dict):
      candidate["timeframe"] = signal.get("timeframe")
      candidate["modelConfidence"] = learning_confidence_for_signal(snapshot, candidate)
  signal["modelConfidence"] = learning_confidence_for_signal(snapshot, signal)
  return signal


def schedule_historical_replay(symbol=SYMBOL):
  runtime = market_runtime_snapshot(symbol)
  if len(runtime["five_minute_history"]) < 160 and len(runtime["daily_history"]) < 180:
    return False
  settings = load_strategy_settings()
  signature = backtest_source_signature(runtime, settings, symbol)
  current = runtime.get("backtest") or {}
  if current.get("sourceSignature") == signature:
    return False
  with BACKTEST_JOB_LOCK:
    if symbol in BACKTEST_JOBS_ACTIVE:
      return False
    BACKTEST_JOBS_ACTIVE.add(symbol)
  with MARKET_RUNTIME_LOCK:
    MARKET_RUNTIMES[symbol]["backtest_status"] = "running"
    MARKET_RUNTIMES[symbol]["backtest_error"] = None

  def run():
    try:
      result = backtest_engine.run_replay(
        one_minute=runtime["history"],
        five_minute=runtime["five_minute_history"],
        daily=runtime["daily_history"],
        settings=settings,
        symbol=symbol,
      )
      result["generatedAt"] = now_ms()
      result["sourceSignature"] = signature
      result["strategyVersion"] = STRATEGY_VERSION
      with db() as connection:
        save_backtest_result(connection, signature, result, symbol)
      with MARKET_RUNTIME_LOCK:
        MARKET_RUNTIMES[symbol]["backtest"] = result
        MARKET_RUNTIMES[symbol]["backtest_status"] = "ready"
        MARKET_RUNTIMES[symbol]["backtest_error"] = None
    except Exception as error:
      with MARKET_RUNTIME_LOCK:
        MARKET_RUNTIMES[symbol]["backtest_status"] = "error"
        MARKET_RUNTIMES[symbol]["backtest_error"] = str(error)[:240]
    finally:
      with BACKTEST_JOB_LOCK:
        BACKTEST_JOBS_ACTIVE.discard(symbol)

  threading.Thread(target=run, name=f"historical-replay-{symbol}", daemon=True).start()
  return True


def persist_generated_signal(connection, provider, timeframe, signal, settings, symbol=SYMBOL):
  if signal.get("direction") not in {"long", "short"} or signal.get("watchOnly"):
    return None
  threshold = int(settings.get("activeTradeThreshold", 62)) + {"scalp": -6, "normal": 0, "strict": 8}.get(settings.get("mode", "normal"), 0)
  if int(signal.get("score") or 0) < threshold:
    return None
  actionable_at = int(signal["actionableAt"])
  freshness = 5 * 24 * 60 * MINUTE_MS if timeframe == strategy_engine.DAILY_TIMEFRAME else 3 * MINUTE_MS
  future_tolerance = 5 * 24 * 60 * MINUTE_MS if timeframe == strategy_engine.DAILY_TIMEFRAME else MINUTE_MS
  if now_ms() - actionable_at > freshness or actionable_at > now_ms() + future_tolerance:
    return None
  latest = signal.get("latestIndicator") or {}
  entry = float(signal["entry"])
  plan_id = "|".join((
    symbol,
    str(timeframe),
    signal["direction"],
    signal["setup"],
    str(signal["signalCandleTime"]),
    str(round(entry * 20)),
  ))
  duplicate = connection.execute("""
    SELECT id, entry
    FROM plans
    WHERE symbol = ? AND timeframe = ? AND direction = ?
      AND COALESCE(setup_type, 'unknown') = ? AND created_at >= ?
      AND outcome_status IN ('open', 'target1')
      AND COALESCE(lifecycle_status, 'waiting') IN ('waiting', 'entered')
      AND strategy_version = ?
    ORDER BY created_at DESC LIMIT 1
  """, (
    symbol, timeframe, signal["direction"], signal.get("setupType", "unknown"),
    actionable_at - (7 * 24 * 60 * MINUTE_MS if timeframe == strategy_engine.DAILY_TIMEFRAME else 15 * MINUTE_MS), STRATEGY_VERSION,
  )).fetchone()
  if duplicate and abs(float(duplicate["entry"]) - entry) / max(1, entry) < 0.0015:
    return duplicate["id"]
  row = {
    "id": plan_id,
    "created_at": actionable_at,
    "updated_at": actionable_at,
    "symbol": symbol,
    "provider": provider,
    "timeframe": timeframe,
    "direction": signal["direction"],
    "setup": signal["setup"],
    "setup_type": signal.get("setupType", "unknown"),
    "market_phase": signal.get("marketPhase", "unknown"),
    "status": "alert",
    "score": int(signal["score"]),
    "entry": entry,
    "stop": float(signal["stop"]),
    "target1": float(signal["target"]),
    "target2": float(signal["target2"]),
    "risk_reward": finite_or_none(signal.get("riskReward")),
    "price_at_plan": float(latest["close"]),
    "rsi": finite_or_none(latest.get("rsi")),
    "atr": finite_or_none(latest.get("atr")),
    "vwap": finite_or_none(latest.get("vwap")),
    "ema20": finite_or_none(latest.get("ema20")),
    "ema50": finite_or_none(latest.get("ema50")),
    "ema150": finite_or_none(latest.get("ema150")),
    "sma20": finite_or_none(latest.get("sma20")),
    "sma50": finite_or_none(latest.get("sma50")),
    "sma150": finite_or_none(latest.get("sma150")),
    "selected_trend": (signal.get("selectedTrend") or {}).get("label"),
    "trend_5": (signal.get("trend5") or {}).get("label"),
    "trend_15": (signal.get("trend15") or {}).get("label"),
    "reasons_json": json.dumps(signal.get("reasons") or []),
    "exit_rules_json": json.dumps(signal.get("exitRules") or []),
    "strategy_version": STRATEGY_VERSION,
    "signal_candle_time": int(signal["signalCandleTime"]),
    "settings_json": json.dumps(settings),
    "data_quality": signal.get("dataQuality", "unknown"),
    "eligible_for_learning": 1,
    "calibration_json": json.dumps(signal.get("calibration") or {}),
    "feature_snapshot_json": json.dumps({
      "rawScore": signal.get("rawScore"),
      "regime": signal.get("regime"),
      "selectedTrend": signal.get("selectedTrend"),
      "trend5": signal.get("trend5"),
      "trend15": signal.get("trend15"),
      "marketConfirmation": signal.get("marketConfirmation"),
      "dataQuality": signal.get("dataQuality"),
    }),
  }
  cursor = connection.execute("""
    INSERT OR IGNORE INTO plans (
      id, created_at, updated_at, symbol, provider, timeframe, direction, setup, setup_type, market_phase, status, score,
      entry, stop, target1, target2, risk_reward, price_at_plan, rsi, atr, vwap,
      ema20, ema50, ema150, sma20, sma50, sma150, selected_trend, trend_5, trend_15,
      reasons_json, exit_rules_json, last_price, strategy_version, signal_candle_time, settings_json, data_quality, eligible_for_learning,
      calibration_json, feature_snapshot_json
    ) VALUES (
      :id, :created_at, :updated_at, :symbol, :provider, :timeframe, :direction, :setup, :setup_type, :market_phase, :status, :score,
      :entry, :stop, :target1, :target2, :risk_reward, :price_at_plan, :rsi, :atr, :vwap,
      :ema20, :ema50, :ema150, :sma20, :sma50, :sma150, :selected_trend, :trend_5, :trend_15,
      :reasons_json, :exit_rules_json, :price_at_plan, :strategy_version, :signal_candle_time, :settings_json, :data_quality, :eligible_for_learning,
      :calibration_json, :feature_snapshot_json
    )
  """, row)
  if cursor.rowcount:
    insert_event(connection, plan_id, "created", actionable_at, latest["close"], {"score": row["score"], "source": "server"})
  return plan_id


def realized_volatility(candles, periods=20):
  closes = [
    finite_number(candle.get("close"))
    for candle in (candles or [])[-(periods + 1):]
  ]
  closes = [value for value in closes if value and value > 0]
  if len(closes) < periods:
    return None
  returns = [math.log(closes[index] / closes[index - 1]) for index in range(1, len(closes))]
  if len(returns) < 2:
    return None
  mean = sum(returns) / len(returns)
  variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
  return math.sqrt(variance) * math.sqrt(252)


def options_usage_day(timestamp=None):
  moment = datetime.fromtimestamp((timestamp or now_ms()) / 1000, tz=MARKET_TIME_ZONE)
  return moment.date().isoformat()


def options_provider_usage(connection, timestamp=None):
  row = connection.execute(
    "SELECT credits FROM options_provider_usage WHERE usage_day = ?",
    (options_usage_day(timestamp),),
  ).fetchone()
  return int(row["credits"] or 0) if row else 0


def reserve_options_provider_credits(credits, timestamp=None):
  credits = max(1, int(credits))
  usage_day = options_usage_day(timestamp)
  with db() as connection:
    used = options_provider_usage(connection, timestamp)
    if used + credits > OPTIONS_PROVIDER_DAILY_LIMIT:
      return False, used
    total = used + credits
    connection.execute("""
      INSERT INTO options_provider_usage (usage_day, credits, updated_at)
      VALUES (?, ?, ?)
      ON CONFLICT(usage_day) DO UPDATE SET
        credits = excluded.credits,
        updated_at = excluded.updated_at
    """, (usage_day, total, now_ms()))
  return True, total


def marketdata_get(path, params=None):
  if not MARKETDATA_TOKEN:
    raise RuntimeError("MARKETDATA_TOKEN is not set")
  query = urlencode(params or {})
  url = f"{MARKETDATA_BASE}{path}"
  if query:
    url = f"{url}?{query}"
  request = Request(url, headers={
    "Accept": "application/json",
    "Authorization": f"Bearer {MARKETDATA_TOKEN}",
    "User-Agent": "qqq-alert-helper/3.0",
  })
  with urlopen(request, timeout=12) as response:
    if response.status not in {200, 203}:
      raise RuntimeError(f"Market Data returned HTTP {response.status}")
    payload = json.loads(response.read().decode("utf-8"))
  if not isinstance(payload, dict) or payload.get("s") not in {"ok", "success"}:
    raise ValueError(str((payload or {}).get("errmsg") or "Market Data returned no option chain"))
  return payload


def fetch_options_chain(guidance, timestamp=None):
  cache_key = ("options-chain", guidance["signalKey"])
  current = time.time()
  with FETCH_CACHE_LOCK:
    cached = FETCH_CACHE.get(cache_key)
    if cached and current - cached["time"] < OPTIONS_CACHE_TTL_SECONDS:
      return cached["value"], True, None

  reserved, usage = reserve_options_provider_credits(OPTIONS_PROVIDER_REQUEST_CREDITS, timestamp)
  if not reserved:
    return None, False, f"Daily options quote allowance reached ({usage}/{OPTIONS_PROVIDER_DAILY_LIMIT})."
  payload = marketdata_get(f"/v1/options/chain/{guidance['optionSymbol']}/", {
    "dte": guidance["dte"]["target"],
    "side": guidance["side"],
    "delta": f"{options_engine.MIN_DELTA:.2f}-{options_engine.MAX_DELTA:.2f}",
    "strikeLimit": OPTIONS_PROVIDER_REQUEST_CREDITS,
    "minBid": "0.01",
    "minOpenInterest": options_engine.MIN_OPEN_INTEREST,
    "minVolume": options_engine.MIN_VOLUME,
    "nonstandard": "false",
  })
  contracts = options_engine.normalize_marketdata_chain(payload)
  with FETCH_CACHE_LOCK:
    FETCH_CACHE[cache_key] = {"time": current, "value": contracts}
  return contracts, False, None


def option_learning_profile(connection, symbol=SYMBOL):
  rows = connection.execute("""
    SELECT delta_bucket,
           COUNT(*) AS sample_size,
           AVG(realized_return) AS average_return,
           AVG(CASE WHEN realized_return > 0 THEN 1.0 ELSE 0.0 END) AS win_rate
    FROM option_ideas
    WHERE symbol = ?
      AND eligible_for_learning = 1
      AND realized_return IS NOT NULL
      AND delta_bucket IS NOT NULL
    GROUP BY delta_bucket
  """, (symbol,)).fetchall()
  return {
    row["delta_bucket"]: {
      "sampleSize": int(row["sample_size"] or 0),
      "averageReturn": finite_or_none(row["average_return"]),
      "winRate": finite_or_none(row["win_rate"]),
    }
    for row in rows
  }


def persist_options_opportunity(connection, opportunity):
  if not isinstance(opportunity, dict) or opportunity.get("status") == "none":
    return None
  contract = opportunity.get("contract") or {}
  underlying = opportunity.get("underlying") or {}
  provider = opportunity.get("provider") or {}
  timestamp = int(opportunity.get("generatedAt") or now_ms())
  row = {
    "signal_key": opportunity["signalKey"],
    "plan_id": opportunity.get("planId"),
    "symbol": opportunity.get("symbol", SYMBOL),
    "created_at": timestamp,
    "updated_at": timestamp,
    "timeframe": int(opportunity["timeframe"]),
    "direction": opportunity["direction"],
    "side": opportunity["side"],
    "score": int(opportunity.get("score") or 0),
    "status": opportunity["status"],
    "provider": provider.get("name"),
    "contract_symbol": contract.get("optionSymbol"),
    "expiration": options_engine.timestamp_ms(contract.get("expiration")),
    "strike": finite_or_none(contract.get("strike")),
    "dte": int(contract["dte"]) if finite_number(contract.get("dte")) is not None else None,
    "entry_bid": finite_or_none(contract.get("bid")),
    "entry_ask": finite_or_none(contract.get("ask")),
    "entry_mid": finite_or_none(contract.get("mid")),
    "entry_quote_at": options_engine.timestamp_ms(contract.get("quoteAt") or contract.get("updated")),
    "delta": finite_or_none(contract.get("delta")),
    "delta_bucket": contract.get("deltaBucket"),
    "underlying_entry": finite_or_none(underlying.get("entry")),
    "underlying_stop": finite_or_none(underlying.get("stop")),
    "underlying_target1": finite_or_none(underlying.get("target1")),
    "underlying_target2": finite_or_none(underlying.get("target2")),
    "payload_json": json.dumps(opportunity, separators=(",", ":")),
  }
  connection.execute("""
    INSERT INTO option_ideas (
      signal_key, plan_id, symbol, created_at, updated_at, timeframe, direction, side, score, status,
      provider, contract_symbol, expiration, strike, dte, entry_bid, entry_ask, entry_mid,
      entry_quote_at, delta, delta_bucket, underlying_entry, underlying_stop,
      underlying_target1, underlying_target2, payload_json
    ) VALUES (
      :signal_key, :plan_id, :symbol, :created_at, :updated_at, :timeframe, :direction, :side, :score, :status,
      :provider, :contract_symbol, :expiration, :strike, :dte, :entry_bid, :entry_ask, :entry_mid,
      :entry_quote_at, :delta, :delta_bucket, :underlying_entry, :underlying_stop,
      :underlying_target1, :underlying_target2, :payload_json
    )
    ON CONFLICT(signal_key) DO UPDATE SET
      plan_id = COALESCE(option_ideas.plan_id, excluded.plan_id),
      updated_at = excluded.updated_at,
      score = excluded.score,
      status = excluded.status,
      provider = excluded.provider,
      contract_symbol = COALESCE(excluded.contract_symbol, option_ideas.contract_symbol),
      expiration = COALESCE(excluded.expiration, option_ideas.expiration),
      strike = COALESCE(excluded.strike, option_ideas.strike),
      dte = COALESCE(excluded.dte, option_ideas.dte),
      entry_bid = COALESCE(option_ideas.entry_bid, excluded.entry_bid),
      entry_ask = COALESCE(option_ideas.entry_ask, excluded.entry_ask),
      entry_mid = COALESCE(option_ideas.entry_mid, excluded.entry_mid),
      entry_quote_at = COALESCE(option_ideas.entry_quote_at, excluded.entry_quote_at),
      delta = COALESCE(excluded.delta, option_ideas.delta),
      delta_bucket = COALESCE(excluded.delta_bucket, option_ideas.delta_bucket),
      payload_json = excluded.payload_json
  """, row)
  idea = connection.execute(
    "SELECT id FROM option_ideas WHERE signal_key = ?",
    (row["signal_key"],),
  ).fetchone()
  if not idea or not contract.get("optionSymbol"):
    return idea["id"] if idea else None
  quote_at = row["entry_quote_at"]
  duplicate = connection.execute("""
    SELECT id
    FROM option_quote_observations
    WHERE idea_id = ? AND quote_at = ?
    LIMIT 1
  """, (idea["id"], quote_at)).fetchone()
  if not duplicate:
    connection.execute("""
      INSERT INTO option_quote_observations (
        idea_id, observed_at, quote_at, bid, ask, mid, volume, open_interest,
        iv, delta, gamma, theta, vega
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
      idea["id"], timestamp, quote_at,
      finite_or_none(contract.get("bid")), finite_or_none(contract.get("ask")),
      finite_or_none(contract.get("mid")), int(finite_number(contract.get("volume")) or 0),
      int(finite_number(contract.get("openInterest")) or 0), finite_or_none(contract.get("iv")),
      finite_or_none(contract.get("delta")), finite_or_none(contract.get("gamma")),
      finite_or_none(contract.get("theta")), finite_or_none(contract.get("vega")),
    ))
  return idea["id"]


def resolve_option_ideas(connection):
  rows = connection.execute("""
    SELECT ideas.id, ideas.created_at, ideas.entry_mid, ideas.entry_quote_at,
           plans.outcome_status, plans.closed_at
    FROM option_ideas AS ideas
    JOIN plans ON plans.id = ideas.plan_id
    WHERE ideas.resolved_at IS NULL
      AND ideas.status = 'contract'
      AND plans.lifecycle_status IN ('closed', 'expired')
  """).fetchall()
  resolved = 0
  for row in rows:
    closed_at = int(row["closed_at"] or now_ms())
    quote = connection.execute("""
      SELECT quote_at, mid
      FROM option_quote_observations
      WHERE idea_id = ?
        AND mid IS NOT NULL
        AND COALESCE(quote_at, observed_at) > COALESCE(?, 0)
      ORDER BY ABS(COALESCE(quote_at, observed_at) - ?) ASC
      LIMIT 1
    """, (row["id"], row["entry_quote_at"], closed_at)).fetchone()
    exit_mid = finite_number(quote["mid"]) if quote else None
    exit_quote_at = int(quote["quote_at"]) if quote and quote["quote_at"] is not None else None
    entry_mid = finite_number(row["entry_mid"])
    fresh_exit = (
      exit_mid is not None
      and exit_quote_at is not None
      and abs(exit_quote_at - closed_at) <= options_engine.MAX_QUOTE_AGE_MS
    )
    entry_quote_at = int(row["entry_quote_at"]) if row["entry_quote_at"] is not None else None
    fresh_entry = (
      entry_mid is not None
      and entry_mid > 0
      and entry_quote_at is not None
      and abs(entry_quote_at - int(row["created_at"])) <= options_engine.MAX_QUOTE_AGE_MS
    )
    eligible = bool(fresh_entry and fresh_exit)
    realized_return = (exit_mid - entry_mid) / entry_mid if eligible else None
    connection.execute("""
      UPDATE option_ideas
      SET underlying_outcome = ?,
          exit_mid = ?,
          exit_quote_at = ?,
          realized_return = ?,
          eligible_for_learning = ?,
          resolved_at = ?,
          updated_at = ?
      WHERE id = ?
    """, (
      row["outcome_status"], exit_mid if fresh_exit else None, exit_quote_at if fresh_exit else None,
      realized_return, int(eligible), closed_at, now_ms(), row["id"],
    ))
    resolved += 1
  return resolved


def options_market_open(timestamp):
  return bool(strategy_engine.market_session(timestamp, "QQQ").get("regular"))


def option_proxy_price(symbol, runtime):
  contract_symbol = options_engine.option_symbol(symbol)
  if not contract_symbol:
    return None
  if contract_symbol == symbol:
    return finite_number((runtime.get("candle") or {}).get("close"))
  try:
    candle = latest_candle("yahoo", contract_symbol)
    return finite_number((candle or {}).get("close"))
  except Exception:
    return None


def build_options_opportunity(recommendations, plan_ids, runtime, timestamp=None, symbol=SYMBOL):
  timestamp = int(timestamp or now_ms())
  profile = options_engine.option_profile(symbol)
  if not profile:
    return options_engine.none_opportunity(
      "Options guidance is not configured for this asset.",
      symbol=symbol,
    )
  regular_session = options_market_open(timestamp)
  selected, empty = options_engine.select_underlying_signal(recommendations, regular_session, symbol)
  if not selected:
    return empty
  timeframe, signal = selected
  latest_price = finite_number((runtime.get("candle") or {}).get("close"))
  contract_price = option_proxy_price(symbol, runtime)
  if contract_price is None:
    return options_engine.none_opportunity(
      f"{profile['optionSymbol']} proxy price is unavailable; wait for a fresh listed-ETF quote.",
      symbol=symbol,
    )
  guidance = options_engine.build_guidance(
    timeframe,
    signal,
    plan_id=(plan_ids or {}).get(timeframe),
    generated_at=timestamp,
    underlying_price=latest_price,
    option_price=contract_price,
    symbol=symbol,
  )
  if not MARKETDATA_TOKEN:
    return guidance
  guidance["provider"].update({
    "configured": True,
    "detail": f"Exact {profile['optionSymbol']} contract selection runs during the US regular session.",
  })
  if not regular_session:
    return guidance

  try:
    contracts, cached, quota_detail = fetch_options_chain(guidance, timestamp)
    if quota_detail:
      guidance["provider"]["detail"] = quota_detail
      return guidance
    with db() as connection:
      learning = option_learning_profile(connection, symbol)
    ranked = options_engine.rank_contracts(
      contracts,
      guidance,
      timestamp,
      realized_vol=realized_volatility(runtime.get("daily_history")),
      learning=learning,
    )
    if not ranked:
      guidance["provider"]["detail"] = "No quoted contract passed the spread, liquidity, DTE, delta, and freshness gates."
      return guidance
    detail = "Cached delayed options quote" if cached else "15-minute delayed options quote"
    return options_engine.attach_contract(guidance, ranked[0], detail)
  except Exception as error:
    guidance["provider"]["detail"] = f"Exact contract data is temporarily unavailable: {str(error)[:160]}"
    return guidance


def candles_for_confirmation(runtime, timeframe):
  if timeframe == strategy_engine.DAILY_TIMEFRAME:
    return merge_candle_series(runtime.get("daily_history") or [])
  if timeframe == 1:
    return merge_candle_series([
      *(runtime.get("history") or []),
      *([runtime["candle"]] if runtime.get("candle") else []),
    ])
  source = runtime.get("five_minute_history") or runtime.get("history") or []
  return strategy_engine.resample(source, timeframe)


def return_over_bars(candles, lookback):
  values = [
    finite_number(candle.get("close"))
    for candle in (candles or [])
    if finite_number(candle.get("close")) and finite_number(candle.get("close")) > 0
  ]
  if len(values) <= lookback:
    return None
  return values[-1] / values[-1 - lookback] - 1


def signal_for_timeframe(recommendations, timeframe):
  return (recommendations or {}).get(timeframe) or (recommendations or {}).get(str(timeframe)) or {}


def qqq_spy_confirmation(timeframe, direction, qqq_runtime, spy_runtime, spy_recommendations):
  reference_timeframes = (5, 15, strategy_engine.DAILY_TIMEFRAME)
  reference_signals = {
    value: signal_for_timeframe(spy_recommendations, value)
    for value in reference_timeframes
  }
  reference_tones = {
    value: str((signal.get("selectedTrend") or {}).get("tone") or "neutral")
    for value, signal in reference_signals.items()
  }
  lookbacks = {1: 10, 5: 6, 15: 4, strategy_engine.DAILY_TIMEFRAME: 5}
  lookback = lookbacks.get(timeframe, 6)
  qqq_return = return_over_bars(candles_for_confirmation(qqq_runtime, timeframe), lookback)
  spy_return = return_over_bars(candles_for_confirmation(spy_runtime, timeframe), lookback)
  relative_pct = (qqq_return - spy_return) * 100 if qqq_return is not None and spy_return is not None else None
  threshold = {1: 0.05, 5: 0.08, 15: 0.10, strategy_engine.DAILY_TIMEFRAME: 0.35}.get(timeframe, 0.10)
  expected_tone = "positive" if direction == "long" else "negative"
  aligned = sum(tone == expected_tone for tone in reference_tones.values())
  opposed = sum(tone in {"positive", "negative"} and tone != expected_tone for tone in reference_tones.values())
  adjustment = 0
  reasons = []

  if direction in {"long", "short"}:
    selected_tone = reference_tones.get(timeframe, "neutral")
    if selected_tone == expected_tone:
      adjustment += 4
      reasons.append(f"SPY {timeframe if timeframe != strategy_engine.DAILY_TIMEFRAME else '1D'} trend confirms the trade direction")
    elif selected_tone in {"positive", "negative"}:
      adjustment -= 7
      reasons.append(f"SPY {timeframe if timeframe != strategy_engine.DAILY_TIMEFRAME else '1D'} trend conflicts with the trade direction")
    if aligned >= 2:
      adjustment += 3
      reasons.append("SPY is aligned across multiple timeframes")
    elif opposed >= 2:
      adjustment -= 5
      reasons.append("SPY has broad multi-timeframe opposition")
    if relative_pct is not None:
      leading = relative_pct >= threshold
      lagging = relative_pct <= -threshold
      if (direction == "long" and leading) or (direction == "short" and lagging):
        adjustment += 3
        reasons.append(f"QQQ relative strength supports the {direction} thesis")
      elif (direction == "long" and lagging) or (direction == "short" and leading):
        adjustment -= 3
        reasons.append(f"QQQ relative strength weakens the {direction} thesis")
  adjustment = max(-12, min(10, adjustment))

  if relative_pct is None:
    relative_label = "Building"
    relative_tone = "neutral"
  elif relative_pct >= threshold:
    relative_label = "Leading"
    relative_tone = "positive"
  elif relative_pct <= -threshold:
    relative_label = "Lagging"
    relative_tone = "negative"
  else:
    relative_label = "Neutral"
    relative_tone = "neutral"
  if adjustment >= 5:
    label, tone = "Confirmed", "positive"
  elif adjustment <= -5:
    label, tone = "Conflicting", "negative"
  else:
    label, tone = "Mixed", "neutral"
  scope = "Broad market"
  if aligned == 0 or opposed:
    scope = "Technology-led / divergent"
  return {
    "referenceSymbol": "SPY",
    "label": label,
    "tone": tone,
    "scoreAdjustment": adjustment,
    "detail": "; ".join(reasons) if reasons else "Waiting for enough SPY context to confirm QQQ.",
    "scope": scope,
    "relativeStrength": {
      "label": relative_label,
      "tone": relative_tone,
      "pct": round(relative_pct, 3) if relative_pct is not None else None,
      "lookbackBars": lookback,
    },
    "spyTrends": {
      str(value if value != strategy_engine.DAILY_TIMEFRAME else "1D"): {
        "label": (reference_signals[value].get("selectedTrend") or {}).get("label", "Building"),
        "tone": reference_tones[value],
      }
      for value in reference_timeframes
    },
  }


def apply_qqq_spy_confirmation(recommendations, qqq_runtime, spy_runtime, spy_recommendations, settings):
  threshold = int(settings.get("activeTradeThreshold", 62)) + {
    "scalp": -6, "normal": 0, "strict": 8,
  }.get(settings.get("mode", "normal"), 0)
  for timeframe, signal in (recommendations or {}).items():
    timeframe = int(timeframe)
    targets = [signal, signal.get("bestLong"), signal.get("bestShort")]
    seen = set()
    for candidate in targets:
      if not isinstance(candidate, dict) or id(candidate) in seen:
        continue
      seen.add(id(candidate))
      context = qqq_spy_confirmation(
        timeframe,
        str(candidate.get("direction") or "neutral"),
        qqq_runtime,
        spy_runtime,
        spy_recommendations,
      )
      candidate["marketConfirmation"] = context
      if candidate.get("direction") not in {"long", "short"}:
        continue
      adjustment = int(context["scoreAdjustment"])
      if adjustment:
        candidate["score"] = max(0, min(95, int(candidate.get("score") or 0) + adjustment))
        if candidate.get("rawScore") is not None:
          candidate["rawScore"] = int(candidate["rawScore"]) + adjustment
        candidate.setdefault("reasons", []).extend(context["detail"].split("; "))
      if candidate is signal and candidate["score"] < threshold:
        candidate["watchOnly"] = True
        candidate.setdefault("reasons", []).append("QQQ/SPY confirmation reduced the setup below the active threshold")
    best_long = signal.get("bestLong")
    best_short = signal.get("bestShort")
    signal["biasScore"] = (
      int(best_long.get("score") or 0) - int(best_short.get("score") or 0)
      if best_long and best_short
      else round(int(best_long.get("score") or 0) * 0.5) if best_long
      else -round(int(best_short.get("score") or 0) * 0.5) if best_short
      else 0
    )
  return recommendations


def refresh_server_recommendations(provider, symbol=SYMBOL):
  runtime = market_runtime_snapshot(symbol)
  candles = merge_candle_series([*runtime["history"], *([runtime["candle"]] if runtime["candle"] else [])])
  if not candles:
    return {}
  settings = load_strategy_settings()
  plan_ids = {}
  generated_at = now_ms()
  with db() as connection:
    learning_snapshot = load_learning_snapshot(connection, symbol)
    performance = learning_snapshot.get("performance") or {}
    recommendations = strategy_engine.analyze_all(
      candles,
      settings,
      performance,
      generated_at,
      five_minute_candles=runtime["five_minute_history"],
      symbol=symbol,
    )
    daily = runtime["daily_history"]
    if daily:
      recommendations[strategy_engine.DAILY_TIMEFRAME] = strategy_engine.analyze_daily(
        daily,
        settings,
        performance,
        generated_at,
        intraday_context=recommendations.get(5),
        symbol=symbol,
      )
    if symbol == "QQQ":
      spy_runtime = market_runtime_snapshot("SPY")
      apply_qqq_spy_confirmation(
        recommendations,
        runtime,
        spy_runtime,
        spy_runtime.get("recommendations") or {},
        settings,
      )
    replay = runtime.get("backtest") or {}
    replay_trades = replay.get("trades") or []
    for timeframe, signal in recommendations.items():
      attach_signal_calibration(signal, replay_trades)
      attach_signal_learning_confidence(signal, learning_snapshot)
      plan_ids[int(timeframe)] = persist_generated_signal(
        connection, provider, int(timeframe), signal, settings, symbol
      )
  options_opportunity = build_options_opportunity(
    recommendations, plan_ids, runtime, generated_at, symbol
  )
  with db() as connection:
    persist_options_opportunity(connection, options_opportunity)
  with MARKET_RUNTIME_LOCK:
    MARKET_RUNTIMES[symbol]["recommendations"] = recommendations
    MARKET_RUNTIMES[symbol]["recommendations_at"] = generated_at
    MARKET_RUNTIMES[symbol]["options_opportunity"] = options_opportunity
    MARKET_RUNTIMES[symbol]["options_opportunity_at"] = generated_at
  return recommendations


def market_runtime_snapshot(symbol=SYMBOL):
  symbol = validate_symbol(symbol)
  with MARKET_RUNTIME_LOCK:
    runtime = MARKET_RUNTIMES[symbol]
    return {
      **runtime,
      "history": list(runtime["history"]),
      "five_minute_history": list(runtime["five_minute_history"]),
      "daily_history": list(runtime["daily_history"]),
      "candle": dict(runtime["candle"]) if runtime["candle"] else None,
    }


def market_data_loop(symbol):
  provider = active_provider(symbol)
  if not provider:
    return
  base_interval = 15 if provider == "yahoo" else 5
  next_history_at = 0
  next_five_minute_at = 0
  next_daily_at = 0
  cached = load_cached_candles(symbol)
  cached_daily, daily_fetched_at = load_daily_candles(symbol)
  prior_candle = cached[-1] if cached else None
  if cached:
    with MARKET_RUNTIME_LOCK:
      MARKET_RUNTIMES[symbol]["history"] = cached
      MARKET_RUNTIMES[symbol]["candle"] = prior_candle
  if cached_daily:
    with MARKET_RUNTIME_LOCK:
      MARKET_RUNTIMES[symbol]["daily_history"] = cached_daily
  if cached:
    refresh_server_recommendations(provider, symbol)
  while not MARKET_STOP_EVENT.is_set():
    try:
      current_time = time.time()
      if current_time >= next_history_at:
        history = fetch_history_candles(provider, symbol)
        history = merge_candle_series([*cached, *history])[-2500:]
        record_market_candles(symbol, provider, history)
        with MARKET_RUNTIME_LOCK:
          MARKET_RUNTIMES[symbol]["history"] = history[-2500:]
          MARKET_RUNTIMES[symbol]["last_history_at"] = now_ms()
        next_history_at = current_time + 5 * 60

      if current_time >= next_five_minute_at:
        five_minute = fetch_five_minute_candles(provider, symbol)
        if len(five_minute) < 160:
          raise ValueError("Five-minute provider history is incomplete")
        with MARKET_RUNTIME_LOCK:
          MARKET_RUNTIMES[symbol]["five_minute_history"] = five_minute[-20_000:]
        next_five_minute_at = current_time + 15 * 60

      daily_is_stale = len(cached_daily) < 400 or not daily_fetched_at or now_ms() - int(daily_fetched_at) >= DAILY_CACHE_TTL_MS
      if current_time >= next_daily_at and daily_is_stale:
        daily = fetch_daily_candles(symbol)
        save_daily_candles(symbol, "yahoo", daily)
        daily_fetched_at = now_ms()
        with MARKET_RUNTIME_LOCK:
          MARKET_RUNTIMES[symbol]["daily_history"] = daily[-520:]
        next_daily_at = current_time + 60 * 60
      elif current_time >= next_daily_at:
        next_daily_at = current_time + 60 * 60

      candle = latest_candle(provider, symbol)
      if candle:
        if prior_candle and candle["time"] > prior_candle["time"]:
          record_market_candles(symbol, provider, [prior_candle])
        record_market_candles(symbol, provider, [candle])
        prior_candle = candle
      with MARKET_RUNTIME_LOCK:
        MARKET_RUNTIMES[symbol]["candle"] = candle
        MARKET_RUNTIMES[symbol]["last_success_at"] = now_ms()
        MARKET_RUNTIMES[symbol]["error_count"] = 0
        MARKET_RUNTIMES[symbol]["last_error"] = None
      refresh_server_recommendations(provider, symbol)
      schedule_historical_replay(symbol)
      delay = base_interval
    except Exception as error:
      with MARKET_RUNTIME_LOCK:
        MARKET_RUNTIMES[symbol]["error_count"] += 1
        MARKET_RUNTIMES[symbol]["last_error"] = str(error)[:240]
        error_count = MARKET_RUNTIMES[symbol]["error_count"]
      delay = min(120, base_interval * (2 ** min(error_count, 4)))
    MARKET_STOP_EVENT.wait(delay)


def start_market_data_workers():
  MARKET_STOP_EVENT.clear()
  workers = []
  for symbol in SUPPORTED_SYMBOLS:
    worker = threading.Thread(target=market_data_loop, args=(symbol,), name=f"market-data-{symbol}", daemon=True)
    worker.start()
    workers.append(worker)
  return workers


def save_candles(connection, symbol, provider, candles, is_closed=1):
  saved = 0
  for candle in merge_candle_series(candles):
    connection.execute("""
      INSERT INTO candles (symbol, time, open, high, low, close, volume, provider, is_closed, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(symbol, time) DO UPDATE SET
        open = excluded.open,
        high = excluded.high,
        low = excluded.low,
        close = excluded.close,
        volume = MAX(candles.volume, excluded.volume),
        provider = excluded.provider,
        is_closed = excluded.is_closed
    """, (
      symbol,
      int(candle["time"]),
      candle["open"],
      candle["high"],
      candle["low"],
      candle["close"],
      int(candle.get("volume") or 0),
      provider,
      int(is_closed),
      now_ms(),
    ))
    saved += 1
  return saved


def insert_event(connection, plan_id, event_type, event_at, price=None, details=None):
  connection.execute("""
    INSERT INTO plan_events (plan_id, event_type, event_at, price, details_json)
    VALUES (?, ?, ?, ?, ?)
  """, (plan_id, event_type, int(event_at), price, json.dumps(details or {})))


def realized_r_for(status, row):
  entry = float(row["entry"])
  stop = float(row["stop"])
  target1 = float(row["target1"])
  target2 = float(row["target2"])
  risk = abs(entry - stop)
  if risk <= 0:
    return None
  if status == "stopped":
    return -1.0
  if status == "target1_stop":
    return (abs(target1 - entry) / risk * 0.5) - 0.5
  if status == "target2":
    return abs(target2 - entry) / risk
  return None


def hit_map(row, candle):
  direction = row["direction"]
  entry = float(row["entry"])
  stop = float(row["stop"])
  target1 = float(row["target1"])
  target2 = float(row["target2"])
  if direction == "long":
    return {
      "entry": candle["high"] >= entry,
      "stop": candle["low"] <= stop,
      "target1": candle["high"] >= target1,
      "target2": candle["high"] >= target2,
      "favorable": max(0, candle["high"] - entry),
      "adverse": max(0, entry - candle["low"]),
    }
  return {
    "entry": candle["low"] <= entry,
    "stop": candle["high"] >= stop,
    "target1": candle["low"] <= target1,
    "target2": candle["low"] <= target2,
    "favorable": max(0, entry - candle["low"]),
    "adverse": max(0, candle["high"] - entry),
  }


def close_lifecycle(status):
  if status in {"target2", "stopped", "target1_stop", "ambiguous"}:
    return "closed"
  if status == "expired":
    return "expired"
  return "entered" if status == "target1" else "waiting"


def update_plan_row(connection, row, candle, updates):
  status = updates.get("outcome_status", row["outcome_status"])
  lifecycle = updates.get("lifecycle_status", row["lifecycle_status"] or "waiting")
  realized_r = realized_r_for(status, row)
  closed_at = candle["time"] if lifecycle in {"closed", "expired"} else row["closed_at"]
  params = {
    "updated_at": candle["time"],
    "outcome_status": status,
    "lifecycle_status": lifecycle,
    "entry_hit_at": updates.get("entry_hit_at", row["entry_hit_at"]),
    "expired_at": updates.get("expired_at", row["expired_at"]),
    "hit_target1_at": updates.get("hit_target1_at", row["hit_target1_at"]),
    "hit_target2_at": updates.get("hit_target2_at", row["hit_target2_at"]),
    "hit_stop_at": updates.get("hit_stop_at", row["hit_stop_at"]),
    "time_to_target1_ms": updates.get("time_to_target1_ms", row["time_to_target1_ms"]),
    "time_to_stop_ms": updates.get("time_to_stop_ms", row["time_to_stop_ms"]),
    "max_favorable": updates.get("max_favorable", row["max_favorable"]),
    "max_adverse": updates.get("max_adverse", row["max_adverse"]),
    "last_price": candle["close"],
    "realized_r": realized_r,
    "closed_at": closed_at,
    "last_observed_at": candle["time"],
    "id": row["id"],
  }
  connection.execute("""
    UPDATE plans
    SET updated_at = :updated_at,
        outcome_status = :outcome_status,
        lifecycle_status = :lifecycle_status,
        entry_hit_at = :entry_hit_at,
        expired_at = :expired_at,
        hit_target1_at = :hit_target1_at,
        hit_target2_at = :hit_target2_at,
        hit_stop_at = :hit_stop_at,
        time_to_target1_ms = :time_to_target1_ms,
        time_to_stop_ms = :time_to_stop_ms,
        max_favorable = :max_favorable,
        max_adverse = :max_adverse,
        last_price = :last_price,
        realized_r = :realized_r,
        closed_at = :closed_at,
        last_observed_at = :last_observed_at,
        observations = observations + 1
    WHERE id = :id
  """, params)


def evaluate_plans(connection, symbol, candles):
  normalized = merge_candle_series(candles)
  if not normalized:
    return 0
  rows = connection.execute("""
    SELECT *
    FROM plans
    WHERE symbol = ?
      AND outcome_status IN ('open', 'target1')
      AND COALESCE(lifecycle_status, 'waiting') IN ('waiting', 'entered')
    ORDER BY created_at ASC
  """, (symbol,)).fetchall()
  updates = 0
  for row in rows:
    for candle in normalized:
      candle_time = int(candle["time"])
      if row["last_observed_at"] is not None:
        if candle_time <= int(row["last_observed_at"]):
          continue
      elif candle_time < int(row["created_at"]):
        continue
      hits = hit_map(row, candle)
      lifecycle = row["lifecycle_status"] or "waiting"
      status = row["outcome_status"]
      changed = {}
      event_type = None
      max_age = 14 * 24 * 60 * 60 * 1000 if int(row["timeframe"]) == strategy_engine.DAILY_TIMEFRAME else 4 * 60 * 60 * 1000

      if lifecycle == "waiting":
        if not hits["entry"] and hits["stop"]:
          changed = {"outcome_status": "expired", "lifecycle_status": "expired", "expired_at": candle["time"]}
          event_type = "invalidated_before_entry"
        elif candle["time"] - int(row["created_at"]) > max_age:
          changed = {"outcome_status": "expired", "lifecycle_status": "expired", "expired_at": candle["time"]}
          event_type = "expired"
        elif hits["entry"]:
          if hits["stop"]:
            changed = {
              "outcome_status": "ambiguous",
              "lifecycle_status": "closed",
              "entry_hit_at": row["entry_hit_at"] or candle["time"],
              "hit_stop_at": row["hit_stop_at"] or candle["time"],
              "hit_target1_at": row["hit_target1_at"] or (candle["time"] if hits["target1"] else None),
              "hit_target2_at": row["hit_target2_at"] or (candle["time"] if hits["target2"] else None),
              "time_to_stop_ms": candle["time"] - int(row["created_at"]),
              "time_to_target1_ms": candle["time"] - int(row["created_at"]) if hits["target1"] else row["time_to_target1_ms"],
            }
            event_type = "ambiguous_entry_bar"
          else:
            # The entry bar establishes the position only. Crediting a target
            # from the same OHLC bar would assume an intrabar price sequence.
            changed = {"lifecycle_status": "entered", "entry_hit_at": row["entry_hit_at"] or candle["time"]}
            event_type = "entry"
        else:
          changed = {}

      elif lifecycle == "entered":
        entry_at = int(row["entry_hit_at"] or row["created_at"])
        favorable = max(float(row["max_favorable"] or 0), hits["favorable"])
        adverse = max(float(row["max_adverse"] or 0), hits["adverse"])
        if status == "target1":
          if hits["target2"] and hits["stop"]:
            changed = {
              "outcome_status": "ambiguous",
              "lifecycle_status": "closed",
              "hit_target2_at": row["hit_target2_at"] or candle["time"],
              "hit_stop_at": row["hit_stop_at"] or candle["time"],
              "time_to_stop_ms": row["time_to_stop_ms"] or candle["time"] - entry_at,
              "max_favorable": favorable,
              "max_adverse": adverse,
            }
            event_type = "ambiguous_after_target1"
          elif hits["target2"]:
            changed = {
              "outcome_status": "target2",
              "lifecycle_status": "closed",
              "hit_target2_at": row["hit_target2_at"] or candle["time"],
              "max_favorable": favorable,
              "max_adverse": adverse,
            }
            event_type = "target2"
          elif hits["stop"]:
            changed = {
              "outcome_status": "target1_stop",
              "lifecycle_status": "closed",
              "hit_stop_at": row["hit_stop_at"] or candle["time"],
              "time_to_stop_ms": row["time_to_stop_ms"] or candle["time"] - entry_at,
              "max_favorable": favorable,
              "max_adverse": adverse,
            }
            event_type = "target1_stop"
          else:
            changed = {"max_favorable": favorable, "max_adverse": adverse}
        elif hits["stop"] and (hits["target1"] or hits["target2"]):
          changed = {
            "outcome_status": "ambiguous",
            "lifecycle_status": "closed",
            "hit_stop_at": row["hit_stop_at"] or candle["time"],
            "hit_target1_at": row["hit_target1_at"] or candle["time"],
            "hit_target2_at": row["hit_target2_at"] or (candle["time"] if hits["target2"] else None),
            "time_to_stop_ms": row["time_to_stop_ms"] or candle["time"] - entry_at,
            "time_to_target1_ms": row["time_to_target1_ms"] or candle["time"] - entry_at,
            "max_favorable": favorable,
            "max_adverse": adverse,
          }
          event_type = "ambiguous"
        elif hits["target2"]:
          changed = {
            "outcome_status": "target2",
            "lifecycle_status": "closed",
            "hit_target1_at": row["hit_target1_at"] or candle["time"],
            "hit_target2_at": row["hit_target2_at"] or candle["time"],
            "time_to_target1_ms": row["time_to_target1_ms"] or candle["time"] - entry_at,
            "max_favorable": favorable,
            "max_adverse": adverse,
          }
          event_type = "target2"
        elif hits["target1"]:
          changed = {
            "outcome_status": "target1",
            "lifecycle_status": "entered",
            "hit_target1_at": row["hit_target1_at"] or candle["time"],
            "time_to_target1_ms": row["time_to_target1_ms"] or candle["time"] - entry_at,
            "max_favorable": favorable,
            "max_adverse": adverse,
          }
          event_type = "target1"
        elif hits["stop"]:
          changed = {
            "outcome_status": "stopped",
            "lifecycle_status": "closed",
            "hit_stop_at": row["hit_stop_at"] or candle["time"],
            "time_to_stop_ms": row["time_to_stop_ms"] or candle["time"] - entry_at,
            "max_favorable": favorable,
            "max_adverse": adverse,
          }
          event_type = "stopped"
        else:
          changed = {"max_favorable": favorable, "max_adverse": adverse}

      if changed:
        update_plan_row(connection, row, candle, changed)
        if event_type:
          insert_event(connection, row["id"], event_type, candle["time"], candle["close"], changed)
        row = connection.execute("SELECT * FROM plans WHERE id = ?", (row["id"],)).fetchone()
        updates += 1
        if row["lifecycle_status"] in {"closed", "expired"}:
          break
      else:
        update_plan_row(connection, row, candle, {})
        row = connection.execute("SELECT * FROM plans WHERE id = ?", (row["id"],)).fetchone()
        updates += 1
  return updates


def validate_plan_payload(payload):
  plan = payload.get("plan")
  if not isinstance(plan, dict):
    raise ValueError("missing plan")
  symbol = validate_symbol(payload.get("symbol"))
  direction = str(plan.get("direction") or "")
  if direction not in {"long", "short"}:
    raise ValueError("invalid direction")
  timeframe = int(payload.get("timeframe") or 1)
  if timeframe not in {1, 5, 15, strategy_engine.DAILY_TIMEFRAME}:
    raise ValueError("invalid timeframe")
  prices = {}
  for key in ("entry", "stop", "target", "target2"):
    number = finite_number(plan.get(key))
    if number is None:
      raise ValueError(f"invalid {key}")
    prices[key] = number
  if direction == "long" and not (prices["stop"] < prices["entry"] < prices["target"] <= prices["target2"]):
    raise ValueError("invalid long price order")
  if direction == "short" and not (prices["stop"] > prices["entry"] > prices["target"] >= prices["target2"]):
    raise ValueError("invalid short price order")
  return plan, symbol, timeframe, prices


def learning_filter():
  return "symbol = ? AND eligible_for_learning = 1 AND strategy_version = ?"


class Handler(SimpleHTTPRequestHandler):
  server_version = "QQQAlertHelper/3.0"

  def log_message(self, fmt, *args):
    print(json.dumps({
      "time": datetime.now().astimezone().isoformat(),
      "client": self.client_address[0],
      "method": self.command,
      "path": self.path,
      "message": fmt % args,
    }), flush=True)

  def version_string(self):
    return self.server_version

  def end_headers(self):
    self.send_header("Cache-Control", "no-store")
    self.send_header("X-Content-Type-Options", "nosniff")
    self.send_header("Referrer-Policy", "same-origin")
    self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    self.send_header("Content-Security-Policy", "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'")
    super().end_headers()

  def require_auth(self):
    if not APP_PASSWORD:
      return True
    authorization = self.headers.get("Authorization", "")
    try:
      scheme, encoded = authorization.split(" ", 1)
      username, password = base64.b64decode(encoded).decode("utf-8").split(":", 1)
      valid = scheme.lower() == "basic"
      valid = valid and hmac.compare_digest(username, APP_USERNAME)
      valid = valid and hmac.compare_digest(password, APP_PASSWORD)
    except (ValueError, UnicodeDecodeError, binascii.Error):
      valid = False
    if valid:
      return True
    self.send_response(401)
    self.send_header("WWW-Authenticate", 'Basic realm="QQQ Trader Helper", charset="UTF-8"')
    self.send_header("Content-Length", "0")
    self.end_headers()
    return False

  def valid_write_origin(self):
    origin = self.headers.get("Origin")
    if not origin:
      return True
    parsed = urlparse(origin)
    return parsed.netloc == self.headers.get("Host") and parsed.scheme in {"http", "https"}

  def send_json(self, status, payload):
    body = json.dumps(payload).encode("utf-8")
    self.send_response(status)
    self.send_header("Content-Type", "application/json")
    self.send_header("Content-Length", str(len(body)))
    self.end_headers()
    self.wfile.write(body)

  def read_json_body(self):
    try:
      length = int(self.headers.get("Content-Length", "0"))
    except ValueError as exc:
      raise ValueError("invalid content length") from exc
    if length > 1_000_000:
      raise ValueError("request body too large")
    if length <= 0:
      return {}
    try:
      return json.loads(self.rfile.read(length).decode("utf-8"))
    except json.JSONDecodeError as exc:
      raise ValueError("invalid json") from exc

  def send_sse(self, event, payload):
    self.wfile.write(f"event: {event}\n".encode("utf-8"))
    self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode("utf-8"))
    self.wfile.flush()

  def api_error(self, error):
    if isinstance(error, HTTPError):
      message = error.read().decode("utf-8", errors="replace")
      return error.code, {"error": "provider_http_error", "detail": message}
    if isinstance(error, URLError):
      return 502, {"error": "provider_network_error", "detail": str(error.reason)}
    if isinstance(error, ValueError):
      return 400, {"error": "bad_request", "detail": str(error)}
    payload = {"error": "server_error"}
    if DEBUG_ERRORS:
      payload["detail"] = str(error)
    return 500, payload

  def serve_static(self, parsed):
    filename = STATIC_FILES.get(parsed.path)
    if not filename:
      self.send_json(404, {"error": "not_found"})
      return
    path = os.path.join(APP_DIR, filename)
    try:
      with open(path, "rb") as handle:
        body = handle.read()
    except OSError:
      self.send_json(404, {"error": "not_found"})
      return
    content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    if filename.endswith(".js"):
      content_type = "text/javascript"
    self.send_response(200)
    self.send_header("Content-Type", content_type)
    self.send_header("Content-Length", str(len(body)))
    self.end_headers()
    self.wfile.write(body)

  def do_HEAD(self):
    parsed = urlparse(self.path)
    if parsed.path in {"/health", "/ready"}:
      self.send_response(200)
      self.send_header("Content-Type", "application/json")
      self.send_header("Content-Length", "0")
      self.end_headers()
      return
    if parsed.path not in {"/health", "/ready"} and not self.require_auth():
      return
    filename = STATIC_FILES.get(parsed.path)
    if not filename:
      self.send_response(404)
      self.send_header("Content-Type", "application/json")
      self.send_header("Content-Length", "0")
      self.end_headers()
      return
    path = os.path.join(APP_DIR, filename)
    if not os.path.exists(path):
      self.send_response(404)
      self.send_header("Content-Type", "application/json")
      self.send_header("Content-Length", "0")
      self.end_headers()
      return
    content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    if filename.endswith(".js"):
      content_type = "text/javascript"
    self.send_response(200)
    self.send_header("Content-Type", content_type)
    self.send_header("Content-Length", str(os.path.getsize(path)))
    self.end_headers()

  def do_GET(self):
    parsed = urlparse(self.path)
    if parsed.path == "/health":
      self.send_json(200, {"status": "ok"})
      return
    if parsed.path == "/ready":
      runtimes = {symbol: market_runtime_snapshot(symbol) for symbol in SUPPORTED_SYMBOLS}
      ready = all(active_provider(symbol) and (runtime["last_success_at"] or runtime["history"]) for symbol, runtime in runtimes.items())
      degraded = any(runtime["error_count"] for runtime in runtimes.values())
      status = "degraded" if ready and degraded else "ready" if ready else "starting"
      self.send_json(200 if ready else 503, {"status": status, "symbols": list(SUPPORTED_SYMBOLS)})
      return
    if not self.require_auth():
      return
    if parsed.path == "/api/config":
      params = parse_qs(parsed.query)
      symbol = validate_symbol((params.get("symbol") or [SYMBOL])[0])
      provider = active_provider(symbol)
      runtime = market_runtime_snapshot(symbol)
      ibkr_status = IBKR_CLIENT.status() if provider == "ibkr" and IBKR_CLIENT is not None else None
      self.send_json(200, {
        "symbol": symbol,
        "symbols": list(SUPPORTED_SYMBOLS),
        "marketType": "crypto" if strategy_engine.is_continuous_market(symbol) else "equity",
        "continuousMarket": strategy_engine.is_continuous_market(symbol),
        "provider": provider or "unavailable",
        "feed": ALPACA_FEED if provider == "alpaca" else ("chart" if provider == "yahoo" else ("tws" if provider == "ibkr" else "snapshot")),
        "realTimeEnabled": bool(provider),
        "pollIntervalMs": 15000 if provider == "yahoo" else 5000,
        "serverFeed": True,
        "lastSuccessAt": runtime["last_success_at"],
        "providerErrors": runtime["error_count"],
        "providerMessage": runtime["last_error"] if provider == "ibkr" else None,
        "ibkrMarketDataType": ibkr_status["marketDataType"] if ibkr_status else None,
        "recommendationsAt": runtime["recommendations_at"],
        "analysisEngine": "python-server",
        "backtestStatus": runtime["backtest_status"],
        "optionsProvider": {
          "name": "Market Data",
          "configured": bool(MARKETDATA_TOKEN),
          "mode": "delayed" if MARKETDATA_TOKEN else "guidance",
        },
      })
      return
    if parsed.path == "/api/history":
      self.handle_history(parsed)
      return
    if parsed.path == "/api/five-minute":
      self.handle_five_minute(parsed)
      return
    if parsed.path == "/api/daily":
      self.handle_daily(parsed)
      return
    if parsed.path == "/api/latest":
      self.handle_latest(parsed)
      return
    if parsed.path == "/api/recommendations":
      params = parse_qs(parsed.query)
      symbol = validate_symbol((params.get("symbol") or [SYMBOL])[0])
      runtime = market_runtime_snapshot(symbol)
      self.send_json(200, {
        "generatedAt": runtime["recommendations_at"],
        "recommendations": runtime["recommendations"],
        "optionsOpportunity": runtime["options_opportunity"],
        "analysisEngine": "python-server",
        "backtestStatus": runtime["backtest_status"],
      })
      return
    if parsed.path == "/api/options-opportunity":
      params = parse_qs(parsed.query)
      symbol = validate_symbol((params.get("symbol") or [SYMBOL])[0])
      runtime = market_runtime_snapshot(symbol)
      self.send_json(200, runtime["options_opportunity"])
      return
    if parsed.path == "/api/backtest":
      params = parse_qs(parsed.query)
      symbol = validate_symbol((params.get("symbol") or [SYMBOL])[0])
      runtime = market_runtime_snapshot(symbol)
      result = runtime.get("backtest")
      if not result:
        self.send_json(202, {
          "status": runtime.get("backtest_status", "not_started"),
          "detail": runtime.get("backtest_error") or "Historical replay is building",
        })
      else:
        self.send_json(200, {"status": runtime.get("backtest_status", "ready"), **result})
      return
    if parsed.path == "/api/sentiment/fear-greed":
      try:
        self.send_json(200, cnn_fear_greed())
      except Exception as error:
        status, payload = self.api_error(error)
        self.send_json(status, payload)
      return
    if parsed.path == "/api/stream":
      self.handle_stream(parsed)
      return
    if parsed.path == "/api/journal/stats":
      self.handle_journal_stats(parsed)
      return
    if parsed.path == "/api/journal/replay":
      self.handle_journal_replay(parsed)
      return
    self.serve_static(parsed)

  def do_POST(self):
    parsed = urlparse(self.path)
    if not self.require_auth():
      return
    if not self.valid_write_origin():
      self.send_json(403, {"error": "invalid_origin"})
      return
    if parsed.path == "/api/journal/plan":
      self.handle_journal_plan()
      return
    if parsed.path == "/api/journal/feedback":
      self.handle_journal_feedback()
      return
    self.send_json(404, {"error": "not_found"})

  def handle_journal_plan(self):
    try:
      payload = self.read_json_body()
      plan, symbol, timeframe, prices = validate_plan_payload(payload)
      indicators = payload.get("indicators") or {}
      trends = payload.get("trends") or {}
      timestamp = int(payload.get("timestamp") or now_ms())
      signal_candle_time = int(payload.get("signalCandleTime") or 0)
      expected_actionable_at = signal_candle_time + timeframe * MINUTE_MS
      if signal_candle_time <= 0 or abs(timestamp - expected_actionable_at) > 5_000:
        raise ValueError("invalid signal timestamp")
      if timestamp > now_ms() + 2 * MINUTE_MS or now_ms() - timestamp > 30 * MINUTE_MS:
        raise ValueError("stale signal timestamp")
      price_at_plan = finite_number(payload.get("price"))
      if price_at_plan is None:
        raise ValueError("invalid price")
      if any(abs(value - price_at_plan) / price_at_plan > 0.05 for value in prices.values()):
        raise ValueError("plan prices are too far from market price")

      row = {
        "id": str(plan["id"])[:240],
        "created_at": timestamp,
        "updated_at": timestamp,
        "symbol": symbol,
        "provider": str(payload.get("provider") or active_provider(symbol) or "unavailable")[:40],
        "timeframe": timeframe,
        "direction": str(plan["direction"]),
        "setup": str(plan.get("setup") or "unknown")[:160],
        "setup_type": str(plan.get("setupType") or "unknown")[:40],
        "market_phase": str(payload.get("marketPhase") or "unknown")[:40],
        "status": "watch" if plan.get("watchOnly") else "alert",
        "score": max(0, min(100, int(plan.get("score") or 0))),
        "entry": prices["entry"],
        "stop": prices["stop"],
        "target1": prices["target"],
        "target2": prices["target2"],
        "risk_reward": finite_or_none(plan.get("riskReward")),
        "price_at_plan": price_at_plan,
        "rsi": finite_or_none(indicators.get("rsi")),
        "atr": finite_or_none(indicators.get("atr")),
        "vwap": finite_or_none(indicators.get("vwap")),
        "ema20": finite_or_none(indicators.get("ema20")),
        "ema50": finite_or_none(indicators.get("ema50")),
        "ema150": finite_or_none(indicators.get("ema150")),
        "sma20": finite_or_none(indicators.get("sma20")),
        "sma50": finite_or_none(indicators.get("sma50")),
        "sma150": finite_or_none(indicators.get("sma150")),
        "selected_trend": trends.get("selected"),
        "trend_5": trends.get("five"),
        "trend_15": trends.get("fifteen"),
        "reasons_json": json.dumps(plan.get("reasons") or []),
        "exit_rules_json": json.dumps(plan.get("exitRules") or []),
        "strategy_version": str(payload.get("strategyVersion") or STRATEGY_VERSION),
        "signal_candle_time": signal_candle_time,
        "settings_json": json.dumps(payload.get("settings") or {}),
        "data_quality": str(payload.get("dataQuality") or "unknown")[:120],
        "eligible_for_learning": 1 if str(payload.get("strategyVersion") or STRATEGY_VERSION) == STRATEGY_VERSION else 0,
      }

      with db() as connection:
        duplicate = connection.execute("""
          SELECT id, entry
          FROM plans
          WHERE symbol = ?
            AND timeframe = ?
            AND direction = ?
            AND COALESCE(setup_type, 'unknown') = ?
            AND created_at >= ?
            AND outcome_status IN ('open', 'target1')
            AND COALESCE(lifecycle_status, 'waiting') IN ('waiting', 'entered')
            AND strategy_version = ?
          ORDER BY created_at DESC
          LIMIT 1
        """, (
          row["symbol"],
          row["timeframe"],
          row["direction"],
          row["setup_type"],
          timestamp - 15 * 60 * 1000,
          STRATEGY_VERSION,
        )).fetchone()
        if duplicate:
          previous_entry = float(duplicate["entry"])
          entry_changed = abs(previous_entry - row["entry"]) / max(1, row["entry"])
          if entry_changed < 0.0015:
            connection.execute("""
              UPDATE plans
              SET updated_at = ?, score = MAX(score, ?), last_price = ?
              WHERE id = ?
            """, (timestamp, row["score"], row["price_at_plan"], duplicate["id"]))
            self.send_json(200, {"saved": False, "duplicateOf": duplicate["id"], "id": duplicate["id"]})
            return

        connection.execute("""
          INSERT INTO plans (
            id, created_at, updated_at, symbol, provider, timeframe, direction, setup, setup_type, market_phase, status, score,
            entry, stop, target1, target2, risk_reward, price_at_plan, rsi, atr, vwap,
            ema20, ema50, ema150, sma20, sma50, sma150, selected_trend, trend_5, trend_15,
            reasons_json, exit_rules_json, last_price, strategy_version, signal_candle_time, settings_json, data_quality, eligible_for_learning
          ) VALUES (
            :id, :created_at, :updated_at, :symbol, :provider, :timeframe, :direction, :setup, :setup_type, :market_phase, :status, :score,
            :entry, :stop, :target1, :target2, :risk_reward, :price_at_plan, :rsi, :atr, :vwap,
            :ema20, :ema50, :ema150, :sma20, :sma50, :sma150, :selected_trend, :trend_5, :trend_15,
            :reasons_json, :exit_rules_json, :price_at_plan, :strategy_version, :signal_candle_time, :settings_json, :data_quality, :eligible_for_learning
          )
          ON CONFLICT(id) DO UPDATE SET
            updated_at = excluded.updated_at,
            score = excluded.score,
            reasons_json = excluded.reasons_json,
            exit_rules_json = excluded.exit_rules_json,
            last_price = excluded.last_price
        """, row)
        insert_event(connection, row["id"], "created", timestamp, price_at_plan, {"score": row["score"]})

      self.send_json(200, {"saved": True, "id": row["id"]})
    except Exception as error:
      status, payload = self.api_error(error)
      self.send_json(status, payload)

  def handle_journal_feedback(self):
    try:
      payload = self.read_json_body()
      plan_id = str(payload["id"])
      feedback = str(payload["feedback"])
      if feedback not in {"took", "skipped", "bad"}:
        self.send_json(400, {"error": "invalid_feedback"})
        return
      with db() as connection:
        cursor = connection.execute("""
          UPDATE plans
          SET user_feedback = ?, updated_at = ?
          WHERE id = ?
        """, (feedback, now_ms(), plan_id))
      if cursor.rowcount <= 0:
        self.send_json(404, {"error": "plan_not_found"})
        return
      self.send_json(200, {"updated": cursor.rowcount, "id": plan_id, "feedback": feedback})
    except Exception as error:
      status, payload = self.api_error(error)
      self.send_json(status, payload)

  def handle_latest(self, parsed):
    params = parse_qs(parsed.query)
    try:
      symbol = validate_symbol((params.get("symbol") or [SYMBOL])[0])
      provider = active_provider(symbol)
      if not provider:
        self.send_json(503, {"error": "missing_provider", "detail": "No live provider is configured"})
        return
      runtime = market_runtime_snapshot(symbol)
      candle = runtime["candle"] or latest_candle(provider, symbol)
      if not candle:
        self.send_json(404, {"error": "no_candle", "detail": "Provider did not return a latest candle"})
        return
      record_market_candles(symbol, provider, [candle])
      self.send_json(200, {
        "symbol": symbol,
        "candle": candle,
        "lastSuccessAt": runtime["last_success_at"],
        "providerErrors": runtime["error_count"],
      })
    except Exception as error:
      status, payload = self.api_error(error)
      self.send_json(status, payload)

  def handle_journal_stats(self, parsed):
    try:
      params = parse_qs(parsed.query)
      symbol = validate_symbol((params.get("symbol") or [SYMBOL])[0])
      filter_sql = learning_filter()
      with db() as connection:
        summary = connection.execute(f"""
          SELECT
            COUNT(*) AS total,
            COALESCE(SUM(CASE WHEN status = 'alert' THEN 1 ELSE 0 END), 0) AS alerts,
            COALESCE(SUM(CASE WHEN status = 'watch' THEN 1 ELSE 0 END), 0) AS watches,
            COALESCE(SUM(CASE WHEN outcome_status IN ('target1', 'target1_stop') THEN 1 ELSE 0 END), 0) AS target1,
            COALESCE(SUM(CASE WHEN outcome_status = 'target2' THEN 1 ELSE 0 END), 0) AS target2,
            COALESCE(SUM(CASE WHEN outcome_status = 'stopped' THEN 1 ELSE 0 END), 0) AS stopped,
            COALESCE(SUM(CASE WHEN outcome_status = 'ambiguous' THEN 1 ELSE 0 END), 0) AS ambiguous,
            COALESCE(SUM(CASE WHEN outcome_status = 'expired' THEN 1 ELSE 0 END), 0) AS expired,
            COALESCE(SUM(CASE WHEN lifecycle_status = 'waiting' AND outcome_status = 'open' THEN 1 ELSE 0 END), 0) AS waiting,
            COALESCE(SUM(CASE WHEN lifecycle_status = 'entered' AND outcome_status IN ('open', 'target1') THEN 1 ELSE 0 END), 0) AS entered,
            COALESCE(SUM(CASE WHEN outcome_status IN ('open', 'target1') AND lifecycle_status IN ('waiting', 'entered') THEN 1 ELSE 0 END), 0) AS open,
            COALESCE(SUM(CASE WHEN realized_r IS NOT NULL THEN 1 ELSE 0 END), 0) AS resolved,
            COALESCE(SUM(CASE WHEN realized_r > 0 THEN 1 ELSE 0 END), 0) AS profitable,
            COALESCE(AVG(CASE WHEN ABS(entry - stop) > 0 THEN max_favorable / ABS(entry - stop) END), 0) AS avg_favorable_r,
            COALESCE(AVG(CASE WHEN ABS(entry - stop) > 0 THEN max_adverse / ABS(entry - stop) END), 0) AS avg_adverse_r,
            COALESCE(AVG(realized_r), 0) AS avg_realized_r,
            COALESCE(AVG(time_to_target1_ms), 0) AS avg_time_to_target1_ms,
            COALESCE(AVG(time_to_stop_ms), 0) AS avg_time_to_stop_ms
          FROM plans
          WHERE {filter_sql}
        """, (symbol, STRATEGY_VERSION)).fetchone()
        quarantined = connection.execute("""
          SELECT COUNT(*) AS total
          FROM plans
          WHERE symbol = ? AND (eligible_for_learning = 0 OR strategy_version IS NULL OR strategy_version <> ?)
        """, (symbol, STRATEGY_VERSION)).fetchone()
        by_direction = connection.execute(f"""
          SELECT direction, COUNT(*) AS total,
                 SUM(CASE WHEN realized_r > 0 THEN 1 ELSE 0 END) AS winners,
                 SUM(CASE WHEN realized_r <= 0 THEN 1 ELSE 0 END) AS stopped
          FROM plans
          WHERE {filter_sql}
          GROUP BY direction
        """, (symbol, STRATEGY_VERSION)).fetchall()
        by_setup = connection.execute(f"""
          SELECT COALESCE(setup_type, 'unknown') AS setup_type,
                 COUNT(*) AS total,
                 SUM(CASE WHEN realized_r > 0 THEN 1 ELSE 0 END) AS winners,
                 SUM(CASE WHEN realized_r <= 0 THEN 1 ELSE 0 END) AS stopped
          FROM plans
          WHERE {filter_sql}
          GROUP BY COALESCE(setup_type, 'unknown')
          HAVING total >= 2
          ORDER BY (1.0 * winners / NULLIF(winners + stopped, 0)) DESC, total DESC
        """, (symbol, STRATEGY_VERSION)).fetchall()
        by_timeframe = connection.execute(f"""
          SELECT timeframe,
                 COUNT(*) AS total,
                 SUM(CASE WHEN realized_r > 0 THEN 1 ELSE 0 END) AS winners,
                 SUM(CASE WHEN realized_r <= 0 THEN 1 ELSE 0 END) AS stopped
          FROM plans
          WHERE {filter_sql}
          GROUP BY timeframe
          ORDER BY (1.0 * winners / NULLIF(winners + stopped, 0)) DESC, total DESC
        """, (symbol, STRATEGY_VERSION)).fetchall()
        by_phase = connection.execute(f"""
          SELECT COALESCE(market_phase, 'unknown') AS market_phase,
                 COUNT(*) AS total,
                 SUM(CASE WHEN realized_r > 0 THEN 1 ELSE 0 END) AS winners,
                 SUM(CASE WHEN realized_r <= 0 THEN 1 ELSE 0 END) AS stopped
          FROM plans
          WHERE {filter_sql}
          GROUP BY COALESCE(market_phase, 'unknown')
          ORDER BY total DESC
        """, (symbol, STRATEGY_VERSION)).fetchall()
        recent = connection.execute(f"""
          SELECT id, created_at, timeframe, direction, setup, setup_type, score, lifecycle_status, outcome_status,
                 entry, stop, target1, target2, user_feedback, max_favorable, max_adverse,
                 time_to_target1_ms, time_to_stop_ms, realized_r
          FROM plans
          WHERE {filter_sql}
          ORDER BY created_at DESC
          LIMIT 40
        """, (symbol, STRATEGY_VERSION)).fetchall()
      summary_dict = dict(summary)
      summary_dict["quarantined"] = quarantined["total"]
      self.send_json(200, {
        "symbol": symbol,
        "summary": summary_dict,
        "byDirection": [dict(row) for row in by_direction],
        "bySetup": [dict(row) for row in by_setup],
        "byTimeframe": [dict(row) for row in by_timeframe],
        "byPhase": [dict(row) for row in by_phase],
        "recent": [dict(row) for row in recent],
      })
    except Exception as error:
      status, payload = self.api_error(error)
      self.send_json(status, payload)

  def handle_journal_replay(self, parsed):
    try:
      params = parse_qs(parsed.query)
      symbol = validate_symbol((params.get("symbol") or [SYMBOL])[0])
      runtime = market_runtime_snapshot(symbol)
      result = runtime.get("backtest")
      if not result:
        self.send_json(202, {
          "status": runtime.get("backtest_status", "not_started"),
          "detail": runtime.get("backtest_error") or "Historical replay is building",
        })
        return
      self.send_json(200, {"status": runtime.get("backtest_status", "ready"), **result})
    except Exception as error:
      status, payload = self.api_error(error)
      self.send_json(status, payload)

  def handle_history(self, parsed):
    params = parse_qs(parsed.query)
    try:
      symbol = validate_symbol((params.get("symbol") or [SYMBOL])[0])
      provider = active_provider(symbol)
      if not provider:
        self.send_json(503, {"error": "missing_provider", "detail": "No live provider is configured"})
        return
      runtime = market_runtime_snapshot(symbol)
      candles = runtime["history"] or fetch_history_candles(provider, symbol)
      record_market_candles(symbol, provider, candles)
      self.send_json(200, {
        "symbol": symbol,
        "candles": candles[-2500:],
        "providerErrors": runtime["error_count"],
        "lastSuccessAt": runtime["last_success_at"],
      })
    except Exception as error:
      status, payload = self.api_error(error)
      self.send_json(status, payload)

  def handle_daily(self, parsed):
    params = parse_qs(parsed.query)
    try:
      symbol = validate_symbol((params.get("symbol") or [SYMBOL])[0])
      daily_cache, fetched_at = load_daily_candles(symbol)
      if len(daily_cache) >= 400 and fetched_at and now_ms() - int(fetched_at) < DAILY_CACHE_TTL_MS:
        with MARKET_RUNTIME_LOCK:
          MARKET_RUNTIMES[symbol]["daily_history"] = daily_cache
        self.send_json(200, {
          "symbol": symbol,
          "provider": "yahoo",
          "candles": daily_cache,
          "cached": True,
          "degraded": False,
        })
        return
      try:
        candles = fetch_daily_candles(symbol)
        save_daily_candles(symbol, "yahoo", candles)
        with MARKET_RUNTIME_LOCK:
          MARKET_RUNTIMES[symbol]["daily_history"] = candles[-520:]
        self.send_json(200, {
          "symbol": symbol,
          "provider": "yahoo",
          "candles": candles[-520:],
          "cached": False,
          "degraded": False,
        })
      except (HTTPError, URLError, ValueError):
        if daily_cache:
          self.send_json(200, {
            "symbol": symbol,
            "provider": "yahoo",
            "candles": daily_cache,
            "cached": True,
            "degraded": True,
          })
          return
        cached = market_runtime_snapshot(symbol)["history"] or load_cached_candles(symbol)
        if not cached:
          raise
        self.send_json(200, {
          "symbol": symbol,
          "provider": active_provider(symbol) or "unavailable",
          "candles": cached,
          "degraded": True,
        })
    except Exception as error:
      status, payload = self.api_error(error)
      self.send_json(status, payload)

  def handle_five_minute(self, parsed):
    params = parse_qs(parsed.query)
    try:
      symbol = validate_symbol((params.get("symbol") or [SYMBOL])[0])
      provider = active_provider(symbol)
      if not provider:
        self.send_json(503, {"error": "missing_provider", "detail": "No live provider is configured"})
        return
      runtime = market_runtime_snapshot(symbol)
      candles = runtime["five_minute_history"]
      if not candles:
        candles = fetch_five_minute_candles(provider, symbol)
        with MARKET_RUNTIME_LOCK:
          MARKET_RUNTIMES[symbol]["five_minute_history"] = candles[-20_000:]
      self.send_json(200, {
        "symbol": symbol,
        "provider": provider,
        "timeframe": 5,
        "candles": candles[-20_000:],
      })
    except Exception as error:
      status, payload = self.api_error(error)
      self.send_json(status, payload)

  def handle_stream(self, parsed):
    params = parse_qs(parsed.query)
    try:
      symbol = validate_symbol((params.get("symbol") or [SYMBOL])[0])
    except ValueError as error:
      self.send_json(400, {"error": "bad_request", "detail": str(error)})
      return
    provider = active_provider(symbol)
    if not provider:
      self.send_response(503)
      self.send_header("Content-Type", "text/event-stream")
      self.end_headers()
      self.send_sse("error", {"error": "missing_provider", "detail": "No live provider is configured"})
      return

    self.send_response(200)
    self.send_header("Content-Type", "text/event-stream")
    self.send_header("Connection", "keep-alive")
    self.send_header("X-Accel-Buffering", "no")
    self.end_headers()

    last_key = None
    last_error_count = -1
    last_recommendations_key = None
    last_options_key = None
    while True:
      try:
        runtime = market_runtime_snapshot(symbol)
        candle = runtime["candle"]
        if candle:
          key = f"{candle['time']}-{candle['close']}-{candle['volume']}"
          if key != last_key:
            last_key = key
            self.send_sse("candle", candle)
          else:
            self.send_sse("status", {
              "message": "Stream connected",
              "candleTime": candle["time"],
              "lastSuccessAt": runtime["last_success_at"],
              "providerErrors": runtime["error_count"],
            })
        else:
          self.send_sse("status", {"message": "Server feed is starting"})
        if runtime["error_count"] and runtime["error_count"] != last_error_count:
          last_error_count = runtime["error_count"]
          self.send_sse("provider_error", {
            "error": "provider_unavailable",
            "detail": runtime["last_error"] if provider == "ibkr" else "Market data provider is temporarily unavailable.",
            "count": runtime["error_count"],
          })
        recommendations_key = json.dumps(runtime["recommendations"], sort_keys=True, separators=(",", ":"))
        if recommendations_key != last_recommendations_key:
          last_recommendations_key = recommendations_key
          self.send_sse("recommendations", {
            "generatedAt": runtime["recommendations_at"],
            "recommendations": runtime["recommendations"],
            "optionsOpportunity": runtime["options_opportunity"],
          })
        options_key = json.dumps(runtime["options_opportunity"], sort_keys=True, separators=(",", ":"))
        if options_key != last_options_key:
          last_options_key = options_key
          self.send_sse("options_opportunity", runtime["options_opportunity"])
      except (BrokenPipeError, ConnectionResetError):
        return
      except Exception as error:
        self.send_sse("error", self.api_error(error)[1])
      time.sleep(15 if provider == "yahoo" else 5)


class AppHTTPServer(ThreadingHTTPServer):
  daemon_threads = True
  allow_reuse_address = True
  request_queue_size = 64

  def handle_error(self, request, client_address):
    error = sys.exc_info()[1]
    if isinstance(error, (BrokenPipeError, ConnectionResetError)):
      return
    super().handle_error(request, client_address)


def main():
  if HOST not in {"127.0.0.1", "localhost", "::1"} and not APP_PASSWORD:
    raise RuntimeError("APP_PASSWORD is required when binding beyond localhost")
  if DATA_PROVIDER == "ibkr" and not ibkr_provider.available():
    raise RuntimeError("DATA_PROVIDER=ibkr requires the official IBKR Python API; run this server from the project .venv")
  os.chdir(APP_DIR)
  init_db()
  with db() as connection:
    cached_backtests = {symbol: load_latest_backtest(connection, symbol) for symbol in SUPPORTED_SYMBOLS}
  with MARKET_RUNTIME_LOCK:
    for symbol, cached_backtest in cached_backtests.items():
      if cached_backtest:
        MARKET_RUNTIMES[symbol]["backtest"] = cached_backtest
        MARKET_RUNTIMES[symbol]["backtest_status"] = "ready"
  server = AppHTTPServer((HOST, PORT), Handler)
  start_market_data_workers()
  provider = active_provider(SYMBOL)
  if provider == "alpaca":
    mode = f"Alpaca {ALPACA_FEED} data proxy"
  elif provider == "yahoo":
    mode = "Yahoo Finance chart web data"
  elif provider == "ibkr":
    mode = f"IBKR TWS read-only market data on {IBKR_HOST}:{IBKR_PORT}"
  elif provider == "polygon":
    mode = "Polygon/Massive data proxy"
  else:
    mode = "no market provider configured"
  print(f"Serving QQQ, SPY, and BTC-USD helper at http://{HOST}:{PORT}/ ({mode})")
  try:
    server.serve_forever()
  except KeyboardInterrupt:
    pass
  finally:
    MARKET_STOP_EVENT.set()
    if IBKR_CLIENT is not None:
      IBKR_CLIENT.close()
    server.server_close()


if __name__ == "__main__":
  main()
