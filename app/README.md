# QQQ and Bitcoin Trader Alert Helper

Alert-only technical-analysis helper for QQQ and BTC-USD. It does not import order APIs and cannot place trades.

## Local Run

```bash
cd app
python3 server.py
```

Open `http://127.0.0.1:5173/`. Use the QQQ and BTC-USD buttons in the top bar to switch between isolated asset pages. The selected asset is also addressable with `?symbol=QQQ` or `?symbol=BTC-USD`.

Yahoo Finance chart data is used by default without an account or API key. It is best-effort web data and may be delayed, rate-limited, unavailable, or changed by Yahoo. The application pauses recommendations when recent data quality is not clean.

The market-context area also shows CNN's Fear & Greed Index. The server retrieves the public CNN reading, caches it for five minutes, and can serve the last cached reading as stale if CNN is temporarily unavailable. This broad-market sentiment is contextual only and does not currently change trade scores, entries, targets, or stops.

Synthetic demo prices are not used. Provider failure is shown as unavailable.

### Interactive Brokers TWS

For live QQQ bars without giving the application trading capability, run TWS with **Enable ActiveX and Socket Clients** and **Read-Only API** enabled. The live TWS port is normally `7496`. TWS must remain open and logged in. In Client Portal, the same username must complete the **Market Data API Acknowledgement** and have the required US equity market-data entitlement. Log out of all IBKR applications and log back in after changing the acknowledgement or subscriptions.

