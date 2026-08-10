"""Leakage-aware score calibration, hierarchical evidence, and drift checks."""

import math


CALIBRATION_VERSION = "platt-v1"
MIN_CALIBRATION_SAMPLES = 20
MIN_DRIFT_WARNING_SAMPLES = 5
MIN_DRIFT_BLOCK_SAMPLES = 8


def clamp(value, low, high):
  return max(low, min(high, value))


def sigmoid(value):
  if value >= 0:
    decay = math.exp(-value)
    return 1 / (1 + decay)
  growth = math.exp(value)
  return growth / (1 + growth)


def target1_hit(row):
  if row.get("target1_hit") is not None:
    return bool(row.get("target1_hit"))
  return row.get("outcome_status") in {"target1", "target1_stop", "target2"}


def ordered_outcomes(rows):
  return sorted([
    row for row in rows or []
    if row.get("score") is not None and row.get("realized_r") is not None
  ], key=lambda row: (int(row.get("closed_at") or 0), str(row.get("id") or "")))


def fit_sigmoid(rows, regularization=1.0, iterations=40):
  samples = ordered_outcomes(rows)
  if not samples:
    return {"intercept": 0.0, "slope": 0.0}
  intercept = 0.0
  slope = 0.0
  for _ in range(iterations):
    gradient_a = -regularization * intercept
    gradient_b = -regularization * slope
    h_aa = regularization
    h_ab = 0.0
    h_bb = regularization
    for row in samples:
      feature = (float(row["score"]) - 75.0) / 15.0
      label = 1.0 if target1_hit(row) else 0.0
      probability = sigmoid(intercept + slope * feature)
      variance = max(1e-6, probability * (1 - probability))
      error = label - probability
      gradient_a += error
      gradient_b += error * feature
      h_aa += variance
      h_ab += variance * feature
      h_bb += variance * feature * feature
    determinant = h_aa * h_bb - h_ab * h_ab
    if abs(determinant) < 1e-9:
      break
    delta_a = (gradient_a * h_bb - gradient_b * h_ab) / determinant
    delta_b = (gradient_b * h_aa - gradient_a * h_ab) / determinant
    intercept += delta_a
    slope += delta_b
    if abs(delta_a) + abs(delta_b) < 1e-7:
      break
  return {"intercept": round(intercept, 8), "slope": round(slope, 8)}


def predict_probability(model, score):
  if not model or model.get("status") == "building":
    return None
  feature = (float(score) - 75.0) / 15.0
  return clamp(sigmoid(float(model.get("intercept") or 0) + float(model.get("slope") or 0) * feature), 0.05, 0.95)


def brier_score(rows, model):
  if not rows:
    return None
  errors = []
  for row in rows:
    probability = predict_probability(model, row["score"])
    if probability is None:
      continue
    label = 1.0 if target1_hit(row) else 0.0
    errors.append((probability - label) ** 2)
  return sum(errors) / len(errors) if errors else None


def build_score_calibration(rows):
  ordered = ordered_outcomes(rows)
  if len(ordered) < MIN_CALIBRATION_SAMPLES:
    return {
      "version": CALIBRATION_VERSION,
      "status": "building",
      "sampleSize": len(ordered),
      "minimumSamples": MIN_CALIBRATION_SAMPLES,
      "lookAheadSafe": True,
    }
  split = max(10, min(len(ordered) - 1, round(len(ordered) * 0.7)))
  training = ordered[:split]
  holdout = ordered[split:]
  validation_model = {"status": "fitted", **fit_sigmoid(training)}
  full_model = fit_sigmoid(ordered)
  positives = sum(target1_hit(row) for row in training)
  baseline = positives / len(training)
  baseline_brier = sum((baseline - (1 if target1_hit(row) else 0)) ** 2 for row in holdout) / len(holdout)
  holdout_brier = brier_score(holdout, validation_model)
  return {
    "version": CALIBRATION_VERSION,
    "status": "validated" if holdout_brier is not None and holdout_brier <= baseline_brier else "provisional",
    "sampleSize": len(ordered),
    "trainingSamples": len(training),
    "holdoutSamples": len(holdout),
    "intercept": full_model["intercept"],
    "slope": full_model["slope"],
    "holdoutBrier": round(holdout_brier, 5) if holdout_brier is not None else None,
    "baselineBrier": round(baseline_brier, 5),
    "lookAheadSafe": True,
  }


