import unittest

import context_router


def trade(index, realized_r, phase="morning", regime="trend_up", setup="breakout"):
  return {
    "timeframe": 5,
    "direction": "long",
    "setup": f"Long 5m {setup}",
    "setupType": setup,
    "marketPhase": phase,
    "marketRegime": regime,
    "qualityScore": 75,
    "signalTime": index * 300_000,
    "entry": 100,
    "stop": 99,
    "target1": 101,
    "target2": 102,
    "enteredAt": index * 300_000 + 1,
    "closedAt": index * 300_000 + 2,
    "outcome": "target2" if realized_r > 0 else "stopped",
    "target1Hit": realized_r > 0,
    "realizedR": realized_r,
    "mfeR": 1.4 if realized_r > 0 else 0.2,
    "maeR": 0.2 if realized_r > 0 else 1.0,
    "timeToTarget1Ms": 60_000 if realized_r > 0 else None,
  }


class ContextRouterTests(unittest.TestCase):
  def test_policy_blocks_only_evidence_qualified_negative_context(self):
    rows = [trade(index, -1.0, phase="midday", regime="chop") for index in range(18)]
    rows += [trade(100 + index, 1.0, phase="morning", regime="trend_up") for index in range(22)]
    policy = context_router.learn_policy(rows)
    self.assertEqual(len(policy["blocked"]), 1)
    self.assertEqual(policy["blocked"][0]["marketPhase"], "midday")
    self.assertEqual(len(policy["preferred"]), 1)
    self.assertEqual(policy["preferred"][0]["marketRegime"], "trend_up")

  def test_small_negative_sample_remains_observational(self):
    policy = context_router.learn_policy([trade(index, -1.0, phase="midday", regime="chop") for index in range(14)])
    self.assertEqual(policy["blocked"], [])

  def test_walk_forward_router_filters_holdout_without_future_leakage(self):
    training = [trade(index, -1.0, phase="midday", regime="chop") for index in range(30)]
    training += [trade(30 + index, 1.0, phase="morning", regime="trend_up") for index in range(30)]
    holdout = [trade(60 + index, -1.0, phase="midday", regime="chop") for index in range(20)]
    holdout += [trade(80 + index, 1.0, phase="morning", regime="trend_up") for index in range(20)]
    result = context_router.run([*training, *holdout])
    self.assertEqual(result["validation"]["filteredSamples"], 20)
    self.assertEqual(result["validation"]["outOfSample"]["resolved"], 20)
    self.assertEqual(result["validation"]["outOfSample"]["expectedR"], 1.0)
    self.assertTrue(result["method"]["lookAheadSafe"])

  def test_candidate_decision_is_shadow_only(self):
    candidate = trade(1, -1.0, phase="midday", regime="chop")
    policy = context_router.learn_policy([trade(index, -1.0, phase="midday", regime="chop") for index in range(18)])
    decision = context_router.decision_for_candidate(policy, candidate)
    self.assertEqual(decision["status"], "block")
    self.assertFalse(decision["appliedToProduction"])


if __name__ == "__main__":
  unittest.main()
