import unittest

import learning_engine


def outcome(index, score, hit, realized):
  return {
    "id": str(index), "score": score, "target1_hit": hit,
    "realized_r": realized, "closed_at": index,
  }


class LearningEngineTests(unittest.TestCase):
  def test_score_calibration_is_chronological_and_monotonic_for_positive_score_edge(self):
    rows = []
    for index in range(60):
      score = 60 + index % 36
      hit = score >= 78
      rows.append(outcome(index, score, hit, 1 if hit else -1))
    model = learning_engine.build_score_calibration(rows)
    self.assertIn(model["status"], {"validated", "provisional"})
    self.assertTrue(model["lookAheadSafe"])
    self.assertGreater(
      learning_engine.predict_probability(model, 90),
      learning_engine.predict_probability(model, 65),
    )

  def test_small_sample_calibration_stays_building(self):
    model = learning_engine.build_score_calibration([outcome(index, 80, False, -1) for index in range(10)])
    self.assertEqual(model["status"], "building")
    self.assertIsNone(learning_engine.predict_probability(model, 80))

  def test_drift_blocks_only_after_eight_independent_recent_outcomes(self):
    training = [outcome(index, 85, True, 1) for index in range(30)]
    model = learning_engine.build_score_calibration(training)
    model["status"] = "validated"
    warning = learning_engine.calibration_drift([outcome(100 + i, 85, False, -1) for i in range(5)], model)
    blocked = learning_engine.calibration_drift([outcome(100 + i, 85, False, -1) for i in range(8)], model)
    self.assertEqual(warning["bands"]["80-89"]["status"], "warning")
    self.assertEqual(blocked["bands"]["80-89"]["status"], "blocked")

  def test_drift_uses_latest_outcomes_within_each_score_band(self):
    training = [outcome(index, 85, True, 1) for index in range(30)]
    model = learning_engine.build_score_calibration(training)
    model["status"] = "validated"
    rows = [outcome(100 + i, 85, False, -1) for i in range(8)]
    rows.extend(outcome(200 + i, 65, True, 1) for i in range(8))
    drift = learning_engine.calibration_drift(rows, model)
    self.assertEqual(drift["bands"]["80-89"]["samples"], 8)
    self.assertEqual(drift["bands"]["80-89"]["status"], "blocked")
    self.assertEqual(drift["bands"]["60-69"]["samples"], 8)

  def test_hierarchical_estimate_shrinks_sparse_exact_context(self):
    groups = {
      "byTimeframe": {"5": {"sample_size": 100, "target1_hits": 60, "expected_r": 0.3}},
      "byComparable": {"breakout|5|morning|long|trend_up": {
        "sample_size": 1, "target1_hits": 0, "expected_r": -1,
      }},
    }
    estimate = learning_engine.hierarchical_estimate(groups, {
      "setupType": "breakout", "timeframe": 5, "marketPhase": "morning",
      "direction": "long", "marketRegime": "trend_up",
    })
    self.assertGreater(estimate["probabilityT1"], 0.4)
    self.assertLess(estimate["probabilityT1"], 0.6)
    self.assertEqual(estimate["sampleSize"], 1)


if __name__ == "__main__":
  unittest.main()
