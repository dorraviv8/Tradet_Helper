# Multi-Market Trader Alert Helper

Technical-analysis helper for QQQ, SPY, BTC-USD, and TA-125. It does not import broker order APIs and cannot place real trades. Its Demo Auto Trading account executes simulations only.

## Local Run

```bash
cd app
python3 server.py
```

Open `http://127.0.0.1:5173/`. Use the market selector in the top bar to switch between isolated asset views. The selected asset is also addressable with `?symbol=QQQ`, `?symbol=SPY`, `?symbol=BTC-USD`, or `?symbol=TA125`.

Yahoo Finance chart data is used by default without an account or API key. It is best-effort web data and may be delayed, rate-limited, unavailable, or changed by Yahoo. The application pauses recommendations when recent data quality is not clean.

The market-context area also shows CNN's Fear & Greed Index. The server retrieves the public CNN reading, caches it for five minutes, and can serve the last cached reading as stale if CNN is temporarily unavailable. This broad-market sentiment is contextual only and does not currently change trade scores, entries, targets, or stops.

Synthetic demo prices are not used. Provider failure is shown as unavailable.

## Demo Auto Trading

The forward-only demo account starts once with $20,000 and has no reset or manual-order endpoint. A dedicated background worker can hold day, swing, and long-horizon positions simultaneously. Day setups favor the 5m analysis; swing and long setups use closed daily momentum.

The portfolio targets at least two new day-trade entries per trailing 24 hours. Until that target is reached, activity-target mode can accept the strongest score-50+ day candidate with at least 0.8 reward/risk even when it is below the normal alert threshold or remains watch-only for setup quality. It still rejects stale or blocked data, malformed levels, non-clean data quality, stop distances outside 0.05%-6%, insufficient cash, and risk-limit violations. The ordinary stricter selection resumes after two day entries.

Entries fill at the next eligible candle open with adverse asset-specific slippage. QQQ and SPY use whole ETF shares, BTC-USD supports fractional units, and TA-125 signals execute through the `IBI-F42.TA` tracking ETF. Yahoo quotes that ETF in agorot, so prices are divided by 100 and converted into account USD using `ILS=X`. A missing ETF or FX quote blocks TA-125 execution.

The account has no leverage. Long purchases consume cash, while shorts reserve 100% of entry notional as collateral. Every entry, partial exit, and final exit costs $5. A profitable completed trade pays 25% tax on positive gross P&L after its commissions; losing trades receive no tax credit. Position sizing is rechecked at fill time against cash, a 40% per-market exposure cap, 90% total exposure cap, and 4% total open stop-risk cap. New demo positions use cost-aware stops: the engine preserves wider technical invalidation, but widens stops that are too close using timeframe volatility, a percentage floor, and a minimum $30 gross stop risk (three times the $10 round-trip commission). Targets expand with an adjusted stop to preserve reward/risk, and an order is rejected when available capital cannot support an economically sensible stop. Day trades may use up to 40% of account equity; existing open positions are never widened after entry.

SQLite stores the permanent account, orders, fills, positions, cash ledger, and five-minute equity snapshots. `GET /api/demo-trading` is read-only and returns the account, open positions, pending orders, completed trades, performance cohorts, equity curve, and learning state. Every completed trade enters forward cohort analysis. Policy proposals remain unapplied until at least 50 comparable outcomes are available and the existing shadow-validation process supports a reviewed strategy change.

Prometheus exports demo equity, net P&L, open positions, pending orders, completed trades, and maximum drawdown. Monitoring raises incidents for worker failures and accounting invariants.

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

The Python strategy engine is the only authority for entries, exits, targets, trend state, regime, and candidate scores. The browser renders those server results and shows a neutral waiting state while server analysis is unavailable; it cannot silently substitute a second browser-generated trade. Every market has a separate live runtime, recommendation set, journal, historical replay, and calibration sample.

QQQ and SPY use New York regular and extended sessions with distinct ETF volatility profiles. BTC-USD is analyzed continuously: day boundaries and daily VWAP reset at 00:00 UTC, weekends remain active, and crypto-specific limits are used. TA-125 follows the Tel Aviv session and does not use unreliable index volume as a confirmation factor. CNN Fear & Greed remains contextual and does not alter scores.

The engine evaluates closed 1m, 5m, and 15m candles on every refresh, regardless of which chart is visible. Yahoo's native 5m feed supplies up to 60 days per fetch and is accumulated in persistent storage. Non-boundary quote rows are rejected before 5m analysis. The General Trend panel also reports 1D momentum from closed daily candles. The opportunity scanner ranks current day and swing candidates across all configured markets.

