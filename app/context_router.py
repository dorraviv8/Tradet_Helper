"""Walk-forward evaluation for regime and session-aware setup routing."""

from collections import defaultdict

import backtest_engine


VERSION = "context-router-v1"
LABEL = "Context router"
DESCRIPTION = "Blocks historically weak setup/timeframe/side/regime/session combinations and identifies preferred combinations."
MIN_BLOCK_SAMPLES = 15
MIN_PREFER_SAMPLES = 20


def context_values(row):
  return (
    str(row.get("setupType") or "unknown"),
    str(int(row.get("timeframe") or 0)),
    str(row.get("direction") or "unknown"),
    str(row.get("marketRegime") or "unknown"),
    str(row.get("marketPhase") or "unknown"),
  )


def context_key(row):
  return "|".join(context_values(row))


def resolved_trades(trades):
  return sorted([
    row for row in trades or []
    if row.get("enteredAt") is not None
    and row.get("outcome") in backtest_engine.RESOLVED_OUTCOMES
    and row.get("realizedR") is not None
  ], key=lambda row: (int(row.get("signalTime") or 0), int(row.get("timeframe") or 0)))


def segment_summary(rows):
  summary = backtest_engine.summarize(rows)
  samples = int(summary.get("resolved") or 0)
  expected_r = float(summary.get("expectedR") or 0)
  return {
    "samples": samples,
    "winRate": summary.get("winRate"),
    "expectedR": expected_r,
    "calibratedExpectedR": expected_r * samples / (samples + 10) if samples else 0,
    "profitFactor": summary.get("profitFactor"),
  }


def learn_policy(trades):
  groups = defaultdict(list)
  for trade in resolved_trades(trades):
    groups[context_key(trade)].append(trade)
  blocked = []
  preferred = []
  for key, rows in groups.items():
    metrics = segment_summary(rows)
    setup_type, timeframe, direction, regime, phase = key.split("|", 4)
    item = {
      "key": key,
      "setupType": setup_type,
      "timeframe": int(timeframe),
      "direction": direction,
      "marketRegime": regime,
      "marketPhase": phase,
      **metrics,
    }
    profit_factor = metrics.get("profitFactor")
    if (
      metrics["samples"] >= MIN_BLOCK_SAMPLES
      and metrics["calibratedExpectedR"] <= -0.12
      and float(metrics.get("winRate") or 0) <= 0.45
      and (profit_factor is None or float(profit_factor) < 0.85)
    ):
      blocked.append(item)
    elif (
      metrics["samples"] >= MIN_PREFER_SAMPLES
      and metrics["calibratedExpectedR"] >= 0.12
      and float(metrics.get("winRate") or 0) >= 0.55
      and (profit_factor is None or float(profit_factor) >= 1.20)
    ):
      preferred.append(item)
  blocked.sort(key=lambda row: (row["calibratedExpectedR"], -row["samples"]))
  preferred.sort(key=lambda row: (row["calibratedExpectedR"], row["samples"]), reverse=True)
  return {
    "version": VERSION,
    "trainingSamples": sum(len(rows) for rows in groups.values()),
    "segmentsObserved": len(groups),
    "minimumBlockSamples": MIN_BLOCK_SAMPLES,
    "minimumPreferSamples": MIN_PREFER_SAMPLES,
    "blocked": blocked,
    "preferred": preferred,
  }


def apply_policy(trades, policy):
  blocked = {row["key"] for row in (policy or {}).get("blocked") or []}
  return [row for row in trades or [] if context_key(row) not in blocked]


def evaluation_window(trades):
  times = [int(row["signalTime"]) for row in trades or [] if row.get("signalTime") is not None]
  return {
    "start": min(times) if times else None,
    "end": max(times) if times else None,
    "timeframes": sorted({int(row["timeframe"]) for row in trades or [] if row.get("timeframe") is not None}),
  }


