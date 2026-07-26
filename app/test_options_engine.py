import unittest
from datetime import datetime, timezone

import options_engine as options


NOW = int(datetime(2026, 7, 24, 15, 0, tzinfo=timezone.utc).timestamp() * 1000)


def signal(direction="long", timeframe=5, **overrides):
  long = direction == "long"
  item = {
    "timeframe": timeframe,
    "direction": direction,
    "watchOnly": False,
    "score": 86,
    "setup": "Momentum continuation",
    "setupType": "momentum",
    "dataQuality": "clean",
    "riskReward": 1.7,
    "entry": 600.0,
    "stop": 598.0 if long else 602.0,
    "target": 603.0 if long else 597.0,
    "target2": 605.0 if long else 595.0,
    "signalCandleTime": NOW - timeframe * 60_000,
    "trend5": {"tone": "positive" if long else "negative"},
    "trend15": {"tone": "positive" if long else "negative"},
    "regime": {"type": "trend_up" if long else "trend_down"},
  }
  item.update(overrides)
  return item


def contract(guidance, **overrides):
  put = guidance["side"] == "put"
  item = {
    "optionSymbol": "QQQ260807P00600000" if put else "QQQ260807C00600000",
    "underlying": "QQQ",
    "expiration": (NOW // 1000) + 14 * 86_400,
    "side": guidance["side"],
    "strike": 600,
    "dte": guidance["dte"]["target"],
    "bid": 6.00,
    "ask": 6.40,
    "mid": 6.20,
    "volume": 800,
    "openInterest": 4000,
    "underlyingPrice": 600,
    "updated": (NOW - 15 * 60_000) // 1000,
    "iv": 0.22,
    "delta": -0.62 if put else 0.62,
    "gamma": 0.025,
    "theta": -0.12,
    "vega": 0.31,
  }
  item.update(overrides)
  return item


class OptionsEngineTests(unittest.TestCase):
  def test_selects_only_strong_supported_aligned_signal(self):
    recommendations = {
      1: signal(timeframe=1, score=99),
      5: signal(timeframe=5, score=86),
      15: signal(timeframe=15, score=79),
    }
    selected, empty = options.select_underlying_signal(recommendations, regular_session=True)
    self.assertIsNone(empty)
    self.assertEqual(selected[0], 5)

  def test_intraday_signal_is_blocked_outside_regular_session(self):
    selected, empty = options.select_underlying_signal({5: signal()}, regular_session=False)
    self.assertIsNone(selected)
    self.assertEqual(empty["status"], "none")
    self.assertIn("regular session", " ".join(empty["diagnostics"]["5"]))

  def test_intraday_signal_requires_5m_and_15m_alignment(self):
    selected, empty = options.select_underlying_signal({
      5: signal(trend15={"tone": "negative"}),
    }, regular_session=True)
    self.assertIsNone(selected)
    self.assertIn("15m trend is not aligned", empty["diagnostics"]["5"])

  def test_guidance_maps_long_to_call_and_balanced_dte(self):
    guidance = options.build_guidance(5, signal(), plan_id="plan-1", generated_at=NOW, underlying_price=601)
    self.assertEqual(guidance["status"], "guidance")
    self.assertEqual(guidance["sideLabel"], "CALL")
    self.assertEqual(guidance["dte"]["target"], 10)
    self.assertEqual(guidance["delta"]["target"], 0.62)
    self.assertLess(guidance["strikeGuidance"]["min"], guidance["strikeGuidance"]["max"])
    self.assertEqual(guidance["planId"], "plan-1")
    self.assertNotIn(
      datetime.fromisoformat(guidance["dte"]["targetExpiration"]).weekday(),
      {5, 6},
    )
    self.assertFalse(guidance["provider"]["delayed"])

  def test_btc_guidance_uses_ibit_as_the_option_proxy(self):
    guidance = options.build_guidance(
      15,
      signal(timeframe=15, entry=110_000, stop=109_000, target=112_000, target2=113_000),
      generated_at=NOW,
      underlying_price=110_500,
      option_price=70,
      symbol="BTC-USD",
    )
    self.assertEqual(guidance["symbol"], "BTC-USD")
    self.assertEqual(guidance["underlyingSymbol"], "BTC-USD")
    self.assertEqual(guidance["optionSymbol"], "IBIT")
    self.assertEqual(guidance["dte"]["target"], 21)
    self.assertLess(guidance["strikeGuidance"]["min"], 71)
    self.assertLess(guidance["strikeGuidance"]["max"], 71)

  def test_ibit_guidance_requires_the_us_regular_session(self):
    selected, empty = options.select_underlying_signal(
      {1440: signal(timeframe=1440)},
      regular_session=False,
      symbol="BTC-USD",
    )
    self.assertIsNone(selected)
    self.assertIn("IBIT options ideas require the US regular session", empty["diagnostics"]["1440"])

  def test_spy_guidance_uses_spy_contracts(self):
    guidance = options.build_guidance(5, signal(), generated_at=NOW, symbol="SPY")
    self.assertEqual(guidance["underlyingSymbol"], "SPY")
    self.assertEqual(guidance["optionSymbol"], "SPY")

  def test_marketdata_column_arrays_are_normalized(self):
    payload = {
      "s": "ok",
      "optionSymbol": ["A", "B"],
      "side": ["call", "put"],
      "strike": [600, 601],
      "bid": [5.0, 5.1],
    }
    rows = options.normalize_marketdata_chain(payload)
    self.assertEqual(len(rows), 2)
    self.assertEqual(rows[1]["optionSymbol"], "B")
    self.assertIsNone(rows[1]["ask"])

  def test_contract_ranking_rejects_wide_spread_and_illiquidity(self):
    guidance = options.build_guidance(15, signal(timeframe=15), generated_at=NOW)
    wide = contract(guidance, bid=4.0, ask=6.0, mid=5.0)
    illiquid = contract(guidance, optionSymbol="LOW", openInterest=200)
    good = contract(guidance, optionSymbol="GOOD", dte=14)
    ranked = options.rank_contracts([wide, illiquid, good], guidance, NOW, realized_vol=0.18)
    self.assertEqual([item["optionSymbol"] for item in ranked], ["GOOD"])
    self.assertLessEqual(ranked[0]["spreadPct"], 0.10)

  def test_contract_quote_older_than_thirty_minutes_is_rejected(self):
    guidance = options.build_guidance(5, signal(), generated_at=NOW)
    stale = contract(guidance, updated=(NOW - 31 * 60_000) // 1000)
    self.assertEqual(options.rank_contracts([stale], guidance, NOW), [])

  def test_put_scenario_uses_negative_delta_for_underlying_decline(self):
    guidance = options.build_guidance(15, signal("short", timeframe=15), generated_at=NOW)
    selected = contract(guidance, dte=14)
    ranked = options.rank_contracts([selected], guidance, NOW)
    result = options.attach_contract(guidance, ranked[0])
    self.assertEqual(result["status"], "contract")
    self.assertEqual(result["sideLabel"], "PUT")
    self.assertGreater(
      result["contract"]["scenarios"]["target1"]["estimatedOptionMid"],
      result["contract"]["mid"],
    )

  def test_learning_adjustment_waits_for_thirty_exact_outcomes(self):
    below = {"0.60-0.65": {"sampleSize": 29, "averageReturn": 0.4, "winRate": 0.8}}
    enough = {"0.60-0.65": {"sampleSize": 30, "averageReturn": 0.4, "winRate": 0.8}}
    self.assertEqual(options.option_learning_adjustment(below, 0.62), 0)
    self.assertGreater(options.option_learning_adjustment(enough, 0.62), 0)


if __name__ == "__main__":
  unittest.main()
