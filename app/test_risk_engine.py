import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import risk_engine


class RiskEngineTests(unittest.TestCase):
  def test_position_size_respects_risk_and_position_value_caps(self):
    plan = risk_engine.position_plan({
      "entry": 100,
      "stop": 99,
      "target": 102,
      "target2": 103,
    }, {"risk": {"accountSize": 10_000, "riskPerTradePct": 1, "maxPositionValuePct": 20}})
    self.assertTrue(plan["configured"])
    self.assertEqual(plan["riskBudget"], 100)
    self.assertEqual(plan["quantity"], 20)
    self.assertEqual(plan["plannedRisk"], 20)
    self.assertEqual(plan["positionValue"], 2_000)

  def test_unconfigured_account_never_returns_a_quantity(self):
    plan = risk_engine.position_plan({"entry": 100, "stop": 99, "target": 101, "target2": 102})
    self.assertFalse(plan["configured"])
    self.assertIsNone(plan["quantity"])
    self.assertTrue(plan["blockers"])

  def test_invalid_settings_are_constrained(self):
    values = risk_engine.normalize_settings({"risk": {
      "accountSize": -100,
      "riskPerTradePct": 99,
      "maxConsecutiveLosses": 0,
    }})
    self.assertEqual(values["accountSize"], 0)
    self.assertEqual(values["riskPerTradePct"], 5)
    self.assertEqual(values["maxConsecutiveLosses"], 1)


if __name__ == "__main__":
  unittest.main()
