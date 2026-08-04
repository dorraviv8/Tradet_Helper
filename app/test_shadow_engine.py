import unittest

import shadow_engine


def replay(expected_r, resolved=140, profit_factor=1.4, drawdown=5.0, fold_values=(0.2, 0.3, 0.1)):
  return {
    "validation": {
      "outOfSample": {
        "resolved": resolved,
        "expectedR": expected_r,
        "profitFactor": profit_factor,
        "maxDrawdownR": drawdown,
      },
      "folds": [
        {"test": {"resolved": 40, "expectedR": value}}
        for value in fold_values
      ],
    },
    "groups": [],
  }


class ShadowEngineTests(unittest.TestCase):
  def test_variants_do_not_mutate_production_settings(self):
    settings = {"activeTradeThreshold": 62, "mode": "normal", "risk": {"riskPerTradePct": 0.5}}
    variants = shadow_engine.variants(settings, "6.0.0")
    self.assertEqual(settings["activeTradeThreshold"], 62)
    self.assertEqual(variants[0]["settings"]["activeTradeThreshold"], 66)
    self.assertEqual(variants[1]["settings"]["mode"], "strict")
    self.assertTrue(all("shadow" in row["version"] for row in variants))

  def test_promotion_requires_material_stable_out_of_sample_improvement(self):
    comparison = shadow_engine.compare(replay(0.10, drawdown=6.0), replay(0.18, drawdown=6.2), 120)
    self.assertTrue(comparison["eligibleForPromotionReview"])
    self.assertEqual(comparison["status"], "eligible_for_review")
    self.assertFalse(comparison["autoPromote"])

  def test_small_sample_remains_building(self):
    comparison = shadow_engine.compare(replay(0.10, resolved=70), replay(0.30, resolved=50), 120)
    self.assertEqual(comparison["status"], "building")
    self.assertFalse(comparison["eligibleForPromotionReview"])

  def test_unstable_folds_block_promotion(self):
    comparison = shadow_engine.compare(
      replay(0.10), replay(0.20, fold_values=(0.4, -0.2, -0.1)), 120,
    )
    self.assertFalse(comparison["criteria"]["stableFolds"])
    self.assertFalse(comparison["eligibleForPromotionReview"])

  def test_missing_champion_is_not_reported_as_zero_expectancy(self):
    comparison = shadow_engine.compare({}, replay(0.20), 120)
    self.assertIsNone(comparison["champion"]["expectedR"])
    self.assertIsNone(comparison["expectancyImprovement"])
    self.assertEqual(comparison["status"], "observing")
    self.assertFalse(comparison["eligibleForPromotionReview"])


if __name__ == "__main__":
  unittest.main()
