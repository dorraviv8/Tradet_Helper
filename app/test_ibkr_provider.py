import os
import sys
import unittest
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))

import ibkr_provider


class IBKRProviderTests(unittest.TestCase):
  def test_epoch_seconds_and_milliseconds_are_normalized(self):
    self.assertEqual(ibkr_provider.parse_bar_time("1721304000"), 1_721_304_000_000)
    self.assertEqual(ibkr_provider.parse_bar_time("1721304000000"), 1_721_304_000_000)

  def test_market_active_covers_extended_session_only(self):
    eastern = ZoneInfo("America/New_York")
    self.assertTrue(ibkr_provider.market_is_active(datetime(2026, 7, 17, 10, 0, tzinfo=eastern)))
    self.assertFalse(ibkr_provider.market_is_active(datetime(2026, 7, 18, 10, 0, tzinfo=eastern)))
    self.assertFalse(ibkr_provider.market_is_active(datetime(2026, 7, 17, 21, 0, tzinfo=eastern)))

  @unittest.skipUnless(ibkr_provider.available(), "official IBKR Python API is not installed")
  def test_qqq_contract_is_market_data_only_smart_stock(self):
    contract = ibkr_provider.qqq_contract()
    self.assertEqual(contract.symbol, "QQQ")
    self.assertEqual(contract.secType, "STK")
    self.assertEqual(contract.exchange, "SMART")
    self.assertEqual(contract.currency, "USD")

  @unittest.skipUnless(ibkr_provider.available(), "official IBKR Python API is not installed")
  def test_invalid_volume_does_not_drop_valid_bar(self):
    client = ibkr_provider.IBKRMarketDataClient()
    bar = SimpleNamespace(
      date="1721304000",
      open=480.0,
      high=481.0,
      low=479.5,
      close=480.5,
      volume="NaN",
    )
    candle = client._bar_candle(bar)
    self.assertEqual(candle["volume"], 0)
    self.assertEqual(candle["close"], 480.5)

  @unittest.skipUnless(ibkr_provider.available(), "official IBKR Python API is not installed")
  def test_subscription_error_has_actionable_message_in_strict_mode(self):
    client = ibkr_provider.IBKRMarketDataClient(require_live=True)
    client.error(client.QUOTE_REQUEST_ID, 0, 10089, "subscription missing")
    self.assertIn("NASDAQ Network C/UTP", client.status()["error"])


if __name__ == "__main__":
  unittest.main()
