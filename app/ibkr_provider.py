import math
import os
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo


MARKET_TIME_ZONE = ZoneInfo("America/New_York")
INFORMATIONAL_CODES = {2104, 2106, 2107, 2108, 2158, 2176}
CONNECTIVITY_CODES = {1100, 1101, 1102}
SUBSCRIPTION_CODES = {10089, 10090, 10091}

try:
  from ibapi.client import EClient
  from ibapi.contract import Contract
  from ibapi.wrapper import EWrapper
  IBAPI_IMPORT_ERROR = None
except ImportError as error:
  EClient = None
  Contract = None
  EWrapper = None
  IBAPI_IMPORT_ERROR = error


def available():
  return IBAPI_IMPORT_ERROR is None


def parse_bar_time(value):
  text = str(value).strip()
  try:
    number = int(float(text))
    if number > 10_000_000_000:
      return number
    return number * 1000
  except ValueError:
    pass
  for pattern in ("%Y%m%d %H:%M:%S %Z", "%Y%m%d  %H:%M:%S", "%Y%m%d %H:%M:%S", "%Y%m%d"):
    try:
      parsed = datetime.strptime(text, pattern)
      if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=MARKET_TIME_ZONE)
      return int(parsed.timestamp() * 1000)
    except ValueError:
      continue
  raise ValueError(f"Unsupported IBKR bar time: {text}")


def qqq_contract():
  if Contract is None:
    raise RuntimeError("IBKR Python API is not installed") from IBAPI_IMPORT_ERROR
  contract = Contract()
  contract.symbol = "QQQ"
  contract.secType = "STK"
  contract.exchange = "SMART"
  contract.primaryExchange = "NASDAQ"
  contract.currency = "USD"
  return contract


def market_is_active(now=None):
  current = now or datetime.now(MARKET_TIME_ZONE)
  if current.tzinfo is None:
    current = current.replace(tzinfo=MARKET_TIME_ZONE)
  else:
    current = current.astimezone(MARKET_TIME_ZONE)
  minute = current.hour * 60 + current.minute
  return current.weekday() < 5 and 4 * 60 <= minute < 20 * 60