def run(trades, folds=3):
  ordered = resolved_trades(trades)
  if len(ordered) < 30:
    policy = learn_policy(ordered)
    return {
      "summary": backtest_engine.summarize([]),
      "byTimeframe": {},
      "groups": [],
      "trades": [],
      "contextPolicy": policy,
      "evaluationWindow": evaluation_window(ordered),
      "validation": {
        "status": "building",
        "detail": "At least 30 resolved champion trades are required for context routing",
        "sampleSize": len(ordered),
        "inSample": backtest_engine.summarize(ordered),
        "outOfSample": backtest_engine.summarize([]),
        "folds": [],
      },
      "method": {"lookAheadSafe": True, "contextPolicy": "trained only on candles before each test window"},
    }
  split = max(1, min(len(ordered) - 1, round(len(ordered) * 0.6)))
  training = ordered[:split]
  holdout = ordered[split:]
  validation_policy = learn_policy(training)
  filtered_holdout = apply_policy(holdout, validation_policy)
  fold_rows = []
  fold_size = max(1, len(ordered) // (folds + 1))
  for index in range(folds):
    test_start = min(len(ordered), fold_size * (index + 1))
    test_end = len(ordered) if index == folds - 1 else min(len(ordered), test_start + fold_size)
    fold_test = ordered[test_start:test_end]
    if not fold_test:
      continue
    fold_policy = learn_policy(ordered[:test_start])
    routed = apply_policy(fold_test, fold_policy)
    fold_rows.append({
      "fold": index + 1,
      "trainingSamples": test_start,
      "testStart": fold_test[0]["signalTime"],
      "testEnd": fold_test[-1]["signalTime"],
      "blockedSegments": len(fold_policy["blocked"]),
      "retained": len(routed),
      "test": backtest_engine.summarize(routed),
    })
  holdout_summary = backtest_engine.summarize(filtered_holdout)
  status = "validated" if (
    int(holdout_summary.get("resolved") or 0) >= 30
    and float(holdout_summary.get("expectedR") or 0) > 0
    and float(holdout_summary.get("profitFactor") or 0) > 1
  ) else "provisional"
  return {
    "summary": holdout_summary,
    "byTimeframe": backtest_engine.timeframe_summaries(filtered_holdout),
    "groups": backtest_engine.grouped_summaries(filtered_holdout),
    "trades": filtered_holdout,
    # Live shadow decisions can use every completed outcome. Validation below
    # remains based only on the earlier training window.
    "contextPolicy": learn_policy(ordered),
    "evaluationWindow": evaluation_window(holdout),
    "validation": {
      "status": status,
      "detail": "Chronological context policy: train on the first 60%, route only the later 40%",
      "sampleSize": len(ordered),
      "retainedSamples": len(filtered_holdout),
      "filteredSamples": len(holdout) - len(filtered_holdout),
      "inSample": backtest_engine.summarize(training),
      "outOfSample": holdout_summary,
      "folds": fold_rows,
    },
    "method": {
      "lookAheadSafe": True,
      "contextPolicy": "setup + timeframe + direction + regime + session phase",
      "automaticPromotion": False,
    },
  }


def decision_for_candidate(policy, candidate):
  if not isinstance(candidate, dict) or candidate.get("direction") not in {"long", "short"}:
    return {"status": "building", "appliedToProduction": False, "detail": "No directional context to evaluate."}
  key = context_key(candidate)
  for status, rows in (("block", (policy or {}).get("blocked") or []), ("prefer", (policy or {}).get("preferred") or [])):
    match = next((row for row in rows if row.get("key") == key), None)
    if match:
      action = "would block" if status == "block" else "would prefer"
      return {
        "status": status,
        "appliedToProduction": False,
        "samples": match["samples"],
        "expectedR": match["calibratedExpectedR"],
        "winRate": match["winRate"],
        "detail": f"Shadow router {action} this exact setup/timeframe/side/regime/session context from {match['samples']} training outcomes ({match['calibratedExpectedR']:+.2f}R).",
      }
  return {
    "status": "neutral",
    "appliedToProduction": False,
    "samples": 0,
    "expectedR": None,
    "winRate": None,
    "detail": "This exact setup/timeframe/side/regime/session context has no evidence-qualified routing rule yet.",
  }
