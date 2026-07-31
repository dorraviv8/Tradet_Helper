import json
import os
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


TRADE_ALERT_WEBHOOK_URL = os.environ.get("TRADE_ALERT_WEBHOOK_URL", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
DELIVERY_LOCK = threading.Lock()
DELIVERY_STATUS = {"attempts": 0, "delivered": 0, "failures": 0, "lastAttemptAt": None, "lastSuccessAt": None}


def configured_channels():
  channels = []
  if TRADE_ALERT_WEBHOOK_URL:
    channels.append("webhook")
  if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
    channels.append("telegram")
  return channels


def event_text(event, plan):
  symbol = str(plan.get("symbol") or "Market")
  direction = str(plan.get("direction") or "").upper()
  timeframe = "1D" if int(plan.get("timeframe") or 0) == 1440 else f"{int(plan.get('timeframe') or 0)}m"
  state = str(event).replace("_", " ").title()
  prices = (
    f"Entry {float(plan['entry']):.2f} | Stop {float(plan['stop']):.2f} | "
    f"T1 {float(plan['target1']):.2f} | T2 {float(plan['target2']):.2f}"
  )
  score = f" | Setup score {int(plan.get('score') or 0)}/100" if plan.get("score") is not None else ""
  return f"{symbol} {timeframe} {direction} - {state}{score}\n{prices}"


def send(event, plan):
  text = event_text(event, plan)
  delivered = []
  with DELIVERY_LOCK:
    DELIVERY_STATUS["attempts"] += 1
    DELIVERY_STATUS["lastAttemptAt"] = int(time.time() * 1000)
  if TRADE_ALERT_WEBHOOK_URL:
    payload = {"text": text, "content": text, "event": event, "plan": plan}
    request = Request(
      TRADE_ALERT_WEBHOOK_URL,
      data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
      headers={"Content-Type": "application/json", "User-Agent": "TraderHelperSignals/1.0"},
      method="POST",
    )
    try:
      with urlopen(request, timeout=10) as response:
        response.read(1)
      delivered.append("webhook")
    except (HTTPError, URLError, TimeoutError, ValueError):
      pass
  if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
    request = Request(
      f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
      data=urlencode({"chat_id": TELEGRAM_CHAT_ID, "text": text}).encode("utf-8"),
      headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "TraderHelperSignals/1.0"},
      method="POST",
    )
    try:
      with urlopen(request, timeout=10) as response:
        response.read(1)
      delivered.append("telegram")
    except (HTTPError, URLError, TimeoutError, ValueError):
      pass
  with DELIVERY_LOCK:
    if delivered:
      DELIVERY_STATUS["delivered"] += 1
      DELIVERY_STATUS["lastSuccessAt"] = int(time.time() * 1000)
    else:
      DELIVERY_STATUS["failures"] += 1
  return delivered


def send_async(event, plan):
  if not configured_channels():
    return False
  threading.Thread(target=send, args=(event, dict(plan)), name=f"trade-alert-{event}", daemon=True).start()
  return True


def delivery_status():
  with DELIVERY_LOCK:
    return {**DELIVERY_STATUS, "channels": configured_channels(), "configured": bool(configured_channels())}
