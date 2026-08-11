import unittest

import shadow_candidate_engine as engine


def row(index, realized, *, code="below_threshold", score=60, signal_time=None):
  return {
    "id": str(index), "symbol": "QQQ", "timeframe": 5, "direction": "long",
    "signal_candle_time": index if signal_time is None else signal_time,
    "closed_at": index, "score": score, "realized_r": realized,
    "net_realized_r": realized - 0.02, "target1_hit": realized > 0,
    "rejection_codes": [code], "lifecycle_status": "closed",
  }


class ShadowCandidateEngineTests(unittest.TestCase):
  def test_correlated_same_candle_candidates_count_once(self):
    rows = [row(1, 1, score=60, signal_time=100), row(2, -1, score=70, signal_time=100)]
    snapshot = engine.build_snapshot(rows, "QQQ")
    self.assertEqual(snapshot["tracked"], 2)
    self.assertEqual(snapshot["independentResolved"], 1)
    self.assertLess(snapshot["expectedR"], 0)

  def test_positive_train_and_holdout_can_propose_manual_review(self):
    rows = [row(index, 1.0 if index % 4 else -0.3) for index in range(30)]
    rows.extend(row(100 + index, -0.2, code="recommended", signal_time=index) for index in range(30))
    snapshot = engine.build_snapshot(rows, "QQQ")
    filter_row = next(item for item in snapshot["filters"] if item["code"] == "below_threshold")
    self.assertEqual(filter_row["validation"]["status"], "review_easing")
    self.assertGreater(filter_row["expectedRDelta"], 0)
    self.assertEqual(len(snapshot["proposals"]), 1)
    self.assertFalse(snapshot["proposals"][0]["autoApply"])

  def test_bad_filter_cohort_is_retained(self):
    rows = [row(index, -1.0 if index % 3 else 0.2) for index in range(30)]
    snapshot = engine.build_snapshot(rows, "QQQ")
    self.assertEqual(snapshot["filters"][0]["validation"]["status"], "retain")
    self.assertFalse(snapshot["proposals"])

  def test_small_samples_never_propose_change(self):
    snapshot = engine.build_snapshot([row(index, 1.0) for index in range(8)], "QQQ")
    self.assertEqual(snapshot["filters"][0]["validation"]["status"], "building")
    self.assertFalse(snapshot["proposals"])


if __name__ == "__main__":
  unittest.main()
