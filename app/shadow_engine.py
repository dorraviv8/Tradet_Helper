"""Shadow strategy definitions and conservative champion comparisons."""

import copy
import math


VARIANT_DEFINITIONS = (
  {
    "id": "quality-threshold-v1",
    "label": "Quality threshold",
    "description": "Requires four additional setup-quality points before an alert is actionable.",
    "thresholdOffset": 4,
    "mode": None,
  },
  {
    "id": "strict-confirmation-v1",
    "label": "Strict confirmation",
    "description": "Uses the strict confirmation and wider target profile.",
    "thresholdOffset": 0,
    "mode": "strict",
  },
)


def variants(settings, champion_version):
  output = []
  for definition in VARIANT_DEFINITIONS:
    variant_settings = copy.deepcopy(settings or {})
    variant_settings["activeTradeThreshold"] = int(variant_settings.get("activeTradeThreshold", 62)) + int(definition["thresholdOffset"])
    if definition["mode"]:
      variant_settings["mode"] = definition["mode"]
    output.append({
      "id": definition["id"],
      "version": f"{champion_version}-shadow-{definition['id']}",
      "label": definition["label"],
      "description": definition["description"],
      "settings": variant_settings,
    })
  return output


def _number(value):
  try:
    result = float(value)
  except (TypeError, ValueError):
    return None
  return result if math.isfinite(result) else None


def _metric(summary, key, default=0.0):
  value = _number((summary or {}).get(key))
  return default if value is None else value


def top_segments(result, minimum_samples=10, limit=3):
  rows = []
  for row in (result or {}).get("groups") or []:
    resolved = int(row.get("resolved") or 0)
    expected_r = _number(row.get("expectedR"))
    if resolved < minimum_samples or expected_r is None:
      continue
    rows.append({
      "timeframe": int(row.get("timeframe") or 0),
      "setupType": row.get("setupType") or "unknown",
      "marketPhase": row.get("marketPhase") or "unknown",
      "marketRegime": row.get("marketRegime") or "unknown",
      "direction": row.get("direction") or "unknown",
      "resolved": resolved,
      "winRate": _number(row.get("winRate")),
      "expectedR": expected_r,
    })
  rows.sort(key=lambda row: (row["expectedR"], row["resolved"]), reverse=True)
  return rows[:limit]


def compare(champion, challenger, minimum_samples=120):
  champion_validation = (champion or {}).get("validation") or {}
  challenger_validation = (challenger or {}).get("validation") or {}
  champion_holdout = champion_validation.get("outOfSample") or {}
  challenger_holdout = challenger_validation.get("outOfSample") or {}
  champion_samples = int(champion_holdout.get("resolved") or 0)
  challenger_samples = int(challenger_holdout.get("resolved") or 0)
  champion_expectancy = _number(champion_holdout.get("expectedR"))
  challenger_expectancy = _metric(challenger_holdout, "expectedR")
  challenger_profit_factor = _metric(challenger_holdout, "profitFactor")
  champion_drawdown = _number(champion_holdout.get("maxDrawdownR"))
  challenger_drawdown = _metric(challenger_holdout, "maxDrawdownR")
  coverage = challenger_samples / champion_samples if champion_samples else 0.0
  folds = challenger_validation.get("folds") or []
  resolved_folds = [row for row in folds if int((row.get("test") or {}).get("resolved") or 0) > 0]
  positive_folds = sum(_metric(row.get("test"), "expectedR") > 0 for row in resolved_folds)
  required_positive_folds = max(2, math.ceil(len(resolved_folds) * 2 / 3)) if resolved_folds else 2
  expectancy_improvement = challenger_expectancy - champion_expectancy if champion_expectancy is not None else None
  criteria = {
    "minimumSamples": challenger_samples >= int(minimum_samples),
    "positiveExpectancy": challenger_expectancy >= 0.05,
    "profitFactor": challenger_profit_factor >= 1.10,
    "improvesChampion": expectancy_improvement is not None and expectancy_improvement >= 0.03,
    "drawdownControlled": champion_samples > 0 and champion_drawdown is not None and challenger_drawdown <= max(0.5, champion_drawdown * 1.10),
    "coverage": coverage >= 0.60,
    "stableFolds": positive_folds >= required_positive_folds,
  }
  eligible = all(criteria.values())
  if eligible:
    status = "eligible_for_review"
    detail = "All shadow promotion gates passed. Manual review is required; production remains unchanged."
  elif challenger_samples < int(minimum_samples):
    status = "building"
    detail = f"Collecting holdout evidence: {challenger_samples} of {int(minimum_samples)} resolved shadow trades."
  elif champion_expectancy is None:
    status = "observing"
    detail = "The challenger has holdout results, but the matching champion baseline is not available yet."
  elif challenger_expectancy <= champion_expectancy:
    status = "underperforming"
    detail = "The challenger does not improve holdout expectancy versus the production strategy."
  else:
    status = "observing"
    detail = "The challenger shows improvement, but one or more risk or stability gates have not passed."
  return {
    "status": status,
    "eligibleForPromotionReview": eligible,
    "autoPromote": False,
    "minimumPromotionSamples": int(minimum_samples),
    "criteria": criteria,
    "champion": {
      "resolved": champion_samples,
      "expectedR": champion_expectancy,
      "profitFactor": _number(champion_holdout.get("profitFactor")),
      "maxDrawdownR": champion_drawdown,
    },
    "challenger": {
      "resolved": challenger_samples,
      "expectedR": challenger_expectancy,
      "profitFactor": _number(challenger_holdout.get("profitFactor")),
      "maxDrawdownR": challenger_drawdown,
      "coverage": coverage,
      "positiveFolds": positive_folds,
      "totalFolds": len(resolved_folds),
    },
    "expectancyImprovement": expectancy_improvement,
    "detail": detail,
    "topSegments": top_segments(challenger),
  }