def score_band(score):
  lower = int(float(score) // 10) * 10
  return f"{lower}-{min(100, lower + 9)}"


def calibration_drift(rows, calibration, recent_limit=8):
  ordered = ordered_outcomes(rows)
  if not calibration or calibration.get("status") != "validated":
    return {
      "status": "building",
      "recentLimit": recent_limit,
      "minimumWarningSamples": MIN_DRIFT_WARNING_SAMPLES,
      "minimumBlockSamples": MIN_DRIFT_BLOCK_SAMPLES,
      "bands": {},
    }
  grouped = {}
  for row in ordered:
    grouped.setdefault(score_band(row["score"]), []).append(row)
  bands = {}
  overall_status = "stable"
  for key, band_rows in grouped.items():
    values = band_rows[-recent_limit:]
    predicted_values = [predict_probability(calibration, row["score"]) for row in values]
    predicted_values = [value for value in predicted_values if value is not None]
    predicted = sum(predicted_values) / len(predicted_values) if predicted_values else 0.5
    observed = sum(target1_hit(row) for row in values) / len(values)
    expected_r = sum(float(row["realized_r"]) for row in values) / len(values)
    gap = predicted - observed
    if len(values) >= MIN_DRIFT_BLOCK_SAMPLES and gap >= 0.20 and expected_r <= -0.25:
      status = "blocked"
      overall_status = "blocked"
    elif len(values) >= MIN_DRIFT_WARNING_SAMPLES and gap >= 0.15 and expected_r < 0:
      status = "warning"
      if overall_status == "stable":
        overall_status = "warning"
    else:
      status = "stable" if len(values) >= MIN_DRIFT_WARNING_SAMPLES else "building"
    bands[key] = {
      "status": status,
      "samples": len(values),
      "predictedT1": round(predicted, 4),
      "observedT1": round(observed, 4),
      "gap": round(gap, 4),
      "expectedR": round(expected_r, 4),
    }
  return {
    "status": overall_status if bands else "building",
    "recentLimit": recent_limit,
    "minimumWarningSamples": MIN_DRIFT_WARNING_SAMPLES,
    "minimumBlockSamples": MIN_DRIFT_BLOCK_SAMPLES,
    "bands": bands,
  }


def drift_for_score(drift, score):
  row = ((drift or {}).get("bands") or {}).get(score_band(score))
  if not row:
    return {
      "status": "building", "samples": 0, "appliedToProduction": False,
      "detail": "This score band is collecting independent live outcomes.",
    }
  status = row["status"]
  return {
    **row,
    "appliedToProduction": status == "blocked",
    "detail": (
      f"Score-band drift block: {row['samples']} recent independent outcomes produced "
      f"{row['observedT1'] * 100:.0f}% T1 versus {row['predictedT1'] * 100:.0f}% predicted and {row['expectedR']:+.2f}R."
      if status == "blocked" else
      f"Score-band drift warning: {row['samples']} recent outcomes are below calibration."
      if status == "warning" else
      f"Score band has {row['samples']} recent independent outcomes with no evidence-qualified drift block."
    ),
  }


def hierarchical_estimate(groups, signal):
  setup = str(signal.get("setupType") or "unknown")
  timeframe = str(signal.get("timeframe") or "")
  phase = str(signal.get("marketPhase") or "unknown")
  direction = str(signal.get("direction") or "unknown")
  regime = str((signal.get("regime") or {}).get("type") or signal.get("marketRegime") or "unknown")
  levels = (
    ("timeframe", "byTimeframe", timeframe, 45),
    ("setup", "bySetup", setup, 35),
    ("setup/timeframe", "bySetupTimeframe", f"{setup}|{timeframe}", 25),
    ("setup/timeframe/direction", "bySetupTimeframeDirection", f"{setup}|{timeframe}|{direction}", 18),
    ("exact context", "byComparable", f"{setup}|{timeframe}|{phase}|{direction}|{regime}", 12),
  )
  probability = 0.5
  expected_r = 0.0
  used = []
  most_specific = None
  for label, group_name, key, shrinkage in levels:
    row = (groups.get(group_name) or {}).get(key)
    if not row:
      continue
    samples = int(row.get("sample_size") or 0)
    if samples <= 0:
      continue
    raw_probability = int(row.get("target1_hits") or 0) / samples
    raw_expected_r = float(row.get("expected_r") or 0)
    weight = samples / (samples + shrinkage)
    probability = probability * (1 - weight) + raw_probability * weight
    expected_r = expected_r * (1 - weight) + raw_expected_r * weight
    most_specific = row
    used.append({"scope": label, "samples": samples, "weight": round(weight, 3)})
  if most_specific is None:
    return None
  return {
    "probabilityT1": clamp(probability, 0.05, 0.95),
    "expectedR": expected_r,
    "sampleSize": int(most_specific.get("sample_size") or 0),
    "scope": used[-1]["scope"],
    "lastUpdated": most_specific.get("last_closed_at"),
    "avgMfeR": most_specific.get("avg_mfe_r"),
    "avgMaeR": most_specific.get("avg_mae_r"),
    "avgHoldingMs": most_specific.get("avg_holding_ms"),
    "levels": used,
  }
