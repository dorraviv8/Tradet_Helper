"""Conservative analytics for live shadow candidates."""

import math


VERSION = "live-candidate-v1"
MIN_FILTER_SAMPLES = 20
MIN_HOLDOUT_SAMPLES = 6

FILTER_LABELS = {
  "below_threshold": "Score threshold",
  "near_threshold": "Near-threshold setup",
  "execution_quality": "Execution quality",
  "risk_reward": "Risk/reward",
  "structure": "Structural risk",
  "five_minute_filter": "5m no-trade filter",
  "quality_gate": "Live quality gate",
  "calibration_drift": "Calibration drift",
  "context_router": "Context router",
  "not_selected": "Competing setup",
  "recommended": "Recommended baseline",
}


def _finite(value):
  try:
    result = float(value)
  except (TypeError, ValueError):
    return None
  return result if math.isfinite(result) else None


def _target1_hit(row):
  if row.get("target1_hit") is not None:
    return bool(row.get("target1_hit"))
  return row.get("outcome_status") in {"target1", "target1_stop", "target2"}


def _cluster_key(row):
  return (
    str(row.get("symbol") or ""), int(row.get("timeframe") or 0),
    str(row.get("direction") or ""), int(row.get("signal_candle_time") or 0),
  )


def independent_rows(rows):
  """Keep one highest-quality hypothesis per correlated signal cluster."""
  selected = {}
  for row in rows or []:
    if _finite(row.get("net_realized_r")) is None and _finite(row.get("realized_r")) is None:
      continue
    key = _cluster_key(row)
    current = selected.get(key)
    rank = (int(row.get("score") or 0), str(row.get("id") or ""))
    current_rank = (int(current.get("score") or 0), str(current.get("id") or "")) if current else None
    if current is None or rank > current_rank:
      selected[key] = row
  return sorted(selected.values(), key=lambda row: (
    int(row.get("closed_at") or row.get("updated_at") or 0), str(row.get("id") or ""),
  ))


def summarize(rows):
  independent = independent_rows(rows)
  returns = [
    _finite(row.get("net_realized_r"))
    if _finite(row.get("net_realized_r")) is not None else _finite(row.get("realized_r"))
    for row in independent
  ]
  returns = [value for value in returns if value is not None]
  target_hits = sum(_target1_hit(row) for row in independent)
  gains = sum(value for value in returns if value > 0)
  losses = abs(sum(value for value in returns if value < 0))
  return {
    "resolved": len(independent),
    "target1Hits": target_hits,
    "target1Rate": round(target_hits / len(independent), 4) if independent else None,
    "expectedR": round(sum(returns) / len(returns), 4) if returns else None,
    "profitFactor": round(gains / losses, 3) if losses else (None if not gains else 99.0),
    "positive": sum(value > 0 for value in returns),
    "negative": sum(value <= 0 for value in returns),
  }


def _chronological_validation(rows):
  independent = independent_rows(rows)
  if len(independent) < MIN_FILTER_SAMPLES:
    return {"status": "building", "train": summarize([]), "holdout": summarize([])}
  split = max(12, min(len(independent) - MIN_HOLDOUT_SAMPLES, round(len(independent) * 0.7)))
  train = summarize(independent[:split])
  holdout = summarize(independent[split:])
  train_r = _finite(train.get("expectedR"))
  holdout_r = _finite(holdout.get("expectedR"))
  holdout_rate = _finite(holdout.get("target1Rate"))
  holdout_pf = _finite(holdout.get("profitFactor"))
  if (
    train_r is not None and train_r >= 0.10
    and holdout_r is not None and holdout_r >= 0.10
    and holdout_rate is not None and holdout_rate >= 0.50
    and holdout_pf is not None and holdout_pf >= 1.10
  ):
    status = "review_easing"
  elif train_r is not None and train_r <= 0 and holdout_r is not None and holdout_r <= 0:
    status = "retain"
  else:
    status = "inconclusive"
  return {"status": status, "train": train, "holdout": holdout}


def _filter_codes(row):
  values = row.get("rejection_codes") or []
  if isinstance(values, str):
    values = [value for value in values.split(",") if value]
  return set(values)


def build_snapshot(rows, symbol, generated_at=None):
  rows = list(rows or [])
  resolved_rows = [row for row in rows if _finite(row.get("realized_r")) is not None]
  overall = summarize(resolved_rows)
  codes = sorted({code for row in rows for code in _filter_codes(row)})
  recommended = [row for row in rows if "recommended" in _filter_codes(row)]
  baseline = summarize(recommended)
  baseline_validation = _chronological_validation(recommended)
  filters = []
  proposals = []
  for code in codes:
    cohort = [row for row in resolved_rows if code in _filter_codes(row)]
    metrics = summarize(cohort)
    validation = _chronological_validation(cohort)
    row = {
      "code": code,
      "label": FILTER_LABELS.get(code, code.replace("_", " ").title()),
      "tracked": sum(code in _filter_codes(item) for item in rows),
      **metrics,
      "validation": validation,
      "expectedRDelta": (
        round(metrics["expectedR"] - baseline["expectedR"], 4)
        if metrics["expectedR"] is not None and baseline["expectedR"] is not None else None
      ),
    }
    filters.append(row)
    baseline_holdout = baseline_validation.get("holdout") or {}
    baseline_holdout_r = _finite(baseline_holdout.get("expectedR"))
    filter_holdout_r = _finite((validation.get("holdout") or {}).get("expectedR"))
    beats_baseline = (
      int(baseline_holdout.get("resolved") or 0) >= MIN_HOLDOUT_SAMPLES
      and baseline_holdout_r is not None and filter_holdout_r is not None
      and filter_holdout_r >= baseline_holdout_r + 0.05
    )
    if validation["status"] == "review_easing" and beats_baseline and code not in {"recommended", "not_selected"}:
      proposals.append({
        "filter": code,
        "label": row["label"],
        "status": "eligible_for_review",
        "autoApply": False,
        "independentSamples": metrics["resolved"],
        "holdoutExpectedR": validation["holdout"]["expectedR"],
        "holdoutTarget1Rate": validation["holdout"]["target1Rate"],
        "detail": f"Review whether {row['label'].lower()} is rejecting a repeatably positive cohort.",
      })
  qualified = [row for row in filters if row["resolved"] >= 5 and row["code"] not in {"recommended", "not_selected"}]
  ranked = sorted(qualified, key=lambda row: (row["expectedR"], row["resolved"]), reverse=True)
  rejected = [row for row in rows if "recommended" not in _filter_codes(row)]
  missed = [
    row for row in independent_rows(rejected)
    if (_finite(row.get("net_realized_r")) if _finite(row.get("net_realized_r")) is not None else _finite(row.get("realized_r"))) > 0
  ]
  return {
    "version": VERSION,
    "symbol": symbol,
    "generatedAt": generated_at,
    "tracked": len(rows),
    "open": sum(row.get("lifecycle_status") in {"waiting", "entered"} for row in rows),
    "recommendedTracked": len(recommended),
    "rejectedTracked": len(rejected),
    "independentResolved": overall["resolved"],
    "target1Rate": overall["target1Rate"],
    "expectedR": overall["expectedR"],
    "profitFactor": overall["profitFactor"],
    "recommendedBaseline": {**baseline, "validation": baseline_validation},
    "potentiallyMissed": len(missed),
    "filters": filters,
    "bestFilter": ranked[0] if ranked else None,
    "worstFilter": ranked[-1] if ranked else None,
    "proposals": proposals,
    "autoApply": False,
    "minimumFilterSamples": MIN_FILTER_SAMPLES,
  }
