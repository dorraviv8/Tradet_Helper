import math


DEFAULTS = {
  "accountSize": 0.0,
  "riskPerTradePct": 0.5,
  "maxPositionValuePct": 30.0,
  "maxDailyLossPct": 1.5,
  "maxOpenRiskPct": 1.0,
  "maxConsecutiveLosses": 3,
}


def finite_number(value, default=0.0):
  try:
    number = float(value)
  except (TypeError, ValueError):
    return default
  return number if math.isfinite(number) else default


def normalize_settings(settings=None):
  values = {**DEFAULTS, **((settings or {}).get("risk") or {})}
  return {
    "accountSize": max(0.0, finite_number(values.get("accountSize"))),
    "riskPerTradePct": min(5.0, max(0.05, finite_number(values.get("riskPerTradePct"), 0.5))),
    "maxPositionValuePct": min(100.0, max(1.0, finite_number(values.get("maxPositionValuePct"), 30.0))),
    "maxDailyLossPct": min(20.0, max(0.1, finite_number(values.get("maxDailyLossPct"), 1.5))),
    "maxOpenRiskPct": min(20.0, max(0.1, finite_number(values.get("maxOpenRiskPct"), 1.0))),
    "maxConsecutiveLosses": min(20, max(1, int(finite_number(values.get("maxConsecutiveLosses"), 3)))),
  }


def position_plan(signal, settings=None, symbol=None):
  risk_settings = normalize_settings(settings)
  account_size = risk_settings["accountSize"]
  entry = finite_number((signal or {}).get("entry"))
  stop = finite_number((signal or {}).get("stop"))
  per_share_risk = abs(entry - stop)
  risk_budget = account_size * risk_settings["riskPerTradePct"] / 100
  max_position_value = account_size * risk_settings["maxPositionValuePct"] / 100
  market_symbol = str(symbol or (signal or {}).get("symbol") or "QQQ").upper()
  fractional = market_symbol == "BTC-USD"
  direct_instrument = market_symbol != "TA125"
  raw_risk_quantity = risk_budget / per_share_risk if risk_budget > 0 and per_share_risk > 0 else 0
  raw_value_quantity = max_position_value / entry if max_position_value > 0 and entry > 0 else 0
  risk_quantity = round(raw_risk_quantity, 6) if fractional else math.floor(raw_risk_quantity)
  value_quantity = round(raw_value_quantity, 6) if fractional else math.floor(raw_value_quantity)
  quantity = min(risk_quantity, value_quantity) if risk_quantity and value_quantity else 0
  if not direct_instrument:
    quantity = 0
  planned_risk = quantity * per_share_risk
  position_value = quantity * entry
  target1 = finite_number((signal or {}).get("target"))
  target2 = finite_number((signal or {}).get("target2"))
  return {
    **risk_settings,
    "configured": account_size > 0,
    "perShareRisk": per_share_risk if per_share_risk > 0 else None,
    "riskBudget": risk_budget if account_size > 0 else None,
    "quantity": quantity if quantity > 0 else None,
    "positionValue": position_value if quantity > 0 else None,
    "plannedRisk": planned_risk if quantity > 0 else None,
    "target1Reward": quantity * abs(target1 - entry) if quantity > 0 and target1 > 0 else None,
    "target2Reward": quantity * abs(target2 - entry) if quantity > 0 and target2 > 0 else None,
    "dailyLossLimit": account_size * risk_settings["maxDailyLossPct"] / 100 if account_size > 0 else None,
    "openRiskLimit": account_size * risk_settings["maxOpenRiskPct"] / 100 if account_size > 0 else None,
    "blockers": (
      ["TA-125 is an index; select a tradable ETF, future, or derivative before calculating quantity"]
      if not direct_instrument else [] if account_size > 0 else ["Set account size before using calculated position quantity"]
    ),
  }


def attach_position_plan(signal, settings=None, symbol=None):
  if not isinstance(signal, dict):
    return signal
  for key in ("bestLong", "bestShort"):
    candidate = signal.get(key)
    if isinstance(candidate, dict) and candidate.get("entry") is not None:
      candidate["riskPlan"] = position_plan(candidate, settings, symbol)
  if signal.get("entry") is not None:
    signal["riskPlan"] = position_plan(signal, settings, symbol)
  else:
    signal["riskPlan"] = {**normalize_settings(settings), "configured": False, "quantity": None, "blockers": ["No actionable entry"]}
  return signal