The daily engine requests up to ten years of Yahoo candles, retains up to 3,000 bars, and produces a separate Best Swing result. It ranks bull and bear momentum continuation, 20-day breakout/breakdown, EMA 20 pullback/rejection, and support/resistance reversal setups. Daily plans require at least 160 closed candles and use daily EMA 20/50, SMA 150, RSI 14, ATR 14, supported volume context, and 5/20-day price momentum. Session VWAP is intentionally excluded from daily scoring and display.

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

Each actionable long or short plan includes entry, invalidation, Target 1, Target 2, exit warnings, score drivers, and the next missing condition. Intraday targets use asset-specific volatility bounds. QQQ swing targets are bounded at roughly 1.2%-2.5% for Target 1 and up to 4% for Target 2; BTC-USD uses roughly 2%-5% and up to 8%. Scores are rule-based quality ranks, not probabilities. Position sizing is shown only after an account size and risk percentage are supplied; TA-125 requires selection of a tradable instrument first.

Intraday candidates also pass an execution-quality gate. The stop must be at least 0.25 ATR from entry and wide enough that estimated round-trip slippage consumes no more than 0.25R. Intraday entries require a candle close through the trigger; an intrabar touch alone does not activate a plan. Candidates that fail either test remain watch-only.

## Historical Replay And Calibration

The server runs a bounded background candle-by-candle replay over persistent 1m history, up to 50,000 native 5m bars, resampled 15m bars, and up to 3,000 daily bars. Replay calls the same Python setup and scoring functions used by live recommendations. It uses chronological holdouts and rolling forward folds, models opening fills, stop gaps and session-dependent slippage, excludes ambiguous OHLC paths, and keeps simulated trades separate from the live journal.

Each replay also runs three versioned shadow challengers. Two operate over a bounded recent 5m, 15m, and 1D evaluation window: a four-point higher quality threshold and the strict confirmation profile. The third is a context router that learns exact setup, timeframe, direction, market-regime, and session-phase combinations. It requires at least 15 outcomes plus negative expectancy, win rate, and profit-factor evidence before proposing a block, or at least 20 outcomes plus positive evidence before marking a context preferred. Its out-of-sample result is trained on the earlier 60% and evaluated only on the later 40%; current shadow decisions may use all completed history.

Challenger trades and policies are persisted separately with entry, stop, targets, setup, timeframe, direction, regime, MFE, MAE, and realized R. Model Governance filters the fixed production champion to each challenger's identical timeframes and date window, then compares holdout expectancy after execution costs, profit factor, drawdown, sample coverage, and fold stability. The context router remains observational: its proposed block or preference appears under Model Confidence but does not suppress, promote, or rescore a production recommendation without manual review and a later explicit promotion.

Default replay execution assumptions are 0.5 basis points of slippage per side and zero per-share commission. Configure `backtestSlippageBps` and `backtestCommissionPerShare` in `settings.json` if the expected execution environment differs.

Historical Edge reports a neutral-prior estimate of Target 1 occurring before the stop, expected net return in R, profit factor, maximum drawdown, comparable sample size, and a 95% Wilson interval. The most specific group with enough observations is selected in this order: setup/timeframe/direction, setup/timeframe, timeframe/direction, timeframe, then all replay trades. Replay statistics describe the retained sample and do not guarantee future results.

Live learning uses one canonical trade thesis per strategy version, symbol, timeframe, direction, setup, and signal candle. Price-level revisions update that thesis instead of creating a second outcome. A startup migration preserves duplicate rows for audit history, marks them as correlated revisions, and excludes them from learning and success-rate calculations.

The Model Confidence panel separates the rule-based setup score from a regularized sigmoid estimate of Target 1 probability. The calibrator uses a chronological 70/30 train/holdout split and remains in a building state until 20 independent outcomes exist. Context expectancy uses conservative hierarchical shrinkage from timeframe through setup, direction, regime, and session instead of treating a one-trade exact context as independent proof.

Calibration drift is evaluated over the most recent eight independent outcomes in each ten-point score band. Five outcomes can produce a warning; a production pause requires at least eight outcomes, a probability shortfall of at least 20 percentage points, and expectancy of -0.25R or worse. The pause affects only that score band and is exposed in the UI and Prometheus metrics.

## Live Shadow Candidate Learning

Every technically triggered candidate from a fresh regular-session candle is recorded in a persistent shadow ledger, including the production recommendation, near-threshold alternatives, and candidates rejected by execution quality, risk/reward, structural, 5m, quality, calibration-drift, or context filters. Shadow candidates never create trader alerts, never appear as active trade plans, and never enter production calibration. Their deterministic thesis keys prevent browser or server refreshes from duplicating evidence.