if available():
  class IBKRMarketDataClient(EWrapper, EClient):
    HISTORY_REQUEST_ID = 9101
    QUOTE_REQUEST_ID = 9102

    def __init__(self, host="127.0.0.1", port=7496, client_id=17, require_live=True):
      EWrapper.__init__(self)
      EClient.__init__(self, self)
      self.host = host
      self.port = int(port)
      self.client_id = int(client_id)
      self.require_live = bool(require_live)
      self._lock = threading.RLock()
      self._ready = threading.Event()
      self._history_ready = threading.Event()
      self._runner = None
      self._candles = {}
      self._subscribed = False
      self._request_error = None
      self._last_error = None
      self._market_data_type = None
      self._last_update_at = None

    def connect_and_start(self, timeout=12):
      if self.isConnected() and self._ready.is_set() and self._runner and self._runner.is_alive():
        return
      self.close()
      self._ready.clear()
      self._history_ready.clear()
      self._request_error = None
      self._last_error = None
      self.connect(self.host, self.port, clientId=self.client_id)
      self._runner = threading.Thread(target=self.run, name="ibkr-api", daemon=True)
      self._runner.start()
      if not self._ready.wait(timeout):
        detail = self._last_error or f"TWS did not accept the API connection on {self.host}:{self.port}"
        self.close()
        raise RuntimeError(detail)

    def nextValidId(self, orderId):
      self._ready.set()

    def connectionClosed(self):
      self._ready.clear()
      self._subscribed = False

    def error(self, reqId, errorTime, errorCode, errorString, advancedOrderRejectJson=""):
      if errorCode in SUBSCRIPTION_CODES and self.require_live:
        message = (
          "IBKR live QQQ API data is unavailable (error 10089). Complete the Market Data API "
          "Acknowledgement and enable NASDAQ Network C/UTP streaming data for this IBKR user."
        )
      else:
        message = f"IBKR {errorCode}: {errorString}"
      if errorCode in INFORMATIONAL_CODES:
        return
      with self._lock:
        self._last_error = message
        if reqId == self.HISTORY_REQUEST_ID or errorCode not in CONNECTIVITY_CODES:
          self._request_error = message
      if reqId == self.HISTORY_REQUEST_ID:
        self._history_ready.set()
      if errorCode == 1100:
        self._ready.clear()
        self._subscribed = False

    def marketDataType(self, reqId, marketDataType):
      if reqId != self.QUOTE_REQUEST_ID:
        return
      with self._lock:
        self._market_data_type = int(marketDataType)
        if self.require_live and self._market_data_type in {3, 4}:
          self._request_error = "IBKR returned delayed market data; a live QQQ market-data subscription is required"
          self._history_ready.set()

    def _bar_candle(self, bar):
      values = [float(bar.open), float(bar.high), float(bar.low), float(bar.close)]
      if not all(math.isfinite(value) and value > 0 for value in values):
        return None
      if values[1] < max(values[0], values[3]) or values[2] > min(values[0], values[3]):
        return None
      timestamp = parse_bar_time(bar.date)
      try:
        volume = int(float(bar.volume))
      except (TypeError, ValueError, OverflowError):
        volume = 0
      return {
        "time": timestamp // 60_000 * 60_000,
        "open": values[0],
        "high": values[1],
        "low": values[2],
        "close": values[3],
        "volume": max(0, volume),
      }

    def _store_bar(self, bar):
      candle = self._bar_candle(bar)
      if not candle:
        return
      with self._lock:
        self._candles[candle["time"]] = candle
        self._last_update_at = int(time.time() * 1000)

    def historicalData(self, reqId, bar):
      if reqId == self.HISTORY_REQUEST_ID:
        self._store_bar(bar)

    def historicalDataUpdate(self, reqId, bar):
      if reqId == self.HISTORY_REQUEST_ID:
        self._store_bar(bar)

    def historicalDataEnd(self, reqId, start, end):
      if reqId == self.HISTORY_REQUEST_ID:
        self._history_ready.set()

    def request_history(self, duration="2 D", timeout=30):
      self.connect_and_start()
      with self._lock:
        already_streaming = self._subscribed and bool(self._candles) and self._request_error is None
      if already_streaming:
        return self.history_snapshot()
      self._history_ready.clear()
      with self._lock:
        self._request_error = None
        self._candles = {}
      if self.require_live:
        self.reqMarketDataType(1)
        self.reqMktData(
          self.QUOTE_REQUEST_ID,
          qqq_contract(),
          "",
          False,
          False,
          [],
        )
      else:
        with self._lock:
          self._market_data_type = 3
      self.reqHistoricalData(
        self.HISTORY_REQUEST_ID,
        qqq_contract(),
        "",
        duration,
        "1 min",
        "TRADES",
        0,
        2,
        True,
        [],
      )
      with self._lock:
        self._subscribed = True
      if not self._history_ready.wait(timeout):
        raise RuntimeError("Timed out waiting for QQQ historical bars from TWS")
      with self._lock:
        error = self._request_error
      if error:
        raise RuntimeError(error)
      candles = self.history_snapshot()
      if len(candles) < 30:
        raise RuntimeError("TWS returned insufficient QQQ history")
      return candles

    def history_snapshot(self):
      with self._lock:
        return [dict(self._candles[key]) for key in sorted(self._candles)]

    def latest_candle(self, maximum_age_ms=90_000):
      self.connect_and_start()
      with self._lock:
        if self._request_error:
          raise RuntimeError(self._request_error)
        if not self._candles:
          return None
        candle = dict(self._candles[max(self._candles)])
        updated_at = self._last_update_at
      if updated_at and market_is_active() and int(time.time() * 1000) - updated_at > maximum_age_ms:
        raise RuntimeError("IBKR QQQ stream is stale")
      return candle

    def status(self):
      with self._lock:
        return {
          "connected": bool(self.isConnected() and self._ready.is_set()),
          "marketDataType": self._market_data_type,
          "lastUpdateAt": self._last_update_at,
          "error": self._request_error or self._last_error,
          "candles": len(self._candles),
        }

    def close(self):
      try:
        if self.isConnected() and self._subscribed:
          self.cancelHistoricalData(self.HISTORY_REQUEST_ID)
          if self.require_live:
            self.cancelMktData(self.QUOTE_REQUEST_ID)
      except Exception:
        pass
      self._subscribed = False
      if self.isConnected():
        self.disconnect()
      self._ready.clear()

else:
  class IBKRMarketDataClient:
    def __init__(self, *args, **kwargs):
      raise RuntimeError("IBKR Python API is not installed") from IBAPI_IMPORT_ERROR


def main():
  if not available():
    raise RuntimeError("IBKR Python API is not installed") from IBAPI_IMPORT_ERROR
  client = IBKRMarketDataClient(
    host=os.environ.get("IBKR_HOST", "127.0.0.1"),
    port=int(os.environ.get("IBKR_PORT", "7496")),
    client_id=int(os.environ.get("IBKR_CLIENT_ID", "17")),
    require_live=os.environ.get("IBKR_REQUIRE_LIVE", "true").lower() in {"1", "true", "yes"},
  )
  try:
    candles = client.request_history(os.environ.get("IBKR_HISTORY_DURATION", "2 D"))
    latest = candles[-1]
    status = client.status()
    print(
      f"Connected to TWS: {len(candles)} QQQ one-minute bars; "
      f"latest={latest['close']:.2f} at {latest['time']}; "
      f"market_data_type={status['marketDataType']}"
    )
  finally:
    client.close()


if __name__ == "__main__":
  main()