Install the official IBKR Python API into the project environment from the `source/pythonclient` directory included in the [official TWS API download](https://interactivebrokers.github.io/):

```bash
python3 -m venv .venv
.venv/bin/pip install /path/to/TWS\ API/source/pythonclient
```

Test the connection without starting the web application:

```bash
IBKR_PORT=7496 .venv/bin/python app/ibkr_provider.py
```

Then run the application from the project root:

```bash
cd app
DATA_PROVIDER=ibkr IBKR_PORT=7496 ../.venv/bin/python server.py
```

The provider requests QQQ trades only. Live and frozen data types are accepted; delayed and delayed-frozen data are rejected when `IBKR_REQUIRE_LIVE=true`. For a NASDAQ-listed ETF such as QQQ, IBKR lists **NASDAQ (Network C/UTP)** as the direct streaming subscription; the bundle route requires both the US Securities Snapshot and Futures Value Bundle and the US Equity and Options Add-On Streaming Bundle. Client ID `17` is used by default and can be changed with `IBKR_CLIENT_ID` if another API client already uses it.

## Analysis

The Python strategy engine is the only authority for entries, exits, targets, trend state, regime, and candidate scores. The browser renders those server results and shows a neutral waiting state while server analysis is unavailable; it cannot silently substitute a second browser-generated trade. QQQ and BTC-USD have separate live runtimes, recommendations, journals, historical replays, and calibration samples.

QQQ uses New York regular and extended trading sessions. BTC-USD is analyzed as a continuous 24/7 market: day boundaries and daily VWAP reset at 00:00 UTC, weekends remain active, and crypto-specific ATR and percentage limits are used for entries, invalidations, and targets. CNN Fear & Greed is labeled as US market context on the BTC page and does not affect Bitcoin scores.

The engine evaluates closed 1m, 5m, and 15m candles on every refresh, regardless of which chart is visible. Yahoo's native 5m feed supplies up to 60 days of context, so 5m/15m averages and momentum do not depend on the shorter retained 1m window. The General Trend panel also reports 1D momentum from closed daily candles using EMA 20/50 alignment, five-session price momentum, EMA slope, and RSI. The Best Day Trade panel shows the strongest actionable intraday timeframe.

The daily engine uses up to two years of Yahoo candles and produces a separate Best Swing result. It ranks bull and bear momentum continuation, 20-day breakout/breakdown, EMA 20 pullback/rejection, and support/resistance reversal setups. Daily plans require at least 160 closed candles and use daily EMA 20/50, SMA 150, RSI 14, ATR 14, relative volume, and 5/20-day price momentum. Session VWAP is intentionally excluded from daily scoring and display.

Indicators:

- Per-candle share-volume histogram on 1m, 5m, 15m, and 1D charts
- RSI 14 pane beneath volume, calculated independently for the selected timeframe with 30/50/70 reference levels
- VWAP
- SMA and EMA 20 / 50 / 150
- RSI 14
- ATR 14
- Relative volume
- Current-session trend, momentum, regime, support, resistance, and opening range

The Patterns control ranks confirmed or geometrically valid structures and displays only the strongest current match. Intraday pattern detection uses regular-session candles only (09:30-16:00 New York time); premarket and after-hours candles may remain visible but cannot create or confirm a pattern. Daily detection is unchanged. Supported families include head-and-shoulders, double and triple tops/bottoms, flags, pennants, triangles, wedges, cup-and-handle, rounded reversals, rectangles, channels, engulfing candles, hammers/shooting stars, dojis, and morning/evening stars. Clicking a pattern toggles its measured-move projection. Pattern scores rank competing shapes; they are not probabilities and do not directly alter the server alert score.

Each actionable long or short plan includes entry, invalidation, Target 1, Target 2, exit warnings, quality score, and reasons. Intraday targets use asset-specific volatility bounds. QQQ swing targets are bounded at roughly 1.2%-2.5% for Target 1 and up to 4% for Target 2; BTC-USD uses roughly 2%-5% and up to 8%. Scores are rule-based quality ranks, not probabilities.

## Historical Replay And Calibration

The server runs a background candle-by-candle replay over retained 1m history, up to 5,000 native 5m bars, resampled 15m bars, and up to 520 daily bars. Replay calls the same Python setup and scoring functions used by live recommendations. It enforces the signal boundary, starts entry evaluation on a later candle, does not award a target on the entry candle, excludes ambiguous OHLC paths from calibration, applies configurable execution friction, and keeps simulated trades separate from the live journal.

Default replay execution assumptions are 0.5 basis points of slippage per side and zero per-share commission. Configure `backtestSlippageBps` and `backtestCommissionPerShare` in `settings.json` if the expected execution environment differs.

Historical Edge reports a neutral-prior estimate of Target 1 occurring before the stop, expected net return in R, comparable sample size, and a 95% Wilson interval. The most specific group with enough observations is selected in this order: setup/timeframe/direction, setup/timeframe, timeframe/direction, timeframe, then all replay trades. Fewer than 20 resolved comparable trades is explicitly labeled Preliminary. Replay statistics describe the retained sample and do not guarantee future results.

On the selected chart, a confirmed long plan marks its exact entry trigger with a green upward arrow. A confirmed short plan uses a red downward arrow. Watch-only candidates and rejected setups do not draw entry arrows.

## Chart Navigation

Use the plus and minus controls to change candle density. Scrolling vertically over the price chart zooms around the cursor, while horizontal trackpad scrolling pans through time. Drag the price chart left or right to inspect newer or older candles; the arrow controls provide the same movement in fixed steps. The viewport can move up to half a screen beyond the newest candle, leaving future space on the right and allowing the current candle to sit near the center. **Live View** restores the latest candles at the right edge and the default zoom.

Each timeframe keeps its own viewport while the page is open. Historical views stay anchored to their ending candle when live data arrives, and the current-price marker and active recommendation overlay appear only when their data is inside the visible window.

## Journal Integrity

Strategy version `5.1.0` records the signal candle separately from the time the plan became actionable. Outcome evaluation starts at the first candle after that boundary and never awards a target from the same OHLC bar that first triggered entry. Intraday waiting plans expire after four hours; daily swing entries can remain valid for up to 14 calendar days.

The server owns candle persistence and outcome evaluation. Browser clients cannot submit outcome candles. Older strategy versions remain in SQLite but are excluded from adaptive statistics.

Adaptive score adjustments require at least 30 resolved examples and use shrinkage toward a neutral prior. Expectancy and positive-R rate are shown alongside target and stop counts.

The journal path defaults to:

```text
app/data/trader_journal.sqlite3
```

Set `JOURNAL_DB_PATH` to keep it elsewhere. Database, WAL, and SHM files are excluded from Git and Docker builds.

## Server Feed

One background worker per symbol polls Yahoo, caches the latest candle for every browser, repairs intraday history every five minutes, evaluates plan outcomes, and applies exponential backoff after provider failures. SSE updates the selected chart without browser refresh; polling remains a watchdog.

The Graph Refresh control manually synchronizes the latest candle, intraday history, native five-minute history, daily history, and server recommendations, then redraws the selected chart without reloading the page or resetting chart controls.

Yahoo data horizons:

- 1m: five-day source window, with the newest 2,500 bars retained for the browser
- 5m: native 60-day source window, refreshed every 15 minutes
- 1D: native two-year source window, refreshed at most every six hours

Health endpoints:

- `GET /health`
- `GET /ready`

## Security

Localhost runs without authentication. Binding to any non-loopback address requires `APP_PASSWORD`; the server refuses to start without it.

```bash
HOST=0.0.0.0 APP_USERNAME=trader APP_PASSWORD="a-long-random-password" python3 server.py
```

Use HTTPS through a cloud load balancer, Caddy, or nginx. The server also validates write origins, limits JSON body size, hides internal errors by default, and emits structured request logs.

## Docker

From the project root:

```bash
cp .env.example .env
# Edit .env and set a long APP_PASSWORD.
docker compose up --build -d
```

The container runs read-only with dropped Linux capabilities. SQLite is stored in the `trader-data` persistent volume. The published port binds to `127.0.0.1`; put an HTTPS reverse proxy in front before exposing it publicly.

The Docker configuration defaults to Yahoo. A container or cloud server cannot reach TWS at the desktop loopback address `127.0.0.1`. Keep the IBKR-enabled application on the same computer as TWS, or later add a private authenticated network bridge. Never expose TWS port `7496` directly to the internet.

## Verification

```bash
node app/test_market_core.js
node app/test_pattern_engine.js
python3 -m unittest discover -s app -p 'test_*.py'
node --check app/app.js
node --check app/pattern-engine.js
python3 -m py_compile app/server.py app/strategy_engine.py app/backtest_engine.py app/ibkr_provider.py
```

This tool is educational decision support, not financial advice. It does not guarantee outcomes.