Shadow outcomes use the same candle-close entry confirmation and OHLC ambiguity rules as live plans. Intraday candidates receive a four-hour time exit and daily candidates a fourteen-day time exit. Analytics subtract the candidate's estimated round-trip execution cost, cluster correlated setups from the same symbol/timeframe/direction/candle into one independent observation, and cache the resulting snapshot persistently.

The Shadow Learning panel compares each rejected filter cohort with the recommended baseline. A rule can become eligible for manual review only after at least 20 independent filter outcomes, at least six chronological holdout outcomes, positive train and holdout expectancy, a holdout T1 rate of at least 50%, holdout profit factor of at least 1.10, and holdout expectancy at least 0.05R above the recommended baseline. Production rules are never changed automatically.

On the selected chart, a confirmed long plan marks its exact entry trigger with a green upward arrow. A confirmed short plan uses a red downward arrow. Watch-only candidates and rejected setups do not draw entry arrows.

## Chart Navigation

Use the plus and minus controls to change candle density. Scrolling vertically over the price chart zooms around the cursor, while horizontal trackpad scrolling pans through time. Drag the price chart left or right to inspect newer or older candles; the arrow controls provide the same movement in fixed steps. The viewport can move up to half a screen beyond the newest candle, leaving future space on the right and allowing the current candle to sit near the center. **Live View** restores the latest candles at the right edge and the default zoom.

Each timeframe keeps its own viewport while the page is open. Historical views stay anchored to their ending candle when live data arrives, and the current-price marker and active recommendation overlay appear only when their data is inside the visible window.

## Journal Integrity

Strategy version `6.0.0` records the signal candle separately from the time the plan became actionable. Outcome evaluation starts at the first candle after that boundary and never awards a target from the same OHLC bar that first triggered entry. Intraday waiting plans expire after four hours; daily swing entries can remain valid for up to 14 calendar days.

The server owns candle persistence and outcome evaluation. Browser clients cannot submit outcome candles. Older strategy versions remain in SQLite but are excluded from adaptive statistics.

Challengers remain in shadow mode and cannot alter production scores. A challenger needs at least 120 resolved holdout trades, positive net expectancy, profit factor of at least 1.10, controlled drawdown, sufficient champion coverage, stable positive folds, and at least +0.03R improvement over the champion before it becomes eligible for manual review. Automatic promotion is disabled. The execution review stores actual fill, quantity, exit, realized R, notes, and an optional chart snapshot. Pattern projections maintain a separate outcome sample and remain descriptive until validated.

The journal path defaults to:

```text
app/data/trader_journal.sqlite3
```

Set `JOURNAL_DB_PATH` to keep it elsewhere. Database, WAL, and SHM files are excluded from Git and Docker builds.

## Server Feed

One background worker per symbol polls Yahoo, caches the latest candle for every browser, repairs intraday history every five minutes, evaluates plan outcomes, and applies exponential backoff after provider failures. SSE updates the selected chart without browser refresh; polling remains a watchdog.

The Graph Refresh control manually synchronizes the latest candle, intraday history, native five-minute history, daily history, and server recommendations, then redraws the selected chart without reloading the page or resetting chart controls.

Yahoo source and retained horizons:

- 1m: five-day source window, with the newest 2,500 bars retained for the browser
- 5m: native 60-day source window, refreshed every 15 minutes and accumulated up to 50,000 bars
- 1D: native ten-year source window, up to 3,000 bars, refreshed at most every six hours

Health endpoints:

- `GET /health`
- `GET /ready`

The server creates an integrity-checked SQLite backup every 24 hours by default and retains 14 copies. Server-side lifecycle alerts can be sent through a webhook or Telegram while the browser is closed. Prometheus tracks provider health, incidents, backup integrity, and notification failures; Grafana displays those metrics and Loki container logs.

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

For a single-user GCP deployment, use the Compute Engine profile in [`deploy/gcp/README.md`](../deploy/gcp/README.md). It adds Caddy for automatic HTTPS while keeping the application container private behind the reverse proxy. Do not deploy the current SQLite and background-worker design to multiple replicas or a stateless Cloud Run service.

## Verification

```bash
node app/test_market_core.js
node app/test_pattern_engine.js
python3 -m unittest discover -s app -p 'test_*.py'
node --check app/app.js
node --check app/pattern-engine.js
python3 -m py_compile app/server.py app/strategy_engine.py app/backtest_engine.py app/shadow_engine.py app/shadow_candidate_engine.py app/context_router.py app/learning_engine.py app/ibkr_provider.py
```

This tool is educational decision support, not financial advice. It does not guarantee outcomes.
