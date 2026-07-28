const Core = window.MarketCore;
const Patterns = window.PatternEngine;
const SUPPORTED_SYMBOLS = new Set(["QQQ", "SPY", "BTC-USD"]);
const requestedSymbol = new URLSearchParams(window.location.search).get("symbol")?.toUpperCase();
const API_SYMBOL = SUPPORTED_SYMBOLS.has(requestedSymbol) ? requestedSymbol : "QQQ";
const ASSET_OPTIONS = { continuous: API_SYMBOL === "BTC-USD" };
const SETTINGS_KEY = `trader-helper-settings:${API_SYMBOL}`;
const STRATEGY_VERSION = "5.2.0";
const ALERT_TIMEFRAMES = [1, 5, 15, 1440];
const DAILY_TIMEFRAME = 1440;
const OPTIONS_ALERT_STORAGE_KEY = `trader-helper-options-alert:${API_SYMBOL}`;

const state = {
  candles: [],
  fiveMinuteCandles: [],
  dailyCandles: [],
  alerts: [],
  lastAlertsByTimeframe: {},
  feedMode: "loading",
  providerLabel: "Starting",
  providerErrors: 0,
  providerMessage: "",
  lastTickAt: null,
  lastStreamAt: null,
  marketCandleAt: null,
  dataQualityIssues: [],
  localDataQualityIssues: [],
  dataHealth: null,
  selectedTimeframe: 1,
  settings: {
    activeTradeThreshold: 62,
    alertLogThreshold: 72,
    alertCooldownMinutes: 15,
    pollIntervalMs: 15000,
    mode: "normal",
    sessionMode: ASSET_OPTIONS.continuous ? "extended" : "regular",
    chartLayers: { movingAverages: true, vwap: true, levels: true, markers: true, volume: true, rsi: true, patterns: false },
    modes: {
      scalp: { scoreOffset: -6, targetScale: 0.82 },
      normal: { scoreOffset: 0, targetScale: 1 },
      strict: { scoreOffset: 8, targetScale: 1.08 },
    },
  },
  lastStatsAt: 0,
  activePlanIds: {},
  lastJournalKeys: {},
  timeframeAnalyses: {},
  bestOpportunityTimeframe: null,
  bestSwingTimeframe: null,
  serverOwnsSignals: false,
  analysisEngine: "unavailable",
  serverRecommendations: null,
  optionsOpportunity: null,
  lastOptionsAlertKey: "",
  journalRecent: [],
  journalStats: null,
  replayStats: null,
  fearGreed: null,
  sentimentTimer: null,
  stream: null,
  pollTimer: null,
  pollIntervalMs: 15000,
  latestRequestPending: false,
  historySyncTimer: null,
  historySyncPending: false,
  graphRefreshPending: false,
  notifyEnabled: false,
  currentPattern: null,
  currentPatternKey: "",
  patternHitZones: [],
  patternProjectionVisible: false,
  chartGeometry: null,
  chartHover: null,
  chartViews: {},
  chartDrag: null,
  chartInteractionFrame: null,
  suppressChartClick: false,
};

const els = {
  canvas: document.getElementById("priceChart"),
  chartOverlay: document.getElementById("chartOverlay"),
  clock: document.getElementById("clock"),
  sessionState: document.getElementById("sessionState"),
  brandEyebrow: document.getElementById("brandEyebrow"),
  chartSymbol: document.getElementById("chartSymbol"),
  assetButtons: [...document.querySelectorAll(".asset-button")],
  lastPrice: document.getElementById("lastPrice"),
  priceChange: document.getElementById("priceChange"),
  graphRefreshButton: document.getElementById("graphRefreshButton"),
  panOlderButton: document.getElementById("panOlderButton"),
  panNewerButton: document.getElementById("panNewerButton"),
  zoomOutButton: document.getElementById("zoomOutButton"),
  zoomInButton: document.getElementById("zoomInButton"),
  liveViewButton: document.getElementById("liveViewButton"),
  chartWindowLabel: document.getElementById("chartWindowLabel"),
  patternsToggle: document.getElementById("patternsToggle"),
  notifyButton: document.getElementById("notifyButton"),
  timeframeButtons: [...document.querySelectorAll(".timeframe-button")],
  layerMAs: document.getElementById("layerMAs"),
  layerVwap: document.getElementById("layerVwap"),
  vwapLayerControl: document.getElementById("vwapLayerControl"),
  vwapLayerLabel: document.getElementById("vwapLayerLabel"),
  layerLevels: document.getElementById("layerLevels"),
  layerMarkers: document.getElementById("layerMarkers"),
  layerVolume: document.getElementById("layerVolume"),
  layerRsi: document.getElementById("layerRsi"),
  tradeMode: document.getElementById("tradeMode"),
  sessionMode: document.getElementById("sessionMode"),
  providerHealthBadge: document.getElementById("providerHealthBadge"),
  providerSource: document.getElementById("providerSource"),
  providerLastTick: document.getElementById("providerLastTick"),
  providerErrors: document.getElementById("providerErrors"),
  marketStatus: document.getElementById("marketStatus"),
  signalBarState: document.getElementById("signalBarState"),
  dataQuality: document.getElementById("dataQuality"),
  tradePermission: document.getElementById("tradePermission"),
  barContinuity: document.getElementById("barContinuity"),
  trendBadge: document.getElementById("trendBadge"),
  trend1m: document.getElementById("trend1m"),
  trend5m: document.getElementById("trend5m"),
  trend15m: document.getElementById("trend15m"),
  generalTrendBadge: document.getElementById("generalTrendBadge"),
  generalTrend1m: document.getElementById("generalTrend1m"),
  generalTrend5m: document.getElementById("generalTrend5m"),
  generalTrend15m: document.getElementById("generalTrend15m"),
  generalTrend1d: document.getElementById("generalTrend1d"),
  regimeBadge: document.getElementById("regimeBadge"),
  regimeDetail: document.getElementById("regimeDetail"),
  marketConfirmationTile: document.getElementById("marketConfirmationTile"),
  marketConfirmationBadge: document.getElementById("marketConfirmationBadge"),
  marketRelativeStrength: document.getElementById("marketRelativeStrength"),
  marketSpyTrend: document.getElementById("marketSpyTrend"),
  marketConfirmationScore: document.getElementById("marketConfirmationScore"),
  marketConfirmationDetail: document.getElementById("marketConfirmationDetail"),
  biasBadge: document.getElementById("biasBadge"),
  biasFill: document.getElementById("biasFill"),
  biasScore: document.getElementById("biasScore"),
  fearGreedBadge: document.getElementById("fearGreedBadge"),
  fearGreedTitle: document.getElementById("fearGreedTitle"),
  fearGreedScore: document.getElementById("fearGreedScore"),
  fearGreedRating: document.getElementById("fearGreedRating"),
  fearGreedMarker: document.getElementById("fearGreedMarker"),
  fearGreedPreviousClose: document.getElementById("fearGreedPreviousClose"),
  fearGreedPreviousWeek: document.getElementById("fearGreedPreviousWeek"),
  fearGreedPreviousMonth: document.getElementById("fearGreedPreviousMonth"),
  fearGreedPreviousYear: document.getElementById("fearGreedPreviousYear"),
  fearGreedUpdated: document.getElementById("fearGreedUpdated"),
  bestOpportunityBadge: document.getElementById("bestOpportunityBadge"),
  bestOpportunityDetail: document.getElementById("bestOpportunityDetail"),
  bestOpportunityView: document.getElementById("bestOpportunityView"),
  bestSwingBadge: document.getElementById("bestSwingBadge"),
  bestSwingScore: document.getElementById("bestSwingScore"),
  bestSwingDetail: document.getElementById("bestSwingDetail"),
  bestSwingRationale: document.getElementById("bestSwingRationale"),
  bestSwingEntryLabel: document.getElementById("bestSwingEntryLabel"),
  bestSwingEntry: document.getElementById("bestSwingEntry"),
  bestSwingStopLabel: document.getElementById("bestSwingStopLabel"),
  bestSwingStop: document.getElementById("bestSwingStop"),
  bestSwingTarget1Label: document.getElementById("bestSwingTarget1Label"),
  bestSwingTarget1: document.getElementById("bestSwingTarget1"),
  bestSwingTarget2Label: document.getElementById("bestSwingTarget2Label"),
  bestSwingTarget2: document.getElementById("bestSwingTarget2"),
  bestSwingView: document.getElementById("bestSwingView"),
  optionsOpportunity: document.getElementById("optionsOpportunity"),
  optionsEyebrow: document.getElementById("optionsEyebrow"),
  optionsOpportunityTitle: document.getElementById("optionsOpportunityTitle"),
  optionsBadge: document.getElementById("optionsBadge"),
  optionsDataStatus: document.getElementById("optionsDataStatus"),
  optionsScore: document.getElementById("optionsScore"),
  optionsDetail: document.getElementById("optionsDetail"),
  optionsProjection: document.getElementById("optionsProjection"),
  optionsContract: document.getElementById("optionsContract"),
  optionsExpiration: document.getElementById("optionsExpiration"),
  optionsDelta: document.getElementById("optionsDelta"),
  optionsCost: document.getElementById("optionsCost"),
  optionsEntry: document.getElementById("optionsEntry"),
  optionsEntryLabel: document.getElementById("optionsEntryLabel"),
  optionsStop: document.getElementById("optionsStop"),
  optionsStopLabel: document.getElementById("optionsStopLabel"),
  optionsTargets: document.getElementById("optionsTargets"),
  optionsTargetsLabel: document.getElementById("optionsTargetsLabel"),
  confidenceScore: document.getElementById("confidenceScore"),
  calibrationBadge: document.getElementById("calibrationBadge"),
  calibrationProbability: document.getElementById("calibrationProbability"),
  calibrationExpectedR: document.getElementById("calibrationExpectedR"),
  calibrationSamples: document.getElementById("calibrationSamples"),
  calibrationRange: document.getElementById("calibrationRange"),
  calibrationExcursion: document.getElementById("calibrationExcursion"),
  calibrationHoldingTime: document.getElementById("calibrationHoldingTime"),
  calibrationScope: document.getElementById("calibrationScope"),
  activeAlert: document.getElementById("activeAlert"),
  riskReward: document.getElementById("riskReward"),
  entryLevel: document.getElementById("entryLevel"),
  stopLevel: document.getElementById("stopLevel"),
  targetLevel: document.getElementById("targetLevel"),
  target2Level: document.getElementById("target2Level"),
  exitWarning: document.getElementById("exitWarning"),
  lifecycleBadge: document.getElementById("lifecycleBadge"),
  lifecycleDetail: document.getElementById("lifecycleDetail"),
  bestSideBadge: document.getElementById("bestSideBadge"),
  whyRejected: document.getElementById("whyRejected"),
  vwapMetric: document.getElementById("vwapMetric"),
  smaMetric: document.getElementById("smaMetric"),
  emaMetric: document.getElementById("emaMetric"),
  rsiMetric: document.getElementById("rsiMetric"),
  atrMetric: document.getElementById("atrMetric"),
  rvolMetric: document.getElementById("rvolMetric"),
  alertLog: document.getElementById("alertLog"),
  clearLog: document.getElementById("clearLog"),
  journalTotal: document.getElementById("journalTotal"),
  journalTargets: document.getElementById("journalTargets"),
  journalStops: document.getElementById("journalStops"),
  journalOpen: document.getElementById("journalOpen"),
  journalWaiting: document.getElementById("journalWaiting"),
  journalEntered: document.getElementById("journalEntered"),
  journalExpired: document.getElementById("journalExpired"),
  journalWinRate: document.getElementById("journalWinRate"),
  journalExpectancy: document.getElementById("journalExpectancy"),
  journalBestSetup: document.getElementById("journalBestSetup"),
  journalBestTimeframe: document.getElementById("journalBestTimeframe"),
  replayBest: document.getElementById("replayBest"),
  replayAvgTarget: document.getElementById("replayAvgTarget"),
  replayAvgStop: document.getElementById("replayAvgStop"),
  replaySamples: document.getElementById("replaySamples"),
  replayExcursion: document.getElementById("replayExcursion"),
  feedbackTook: document.getElementById("feedbackTook"),
  feedbackSkipped: document.getElementById("feedbackSkipped"),
  feedbackBad: document.getElementById("feedbackBad"),
  journalFilter: document.getElementById("journalFilter"),
  journalRows: document.getElementById("journalRows"),
};

function activeTradeThreshold() {
  const mode = state.settings.modes[state.settings.mode] || state.settings.modes.normal;
  return Number(state.settings.activeTradeThreshold || 62) + Number(mode.scoreOffset || 0);
}

function alertLogThreshold() {
  return Number(state.settings.alertLogThreshold || 72);
}

function fmt(value, digits = 2) {
  if (!Number.isFinite(value)) return "--";
  return value.toFixed(digits);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function fmtDuration(ms) {
  if (!Number.isFinite(ms) || ms <= 0) return "--";
  const minutes = Math.round(ms / 60_000);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours}h ${rest}m` : `${hours}h`;
}

function rowWinRate(row) {
  const winners = Number(row?.winners || 0);
  const stopped = Number(row?.stopped || 0);
  const closed = winners + stopped;
  return closed ? winners / closed : null;
}

function mergeDeep(base, override) {
  const output = { ...base };
  Object.entries(override || {}).forEach(([key, value]) => {
    output[key] = value && typeof value === "object" && !Array.isArray(value)
      ? mergeDeep(output[key] || {}, value)
      : value;
  });
  return output;
}

async function loadSettings() {
  try {
    const response = await fetch(`./settings.json?t=${Date.now()}`);
    if (response.ok) {
      state.settings = mergeDeep(state.settings, await response.json());
    }
  } catch (error) {
    console.info("Settings file unavailable.", error);
  }

  try {
    const legacy = API_SYMBOL === "QQQ" ? localStorage.getItem("qqq-helper-settings") : null;
    const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY) || legacy || "{}");
    state.settings = mergeDeep(state.settings, saved);
  } catch {
    localStorage.removeItem(SETTINGS_KEY);
  }

  if (ASSET_OPTIONS.continuous) state.settings.sessionMode = "extended";

  syncSettingsControls();
}

function saveSettings() {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify({
    mode: state.settings.mode,
    sessionMode: state.settings.sessionMode,
    chartLayers: state.settings.chartLayers,
  }));
}

function syncSettingsControls() {
  els.tradeMode.value = state.settings.mode;
  els.sessionMode.value = state.settings.sessionMode || "regular";
  els.sessionMode.disabled = ASSET_OPTIONS.continuous;
  els.sessionMode.closest("label").title = ASSET_OPTIONS.continuous ? "Bitcoin trades continuously, 24 hours a day" : "Choose regular or extended equity sessions";
  els.layerMAs.checked = Boolean(state.settings.chartLayers.movingAverages);
  syncVwapControl();
  els.layerLevels.checked = Boolean(state.settings.chartLayers.levels);
  els.layerMarkers.checked = Boolean(state.settings.chartLayers.markers);
  els.layerVolume.checked = Boolean(state.settings.chartLayers.volume);
  els.layerRsi.checked = Boolean(state.settings.chartLayers.rsi);
  els.patternsToggle.classList.toggle("active", Boolean(state.settings.chartLayers.patterns));
}

function syncVwapControl() {
  const daily = isDailyTimeframe();
  els.layerVwap.disabled = daily;
  els.layerVwap.checked = daily ? false : Boolean(state.settings.chartLayers.vwap);
  els.vwapLayerLabel.textContent = daily ? "VWAP (intraday only)" : "VWAP";
  els.vwapLayerControl.title = daily
    ? "Session VWAP is unavailable for daily candles"
    : "Toggle session VWAP";
}

function renderProviderHealth() {
  const dataHealth = state.dataHealth;
  const marketAgeMs = state.marketCandleAt ? Date.now() - state.marketCandleAt : null;
  const refreshAgeMs = state.lastTickAt ? Date.now() - state.lastTickAt : null;
  const session = Core.marketSession(Date.now(), ASSET_OPTIONS);
  const marketOpen = session.regular;
  const stale = state.feedMode === "real" && marketOpen && (marketAgeMs === null || marketAgeMs > 4 * 60_000);
  const healthy = state.feedMode === "real" && !stale && state.providerErrors === 0 && dataHealth?.status !== "Blocked";
  els.providerHealthBadge.textContent = dataHealth?.status || (stale ? "Stale" : healthy ? (marketOpen ? "Live" : "Connected") : state.feedMode === "real" ? "Issue" : "Demo");
  setTone(els.providerHealthBadge, dataHealth?.tone || (healthy ? "positive" : stale || state.providerErrors ? "negative" : "neutral"));
  els.providerSource.textContent = state.providerLabel;
  const refreshAge = refreshAgeMs === null ? "--" : `${Math.max(0, Math.round(refreshAgeMs / 1000))}s refresh`;
  const candleAge = marketAgeMs === null ? "--" : `${Math.max(0, Math.round(marketAgeMs / 1000))}s candle`;
  els.providerLastTick.textContent = `${refreshAge} / ${candleAge}`;
  els.providerErrors.textContent = state.providerErrors;
  els.sessionState.title = state.providerMessage || "";
  els.marketStatus.textContent = ASSET_OPTIONS.continuous
    ? "24/7 market"
    : marketOpen
    ? "Regular open"
    : session.phase === "premarket"
      ? "Premarket"
      : session.phase === "closed"
        ? "Closed"
        : "After hours";
  const latestSignalBar = selectedCandles(true).at(-1);
  const latestMarketBar = selectedCandles(false).at(-1);
  els.signalBarState.textContent = latestSignalBar && latestMarketBar && latestSignalBar.time === latestMarketBar.time
    ? "Closed"
    : "Forming excluded";
  const blockers = dataHealth?.blockers || [];
  const warnings = dataHealth?.warnings || [];
  const qualityDetail = blockers.length ? blockers.join(", ") : warnings.length ? warnings.join(", ") : state.dataQualityIssues.length ? state.dataQualityIssues.join(", ") : "Clean";
  els.dataQuality.textContent = qualityDetail;
  setTone(els.dataQuality, blockers.length || state.dataQualityIssues.length ? "negative" : warnings.length ? "neutral" : "positive");
  const tradeAllowed = dataHealth?.tradeAllowed;
  els.tradePermission.textContent = tradeAllowed === false ? "Blocked" : marketOpen || ASSET_OPTIONS.continuous ? "Allowed" : "Session closed";
  setTone(els.tradePermission, tradeAllowed === false ? "negative" : marketOpen || ASSET_OPTIONS.continuous ? "positive" : "neutral");
  const timeframes = dataHealth?.timeframes || {};
  const continuity = ["1", "5", "15"].map((timeframe) => timeframes[timeframe]).filter(Boolean);
  const gaps = continuity.reduce((total, item) => total + Number(item.gaps || 0), 0);
  els.barContinuity.textContent = continuity.length ? gaps ? `${gaps} gap${gaps === 1 ? "" : "s"}` : "Clean" : "Building";
  setTone(els.barContinuity, gaps ? "negative" : continuity.length ? "positive" : "neutral");
}

function renderFearGreed(data) {
  const score = Number(data?.score);
  const priorValue = (value) => {
    if (value === null || value === undefined || value === "") return "--";
    const numeric = Number(value);
    return Number.isFinite(numeric) ? fmt(numeric, 0) : "--";
  };
  if (!Number.isFinite(score)) {
    els.fearGreedBadge.textContent = "Unavailable";
    setTone(els.fearGreedBadge, "negative");
    els.fearGreedScore.textContent = "--";
    els.fearGreedRating.textContent = "CNN data unavailable";
    els.fearGreedMarker.hidden = true;
    els.fearGreedPreviousClose.textContent = "--";
    els.fearGreedPreviousWeek.textContent = "--";
    els.fearGreedPreviousMonth.textContent = "--";
    els.fearGreedPreviousYear.textContent = "--";
    els.fearGreedUpdated.textContent = "Retrying automatically";
    return;
  }
  const rating = String(data.rating || "Neutral");
  const tone = score < 45 ? "negative" : score > 55 ? "positive" : "neutral";
  els.fearGreedBadge.textContent = data.stale ? `${rating} stale` : rating;
  setTone(els.fearGreedBadge, data.stale ? "neutral" : tone);
  els.fearGreedScore.textContent = fmt(score, 0);
  els.fearGreedRating.textContent = rating;
  els.fearGreedMarker.hidden = false;
  els.fearGreedMarker.style.left = `${clamp(score, 0, 100)}%`;
  els.fearGreedPreviousClose.textContent = priorValue(data.previousClose);
  els.fearGreedPreviousWeek.textContent = priorValue(data.previousWeek);
  els.fearGreedPreviousMonth.textContent = priorValue(data.previousMonth);
  els.fearGreedPreviousYear.textContent = priorValue(data.previousYear);
  const timestamp = Date.parse(data.timestamp || "");
  const updated = Number.isFinite(timestamp)
    ? new Date(timestamp).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
    : "time unavailable";
  els.fearGreedUpdated.textContent = `${data.stale ? "Stale" : "Updated"} ${updated}`;
}

async function fetchFearGreed() {
  try {
    const response = await fetch(`/api/sentiment/fear-greed?t=${Date.now()}`);
    if (!response.ok) throw new Error(`sentiment failed: ${response.status}`);
    state.fearGreed = await response.json();
    renderFearGreed(state.fearGreed);
  } catch (error) {
    console.info("CNN Fear & Greed unavailable.", error);
    if (!state.fearGreed) renderFearGreed(null);
  }
}

function updateClock() {
  const now = new Date();
  els.clock.textContent = now.toLocaleTimeString([], { hour12: false });
  renderProviderHealth();
}

function normalizeIncomingCandle(candle) {
  return Core.normalizeCandle(candle);
}

function cleanCandles(candles) {
  return Core.mergeCandles(candles);
}

function mergeCandle(candle) {
  const incoming = normalizeIncomingCandle(candle);
  if (!incoming) return;
  state.candles = Core.mergeCandle(state.candles, incoming, 2500);
  state.marketCandleAt = incoming.time;
  refreshCurrentDailyCandle();
  assessDataQuality();
  refresh();
}

function assessDataQuality() {
  const closed = Core.todayCandles(state.candles, undefined, ASSET_OPTIONS).filter((candle) => Core.isCandleClosed(candle));
  const regular = closed.filter((candle) => Core.marketSession(candle.time, ASSET_OPTIONS).regular);
  const recentRegular = regular.slice(-45);
  let gaps = 0;
  const gapLimit = ASSET_OPTIONS.continuous ? 3 * 60_000 : 90_000;
  for (let index = 1; index < recentRegular.length; index += 1) {
    if (recentRegular[index].time - recentRegular[index - 1].time > gapLimit) gaps += 1;
  }
  const issues = [];
  if (gaps >= (ASSET_OPTIONS.continuous ? 2 : 1)) issues.push(`${gaps} gap${gaps === 1 ? "" : "s"}`);
  if (!ASSET_OPTIONS.continuous && regular.slice(-5).some((candle) => candle.volume <= 0)) issues.push("zero volume");
  state.localDataQualityIssues = issues;
  state.dataQualityIssues = [...new Set([
    ...issues,
    ...(state.dataHealth?.blockers || []),
  ])];
}

function applyDataHealth(dataHealth) {
  if (!dataHealth || typeof dataHealth !== "object") return;
  state.dataHealth = dataHealth;
  assessDataQuality();
}

function calculateIndicators(candles) {
  return Core.calculateIndicators(candles, ASSET_OPTIONS);
}

function resample(candles, minutes) {
  if (isDailyTimeframe(minutes)) return Core.resampleDaily(candles, ASSET_OPTIONS);
  return Core.resample(candles, minutes);
}

function selectedCandles(closedOnly = false) {
  const candles = isDailyTimeframe()
    ? (state.dailyCandles.length ? state.dailyCandles : Core.resampleDaily(state.candles, ASSET_OPTIONS))
    : state.selectedTimeframe === 1
      ? state.candles
      : state.selectedTimeframe === 5 && state.fiveMinuteCandles.length
        ? state.fiveMinuteCandles
        : resample(state.fiveMinuteCandles.length ? state.fiveMinuteCandles : state.candles, state.selectedTimeframe);
  return closedOnly
    ? candles.filter((candle) => candleClosedForTimeframe(candle, state.selectedTimeframe))
    : candles;
}

function visibleJournalPlans(visible) {
  if (!state.journalRecent.length || !visible.length) return [];
  const firstTime = visible[0].time;
  const lastTime = visible[visible.length - 1].time + state.selectedTimeframe * 60_000;

  return state.journalRecent
    .filter((plan) => {
      const createdAt = Number(plan.created_at);
      return Number(plan.timeframe) === state.selectedTimeframe
        && Number.isFinite(createdAt)
        && createdAt >= firstTime
        && createdAt <= lastTime;
    })
    .sort((a, b) => Number(a.created_at) - Number(b.created_at));
}

function todayCandles(candles) {
  return Core.todayCandles(candles, undefined, ASSET_OPTIONS);
}

function trendCandles(minutes) {
  const source = minutes === 1 || !state.fiveMinuteCandles.length ? state.candles : state.fiveMinuteCandles;
  const sourceTimeframe = minutes === 1 || !state.fiveMinuteCandles.length ? 1 : 5;
  const closed = source.filter((candle) => Core.isCandleClosed(candle, sourceTimeframe));
  const base = todayCandles(closed);
  if (minutes === sourceTimeframe) return base;
  return resample(base, minutes).filter((candle) => Core.isCandleClosed(candle, minutes));
}

function timeframeLabel(minutes = state.selectedTimeframe) {
  return isDailyTimeframe(minutes) ? "1D" : `${minutes}m`;
}

function isDailyTimeframe(minutes = state.selectedTimeframe) {
  return Number(minutes) === DAILY_TIMEFRAME;
}

function defaultChartCount(timeframe = state.selectedTimeframe) {
  if (Number(timeframe) === DAILY_TIMEFRAME) return 120;
  return Number(timeframe) === 1 ? 120 : 96;
}

function chartWindowOptions(total, timeframe = state.selectedTimeframe) {
  return {
    minCount: Math.min(24, total),
    maxCount: Math.min(600, total),
    defaultCount: defaultChartCount(timeframe),
    maxFutureRatio: 0.5,
  };
}

function endIndexAtTime(candles, endTime) {
  if (!Number.isFinite(endTime)) return candles.length;
  let low = 0;
  let high = candles.length;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (candles[middle].time <= endTime) low = middle + 1;
    else high = middle;
  }
  return low;
}

function resolveChartWindow(candles, timeframe = state.selectedTimeframe) {
  const view = state.chartViews[timeframe] || {};
  const futureBars = Math.max(0, Math.round(Number(view.futureBars) || 0));
  const requestedEnd = futureBars
    ? candles.length + futureBars
    : view.endTime === null || view.endTime === undefined
      ? candles.length
      : endIndexAtTime(candles, Number(view.endTime));
  return Core.normalizeChartWindow(
    candles.length,
    view.count,
    requestedEnd,
    chartWindowOptions(candles.length, timeframe),
  );
}

function saveChartWindow(windowState, sourceTimes, timeframe = state.selectedTimeframe) {
  const futureBars = Math.max(0, windowState.end - windowState.total);
  const endTime = windowState.live || !windowState.end
    ? null
    : sourceTimes[Math.min(windowState.total, windowState.end) - 1];
  state.chartViews[timeframe] = { count: windowState.count, endTime, futureBars };
}

function updateChartWindowControls(windowState = state.chartGeometry) {
  if (!windowState || !windowState.visibleCount) {
    els.chartWindowLabel.textContent = "Loading";
    els.liveViewButton.classList.remove("active");
    els.liveViewButton.disabled = true;
    els.zoomInButton.disabled = true;
    els.zoomOutButton.disabled = true;
    els.panOlderButton.disabled = true;
    els.panNewerButton.disabled = true;
    els.chartOverlay.classList.remove("panning", "dragging");
    return;
  }
  const futureBars = Math.max(0, windowState.endIndex - windowState.totalCount);
  const maxFutureBars = Math.floor(windowState.visibleCount * 0.5);
  const exactLiveView = windowState.live
    && futureBars === 0
    && windowState.visibleCount === Math.min(windowState.totalCount, defaultChartCount());
  els.chartWindowLabel.textContent = futureBars
    ? `${windowState.actualVisibleCount} bars + space`
    : `${windowState.visibleCount} bars | ${windowState.live ? "Live" : "History"}`;
  els.liveViewButton.classList.toggle("active", exactLiveView);
  els.liveViewButton.disabled = exactLiveView;
  els.zoomInButton.disabled = windowState.visibleCount <= Math.min(24, windowState.totalCount);
  els.zoomOutButton.disabled = windowState.visibleCount >= Math.min(600, windowState.totalCount);
  els.panOlderButton.disabled = windowState.startIndex <= 0;
  els.panNewerButton.disabled = futureBars >= maxFutureBars;
  els.chartOverlay.classList.toggle("panning", windowState.startIndex > 0 || futureBars < maxFutureBars);
}

function resetChartView() {
  delete state.chartViews[state.selectedTimeframe];
  state.chartHover = null;
  refresh();
}

function applyChartWindow(windowState, geometry = state.chartGeometry) {
  if (!geometry?.sourceTimes?.length) return;
  saveChartWindow(windowState, geometry.sourceTimes);
  state.chartHover = null;
  refresh();
}

function zoomChart(factor, anchorRatio) {
  const geometry = state.chartGeometry;
  if (!geometry?.visibleCount) return;
  const ratio = Number.isFinite(anchorRatio) ? anchorRatio : geometry.live ? 1 : 0.5;
  const next = Core.zoomChartWindow(
    { total: geometry.totalCount, count: geometry.visibleCount, end: geometry.endIndex },
    factor,
    ratio,
    chartWindowOptions(geometry.totalCount),
  );
  if (next.count === geometry.visibleCount && next.end === geometry.endIndex) return;
  applyChartWindow(next, geometry);
}

function panChart(older) {
  const geometry = state.chartGeometry;
  if (!geometry?.visibleCount) return;
  const bars = Math.max(1, Math.round(geometry.visibleCount * 0.25)) * (older ? 1 : -1);
  const next = Core.panChartWindow(
    { total: geometry.totalCount, count: geometry.visibleCount, end: geometry.endIndex },
    bars,
    chartWindowOptions(geometry.totalCount),
  );
  if (next.end === geometry.endIndex) return;
  applyChartWindow(next, geometry);
}

function candleClosedForTimeframe(candle, minutes = state.selectedTimeframe) {
  if (!candle) return false;
  if (!isDailyTimeframe(minutes)) return Core.isCandleClosed(candle, minutes);
  const candleDate = candle.sessionDate || Core.marketParts(candle.time, ASSET_OPTIONS).date;
  return candleDate !== Core.marketParts(Date.now(), ASSET_OPTIONS).date;
}

function refreshCurrentDailyCandle() {
  if (!state.candles.length) return;
  const latestSessionDate = Core.marketParts(state.candles.at(-1).time, ASSET_OPTIONS).date;
  const currentSessionDate = Core.marketParts(Date.now(), ASSET_OPTIONS).date;
  if (latestSessionDate !== currentSessionDate) return;
  const regular = Core.todayCandles(state.candles, undefined, ASSET_OPTIONS).filter((candle) => Core.marketSession(candle.time, ASSET_OPTIONS).regular);
  const todayDaily = Core.resampleDaily(regular, ASSET_OPTIONS).at(-1);
  if (!todayDaily) return;
  const existing = state.dailyCandles.filter((candle) => {
    const date = candle.sessionDate || Core.marketParts(candle.time, ASSET_OPTIONS).date;
    return date !== todayDaily.sessionDate;
  });
  state.dailyCandles = Core.resampleDaily([...existing, todayDaily], ASSET_OPTIONS).slice(-520);
}

function percentile(values, pct) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.max(0, Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * pct)));
  return sorted[index];
}

function classifyTrend(indicators) {
  if (indicators.length < 8) return { label: "Building", tone: "neutral" };
  const latest = indicators[indicators.length - 1];
  const prior = indicators[indicators.length - Math.min(6, indicators.length - 1)] || indicators[0];
  const fast = latest.ema20 || latest.ema21;
  const mid = latest.ema50;
  const priorFast = prior.ema20 || prior.ema21;
  const slope = fast - priorFast;
  const aboveVwap = latest.close > latest.vwap;
  const belowVwap = latest.close < latest.vwap;
  let score = 0;

  if (latest.close > fast) score += 1;
  if (latest.close < fast) score -= 1;
  if (latest.close > mid) score += 1;
  if (latest.close < mid) score -= 1;
  if (aboveVwap) score += 1;
  if (belowVwap) score -= 1;
  if (slope > 0) score += 1;
  if (slope < 0) score -= 1;
  if (latest.rsi >= 55) score += 1;
  if (latest.rsi <= 45) score -= 1;
  if (latest.close > prior.close) score += 1;
  if (latest.close < prior.close) score -= 1;

  if (score >= 4) return { label: "Strong up", tone: "positive" };
  if (score >= 2) return { label: "Weak up", tone: "positive" };
  if (score <= -4) return { label: "Strong down", tone: "negative" };
  if (score <= -2) return { label: "Weak down", tone: "negative" };
  return { label: "Range", tone: "neutral" };
}

function classifyMomentum(indicators) {
  if (indicators.length < 10) return { label: "Sideways", tone: "neutral", score: 0 };
  const latest = indicators[indicators.length - 1];
  const prior = indicators[indicators.length - Math.min(8, indicators.length - 1)] || indicators[0];
  const ema20 = latest.ema20 || latest.ema21;
  const priorEma20 = prior.ema20 || prior.ema21 || ema20;
  let score = 0;

  if (latest.close > ema20) score += 1;
  if (latest.close < ema20) score -= 1;
  if (latest.close > latest.ema50) score += 1;
  if (latest.close < latest.ema50) score -= 1;
  if (latest.close > latest.vwap) score += 1;
  if (latest.close < latest.vwap) score -= 1;
  if (latest.rsi >= 55) score += 1;
  if (latest.rsi <= 45) score -= 1;
  if (ema20 > priorEma20) score += 1;
  if (ema20 < priorEma20) score -= 1;
  if (latest.close > prior.close) score += 1;
  if (latest.close < prior.close) score -= 1;

  if (score >= 2) return { label: "Up", tone: "positive", score };
  if (score <= -2) return { label: "Down", tone: "negative", score };
  return { label: "Sideways", tone: "neutral", score };
}

function classifyDailyMomentum(indicators) {
  if (indicators.length < 21) return { label: "Building", tone: "neutral", score: 0 };
  const latest = indicators.at(-1);
  const prior = indicators.at(-6);
  const ema20 = latest.ema20 || latest.ema21;
  const priorEma20 = prior.ema20 || prior.ema21;
  let score = 0;

  if (latest.close > ema20) score += 1;
  if (latest.close < ema20) score -= 1;
  if (ema20 > latest.ema50) score += 1;
  if (ema20 < latest.ema50) score -= 1;
  if (latest.close > prior.close) score += 1;
  if (latest.close < prior.close) score -= 1;
  if (ema20 > priorEma20) score += 1;
  if (ema20 < priorEma20) score -= 1;
  if (latest.rsi >= 55) score += 1;
  if (latest.rsi <= 45) score -= 1;

  if (score >= 2) return { label: "Up", tone: "positive", score };
  if (score <= -2) return { label: "Down", tone: "negative", score };
  return { label: "Sideways", tone: "neutral", score };
}

function buildGeneralTrend() {
  const one = classifyMomentum(calculateIndicators(trendCandles(1)));
  const five = classifyMomentum(calculateIndicators(trendCandles(5)));
  const fifteen = classifyMomentum(calculateIndicators(trendCandles(15)));
  const dailyCandles = state.dailyCandles.filter((candle) => candleClosedForTimeframe(candle, DAILY_TIMEFRAME));
  const daily = classifyDailyMomentum(calculateIndicators(dailyCandles));
  const total = one.score + five.score + fifteen.score;
  const overall = total >= 3
    ? { label: "Up", tone: "positive" }
    : total <= -3
      ? { label: "Down", tone: "negative" }
      : { label: "Mixed", tone: "neutral" };

  return { one, five, fifteen, daily, overall };
}

function classifyMarketRegime(indicators) {
  if (indicators.length < 30) {
    return { label: "Building", tone: "neutral", type: "building", detail: "Waiting for enough current-session candles" };
  }

  const latest = indicators[indicators.length - 1];
  const recent = indicators.slice(-30);
  const prior = indicators[indicators.length - Math.min(18, indicators.length - 1)] || indicators[0];
  const high = Math.max(...recent.map((candle) => candle.high));
  const low = Math.min(...recent.map((candle) => candle.low));
  const range = high - low;
  const avgAtr = recent.reduce((sum, candle) => sum + candle.atr, 0) / recent.length;
  const atrExpansion = avgAtr > 0 ? latest.atr / avgAtr : 1;
  const trendScore = (latest.ema20 > latest.ema50 ? 1 : -1)
    + (latest.close > latest.vwap ? 1 : -1)
    + (latest.close > prior.close ? 1 : -1)
    + (latest.ema20 > prior.ema20 ? 1 : -1);
  const rangeAtr = avgAtr > 0 ? range / avgAtr : 0;

  if (atrExpansion > 1.45 && Math.abs(trendScore) <= 1) {
    return { label: "Chop", tone: "neutral", type: "chop", detail: `High volatility without clean direction (${fmt(rangeAtr, 1)} ATR range)` };
  }
  if (trendScore >= 3 && rangeAtr >= 3) {
    return { label: "Trend Up", tone: "positive", type: "trend_up", detail: "Current session has upside alignment across EMA, VWAP, and price slope" };
  }
  if (trendScore <= -3 && rangeAtr >= 3) {
    return { label: "Trend Down", tone: "negative", type: "trend_down", detail: "Current session has downside alignment across EMA, VWAP, and price slope" };
  }
  if (rangeAtr < 2.2) {
    return { label: "Range", tone: "neutral", type: "range", detail: "Price is compressed versus current ATR; prefer fades or wait for expansion" };
  }
  return { label: "Mixed", tone: "neutral", type: "mixed", detail: "Momentum is not fully aligned; require cleaner confirmation" };
}

function recentLevels(candles, lookback = 35) {
  const recent = candles.slice(-lookback);
  const prior = recent.slice(0, -1);
  const highs = prior.map((c) => c.high).filter(Number.isFinite);
  const lows = prior.map((c) => c.low).filter(Number.isFinite);
  const resistance = Math.max(...highs);
  const support = Math.min(...lows);
  const latest = candles[candles.length - 1];
  const tolerance = latest?.atr ? latest.atr * 0.35 : 0.25;
  const resistanceTouches = highs.filter((value) => Math.abs(value - resistance) <= tolerance).length;
  const supportTouches = lows.filter((value) => Math.abs(value - support) <= tolerance).length;

  return {
    resistance,
    support,
    resistanceTouches,
    supportTouches,
  };
}

function sessionLevels() {
  const today = todayCandles(state.candles);
  const regular = today.filter((candle) => {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).formatToParts(new Date(candle.time));
    const total = Number(parts.find((part) => part.type === "hour")?.value || 0) * 60
      + Number(parts.find((part) => part.type === "minute")?.value || 0);
    return total >= 570 && total <= 960;
  });
  const opening = regular.slice(0, 30);
  if (!opening.length) return {};
  return {
    openingHigh: Math.max(...opening.map((candle) => candle.high)),
    openingLow: Math.min(...opening.map((candle) => candle.low)),
    sessionHigh: Math.max(...regular.map((candle) => candle.high)),
    sessionLow: Math.min(...regular.map((candle) => candle.low)),
  };
}

function sessionLevelsForWindow(candles, endIndex, timeframe = state.selectedTimeframe) {
  if (!candles.length || !endIndex) return {};
  const last = candles[endIndex - 1];
  const sessionDate = Core.marketParts(last.time, ASSET_OPTIONS).date;
  const sessionCandles = candles.slice(0, endIndex).filter((candle) => {
    const session = Core.marketSession(candle.time, ASSET_OPTIONS);
    return session.regular && session.date === sessionDate;
  });
  if (!sessionCandles.length) return {};
  const openingCount = Math.max(1, Math.ceil(30 / Math.max(1, Number(timeframe))));
  const opening = sessionCandles.slice(0, openingCount);
  return {
    openingHigh: Math.max(...opening.map((candle) => candle.high)),
    openingLow: Math.min(...opening.map((candle) => candle.low)),
    sessionHigh: Math.max(...sessionCandles.map((candle) => candle.high)),
    sessionLow: Math.min(...sessionCandles.map((candle) => candle.low)),
  };
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function candleShape(candle) {
  const range = Math.max(0.01, candle.high - candle.low);
  const body = Math.abs(candle.close - candle.open);
  const upperWick = candle.high - Math.max(candle.open, candle.close);
  const lowerWick = Math.min(candle.open, candle.close) - candle.low;

  return {
    range,
    body,
    bodyPct: body / range,
    upperWickPct: upperWick / range,
    lowerWickPct: lowerWick / range,
    bullish: candle.close > candle.open,
    bearish: candle.close < candle.open,
  };
}

function crossesAbove(previous, latest, key) {
  return previous.close <= previous[key] && latest.close > latest[key];
}

function crossesBelow(previous, latest, key) {
  return previous.close >= previous[key] && latest.close < latest[key];
}

function pushReason(reasons, condition, points, text) {
  if (!condition) return 0;
  reasons.push(text);
  return points;
}

function intradayBounds() {
  const scale = { scalp: 0.9, normal: 1, strict: 1.1 }[state.settings.mode] || 1;
  const applyScale = (bounds) => ({
    ...bounds,
    target1MinPct: bounds.target1MinPct * scale,
    target1MaxPct: bounds.target1MaxPct * scale,
    target2MaxPct: bounds.target2MaxPct * scale,
  });

  if (state.selectedTimeframe === 1) {
    return applyScale({
      maxRiskAtr: 1.2,
      maxRiskPct: 0.0028,
      target1MinPct: 0.0025,
      target1MaxPct: 0.0038,
      target2MaxPct: 0.0055,
      lookback: 24,
    });
  }
  if (state.selectedTimeframe === 5) {
    return applyScale({
      maxRiskAtr: 1.35,
      maxRiskPct: 0.0035,
      target1MinPct: 0.003,
      target1MaxPct: 0.0045,
      target2MaxPct: 0.0065,
      lookback: 18,
    });
  }
  return applyScale({
    maxRiskAtr: 1.5,
    maxRiskPct: 0.0042,
    target1MinPct: 0.0032,
    target1MaxPct: 0.005,
    target2MaxPct: 0.007,
    lookback: 14,
  });
}

function marketPhase(timestamp = Date.now()) {
  if (Core.marketSession(timestamp, ASSET_OPTIONS).phase === "closed") return "closed";
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date(timestamp));
  const hour = Number(parts.find((part) => part.type === "hour")?.value || 0);
  const minute = Number(parts.find((part) => part.type === "minute")?.value || 0);
  const total = hour * 60 + minute;

  if (total < 570) return "premarket";
  if (total < 585) return "open";
  if (total < 660) return "morning";
  if (total < 780) return "midday";
  if (total < 900) return "afternoon";
  if (total < 960) return "power_hour";
  return "after_hours";
}

function setupType(setup) {
  const value = setup.toLowerCase();
  if (value.includes("momentum")) return "momentum";
  if (value.includes("pullback")) return "ema_pullback";
  if (value.includes("vwap")) return "vwap";
  if (value.includes("breakout")) return "breakout";
  if (value.includes("breakdown")) return "breakdown";
  if (value.includes("reversal")) return "reversal";
  return "other";
}

function adaptiveScoreAdjustment(setupKind, phase, reasons) {
  const stats = state.journalStats;
  if (!stats) return 0;
  let adjustment = 0;

  const applyRow = (row, label, weight = 1) => {
    const winners = Number(row?.winners || 0);
    const stopped = Number(row?.stopped || 0);
    const closed = winners + stopped;
    if (closed < 30) return;
    const priorStrength = 20;
    const posteriorRate = (winners + priorStrength * 0.5) / (closed + priorStrength);
    const delta = clamp(Math.round((posteriorRate - 0.5) * 14 * weight), -4, 4);
    if (!delta) return;
    adjustment += delta;
    reasons.push(`${label} historical adjustment ${delta > 0 ? "+" : ""}${delta}`);
  };

  applyRow((stats.bySetup || []).find((row) => row.setup_type === setupKind), `${setupKind} setup`, 1);
  applyRow((stats.byTimeframe || []).find((row) => Number(row.timeframe) === state.selectedTimeframe), `${timeframeLabel()} timeframe`, 0.8);
  applyRow((stats.byPhase || []).find((row) => row.market_phase === phase), `${phase} phase`, 0.7);

  return clamp(adjustment, -6, 6);
}

function scoreCandidate(candidate, context) {
  const { latest, previous, trend5, trend15, selectedTrend, levels, localLevels, shape, direction, regime, session } = context;
  const long = direction === "long";
  const reasons = [...candidate.reasons];
  let score = candidate.baseScore;
  const phase = marketPhase(latest.time);
  const kind = setupType(candidate.setup);

  score += pushReason(
    reasons,
    selectedTrend.tone === (long ? "positive" : "negative"),
    16,
    `${timeframeLabel()} trend agrees`,
  );
  score += pushReason(
    reasons,
    ["morning", "afternoon", "power_hour"].includes(phase),
    6,
    `Market phase supports intraday follow-through: ${phase}`,
  );
  if (phase === "midday") {
    score -= 6;
    reasons.push("Midday session can be choppy");
  }
  if ((regime.type === "trend_up" && !long) || (regime.type === "trend_down" && long)) {
    score -= 16;
    reasons.push(`Market regime opposes ${direction} setup`);
  }
  if ((regime.type === "range" || regime.type === "chop") && kind === "momentum") {
    score -= 10;
    reasons.push(`${regime.label} regime reduces momentum follow-through quality`);
  }
  if ((kind === "reversal" || kind === "vwap") && (regime.type === "range" || regime.type === "mixed")) {
    score += 5;
    reasons.push(`${regime.label} regime can favor tactical reversion setups`);
  }
  score += pushReason(
    reasons,
    trend5.tone === (long ? "positive" : "negative"),
    12,
    "5m trend confirms",
  );
  score += pushReason(
    reasons,
    trend15.tone === (long ? "positive" : "negative"),
    12,
    "15m trend confirms",
  );
  score += pushReason(
    reasons,
    long ? latest.ema20 > latest.ema50 : latest.ema20 < latest.ema50,
    12,
    "EMA 20/50 structure agrees",
  );
  score += pushReason(
    reasons,
    long ? latest.sma20 > latest.sma50 : latest.sma20 < latest.sma50,
    8,
    "SMA 20/50 structure agrees",
  );
  score += pushReason(
    reasons,
    long ? latest.close > latest.vwap : latest.close < latest.vwap,
    8,
    "VWAP is on the correct side",
  );
  score += pushReason(
    reasons,
    long ? latest.rsi >= 45 && latest.rsi <= 68 : latest.rsi <= 55 && latest.rsi >= 32,
    10,
    "RSI is in a tradable momentum zone",
  );
  score += pushReason(
    reasons,
    long ? shape.bullish && shape.bodyPct >= 0.35 : shape.bearish && shape.bodyPct >= 0.35,
    10,
    "Confirmation candle has a real body",
  );
  score += pushReason(
    reasons,
    latest.relativeVolume >= 1.15 || shape.body >= latest.atr * 0.35,
    8,
    "Volume or candle expansion supports the move",
  );
  score += pushReason(
    reasons,
    long ? localLevels.supportTouches >= 2 : localLevels.resistanceTouches >= 2,
    4,
    "Nearby level has repeated touches",
  );

  const buffer = Math.max(0.03, latest.atr * 0.08);
  const fastAverage = latest.ema20 || latest.ema21;
  const bounds = intradayBounds();
  let entry;
  let stop;
  let rawStop;

  if (long) {
    entry = Math.max(latest.high + buffer, latest.close + 0.01);
    rawStop = Math.min(latest.low, fastAverage, localLevels.support) - latest.atr * 0.2;
    stop = rawStop;
  } else {
    entry = Math.min(latest.low - buffer, latest.close - 0.01);
    rawStop = Math.max(latest.high, fastAverage, localLevels.resistance) + latest.atr * 0.2;
    stop = rawStop;
  }

  const risk = Math.abs(entry - stop);
  const maxAllowedRisk = Math.min(latest.atr * bounds.maxRiskAtr, entry * bounds.maxRiskPct);
  const structuralRiskTooWide = risk > maxAllowedRisk;
  if (structuralRiskTooWide) {
    score -= 14;
    reasons.push("Structural invalidation is wider than this timeframe risk limit");
  }
  const minTargetMove = entry * bounds.target1MinPct;
  const maxTargetMove = entry * bounds.target1MaxPct;
  const maxTarget2Move = entry * bounds.target2MaxPct;
  const projectedTarget1Move = clamp(
    Math.max(risk * 1.05, minTargetMove),
    minTargetMove,
    maxTargetMove,
  );
  const projectedTarget2Move = clamp(
    Math.max(risk * 1.5, maxTargetMove),
    maxTargetMove,
    maxTarget2Move,
  );
  const riskTarget1 = long ? entry + projectedTarget1Move : entry - projectedTarget1Move;
  const graphTarget1 = long && localLevels.resistance > entry
    ? localLevels.resistance - buffer
    : !long && localLevels.support < entry
      ? localLevels.support + buffer
      : null;
  const sessionTarget = long
    ? [session.openingHigh, session.sessionHigh].filter((level) => Number.isFinite(level) && level > entry).sort((a, b) => a - b)[0]
    : [session.openingLow, session.sessionLow].filter((level) => Number.isFinite(level) && level < entry).sort((a, b) => b - a)[0];
  const structuralTarget = sessionTarget
    ? long ? sessionTarget - buffer : sessionTarget + buffer
    : graphTarget1;
  const graphReward = structuralTarget ? Math.abs(structuralTarget - entry) : 0;
  const target1 = structuralTarget && graphReward >= Math.min(risk * 0.9, minTargetMove) && graphReward <= maxTargetMove
    ? structuralTarget
    : riskTarget1;
  const target2 = long
    ? Math.min(Math.max(target1 + latest.atr * 0.35, entry + projectedTarget2Move), entry + maxTarget2Move)
    : Math.max(Math.min(target1 - latest.atr * 0.35, entry - projectedTarget2Move), entry - maxTarget2Move);
  const reward = Math.abs(target1 - entry);
  const riskReward = risk > 0 ? reward / risk : null;
  const usesStructuralTarget = structuralTarget && graphReward >= Math.min(risk * 0.9, minTargetMove) && graphReward <= maxTargetMove;
  const targetBasis = usesStructuralTarget
    ? long ? "Target 1 is the nearest resistance/session sell zone" : "Target 1 is the nearest support/session cover zone"
    : "Target 1 uses bounded intraday ATR projection";

  const targetMovePct = reward / entry;
  score += pushReason(reasons, riskReward >= 1.05, 8, "Target 1 offers acceptable reward/risk");
  score += pushReason(reasons, targetMovePct >= bounds.target1MinPct && targetMovePct <= bounds.target1MaxPct, 10, `Target 1 is in the realistic ${API_SYMBOL} intraday move area`);
  if (riskReward < 0.85) {
    score -= 22;
    reasons.push("Reward/risk is weak; trade needs a tighter entry or invalidation");
  } else if (riskReward < 1.05) {
    score -= 8;
    reasons.push("Reward/risk is marginal");
  }
  reasons.push(targetBasis);
  score += pushReason(
    reasons,
    long ? latest.close > previous.close : latest.close < previous.close,
    4,
    "Latest close moved in the setup direction",
  );
  score += adaptiveScoreAdjustment(kind, phase, reasons);

  return {
    ...candidate,
    direction,
    rawScore: Math.round(score),
    score: clamp(Math.round(50 + (score - 50) * 0.68), 0, 95),
    reasons,
    entry,
    stop,
    target: target1,
    target2,
    riskReward,
    targetBasis,
    setupType: kind,
    marketPhase: phase,
    watchOnly: structuralRiskTooWide || riskReward < 0.85 || targetMovePct < bounds.target1MinPct || targetMovePct > bounds.target1MaxPct,
  };
}

function exitPlan(direction, latest, previous) {
  if (direction === "long") {
    const warning = [];
    if (latest.close < latest.ema20) warning.push("lost EMA 20");
    if (latest.close < latest.vwap) warning.push("lost VWAP");
    if (latest.rsi > 72 && latest.close < previous.close) warning.push("RSI stretch is fading");
    if (latest.ema20 < latest.ema50) warning.push("EMA 20 crossed below EMA 50");

    return {
      warning: warning.length ? `Long exit warning: ${warning.join(", ")}` : "For long: scale at T1, trail below EMA 20/VWAP",
      rules: [
        "Take partial profit near Target 1",
        "Exit if price closes below invalidation",
        "Trail remainder below EMA 20 or VWAP after Target 1",
      ],
    };
  }

  if (direction === "short") {
    const warning = [];
    if (latest.close > latest.ema20) warning.push("reclaimed EMA 20");
    if (latest.close > latest.vwap) warning.push("reclaimed VWAP");
    if (latest.rsi < 28 && latest.close > previous.close) warning.push("RSI downside stretch is bouncing");
    if (latest.ema20 > latest.ema50) warning.push("EMA 20 crossed above EMA 50");

    return {
      warning: warning.length ? `Short exit warning: ${warning.join(", ")}` : "For short: scale at T1, trail above EMA 20/VWAP",
      rules: [
        "Take partial profit near Target 1",
        "Exit if price closes above invalidation",
        "Trail remainder above EMA 20 or VWAP after Target 1",
      ],
    };
  }

  return {
    warning: "No active entry plan",
    rules: ["Wait for a scored long or short setup"],
  };
}

function neutralSignal(reason, indicators = []) {
  const trend1 = classifyTrend(calculateIndicators(trendCandles(1)));
  const trend5 = classifyTrend(calculateIndicators(trendCandles(5)));
  const trend15 = classifyTrend(calculateIndicators(trendCandles(15)));
  const selectedTrend = isDailyTimeframe()
    ? classifyTrend(indicators)
    : state.selectedTimeframe === 1
      ? trend1
      : state.selectedTimeframe === 5
        ? trend5
        : trend15;
  const regime = classifyMarketRegime(calculateIndicators(trendCandles(1)));
  return {
    setup: "No high-probability trade",
    direction: "neutral",
    score: 0,
    reasons: [reason],
    entry: null,
    stop: null,
    target: null,
    target2: null,
    riskReward: null,
    watchOnly: true,
    exitWarning: "No active trade plan",
    exitRules: isDailyTimeframe()
      ? ["Wait for the server to finish evaluating the closed daily swing setup"]
      : ["Wait for the best setup to reach the active threshold with a realistic 0.3-0.5% target"],
    trend1,
    trend5,
    trend15,
    selectedTrend,
    regime,
    bestLong: null,
    bestShort: null,
    biasScore: 0,
  };
}

function buildSignal(indicators) {
  if (isDailyTimeframe()) {
    return neutralSignal("Daily swing analysis is still loading.", indicators);
  }
  if (indicators.length < 25) {
    return neutralSignal("Waiting for enough closed candles to score an intraday setup.", indicators);
  }

  const latest = indicators[indicators.length - 1];
  const previous = indicators[indicators.length - 2];
  const levels = recentLevels(indicators);
  const localLevels = recentLevels(indicators, intradayBounds().lookback);
  const trend1 = classifyTrend(calculateIndicators(trendCandles(1)));
  const trend5 = classifyTrend(calculateIndicators(trendCandles(5)));
  const trend15 = classifyTrend(calculateIndicators(trendCandles(15)));
  const regime = classifyMarketRegime(calculateIndicators(trendCandles(1)));
  const session = sessionLevels();
  const selectedTrend = state.selectedTimeframe === 1
    ? trend1
    : state.selectedTimeframe === 5
      ? trend5
      : trend15;
  const shape = candleShape(latest);
  const market = Core.marketSession(latest.time, ASSET_OPTIONS);
  const bullishContext = trend5.tone === "positive" || trend15.tone === "positive";
  const bearishContext = trend5.tone === "negative" || trend15.tone === "negative";
  const fastAverage = latest.ema20 || latest.ema21;
  const nearSupport = latest.low <= localLevels.support + latest.atr * 0.45;
  const nearResistance = latest.high >= localLevels.resistance - latest.atr * 0.45;
  const reclaimVwap = crossesAbove(previous, latest, "vwap");
  const loseVwap = crossesBelow(previous, latest, "vwap");
  const bullishPullback = bullishContext && latest.close > latest.vwap && latest.low <= fastAverage && latest.close > fastAverage;
  const bearishPullback = bearishContext && latest.close < latest.vwap && latest.high >= fastAverage && latest.close < fastAverage;
  const bullishMomentum = bullishContext && selectedTrend.tone === "positive" && latest.close > fastAverage && latest.rsi >= 50 && latest.rsi <= 78;
  const bearishMomentum = bearishContext && selectedTrend.tone === "negative" && latest.close < fastAverage && latest.rsi <= 50 && latest.rsi >= 18;
  const breakout = latest.close > localLevels.resistance && (latest.relativeVolume > 1.15 || shape.body >= latest.atr * 0.35);
  const breakdown = latest.close < localLevels.support && (latest.relativeVolume > 1.15 || shape.body >= latest.atr * 0.35);
  const bullishReversal = nearSupport && shape.lowerWickPct >= 0.35 && latest.close > previous.high && latest.rsi > previous.rsi;
  const bearishReversal = nearResistance && shape.upperWickPct >= 0.35 && latest.close < previous.low && latest.rsi < previous.rsi;

  const candidates = [];
  const contextBase = { latest, previous, trend5, trend15, selectedTrend, levels, localLevels, shape, regime, session };

  if (bullishPullback) {
    candidates.push(scoreCandidate({
      setup: `Long ${timeframeLabel()} EMA 20 pullback`,
      baseScore: 24,
      reasons: ["Pullback held the EMA 20/VWAP area"],
    }, { ...contextBase, direction: "long" }));
  }
  if (breakout && bullishContext) {
    candidates.push(scoreCandidate({
      setup: `Long ${timeframeLabel()} breakout`,
      baseScore: 28,
      reasons: ["Price broke above recent resistance"],
    }, { ...contextBase, direction: "long" }));
  }
  if (reclaimVwap && latest.close > fastAverage) {
    candidates.push(scoreCandidate({
      setup: `Long ${timeframeLabel()} VWAP reclaim`,
      baseScore: 20,
      reasons: ["Price reclaimed VWAP and closed above EMA 20"],
    }, { ...contextBase, direction: "long" }));
  }
  if (bullishReversal) {
    candidates.push(scoreCandidate({
      setup: `Long ${timeframeLabel()} support reversal`,
      baseScore: 18,
      reasons: ["Price rejected support with improving RSI"],
    }, { ...contextBase, direction: "long" }));
  }
  if (bullishMomentum && !bullishPullback && !breakout && !reclaimVwap) {
    candidates.push(scoreCandidate({
      setup: `Long ${timeframeLabel()} momentum continuation`,
      baseScore: 18,
      reasons: ["Current momentum is aligned for a small upside continuation"],
    }, { ...contextBase, direction: "long" }));
  }

  if (bearishPullback) {
    candidates.push(scoreCandidate({
      setup: `Short ${timeframeLabel()} EMA 20 pullback`,
      baseScore: 24,
      reasons: ["Pullback rejected the EMA 20/VWAP area"],
    }, { ...contextBase, direction: "short" }));
  }
  if (breakdown && bearishContext) {
    candidates.push(scoreCandidate({
      setup: `Short ${timeframeLabel()} breakdown`,
      baseScore: 28,
      reasons: ["Price broke below recent support"],
    }, { ...contextBase, direction: "short" }));
  }
  if (loseVwap && latest.close < fastAverage) {
    candidates.push(scoreCandidate({
      setup: `Short ${timeframeLabel()} VWAP loss`,
      baseScore: 20,
      reasons: ["Price lost VWAP and closed below EMA 20"],
    }, { ...contextBase, direction: "short" }));
  }
  if (bearishReversal) {
    candidates.push(scoreCandidate({
      setup: `Short ${timeframeLabel()} resistance reversal`,
      baseScore: 18,
      reasons: ["Price rejected resistance with weakening RSI"],
    }, { ...contextBase, direction: "short" }));
  }
  if (bearishMomentum && !bearishPullback && !breakdown && !loseVwap) {
    candidates.push(scoreCandidate({
      setup: `Short ${timeframeLabel()} momentum continuation`,
      baseScore: 18,
      reasons: ["Current momentum is aligned for a small downside continuation"],
    }, { ...contextBase, direction: "short" }));
  }

  candidates.sort((a, b) => b.score - a.score);
  const best = candidates[0];
  const bestLong = candidates.filter((candidate) => candidate.direction === "long").sort((a, b) => b.score - a.score)[0] || null;
  const bestShort = candidates.filter((candidate) => candidate.direction === "short").sort((a, b) => b.score - a.score)[0] || null;
  const biasScore = bestLong && bestShort
    ? clamp(bestLong.score - bestShort.score, -100, 100)
    : bestLong
      ? Math.round(bestLong.score * 0.5)
      : bestShort
        ? -Math.round(bestShort.score * 0.5)
        : 0;
  const candidateContext = { bestLong, bestShort, biasScore };

  const threshold = activeTradeThreshold();
  const outsideAllowedSession = state.settings.sessionMode === "regular" && !market.regular;
  const unreliableData = state.dataQualityIssues.length > 0;
  if (!best || best.watchOnly || best.score < threshold || outsideAllowedSession || unreliableData) {
    let rejected = ["No long or short setup is confirmed right now"];
    if (outsideAllowedSession) {
      rejected = ["Alerts are paused outside regular market hours"];
    } else if (unreliableData) {
      rejected = [`Alerts are paused until data quality is clean: ${state.dataQualityIssues.join(", ")}`];
    } else if (best) {
      rejected = best.score < threshold
        ? [`Best candidate was ${best.setup} at ${best.score}/100, below the ${threshold}+ quality threshold`]
        : [`Best candidate was ${best.setup} at ${best.score}/100, but risk/reward or target distance is not clean enough`];
    }
    return {
      setup: "No high-probability trade",
      direction: "neutral",
      score: 0,
      reasons: rejected,
      entry: null,
      stop: null,
      target: null,
      target2: null,
      riskReward: null,
      watchOnly: true,
      exitWarning: "No active trade plan",
      exitRules: ["Wait for the best setup to reach the active threshold with a realistic 0.3-0.5% target"],
      trend1,
      trend5,
      trend15,
      selectedTrend,
      regime,
      ...candidateContext,
    };
  }

  const exits = exitPlan(best.direction, latest, previous);

  return {
    ...best,
    exitWarning: exits.warning,
    exitRules: exits.rules,
    trend1,
    trend5,
    trend15,
    selectedTrend,
    regime,
    ...candidateContext,
  };
}

function drawChart(indicators, signal) {
  const canvas = els.canvas;
  const ratio = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.floor(rect.width * ratio));
  canvas.height = Math.max(1, Math.floor(rect.height * ratio));
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);

  const width = rect.width;
  const height = rect.height;
  const pad = { top: 18, right: 62, bottom: 30, left: 16 };
  const chartW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const showVolume = Boolean(state.settings.chartLayers.volume);
  const showRsi = Boolean(state.settings.chartLayers.rsi);
  const volumeGap = showVolume ? 12 : 0;
  const rsiGap = showRsi ? 12 : 0;
  const volumeH = showVolume ? clamp(plotH * 0.17, 68, 96) : 0;
  const rsiH = showRsi ? clamp(plotH * 0.2, 80, 108) : 0;
  const chartH = plotH - volumeH - volumeGap - rsiH - rsiGap;
  const volumeTop = pad.top + chartH + volumeGap;
  const rsiTop = pad.top + chartH + volumeGap + volumeH + rsiGap;
  const chartWindow = resolveChartWindow(indicators);
  const actualStart = Math.max(0, chartWindow.start);
  const actualEnd = Math.min(chartWindow.total, chartWindow.end);
  const visible = indicators.slice(actualStart, actualEnd);
  if (!visible.length) {
    updateChartWindowControls(null);
    return;
  }
  const chartLevels = recentLevels(visible, Math.min(35, visible.length));
  const chartSession = isDailyTimeframe() ? {} : sessionLevelsForWindow(indicators, actualEnd);
  const visiblePlans = visibleJournalPlans(visible);
  const technicalPattern = detectChartTechnicalPattern(visible);
  const technicalPatternKey = patternKey(technicalPattern);
  if (state.currentPatternKey && state.currentPatternKey !== technicalPatternKey) {
    state.patternProjectionVisible = false;
  }
  const activeProjection = technicalPattern
    && state.patternProjectionVisible
    && state.currentPatternKey === technicalPatternKey
    ? technicalPattern.projection
    : null;
  const hasActiveTrade = signal
    && signal.direction !== "neutral"
    && !signal.watchOnly
    && signal.score >= activeTradeThreshold()
    && Number.isFinite(signal.entry);
  const timeframeMs = state.selectedTimeframe * 60_000;
  const signalIsVisible = Number(signal?.signalCandleTime) >= visible[0].time - timeframeMs
    && Number(signal?.signalCandleTime) <= visible.at(-1).time + timeframeMs;
  const tradeOverlay = hasActiveTrade && signalIsVisible
    ? signal
    : null;
  const candlePrices = visible.flatMap((c) => [c.open, c.high, c.low, c.close]).filter(Number.isFinite);
  const qLow = percentile(candlePrices, 0.02);
  const qHigh = percentile(candlePrices, 0.98);
  const trimmedRange = qLow !== null && qHigh !== null ? Math.max(0.01, qHigh - qLow) : 0;
  const lowFence = qLow !== null ? qLow - trimmedRange * 0.35 : null;
  const highFence = qHigh !== null ? qHigh + trimmedRange * 0.35 : null;
  const scaleCandles = visible.map((c) => ({
    ...c,
    scaleHigh: highFence === null ? c.high : Math.min(c.high, highFence),
    scaleLow: lowFence === null ? c.low : Math.max(c.low, lowFence),
  }));
  const priceValues = scaleCandles.flatMap((c) => [
    c.scaleHigh,
    c.scaleLow,
    state.settings.chartLayers.vwap && !isDailyTimeframe() ? c.vwap : null,
    state.settings.chartLayers.movingAverages ? c.ema20 : null,
    state.settings.chartLayers.movingAverages ? c.ema50 : null,
    state.settings.chartLayers.movingAverages ? c.ema150 : null,
    state.settings.chartLayers.movingAverages ? c.sma20 : null,
    state.settings.chartLayers.movingAverages ? c.sma50 : null,
    state.settings.chartLayers.movingAverages ? c.sma150 : null,
    tradeOverlay?.entry,
    tradeOverlay?.stop,
    tradeOverlay?.target,
    tradeOverlay?.target2,
    activeProjection?.breakout?.price,
    activeProjection?.target,
    state.settings.chartLayers.levels ? chartLevels.support : null,
    state.settings.chartLayers.levels ? chartLevels.resistance : null,
    state.settings.chartLayers.levels ? chartSession.openingHigh : null,
    state.settings.chartLayers.levels ? chartSession.openingLow : null,
  ]).filter(Number.isFinite);
  const highs = priceValues.length ? priceValues : scaleCandles.map((c) => c.scaleHigh);
  const lows = priceValues.length ? priceValues : scaleCandles.map((c) => c.scaleLow);
  const max = Math.max(...highs);
  const min = Math.min(...lows);
  const range = Math.max(0.01, max - min);
  const candleW = chartW / chartWindow.count;

  const y = (price) => pad.top + (max - price) / range * chartH;
  const x = (index) => pad.left + index * candleW + candleW / 2;
  state.chartGeometry = {
    width,
    height,
    pad,
    chartW,
    chartH,
    plotH,
    min,
    max,
    range,
    candleW,
    volumeTop,
    volumeH,
    rsiTop,
    rsiH,
    startIndex: chartWindow.start,
    endIndex: chartWindow.end,
    totalCount: chartWindow.total,
    visibleCount: chartWindow.count,
    actualVisibleCount: visible.length,
    live: chartWindow.live,
    sourceTimes: indicators.map((candle) => candle.time),
  };
  updateChartWindowControls(state.chartGeometry);

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#111417";
  ctx.fillRect(0, 0, width, height);
  drawExtendedHoursBands(ctx, visible, x, candleW, pad, plotH);

  ctx.strokeStyle = "#242b31";
  ctx.lineWidth = 1;
  for (let i = 0; i < 6; i += 1) {
    const gy = pad.top + (chartH / 5) * i;
    ctx.beginPath();
    ctx.moveTo(pad.left, gy);
    ctx.lineTo(width - pad.right, gy);
    ctx.stroke();
    const price = max - (range / 5) * i;
    ctx.fillStyle = "#8e99a3";
    ctx.font = "12px ui-sans-serif";
    ctx.fillText(fmt(price), width - 54, gy + 4);
  }

  if (showVolume) drawVolumePane(ctx, visible, x, candleW, width, pad, volumeTop, volumeH);
  if (showRsi) drawRsiPane(ctx, visible, x, width, pad, rsiTop, rsiH);

  visible.forEach((candle, index) => {
    const up = candle.close >= candle.open;
    const cx = x(index);
    const wickHigh = highFence === null ? candle.high : Math.min(candle.high, highFence);
    const wickLow = lowFence === null ? candle.low : Math.max(candle.low, lowFence);
    const extended = !isDailyTimeframe() && !Core.marketSession(candle.time, ASSET_OPTIONS).regular;
    ctx.save();
    ctx.globalAlpha = extended ? 0.62 : 1;
    ctx.strokeStyle = up ? "#2fd17c" : "#ff5c66";
    ctx.fillStyle = up ? "#2fd17c" : "#ff5c66";
    ctx.beginPath();
    ctx.moveTo(cx, y(wickHigh));
    ctx.lineTo(cx, y(wickLow));
    ctx.stroke();

    const bodyTop = y(Math.max(candle.open, candle.close));
    const bodyBottom = y(Math.min(candle.open, candle.close));
    const bodyWidth = Math.max(1, candleW * 0.64);
    ctx.fillRect(cx - bodyWidth / 2, bodyTop, bodyWidth, Math.max(2, bodyBottom - bodyTop));
    ctx.restore();
  });

  if (state.settings.chartLayers.movingAverages) {
    drawLine(ctx, visible, x, y, "ema20", "#f4c95d");
    drawLine(ctx, visible, x, y, "ema50", "#58a6ff");
    drawLine(ctx, visible, x, y, "ema150", "#c084fc");
    drawLine(ctx, visible, x, y, "sma20", "#f7a35c", 1.1);
    drawLine(ctx, visible, x, y, "sma50", "#7cc7ff", 1.1);
    drawLine(ctx, visible, x, y, "sma150", "#d8b4fe", 1.1);
  }
  if (state.settings.chartLayers.vwap && !isDailyTimeframe()) {
    const vwapColor = "#f1f5f9";
    drawLine(ctx, visible, x, y, "vwap", vwapColor, 2.3, [7, 4]);
    drawIndicatorLabel(ctx, visible, y, "vwap", "VWAP", vwapColor, width, pad);
  }
  if (state.settings.chartLayers.levels) drawReferenceLevels(ctx, width, pad, y, chartLevels, chartSession);
  drawPatternOverlay(ctx, technicalPattern, x, y, pad);
  if (state.settings.chartLayers.markers) drawJournalMarkers(ctx, visible, x, y, visiblePlans);
  drawTradePlan(ctx, tradeOverlay, width, pad, y, visible, x);
  if (chartWindow.live) {
    drawCurrentPriceMarker(ctx, visible.at(-1), width, height, pad, y, x(visible.length - 1), candleW);
  }
  drawChartHoverOverlay();
}

function compactVolume(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric < 0) return "--";
  if (numeric >= 1_000_000_000) return `${fmt(numeric / 1_000_000_000, 1)}B`;
  if (numeric >= 1_000_000) return `${fmt(numeric / 1_000_000, 1)}M`;
  if (numeric >= 1_000) return `${fmt(numeric / 1_000, 1)}K`;
  return fmt(numeric, 0);
}

function drawVolumePane(ctx, visible, x, candleW, width, pad, volumeTop, volumeH) {
  const volumes = visible.map((candle) => Math.max(0, Number(candle.volume) || 0));
  const reportedVolumes = volumes.filter((volume) => volume > 0);
  const scaleMax = reportedVolumes.length ? Math.max(1, percentile(reportedVolumes, 0.95)) : null;
  const chartRight = width - pad.right;

  ctx.save();
  ctx.strokeStyle = "#303740";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(pad.left, volumeTop - 6);
  ctx.lineTo(chartRight, volumeTop - 6);
  ctx.stroke();

  const drawHeader = () => {
    ctx.globalAlpha = 1;
    ctx.fillStyle = "#8e99a3";
    ctx.font = "700 10px ui-sans-serif";
    ctx.textAlign = "left";
    ctx.fillText("VOLUME", pad.left + 2, volumeTop + 10);
    ctx.textAlign = "right";
    ctx.fillText(scaleMax === null ? "UNAVAILABLE" : compactVolume(scaleMax), width - 7, volumeTop + 10);
  };

  if (scaleMax === null) {
    drawHeader();
    ctx.fillStyle = "#67727c";
    ctx.font = "12px ui-sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("No reported volume for the visible bars", pad.left + (chartRight - pad.left) / 2, volumeTop + volumeH / 2);
    ctx.restore();
    return;
  }

  visible.forEach((candle, index) => {
    const volume = volumes[index];
    const barHeight = Math.min(volumeH - 16, (volume / scaleMax) * (volumeH - 16));
    const up = candle.close >= candle.open;
    const extended = !isDailyTimeframe() && !Core.marketSession(candle.time, ASSET_OPTIONS).regular;
    ctx.globalAlpha = extended ? 0.42 : 0.72;
    ctx.fillStyle = up ? "#2fd17c" : "#ff5c66";
    ctx.fillRect(
      x(index) - candleW * 0.34,
      volumeTop + volumeH - barHeight,
      Math.max(1, candleW * 0.68),
      barHeight,
    );
  });
  drawHeader();
  ctx.restore();
}

function drawRsiPane(ctx, visible, x, width, pad, rsiTop, rsiH) {
  const chartRight = width - pad.right;
  const innerTop = rsiTop + 16;
  const innerBottom = rsiTop + rsiH - 4;
  const innerH = Math.max(1, innerBottom - innerTop);
  const rsiY = (value) => innerTop + (100 - clamp(value, 0, 100)) / 100 * innerH;
  const latest = [...visible].reverse().find((candle) => Number.isFinite(candle.rsi));

  ctx.save();
  ctx.strokeStyle = "#303740";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(pad.left, rsiTop - 6);
  ctx.lineTo(chartRight, rsiTop - 6);
  ctx.stroke();

  ctx.fillStyle = "#8e99a3";
  ctx.font = "700 10px ui-sans-serif";
  ctx.textAlign = "left";
  ctx.fillText("RSI 14", pad.left + 2, rsiTop + 10);
  ctx.textAlign = "right";
  ctx.fillStyle = latest && (latest.rsi > 70 || latest.rsi < 30) ? "#f4c95d" : "#58a6ff";
  ctx.fillText(latest ? fmt(latest.rsi, 1) : "--", width - 7, rsiTop + 10);

  const overboughtY = rsiY(70);
  const oversoldY = rsiY(30);
  ctx.fillStyle = "rgba(255, 92, 102, 0.055)";
  ctx.fillRect(pad.left, innerTop, chartRight - pad.left, overboughtY - innerTop);
  ctx.fillStyle = "rgba(47, 209, 124, 0.055)";
  ctx.fillRect(pad.left, oversoldY, chartRight - pad.left, innerBottom - oversoldY);

  [
    { value: 70, color: "rgba(255, 92, 102, 0.55)", dash: [5, 5] },
    { value: 50, color: "rgba(142, 153, 163, 0.38)", dash: [] },
    { value: 30, color: "rgba(47, 209, 124, 0.55)", dash: [5, 5] },
  ].forEach((level) => {
    const py = rsiY(level.value);
    ctx.strokeStyle = level.color;
    ctx.setLineDash(level.dash);
    ctx.beginPath();
    ctx.moveTo(pad.left, py);
    ctx.lineTo(chartRight, py);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = level.color;
    ctx.font = "9px ui-sans-serif";
    ctx.textAlign = "right";
    ctx.fillText(String(level.value), width - 8, py + 3);
  });

  ctx.strokeStyle = "#58a6ff";
  ctx.lineWidth = 2;
  ctx.beginPath();
  let started = false;
  let hasPoint = false;
  visible.forEach((candle, index) => {
    if (!Number.isFinite(candle.rsi)) {
      started = false;
      return;
    }
    const px = x(index);
    const py = rsiY(candle.rsi);
    hasPoint = true;
    if (!started) {
      ctx.moveTo(px, py);
      started = true;
    } else {
      ctx.lineTo(px, py);
    }
  });
  if (hasPoint) ctx.stroke();
  ctx.restore();
}

function drawPriceTag(ctx, price, py, width, height, pad, options = {}) {
  const chartRight = width - pad.right;
  const tagHeight = 22;
  const tagY = clamp(py - tagHeight / 2, pad.top, height - pad.bottom - tagHeight);
  const tagX = chartRight + 3;
  const tagWidth = Math.max(56, pad.right - 6);
  ctx.save();
  ctx.fillStyle = options.background || "#58a6ff";
  roundedRect(ctx, tagX, tagY, tagWidth, tagHeight, 4);
  ctx.fill();
  if (options.border) {
    ctx.strokeStyle = options.border;
    ctx.lineWidth = 1;
    ctx.stroke();
  }
  ctx.fillStyle = options.color || "#101214";
  ctx.font = "800 11px ui-sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(fmt(price), tagX + tagWidth / 2, tagY + tagHeight / 2 + 0.5, tagWidth - 6);
  ctx.restore();
}

function drawCurrentPriceMarker(ctx, candle, width, height, pad, y, lastX, candleW) {
  if (!candle || !Number.isFinite(candle.close)) return;
  const py = y(candle.close);
  const chartRight = width - pad.right;
  const color = candle.close >= candle.open ? "#2fd17c" : "#ff5c66";
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.25;
  ctx.setLineDash([3, 3]);
  ctx.beginPath();
  ctx.moveTo(Math.min(chartRight, lastX + candleW * 0.36), py);
  ctx.lineTo(chartRight + 3, py);
  ctx.stroke();
  ctx.restore();
  drawPriceTag(ctx, candle.close, py, width, height, pad, {
    background: color,
    color: "#101214",
  });
}

function sizeChartOverlay(geometry) {
  const ratio = window.devicePixelRatio || 1;
  const overlay = els.chartOverlay;
  const pixelWidth = Math.max(1, Math.floor(geometry.width * ratio));
  const pixelHeight = Math.max(1, Math.floor(geometry.height * ratio));
  if (overlay.width !== pixelWidth) overlay.width = pixelWidth;
  if (overlay.height !== pixelHeight) overlay.height = pixelHeight;
  return ratio;
}

function drawChartHoverOverlay() {
  const geometry = state.chartGeometry;
  if (!geometry) return;
  const ratio = sizeChartOverlay(geometry);
  const ctx = els.chartOverlay.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, geometry.width, geometry.height);
  if (!state.chartHover) return;

  const { width, height, pad, chartH, max, range } = geometry;
  const chartRight = width - pad.right;
  const x = clamp(state.chartHover.x, pad.left, chartRight);
  const y = clamp(state.chartHover.y, pad.top, pad.top + chartH);
  const price = max - ((y - pad.top) / chartH) * range;

  ctx.save();
  ctx.strokeStyle = "rgba(215, 221, 226, 0.48)";
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(pad.left, y);
  ctx.lineTo(chartRight, y);
  ctx.moveTo(x, pad.top);
  ctx.lineTo(x, pad.top + chartH);
  ctx.stroke();
  ctx.restore();

  drawPriceTag(ctx, price, y, width, height, pad, {
    background: "#d7dde2",
    border: "#58a6ff",
    color: "#101214",
  });
}

function scheduleChartInteractionRefresh() {
  if (state.chartInteractionFrame) return;
  state.chartInteractionFrame = window.requestAnimationFrame(() => {
    state.chartInteractionFrame = null;
    refresh();
  });
}

function handleChartWheel(event) {
  const geometry = state.chartGeometry;
  if (!geometry?.visibleCount) return;
  event.preventDefault();
  const rect = els.chartOverlay.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const anchorRatio = clamp((x - geometry.pad.left) / Math.max(1, geometry.chartW), 0, 1);
  const deltaScale = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? geometry.height : 1;
  const deltaY = event.deltaY * deltaScale;
  const deltaX = event.deltaX * deltaScale;

  if (Math.abs(deltaX) > Math.abs(deltaY) && Math.abs(deltaX) > 2) {
    const next = Core.panChartWindow(
      { total: geometry.totalCount, count: geometry.visibleCount, end: geometry.endIndex },
      -deltaX / Math.max(1, geometry.candleW),
      chartWindowOptions(geometry.totalCount),
    );
    applyChartWindow(next, geometry);
    return;
  }

  const factor = Math.exp(clamp(deltaY, -240, 240) * 0.0018);
  zoomChart(factor, anchorRatio);
}

function handleChartPointerDown(event) {
  const geometry = state.chartGeometry;
  if (!geometry?.visibleCount || event.button !== 0) return;
  const rect = els.chartOverlay.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  const chartRight = geometry.width - geometry.pad.right;
  if (x < geometry.pad.left || x > chartRight || y < geometry.pad.top || y > geometry.height - geometry.pad.bottom) return;
  state.chartDrag = {
    pointerId: event.pointerId,
    startX: x,
    moved: false,
    initialWindow: {
      total: geometry.totalCount,
      count: geometry.visibleCount,
      end: geometry.endIndex,
    },
    sourceTimes: geometry.sourceTimes,
    candleW: geometry.candleW,
  };
  els.chartOverlay.setPointerCapture(event.pointerId);
  els.chartOverlay.classList.add("dragging");
}

function handleChartPointerMove(event) {
  const geometry = state.chartGeometry;
  if (!geometry) return;
  const rect = els.chartOverlay.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  if (state.chartDrag?.pointerId === event.pointerId) {
    const deltaX = x - state.chartDrag.startX;
    if (Math.abs(deltaX) >= 4) state.chartDrag.moved = true;
    if (state.chartDrag.moved) {
      event.preventDefault();
      const next = Core.panChartWindow(
        state.chartDrag.initialWindow,
        deltaX / Math.max(1, state.chartDrag.candleW),
        chartWindowOptions(state.chartDrag.initialWindow.total),
      );
      saveChartWindow(next, state.chartDrag.sourceTimes);
      state.chartHover = null;
      scheduleChartInteractionRefresh();
    }
    return;
  }
  const chartRight = geometry.width - geometry.pad.right;
  const chartBottom = geometry.pad.top + geometry.chartH;
  if (x < geometry.pad.left || x > chartRight || y < geometry.pad.top || y > chartBottom) {
    state.chartHover = null;
  } else {
    state.chartHover = { x, y };
  }
  drawChartHoverOverlay();
}

function finishChartPointerInteraction(event) {
  if (!state.chartDrag || state.chartDrag.pointerId !== event.pointerId) return;
  const moved = state.chartDrag.moved;
  state.chartDrag = null;
  if (els.chartOverlay.hasPointerCapture(event.pointerId)) {
    els.chartOverlay.releasePointerCapture(event.pointerId);
  }
  els.chartOverlay.classList.remove("dragging");
  if (moved) {
    state.suppressChartClick = true;
    window.setTimeout(() => {
      state.suppressChartClick = false;
    }, 0);
  }
}

function clearChartHover() {
  if (state.chartDrag) return;
  state.chartHover = null;
  drawChartHoverOverlay();
}

function drawExtendedHoursBands(ctx, visible, x, candleW, pad, chartH) {
  if (isDailyTimeframe() || !visible.length) return;
  const segments = [];
  let active = null;
  visible.forEach((candle, index) => {
    const session = Core.marketSession(candle.time, ASSET_OPTIONS);
    const phase = session.regular ? null : session.phase;
    if (!phase) {
      if (active) {
        active.end = index - 1;
        segments.push(active);
        active = null;
      }
      return;
    }
    if (!active || active.phase !== phase) {
      if (active) {
        active.end = index - 1;
        segments.push(active);
      }
      active = { phase, start: index, end: index };
    } else {
      active.end = index;
    }
  });
  if (active) segments.push(active);

  segments.forEach((segment) => {
    const startX = Math.max(pad.left, x(segment.start) - candleW / 2);
    const endX = Math.min(ctx.canvas.width / (window.devicePixelRatio || 1) - pad.right, x(segment.end) + candleW / 2);
    const color = segment.phase === "premarket"
      ? "rgba(88, 166, 255, 0.15)"
      : "rgba(244, 201, 93, 0.14)";
    const label = segment.phase === "premarket" ? "PRE" : "AH";
    ctx.save();
    ctx.fillStyle = color;
    ctx.fillRect(startX, pad.top, Math.max(1, endX - startX), chartH);
    ctx.strokeStyle = segment.phase === "premarket"
      ? "rgba(88, 166, 255, 0.38)"
      : "rgba(244, 201, 93, 0.38)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(startX, pad.top);
    ctx.lineTo(startX, pad.top + chartH);
    ctx.stroke();
    if (endX - startX > 26) {
      ctx.fillStyle = "rgba(17, 20, 23, 0.78)";
      ctx.fillRect(startX + 3, pad.top + 4, 24, 15);
      ctx.fillStyle = segment.phase === "premarket" ? "#58a6ff" : "#f4c95d";
      ctx.font = "700 10px ui-sans-serif";
      ctx.fillText(label, startX + 7, pad.top + 15);
    }
    ctx.restore();
  });
}

function averageRange(candles) {
  if (!candles.length) return 0;
  return candles.reduce((sum, candle) => sum + Math.max(0, candle.high - candle.low), 0) / candles.length;
}

function patternMoveThreshold(price) {
  if (isDailyTimeframe()) return price * 0.025;
  if (state.selectedTimeframe === 15) return price * 0.006;
  if (state.selectedTimeframe === 5) return price * 0.0045;
  return price * 0.0025;
}

function linearSlope(points, key) {
  if (points.length < 2) return 0;
  const n = points.length;
  const meanX = (n - 1) / 2;
  const meanY = points.reduce((sum, point) => sum + point[key], 0) / n;
  let numerator = 0;
  let denominator = 0;
  points.forEach((point, index) => {
    const dx = index - meanX;
    numerator += dx * (point[key] - meanY);
    denominator += dx * dx;
  });
  return denominator ? numerator / denominator : 0;
}

function pivotPoints(candles, span = 3) {
  const pivots = [];
  for (let index = span; index < candles.length - span; index += 1) {
    const window = candles.slice(index - span, index + span + 1);
    const candle = candles[index];
    const isHigh = candle.high === Math.max(...window.map((item) => item.high));
    const isLow = candle.low === Math.min(...window.map((item) => item.low));
    if (isHigh) pivots.push({ index, type: "H", price: candle.high, candle });
    if (isLow) pivots.push({ index, type: "L", price: candle.low, candle });
  }
  return pivots
    .sort((a, b) => a.index - b.index)
    .reduce((items, pivot) => {
      const last = items[items.length - 1];
      if (!last || last.type !== pivot.type) {
        items.push(pivot);
        return items;
      }
      const moreExtreme = pivot.type === "H" ? pivot.price > last.price : pivot.price < last.price;
      if (moreExtreme) items[items.length - 1] = pivot;
      return items;
    }, []);
}

function lineForPattern(a, b, color = "#f4c95d", dash = []) {
  return { from: a, to: b, color, dash };
}

function patternLabelPoint(points) {
  const middle = points[Math.floor(points.length / 2)] || points[0];
  return middle ? { index: middle.index, price: middle.price } : null;
}

function patternKey(pattern) {
  if (!pattern) return "";
  const label = pattern.label || pattern.points?.[0] || {};
  return [
    state.selectedTimeframe,
    pattern.name,
    Math.round(Number(label.index || 0)),
    Math.round(Number(label.price || 0) * 100),
  ].join("|");
}

function projectionFor(name, direction, breakout, target, measuredMove) {
  const move = target - breakout.price;
  const pct = breakout.price ? (move / breakout.price) * 100 : 0;
  return {
    name,
    direction,
    breakout,
    target,
    measuredMove: Math.abs(measuredMove),
    move,
    pct,
  };
}

function detectHeadAndShoulders(candles, pivots, inverted = false) {
  const sequence = inverted ? ["L", "H", "L", "H", "L"] : ["H", "L", "H", "L", "H"];
  const tolerance = Math.max(averageRange(candles.slice(-30)) * 1.15, candles.at(-1).close * (isDailyTimeframe() ? 0.015 : 0.0028));
  for (let start = Math.max(0, pivots.length - 10); start <= pivots.length - 5; start += 1) {
    const group = pivots.slice(start, start + 5);
    if (group.length < 5 || group.some((pivot, index) => pivot.type !== sequence[index])) continue;
    const [leftShoulder, neck1, head, neck2, rightShoulder] = group;
    const shoulderGap = Math.abs(leftShoulder.price - rightShoulder.price);
    const necklineGap = Math.abs(neck1.price - neck2.price);
    const headProminence = inverted
      ? Math.min(leftShoulder.price, rightShoulder.price) - head.price
      : head.price - Math.max(leftShoulder.price, rightShoulder.price);
    const neckline = (neck1.price + neck2.price) / 2;
    const latest = candles.at(-1);
    const confirmed = inverted ? latest.close > neckline : latest.close < neckline;
    if (headProminence < tolerance || shoulderGap > tolerance * 1.5 || necklineGap > tolerance * 2.2 || !confirmed) continue;
    const color = inverted ? "#2fd17c" : "#ff5c66";
    const breakout = { index: Math.max(neck1.index, neck2.index), price: neckline };
    const target = inverted ? neckline + headProminence : neckline - headProminence;
    return {
      name: inverted ? "Inverse Head & Shoulders" : "Head & Shoulders",
      direction: inverted ? "bullish" : "bearish",
      score: 90,
      color,
      projection: projectionFor(inverted ? "Measured move above neckline" : "Measured move below neckline", inverted ? "up" : "down", breakout, target, headProminence),
      label: patternLabelPoint([leftShoulder, head, rightShoulder]),
      points: [leftShoulder, head, rightShoulder],
      lines: [
        lineForPattern(leftShoulder, head, color),
        lineForPattern(head, rightShoulder, color),
        lineForPattern(neck1, neck2, "#d7dde2", [5, 5]),
      ],
    };
  }
  return null;
}

function detectDoublePattern(candles, pivots, bottom = false) {
  const type = bottom ? "L" : "H";
  const recent = pivots.filter((pivot) => pivot.type === type).slice(-4);
  const latest = candles.at(-1);
  const tolerance = Math.max(averageRange(candles.slice(-30)) * 0.85, latest.close * (isDailyTimeframe() ? 0.012 : 0.0022));
  for (let i = 0; i < recent.length - 1; i += 1) {
    const first = recent[i];
    const second = recent[i + 1];
    if (second.index - first.index < 6) continue;
    if (Math.abs(first.price - second.price) > tolerance) continue;
    const between = candles.slice(first.index, second.index + 1);
    const necklinePrice = bottom
      ? Math.max(...between.map((candle) => candle.high))
      : Math.min(...between.map((candle) => candle.low));
    const depth = bottom
      ? necklinePrice - Math.max(first.price, second.price)
      : Math.min(first.price, second.price) - necklinePrice;
    const confirmed = bottom ? latest.close > necklinePrice : latest.close < necklinePrice;
    if (depth < tolerance * 1.4 || !confirmed) continue;
    const neckIndex = first.index + between.findIndex((candle) => bottom ? candle.high === necklinePrice : candle.low === necklinePrice);
    const neckline = { index: neckIndex, price: necklinePrice };
    const color = bottom ? "#2fd17c" : "#ff5c66";
    const breakout = { index: Math.max(second.index, neckIndex), price: necklinePrice };
    const target = bottom ? necklinePrice + depth : necklinePrice - depth;
    return {
      name: bottom ? "Double Bottom" : "Double Top",
      direction: bottom ? "bullish" : "bearish",
      score: 76,
      color,
      projection: projectionFor(bottom ? "Range height above neckline" : "Range height below neckline", bottom ? "up" : "down", breakout, target, depth),
      label: patternLabelPoint([first, second]),
      points: [first, second],
      lines: [
        lineForPattern(first, second, color),
        lineForPattern(neckline, { index: candles.length - 1, price: necklinePrice }, "#d7dde2", [5, 5]),
      ],
    };
  }
  return null;
}

function detectFlag(candles, bullish = true) {
  const flagLen = isDailyTimeframe() ? 12 : state.selectedTimeframe === 1 ? 18 : 14;
  const impulseLen = isDailyTimeframe() ? 18 : 20;
  if (candles.length < flagLen + impulseLen + 4) return null;
  const impulse = candles.slice(-(flagLen + impulseLen), -flagLen);
  const flag = candles.slice(-flagLen);
  const latest = candles.at(-1);
  const impulseMove = impulse.at(-1).close - impulse[0].open;
  const expectedMove = bullish ? impulseMove : -impulseMove;
  const minMove = patternMoveThreshold(latest.close) * (isDailyTimeframe() ? 1.2 : 1.7);
  if (expectedMove < minMove) return null;
  const flagHigh = Math.max(...flag.map((candle) => candle.high));
  const flagLow = Math.min(...flag.map((candle) => candle.low));
  const flagRange = flagHigh - flagLow;
  if (flagRange > expectedMove * 0.72) return null;
  const highSlope = linearSlope(flag, "high");
  const lowSlope = linearSlope(flag, "low");
  const drift = flag.at(-1).close - flag[0].open;
  const healthyDrift = bullish
    ? drift <= expectedMove * 0.32 && drift >= -expectedMove * 0.78 && highSlope <= averageRange(flag) * 0.08
    : -drift <= expectedMove * 0.32 && -drift >= -expectedMove * 0.78 && lowSlope >= -averageRange(flag) * 0.08;
  if (!healthyDrift) return null;
  const startIndex = candles.length - flagLen;
  const flagStartHigh = { index: startIndex, price: flag[0].high };
  const flagEndHigh = { index: candles.length - 1, price: flag.at(-1).high };
  const flagStartLow = { index: startIndex, price: flag[0].low };
  const flagEndLow = { index: candles.length - 1, price: flag.at(-1).low };
  const poleStart = { index: candles.length - flagLen - impulseLen, price: impulse[0].open };
  const poleEnd = { index: startIndex - 1, price: impulse.at(-1).close };
  const color = bullish ? "#2fd17c" : "#ff5c66";
  const poleHeight = Math.abs(poleEnd.price - poleStart.price);
  const breakout = bullish ? flagEndHigh : flagEndLow;
  const target = bullish ? breakout.price + poleHeight : breakout.price - poleHeight;
  return {
    name: bullish ? "Bull Flag" : "Bear Flag",
    direction: bullish ? "bullish" : "bearish",
    score: 72,
    color,
    projection: projectionFor(bullish ? "Flag pole measured move up" : "Flag pole measured move down", bullish ? "up" : "down", breakout, target, poleHeight),
    label: { index: startIndex + Math.floor(flagLen / 2), price: bullish ? flagHigh : flagLow },
    points: [poleStart, poleEnd],
    lines: [
      lineForPattern(poleStart, poleEnd, color),
      lineForPattern(flagStartHigh, flagEndHigh, color, [6, 4]),
      lineForPattern(flagStartLow, flagEndLow, color, [6, 4]),
    ],
  };
}

function detectTechnicalPattern(candles) {
  if (!state.settings.chartLayers.patterns || candles.length < 24) return null;
  const pivots = pivotPoints(candles, isDailyTimeframe() ? 2 : 3);
  const candidates = [
    detectHeadAndShoulders(candles, pivots, false),
    detectHeadAndShoulders(candles, pivots, true),
    detectDoublePattern(candles, pivots, false),
    detectDoublePattern(candles, pivots, true),
    detectFlag(candles, true),
    detectFlag(candles, false),
    ...(Patterns?.detectAdditionalPatterns(candles, { timeframe: state.selectedTimeframe }) || []),
  ].filter(Boolean);
  return candidates.sort((a, b) => b.score - a.score)[0] || null;
}

function detectChartTechnicalPattern(candles) {
  if (isDailyTimeframe()) return detectTechnicalPattern(candles);
  if (ASSET_OPTIONS.continuous) return detectTechnicalPattern(candles);
  const regular = candles
    .map((candle, chartIndex) => ({ candle, chartIndex }))
    .filter(({ candle }) => Core.marketSession(candle.time, ASSET_OPTIONS).regular);
  const pattern = detectTechnicalPattern(regular.map(({ candle }) => candle));
  if (!pattern) return null;
  return Patterns.remapPatternIndices(pattern, regular.map(({ chartIndex }) => chartIndex));
}

function drawPatternOverlay(ctx, pattern, x, y, pad) {
  state.currentPattern = pattern;
  state.currentPatternKey = patternKey(pattern);
  state.patternHitZones = [];
  if (!pattern) {
    state.currentPatternKey = "";
    state.patternProjectionVisible = false;
    return;
  }
  ctx.save();
  ctx.lineWidth = 2;
  pattern.lines.forEach((line) => {
    const x1 = x(line.from.index);
    const y1 = y(line.from.price);
    const x2 = x(line.to.index);
    const y2 = y(line.to.price);
    state.patternHitZones.push({ type: "line", x1, y1, x2, y2, tolerance: 10 });
    ctx.strokeStyle = line.color || pattern.color;
    ctx.setLineDash(line.dash || []);
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
  });
  ctx.setLineDash([]);
  pattern.points.forEach((point) => {
    const px = x(point.index);
    const py = y(point.price);
    state.patternHitZones.push({ type: "circle", x: px, y: py, r: 12 });
    ctx.fillStyle = pattern.color;
    ctx.strokeStyle = "#101214";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(px, py, 4.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  });
  if (pattern.label) {
    const label = pattern.name.toUpperCase();
    ctx.font = "700 11px ui-sans-serif";
    const textWidth = ctx.measureText(label).width;
    const px = Math.max(pad.left + 4, Math.min(x(pattern.label.index) - textWidth / 2 - 8, ctx.canvas.width / (window.devicePixelRatio || 1) - pad.right - textWidth - 18));
    const py = Math.max(pad.top + 8, y(pattern.label.price) - 30);
    state.patternHitZones.push({ type: "rect", x: px, y: py, w: textWidth + 16, h: 22 });
    ctx.fillStyle = "rgba(17, 20, 23, 0.9)";
    roundedRect(ctx, px, py, textWidth + 16, 22, 4);
    ctx.fill();
    ctx.strokeStyle = pattern.color;
    ctx.stroke();
    ctx.fillStyle = pattern.color;
    ctx.fillText(label, px + 8, py + 15);
  }
  if (state.patternProjectionVisible && state.currentPatternKey === patternKey(pattern)) {
    drawPatternProjection(ctx, pattern, x, y, pad);
  }
  ctx.restore();
}

function drawPatternProjection(ctx, pattern, x, y, pad) {
  const projection = pattern.projection;
  if (!projection) return;
  const breakoutX = x(projection.breakout.index);
  const breakoutY = y(projection.breakout.price);
  const targetIndex = Math.min(
    projection.breakout.index + 18,
    Math.max(0, Number(state.chartGeometry?.visibleCount || 1) - 1),
  );
  const targetX = Math.max(breakoutX + 30, x(targetIndex));
  const targetY = y(projection.target);
  const chartRight = ctx.canvas.width / (window.devicePixelRatio || 1) - pad.right;
  const lineEnd = Math.min(chartRight, targetX);
  const direction = projection.move >= 0 ? "up" : "down";
  const targetLabel = `${projection.target >= projection.breakout.price ? "+" : ""}${fmt(projection.move)} (${projection.pct >= 0 ? "+" : ""}${fmt(projection.pct, 2)}%)`;
  const priceLabel = `Target ${fmt(projection.target)}`;
  const color = pattern.color;

  ctx.save();
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = 2;
  ctx.setLineDash([7, 5]);
  ctx.beginPath();
  ctx.moveTo(pad.left, targetY);
  ctx.lineTo(chartRight, targetY);
  ctx.stroke();
  ctx.setLineDash([]);

  ctx.beginPath();
  ctx.moveTo(breakoutX, breakoutY);
  ctx.lineTo(lineEnd, targetY);
  ctx.stroke();
  const arrowSize = 7;
  ctx.beginPath();
  ctx.moveTo(lineEnd, targetY);
  ctx.lineTo(lineEnd - 10, targetY + (direction === "up" ? 7 : -7));
  ctx.lineTo(lineEnd - 10, targetY + (direction === "up" ? -7 : 7));
  ctx.closePath();
  ctx.fill();

  ctx.beginPath();
  ctx.arc(breakoutX, breakoutY, 5, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "rgba(17, 20, 23, 0.94)";
  const label = `${priceLabel} | ${targetLabel}`;
  ctx.font = "700 11px ui-sans-serif";
  const width = Math.min(ctx.measureText(label).width + 16, 230);
  const boxX = Math.max(pad.left + 6, Math.min(chartRight - width, lineEnd - width));
  const boxY = Math.max(pad.top + 8, Math.min(targetY - 30, ctx.canvas.height / (window.devicePixelRatio || 1) - 54));
  roundedRect(ctx, boxX, boxY, width, 42, 4);
  ctx.fill();
  ctx.strokeStyle = color;
  ctx.stroke();
  ctx.fillStyle = color;
  ctx.fillText(label, boxX + 8, boxY + 16, width - 16);

  ctx.font = "10px ui-sans-serif";
  ctx.fillStyle = "#d7dde2";
  const basis = projection.name;
  ctx.fillText(basis, boxX + 8, boxY + 36, Math.min(220, chartRight - boxX));
  ctx.restore();
}

function distanceToSegment(px, py, x1, y1, x2, y2) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  if (dx === 0 && dy === 0) return Math.hypot(px - x1, py - y1);
  const t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)));
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
}

function hitPatternZone(x, y) {
  return state.patternHitZones.some((zone) => {
    if (zone.type === "rect") {
      return x >= zone.x - 4 && x <= zone.x + zone.w + 4 && y >= zone.y - 4 && y <= zone.y + zone.h + 4;
    }
    if (zone.type === "circle") {
      return Math.hypot(x - zone.x, y - zone.y) <= zone.r;
    }
    if (zone.type === "line") {
      return distanceToSegment(x, y, zone.x1, zone.y1, zone.x2, zone.y2) <= zone.tolerance;
    }
    return false;
  });
}

function handlePatternClick(event) {
  if (state.suppressChartClick) return;
  if (!state.settings.chartLayers.patterns || !state.currentPattern || !state.currentPatternKey) return;
  const rect = els.canvas.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  if (!hitPatternZone(x, y)) return;
  state.patternProjectionVisible = !state.patternProjectionVisible;
  refresh();
}

function drawReferenceLevels(ctx, width, pad, y, levels, session) {
  const refs = [
    { price: levels.resistance, label: "RES", color: "rgba(255, 92, 102, 0.45)" },
    { price: levels.support, label: "SUP", color: "rgba(47, 209, 124, 0.45)" },
    { price: session.openingHigh, label: "ORH", color: "rgba(244, 201, 93, 0.38)", dash: [3, 5] },
    { price: session.openingLow, label: "ORL", color: "rgba(244, 201, 93, 0.38)", dash: [3, 5] },
  ].filter((level) => Number.isFinite(level.price));

  refs.forEach((level) => {
    const py = y(level.price);
    ctx.save();
    ctx.strokeStyle = level.color;
    ctx.lineWidth = 1;
    ctx.setLineDash(level.dash || [6, 6]);
    ctx.beginPath();
    ctx.moveTo(pad.left, py);
    ctx.lineTo(width - pad.right, py);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = level.color;
    ctx.font = "10px ui-sans-serif";
    ctx.fillText(level.label, pad.left + 4, py - 4);
    ctx.restore();
  });
}

function drawJournalMarkers(ctx, visible, x, y, plans = visibleJournalPlans(visible)) {
  if (!plans.length || !visible.length) return;
  const byTime = new Map(visible.map((candle, index) => [Math.floor(candle.time / 60_000), { candle, index }]));

  plans.forEach((plan) => {
    const key = Math.floor(plan.created_at / 60_000);
    const match = byTime.get(key) || [...byTime.values()].reduce((closest, item) => {
      if (!closest) return item;
      return Math.abs(item.candle.time - plan.created_at) < Math.abs(closest.candle.time - plan.created_at) ? item : closest;
    }, null);
    if (!match) return;

    const px = x(match.index);
    const py = y(match.candle.close);
    const color = plan.direction === "long" ? "#2fd17c" : "#ff5c66";
    ctx.save();
    ctx.fillStyle = color;
    ctx.strokeStyle = "#101214";
    ctx.lineWidth = 2;
    ctx.beginPath();
    if (plan.direction === "long") {
      ctx.moveTo(px, py - 8);
      ctx.lineTo(px - 6, py + 5);
      ctx.lineTo(px + 6, py + 5);
    } else {
      ctx.moveTo(px, py + 8);
      ctx.lineTo(px - 6, py - 5);
      ctx.lineTo(px + 6, py - 5);
    }
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    if (plan.outcome_status === "target1" || plan.outcome_status === "target2") {
      ctx.fillStyle = "#f4c95d";
      ctx.fillRect(px - 3, py - 3, 6, 6);
    }
    ctx.restore();
  });
}

function drawTradePlan(ctx, signal, width, pad, y, visible, x) {
  if (!signal || signal.direction === "neutral" || !Number.isFinite(signal.entry)) return;

  const long = signal.direction === "long";
  const confirmed = isActionableSignal(signal);
  const levels = [
    {
      price: signal.entry,
      label: long ? "BUY TRIGGER" : "SHORT TRIGGER",
      color: long ? "#2fd17c" : "#ff5c66",
      width: 2.5,
    },
    {
      price: signal.stop,
      label: long ? "SELL IF INVALID" : "COVER IF INVALID",
      color: "#ff5c66",
      width: 2,
      dash: [7, 5],
    },
    {
      price: signal.target,
      label: long ? "SELL TARGET 1" : "COVER TARGET 1",
      color: "#f4c95d",
      width: 2,
    },
    {
      price: signal.target2,
      label: long ? "SELL TARGET 2" : "COVER TARGET 2",
      color: "#58a6ff",
      width: 2,
      dash: [4, 4],
    },
  ].filter((level) => Number.isFinite(level.price));

  const chartRight = width - pad.right;
  const labelRight = width - 8;
  const lineStart = pad.left;
  const lineEnd = chartRight;
  const labelSlots = [];

  levels.forEach((level) => {
    const py = y(level.price);
    ctx.save();
    ctx.strokeStyle = level.color;
    ctx.lineWidth = level.width;
    ctx.globalAlpha = confirmed ? 0.96 : 0.72;
    ctx.setLineDash(level.dash || []);
    ctx.beginPath();
    ctx.moveTo(lineStart, py);
    ctx.lineTo(lineEnd, py);
    ctx.stroke();
    ctx.restore();

    const text = `${level.label} ${fmt(level.price)}`;
    ctx.save();
    ctx.font = "11px ui-sans-serif";
    const textWidth = ctx.measureText(text).width;
    const boxWidth = Math.min(textWidth + 12, 176);
    const boxX = Math.max(lineStart + 4, labelRight - boxWidth);
    const minY = pad.top + 2;
    const maxY = ctx.canvas.height / (window.devicePixelRatio || 1) - 28;
    let boxY = Math.max(minY, Math.min(py - 12, maxY));
    for (const slot of labelSlots) {
      if (Math.abs(boxY - slot) < 24) boxY = Math.min(maxY, slot + 24);
    }
    labelSlots.push(boxY);
    ctx.fillStyle = "rgba(17, 20, 23, 0.92)";
    ctx.strokeStyle = level.color;
    ctx.lineWidth = 1;
    ctx.setLineDash([]);
    roundedRect(ctx, boxX, boxY, boxWidth, 22, 4);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = level.color;
    ctx.fillText(text, boxX + 6, boxY + 15);
    ctx.restore();
  });

  const markerIndex = visible.length - 1;
  const marker = visible[markerIndex];
  if (marker) {
    const markerX = clamp(width - pad.right - 140, pad.left + 18, width - pad.right - 18);
    drawEntryArrow(ctx, markerX, y(signal.entry), signal.direction);
  }
}

function drawEntryArrow(ctx, x, entryY, direction) {
  const long = direction === "long";
  const color = long ? "#2fd17c" : "#ff5c66";
  const sign = long ? 1 : -1;
  const tipY = entryY;
  const shoulderY = tipY + sign * 10;
  const tailY = tipY + sign * 27;

  ctx.save();
  ctx.shadowColor = "rgba(0, 0, 0, 0.75)";
  ctx.shadowBlur = 5;
  ctx.fillStyle = color;
  ctx.strokeStyle = "#eef2f4";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(x, tipY);
  ctx.lineTo(x - 9, shoulderY);
  ctx.lineTo(x - 4, shoulderY);
  ctx.lineTo(x - 4, tailY);
  ctx.lineTo(x + 4, tailY);
  ctx.lineTo(x + 4, shoulderY);
  ctx.lineTo(x + 9, shoulderY);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  ctx.restore();
}

function roundedRect(ctx, x, y, width, height, radius) {
  const r = Math.min(radius, width / 2, height / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + width - r, y);
  ctx.quadraticCurveTo(x + width, y, x + width, y + r);
  ctx.lineTo(x + width, y + height - r);
  ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
  ctx.lineTo(x + r, y + height);
  ctx.quadraticCurveTo(x, y + height, x, y + height - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

function drawLine(ctx, candles, x, y, key, color, lineWidth = 1.7, dash = []) {
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = lineWidth;
  ctx.setLineDash(dash);
  ctx.beginPath();
  let started = false;
  candles.forEach((candle, index) => {
    if (!Number.isFinite(candle[key])) return;
    const px = x(index);
    const py = y(candle[key]);
    if (!started) {
      ctx.moveTo(px, py);
      started = true;
    }
    else ctx.lineTo(px, py);
  });
  if (started) ctx.stroke();
  ctx.restore();
}

function drawIndicatorLabel(ctx, candles, y, key, label, color, width, pad) {
  const latest = [...candles].reverse().find((candle) => Number.isFinite(candle[key]));
  if (!latest) return;
  const py = clamp(y(latest[key]) - 16, pad.top + 2, pad.top + state.chartGeometry.chartH - 18);
  const labelWidth = 38;
  const x = width - pad.right - labelWidth - 4;
  ctx.save();
  ctx.fillStyle = "rgba(17, 20, 23, 0.86)";
  roundedRect(ctx, x, py, labelWidth, 16, 3);
  ctx.fill();
  ctx.fillStyle = color;
  ctx.font = "800 9px ui-sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(label, x + labelWidth / 2, py + 8);
  ctx.restore();
}

function setTone(element, tone) {
  element.classList.remove("positive", "negative", "neutral");
  element.classList.add(tone);
}

function candidateBlocker(candidate) {
  if (!candidate) return "No setup candidate";
  if (candidate.score < activeTradeThreshold()) return `Score below ${activeTradeThreshold()} threshold`;
  if (candidate.watchOnly) return "Risk/reward or target distance is not clean";
  return "Eligible";
}

function renderCandidateComparison(signal) {
  const rows = [
    { label: "Long", candidate: signal.bestLong, tone: "positive" },
    { label: "Short", candidate: signal.bestShort, tone: "negative" },
  ];
  const bestSide = (signal.bestLong?.score || 0) > (signal.bestShort?.score || 0)
    ? "Long"
    : (signal.bestShort?.score || 0) > (signal.bestLong?.score || 0)
      ? "Short"
      : "Mixed";
  els.bestSideBadge.textContent = bestSide;
  setTone(els.bestSideBadge, bestSide === "Long" ? "positive" : bestSide === "Short" ? "negative" : "neutral");
  els.whyRejected.innerHTML = rows.map(({ label, candidate }) => `
    <div class="compare-card">
      <strong>${label} ${candidate ? `${candidate.score}/100` : "--"}</strong>
      <span>${escapeHtml(candidate?.setup || "No candidate")}</span>
      <span>${escapeHtml(candidateBlocker(candidate))}</span>
      <ul>${(candidate?.reasons || []).slice(0, 3).map((reason) => `<li>${escapeHtml(reason)}</li>`).join("")}</ul>
    </div>
  `).join("");
}

function renderBias(signal) {
  const score = Number(signal.biasScore || 0);
  const pct = clamp((score + 100) / 2, 0, 100);
  els.biasFill.style.width = `${pct}%`;
  els.biasFill.style.background = score > 15 ? "var(--green)" : score < -15 ? "var(--red)" : "var(--yellow)";
  els.biasScore.textContent = score > 0 ? `+${score}` : String(score);
  const label = score > 20 ? "Long" : score < -20 ? "Short" : "Mixed";
  els.biasBadge.textContent = label;
  setTone(els.biasBadge, label === "Long" ? "positive" : label === "Short" ? "negative" : "neutral");
}

function renderMarketConfirmation(signal) {
  if (API_SYMBOL !== "QQQ") return;
  const confirmation = signal.marketConfirmation || {};
  const relative = confirmation.relativeStrength || {};
  const spyTrends = confirmation.spyTrends || {};
  const adjustment = Number(confirmation.scoreAdjustment || 0);
  const trendSummary = ["5", "15", "1D"]
    .map((timeframe) => spyTrends[timeframe]?.label)
    .filter(Boolean)
    .join(" / ");

  els.marketConfirmationBadge.textContent = confirmation.label || "Building";
  setTone(els.marketConfirmationBadge, confirmation.tone || "neutral");
  els.marketRelativeStrength.textContent = relative.pct == null
    ? relative.label || "Building"
    : `${relative.label || "Neutral"} ${relative.pct >= 0 ? "+" : ""}${fmt(relative.pct, 2)}%`;
  setTone(els.marketRelativeStrength, relative.tone || "neutral");
  els.marketSpyTrend.textContent = trendSummary || "Building";
  const trendTone = confirmation.tone === "positive" || confirmation.tone === "negative"
    ? confirmation.tone
    : "neutral";
  setTone(els.marketSpyTrend, trendTone);
  els.marketConfirmationScore.textContent = adjustment === 0 ? "0 pts" : `${adjustment > 0 ? "+" : ""}${adjustment} pts`;
  setTone(els.marketConfirmationScore, adjustment > 0 ? "positive" : adjustment < 0 ? "negative" : "neutral");
  els.marketConfirmationDetail.textContent = confirmation.detail || "Waiting for SPY confirmation.";
}

function isActionableSignal(signal) {
  return Boolean(
    signal
    && signal.direction !== "neutral"
    && !signal.watchOnly
    && signal.score >= activeTradeThreshold()
    && state.dataHealth?.tradeAllowed !== false,
  );
}

function renderBestOpportunity(opportunity) {
  if (!opportunity) {
    state.bestOpportunityTimeframe = null;
    els.bestOpportunityBadge.textContent = "No trade";
    setTone(els.bestOpportunityBadge, "neutral");
    els.bestOpportunityDetail.textContent = "No actionable intraday momentum plan is confirmed.";
    els.bestOpportunityView.hidden = true;
    return;
  }

  const { timeframe, signal } = opportunity;
  state.bestOpportunityTimeframe = timeframe;
  els.bestOpportunityBadge.textContent = `${timeframeLabel(timeframe)} ${signal.direction}`;
  setTone(els.bestOpportunityBadge, signal.direction === "long" ? "positive" : "negative");
  els.bestOpportunityDetail.textContent = `${signal.setup}. Entry ${fmt(signal.entry)}, invalidation ${fmt(signal.stop)}, T1 ${fmt(signal.target)}, score ${signal.score}/100.`;
  els.bestOpportunityView.textContent = `View ${timeframeLabel(timeframe)} chart`;
  els.bestOpportunityView.hidden = timeframe === state.selectedTimeframe;
}

function renderBestSwing(analysis) {
  const signal = analysis?.signal;
  const actionable = isActionableSignal(signal);
  const candidate = actionable
    ? signal
    : [signal?.bestLong, signal?.bestShort]
      .filter(Boolean)
      .sort((a, b) => b.score - a.score || (b.riskReward || 0) - (a.riskReward || 0))[0];

  state.bestSwingTimeframe = candidate ? DAILY_TIMEFRAME : null;
  els.bestSwingView.hidden = !candidate || state.selectedTimeframe === DAILY_TIMEFRAME;
  if (!candidate) {
    els.bestSwingBadge.textContent = "No trade";
    setTone(els.bestSwingBadge, "neutral");
    els.bestSwingScore.textContent = "--";
    els.bestSwingDetail.textContent = "No daily bull or bear momentum setup is confirmed.";
    els.bestSwingRationale.textContent = "Waiting for a daily setup with enough structure, momentum, and reward relative to risk.";
    [els.bestSwingEntry, els.bestSwingStop, els.bestSwingTarget1, els.bestSwingTarget2].forEach((element) => {
      element.textContent = "--";
    });
    return;
  }

  const long = candidate.direction === "long";
  const directionTone = long ? "positive" : "negative";
  const target1Pct = ((candidate.target / candidate.entry) - 1) * 100;
  const target2Pct = ((candidate.target2 / candidate.entry) - 1) * 100;
  const signedPct = (value) => `${value >= 0 ? "+" : ""}${fmt(value, 2)}%`;
  const scale = { scalp: 0.9, normal: 1, strict: 1.1 }[state.settings.mode] || 1;
  const minTargetPct = (ASSET_OPTIONS.continuous ? 2 : 1.2) * scale;
  const maxTargetPct = (ASSET_OPTIONS.continuous ? 5 : 2.5) * scale;
  const maxTarget2Pct = (ASSET_OPTIONS.continuous ? 8 : 4) * scale;

  els.bestSwingBadge.textContent = actionable ? `1D ${candidate.direction}` : `Watch ${candidate.direction}`;
  setTone(els.bestSwingBadge, actionable ? directionTone : "neutral");
  els.bestSwingScore.textContent = `${candidate.score}/100`;
  els.bestSwingDetail.textContent = actionable
    ? `${candidate.setup} is confirmed. The plan activates only if ${API_SYMBOL} reaches the entry trigger.`
    : `${candidate.setup} is the strongest daily candidate, but it remains watch-only because its confirmation or reward relative to risk is not yet strong enough.`;
  els.bestSwingEntryLabel.textContent = long ? "Buy above" : "Short below";
  els.bestSwingStopLabel.textContent = long ? "Sell if invalid" : "Cover if invalid";
  els.bestSwingTarget1Label.textContent = long ? "Sell target 1" : "Cover target 1";
  els.bestSwingTarget2Label.textContent = long ? "Sell target 2" : "Cover target 2";
  els.bestSwingEntry.textContent = `$${fmt(candidate.entry)}`;
  els.bestSwingStop.textContent = `$${fmt(candidate.stop)}`;
  els.bestSwingTarget1.textContent = `$${fmt(candidate.target)} (${signedPct(target1Pct)})`;
  els.bestSwingTarget2.textContent = `$${fmt(candidate.target2)} (${signedPct(target2Pct)})`;
  els.bestSwingRationale.textContent = `Daily EMA 20/50, SMA 150, RSI, volume, and 5/20-day momentum determine whether this setup qualifies and how it scores. Target 1 at $${fmt(candidate.target)} projects a ${fmt(Math.abs(target1Pct), 2)}% ${long ? "rise" : "decline"} from entry; its distance uses at least ${fmt(minTargetPct, 2)}% or 1.2 times the structure-based risk, capped near ${fmt(maxTargetPct, 2)}%. Target 2 extends the move toward $${fmt(candidate.target2)}, capped near ${fmt(maxTarget2Pct, 2)}%. These are model projections, not guaranteed prices.`;
}

function optionsDate(value) {
  const timestamp = Number(value);
  if (!Number.isFinite(timestamp)) return "--";
  return new Date(timestamp).toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
}

function renderOptionsOpportunity() {
  const opportunity = state.optionsOpportunity;
  if (!opportunity || opportunity.status === "none") {
    els.optionsOpportunity.hidden = true;
    return;
  }
  els.optionsOpportunity.hidden = false;
  const underlyingSymbol = opportunity.underlyingSymbol || opportunity.symbol || API_SYMBOL;
  const optionSymbol = opportunity.optionSymbol || underlyingSymbol;
  const side = String(opportunity.sideLabel || opportunity.side || "").toUpperCase();
  const long = side === "CALL";
  const contract = opportunity.contract;
  const underlying = opportunity.underlying || {};
  const dte = opportunity.dte || {};
  const delta = opportunity.delta || {};
  const provider = opportunity.provider || {};

  els.optionsEyebrow.textContent = `${underlyingSymbol} momentum via ${optionSymbol}`;
  els.optionsOpportunityTitle.textContent = `${optionSymbol} Options Opportunity`;
  els.optionsEntryLabel.textContent = `${underlyingSymbol} entry`;
  els.optionsStopLabel.textContent = `${underlyingSymbol} invalidation`;
  els.optionsTargetsLabel.textContent = `${underlyingSymbol} targets`;
  els.optionsBadge.textContent = `${side} ${timeframeLabel(Number(opportunity.timeframe))}`;
  setTone(els.optionsBadge, long ? "positive" : "negative");
  els.optionsDataStatus.textContent = contract
    ? (provider.delayed ? "Delayed contract" : "Contract")
    : "Strike / DTE guidance";
  els.optionsDataStatus.classList.toggle("delayed", Boolean(provider.delayed));
  els.optionsScore.textContent = `${Number(opportunity.score || 0)}/100`;
  els.optionsDetail.textContent = opportunity.detail || `${side} momentum opportunity.`;

  if (contract) {
    const expiration = optionsDate(contract.expiration);
    els.optionsContract.textContent = contract.optionSymbol || `${side} $${fmt(Number(contract.strike))}`;
    els.optionsExpiration.textContent = `${expiration} (${Number(contract.dte)} DTE)`;
    els.optionsDelta.textContent = fmt(Math.abs(Number(contract.delta)), 2);
    els.optionsCost.textContent = `$${fmt(Number(contract.mid))} / $${fmt(Number(contract.costPerContract), 0)}`;
    const scenarios = contract.scenarios;
    els.optionsProjection.textContent = scenarios
      ? `At ${underlyingSymbol} T1 $${fmt(Number(underlying.target1))}, estimated option mid is $${fmt(Number(scenarios.target1.estimatedOptionMid))} (${fmt(Number(scenarios.target1.estimatedReturnPct), 1)}%). At ${underlyingSymbol} T2 $${fmt(Number(underlying.target2))}, the estimate is $${fmt(Number(scenarios.target2.estimatedOptionMid))}. ${scenarios.method}`
      : `Option value scenarios are unavailable for this quote; use the ${underlyingSymbol} invalidation and targets.`;
  } else {
    els.optionsContract.textContent = `${opportunity.strikeGuidance?.label || "ATM to 1% ITM"} $${fmt(Number(opportunity.strikeGuidance?.min))}-$${fmt(Number(opportunity.strikeGuidance?.max))}`;
    els.optionsExpiration.textContent = `${dte.min}-${dte.max} DTE; target ${dte.target}`;
    els.optionsDelta.textContent = `${fmt(Number(delta.min), 2)}-${fmt(Number(delta.max), 2)}; target ${fmt(Number(delta.target), 2)}`;
    els.optionsCost.textContent = "Broker quote required";
    els.optionsProjection.textContent = `${underlyingSymbol} target 1 is $${fmt(Number(underlying.target1))} and target 2 is $${fmt(Number(underlying.target2))}. Exact ${optionSymbol} option-price estimates require a qualifying contract quote and Greeks.`;
  }
  els.optionsEntry.textContent = `$${fmt(Number(underlying.entry))}`;
  els.optionsStop.textContent = `$${fmt(Number(underlying.stop))}`;
  els.optionsTargets.textContent = `$${fmt(Number(underlying.target1))} / $${fmt(Number(underlying.target2))}`;
}

function maybeOptionsAlert() {
  const opportunity = state.optionsOpportunity;
  if (!opportunity || opportunity.status === "none" || !opportunity.signalKey) return;
  if (opportunity.signalKey === state.lastOptionsAlertKey) return;
  state.lastOptionsAlertKey = opportunity.signalKey;
  try {
    window.sessionStorage.setItem(OPTIONS_ALERT_STORAGE_KEY, opportunity.signalKey);
  } catch (error) {
    console.info("Options alert key could not be stored.", error);
  }
  const contract = opportunity.contract;
  const underlyingSymbol = opportunity.underlyingSymbol || opportunity.symbol || API_SYMBOL;
  const optionSymbol = opportunity.optionSymbol || underlyingSymbol;
  const contractText = contract
    ? `${contract.optionSymbol} near $${fmt(Number(contract.mid))}`
    : `${opportunity.strikeGuidance?.label || "ATM to 1% ITM"}, ${opportunity.dte?.min}-${opportunity.dte?.max} DTE`;
  const item = {
    time: new Date(),
    text: `${optionSymbol} ${opportunity.sideLabel} candidate ${opportunity.score}/100: ${contractText}. ${underlyingSymbol} invalidation ${fmt(Number(opportunity.underlying?.stop))}, targets ${fmt(Number(opportunity.underlying?.target1))} / ${fmt(Number(opportunity.underlying?.target2))}.`,
  };
  state.alerts.unshift(item);
  state.alerts = state.alerts.slice(0, 25);
  renderAlertLog();
  if (state.notifyEnabled && Notification.permission === "granted") {
    new Notification(`${optionSymbol} Options Opportunity`, { body: item.text });
  }
}

function renderLifecycle(signal, confirmed) {
  const activePlanId = state.activePlanIds[state.selectedTimeframe] || "";
  const journalPlan = state.journalRecent.find((row) => row.id === activePlanId);
  const journalActive = journalPlan
    && ["waiting", "entered"].includes(journalPlan.lifecycle_status)
    && ["open", "target1"].includes(journalPlan.outcome_status);
  const feedbackEnabled = Boolean(activePlanId && (confirmed || journalActive));
  [els.feedbackTook, els.feedbackSkipped, els.feedbackBad].forEach((button) => {
    button.disabled = !feedbackEnabled;
  });
  if (journalActive) {
    const label = journalPlan.outcome_status === "target1" ? "T1 hit" : journalPlan.lifecycle_status === "entered" ? "Entered" : "Waiting";
    els.lifecycleBadge.textContent = label;
    setTone(els.lifecycleBadge, "positive");
    els.lifecycleDetail.textContent = `${journalPlan.direction.toUpperCase()} ${timeframeLabel(Number(journalPlan.timeframe))} plan: entry ${fmt(Number(journalPlan.entry))}, invalidation ${fmt(Number(journalPlan.stop))}, T1 ${fmt(Number(journalPlan.target1))}.`;
    return;
  }
  if (!confirmed) {
    els.lifecycleBadge.textContent = "Idle";
    setTone(els.lifecycleBadge, "neutral");
    els.lifecycleDetail.textContent = "No active plan is waiting for entry.";
    return;
  }
  els.lifecycleBadge.textContent = "Waiting";
  setTone(els.lifecycleBadge, "positive");
  els.lifecycleDetail.textContent = `${signal.direction.toUpperCase()} plan is waiting for entry at ${fmt(signal.entry)}. Invalidation ${fmt(signal.stop)}, T1 ${fmt(signal.target)}.`;
}

function renderCalibration(signal) {
  const comparisonCandidates = [signal?.bestLong, signal?.bestShort].filter(Boolean).sort((a, b) => Number(b.score || 0) - Number(a.score || 0));
  const subject = signal?.direction === "long" || signal?.direction === "short" ? signal : comparisonCandidates[0];
  const calibration = subject?.calibration || {};
  const model = subject?.modelConfidence || {};
  const modelSamples = Number(model.sampleSize || 0);
  const modelTargetRate = Number(model.target1Rate);
  const modelExpectedR = Number(model.expectedR);
  const modelLow = Number(model.confidenceLow);
  const modelHigh = Number(model.confidenceHigh);
  const modelMfe = Number(model.avgMfeR);
  const modelMae = Number(model.avgMaeR);
  const modelHoldingMs = Number(model.avgHoldingMs);
  const samples = Number(calibration.sampleSize || 0);
  const probability = Number(calibration.probabilityT1);
  const expectedR = Number(calibration.expectedR);
  const low = Number(calibration.confidenceLow);
  const high = Number(calibration.confidenceHigh);
  if (modelSamples && Number.isFinite(modelTargetRate)) {
    const established = model.status === "Established";
    els.calibrationBadge.textContent = model.status || "Developing";
    setTone(els.calibrationBadge, established ? "positive" : "neutral");
    els.calibrationProbability.textContent = `${fmt(modelTargetRate * 100, 0)}%`;
    els.calibrationExpectedR.textContent = Number.isFinite(modelExpectedR)
      ? `${modelExpectedR >= 0 ? "+" : ""}${fmt(modelExpectedR, 2)}R`
      : "--";
    setTone(els.calibrationExpectedR, modelExpectedR > 0 ? "positive" : modelExpectedR < 0 ? "negative" : "neutral");
    els.calibrationSamples.textContent = modelSamples;
    els.calibrationRange.textContent = Number.isFinite(modelLow) && Number.isFinite(modelHigh)
      ? `${fmt(modelLow * 100, 0)}-${fmt(modelHigh * 100, 0)}%`
      : "--";
    els.calibrationExcursion.textContent = Number.isFinite(modelMfe) && Number.isFinite(modelMae)
      ? `${fmt(modelMfe, 2)}R / ${fmt(modelMae, 2)}R`
      : "--";
    els.calibrationHoldingTime.textContent = fmtDuration(modelHoldingMs);
    els.calibrationScope.textContent = `${subject?.setup || "Candidate"}. Live model uses ${model.scope || "comparable"} outcomes, with a neutral prior and conservative range until the sample grows.`;
    return;
  }
  if (!samples || !Number.isFinite(probability)) {
    els.calibrationBadge.textContent = "Building";
    setTone(els.calibrationBadge, "neutral");
    els.calibrationProbability.textContent = "--";
    els.calibrationExpectedR.textContent = "--";
    els.calibrationSamples.textContent = samples || "--";
    els.calibrationRange.textContent = "--";
    els.calibrationExcursion.textContent = "--";
    els.calibrationHoldingTime.textContent = "--";
    els.calibrationScope.textContent = "Waiting for automatically resolved comparable plans and historical replay data.";
    return;
  }
  els.calibrationBadge.textContent = calibration.calibrated ? "Replay baseline" : "Replay only";
  setTone(els.calibrationBadge, calibration.calibrated ? "positive" : "neutral");
  els.calibrationProbability.textContent = `${fmt(probability * 100, 0)}%`;
  els.calibrationExpectedR.textContent = Number.isFinite(expectedR) ? `${expectedR >= 0 ? "+" : ""}${fmt(expectedR, 2)}R` : "--";
  setTone(els.calibrationExpectedR, expectedR > 0 ? "positive" : expectedR < 0 ? "negative" : "neutral");
  els.calibrationSamples.textContent = samples;
  els.calibrationRange.textContent = Number.isFinite(low) && Number.isFinite(high)
    ? `${fmt(low * 100, 0)}-${fmt(high * 100, 0)}%`
    : "--";
  els.calibrationExcursion.textContent = "--";
  els.calibrationHoldingTime.textContent = "--";
  els.calibrationScope.textContent = `${subject?.setup || "Candidate"}. Live model is still building; this is a ${calibration.scope || "historical replay"} baseline with a neutral prior.`;
}

function render(signal, indicators) {
  const latest = indicators[indicators.length - 1];
  const previousClose = isDailyTimeframe()
    ? indicators[indicators.length - 2]?.close
    : Core.previousRegularClose(state.candles, latest.time, ASSET_OPTIONS);
  const today = isDailyTimeframe() ? [] : Core.regularSessionCandles(state.candles, latest.time, ASSET_OPTIONS);
  const reference = previousClose || today[0]?.open || latest.open || latest.close;
  const change = latest.close - reference;
  const changePct = (change / reference) * 100;
  const planLabels = signal.direction === "short"
    ? { entry: "Short trigger", stop: "Cover if invalid", target1: "Cover target 1", target2: "Cover target 2" }
    : signal.direction === "long"
      ? { entry: "Buy trigger", stop: "Sell if invalid", target1: "Sell target 1", target2: "Sell target 2" }
      : { entry: "Entry trigger", stop: "Invalidation", target1: "Target 1", target2: "Target 2" };

  els.lastPrice.textContent = fmt(latest.close);
  els.priceChange.textContent = `${change >= 0 ? "+" : ""}${fmt(change)} (${fmt(changePct)}%)`;
  setTone(els.priceChange, change > 0 ? "positive" : change < 0 ? "negative" : "neutral");

  els.trend1m.textContent = signal.trend1.label;
  els.trend5m.textContent = signal.trend5.label;
  els.trend15m.textContent = signal.trend15.label;
  els.trendBadge.textContent = `${timeframeLabel()} ${signal.selectedTrend.label}`;
  setTone(els.trendBadge, signal.selectedTrend.tone);

  const generalTrend = buildGeneralTrend();
  els.generalTrendBadge.textContent = generalTrend.overall.label;
  setTone(els.generalTrendBadge, generalTrend.overall.tone);
  els.generalTrend1m.textContent = generalTrend.one.label;
  els.generalTrend5m.textContent = generalTrend.five.label;
  els.generalTrend15m.textContent = generalTrend.fifteen.label;
  els.generalTrend1d.textContent = generalTrend.daily.label;
  setTone(els.generalTrend1m, generalTrend.one.tone);
  setTone(els.generalTrend5m, generalTrend.five.tone);
  setTone(els.generalTrend15m, generalTrend.fifteen.tone);
  setTone(els.generalTrend1d, generalTrend.daily.tone);
  els.regimeBadge.textContent = signal.regime?.label || "--";
  setTone(els.regimeBadge, signal.regime?.tone || "neutral");
  els.regimeDetail.textContent = signal.regime?.detail || "--";
  renderBias(signal);
  renderMarketConfirmation(signal);
  renderCandidateComparison(signal);

  els.confidenceScore.textContent = `${Number(signal.score || 0)}/100`;
  renderCalibration(signal);
  const confirmed = signal.direction !== "neutral" && signal.score >= activeTradeThreshold() && !signal.watchOnly;
  renderLifecycle(signal, confirmed);
  const statusText = signal.direction === "neutral"
    ? "Watchlist only. No trade alert is active."
    : confirmed
      ? `${signal.direction.toUpperCase()} entry candidate. You decide whether to trade.`
      : `${signal.direction.toUpperCase()} watch plan. Waiting for confirmation.`;
  els.activeAlert.innerHTML = `
    <span class="alert-title">${escapeHtml(signal.setup)}</span>
    <span>${escapeHtml(statusText)}</span>
    <ul class="alert-reasons">${signal.reasons.map((reason) => `<li>${escapeHtml(reason)}</li>`).join("")}</ul>
    <ul class="alert-reasons">${signal.exitRules.map((rule) => `<li>${escapeHtml(rule)}</li>`).join("")}</ul>
  `;

  document.querySelector("#entryLevel").previousElementSibling.textContent = planLabels.entry;
  document.querySelector("#stopLevel").previousElementSibling.textContent = planLabels.stop;
  document.querySelector("#targetLevel").previousElementSibling.textContent = planLabels.target1;
  document.querySelector("#target2Level").previousElementSibling.textContent = planLabels.target2;

  els.entryLevel.textContent = signal.entry ? fmt(signal.entry) : "--";
  els.stopLevel.textContent = signal.stop ? fmt(signal.stop) : "--";
  els.targetLevel.textContent = signal.target ? fmt(signal.target) : "--";
  els.target2Level.textContent = signal.target2 ? fmt(signal.target2) : "--";
  els.exitWarning.textContent = signal.exitWarning || "--";
  els.riskReward.textContent = signal.riskReward ? `1:${fmt(signal.riskReward, 1)}` : "--";

  els.vwapMetric.textContent = isDailyTimeframe() ? "--" : fmt(latest.vwap);
  els.smaMetric.textContent = `${fmt(latest.sma20)} / ${fmt(latest.sma50)} / ${fmt(latest.sma150)}`;
  els.emaMetric.textContent = `${fmt(latest.ema20)} / ${fmt(latest.ema50)} / ${fmt(latest.ema150)}`;
  els.rsiMetric.textContent = fmt(latest.rsi, 1);
  els.atrMetric.textContent = fmt(latest.atr, 2);
  els.rvolMetric.textContent = Number.isFinite(latest.relativeVolume) ? `${fmt(latest.relativeVolume, 2)}x` : "--";
}

function maybeAlert(signal, timeframe = state.selectedTimeframe) {
  if (signal.watchOnly) return;
  if (signal.direction === "neutral" || signal.score < alertLogThreshold()) return;
  const entryBucket = Math.round((signal.entry || 0) * 10);
  const key = `${signal.setupType || setupType(signal.setup)}-${signal.direction}-${timeframe}-${entryBucket}`;
  const now = Date.now();
  const prior = state.lastAlertsByTimeframe[timeframe] || {};
  const cooldown = timeframe === DAILY_TIMEFRAME ? 12 * 60 * 60 * 1000 : Number(state.settings.alertCooldownMinutes || 15) * 60 * 1000;
  if (key === prior.key && now - Number(prior.at || 0) < cooldown) return;
  state.lastAlertsByTimeframe[timeframe] = { key, at: now };

  const item = {
    time: new Date(),
    text: signal.direction === "long"
      ? `BUY ${signal.setup} ${signal.score}/100 near ${fmt(signal.entry)} | sell zone ${fmt(signal.target)} / ${fmt(signal.target2)}`
      : `SHORT ${signal.setup} ${signal.score}/100 near ${fmt(signal.entry)} | cover zone ${fmt(signal.target)} / ${fmt(signal.target2)}`,
  };
  state.alerts.unshift(item);
  state.alerts = state.alerts.slice(0, 25);
  renderAlertLog();

  if (state.notifyEnabled && Notification.permission === "granted") {
    new Notification(`${API_SYMBOL} alert candidate`, { body: item.text });
  }
}

function renderAlertLog() {
  els.alertLog.innerHTML = state.alerts
    .map((alert) => `<li><time>${alert.time.toLocaleTimeString([], { hour12: false })}</time>${escapeHtml(alert.text)}</li>`)
    .join("");
}

function finiteOrNull(value) {
  return Number.isFinite(value) ? value : null;
}

function planJournalId(signal, latest, timeframe = state.selectedTimeframe) {
  const entryBucket = Math.round((signal.entry || 0) * 20);
  return [
    API_SYMBOL,
    timeframe,
    signal.direction,
    signal.setup,
    latest.time,
    entryBucket,
  ].join("|");
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(`${url} failed: ${response.status}`);
  return response.json();
}

function savePlanToJournal(signal, latest, timeframe = state.selectedTimeframe) {
  if (signal.watchOnly || signal.score < activeTradeThreshold()) return;
  if (signal.direction === "neutral" || !signal.entry || !signal.stop || !signal.target || !signal.target2) return;
  const id = planJournalId(signal, latest, timeframe);
  if (id === state.lastJournalKeys[timeframe]) return;
  state.lastJournalKeys[timeframe] = id;

  postJson("/api/journal/plan", {
    symbol: API_SYMBOL,
    provider: state.providerLabel,
    timeframe,
    marketPhase: signal.marketPhase || marketPhase(latest.time),
    marketRegime: signal.regime?.type || "unknown",
    strategyVersion: STRATEGY_VERSION,
    settings: {
      mode: state.settings.mode,
      sessionMode: state.settings.sessionMode,
      activeTradeThreshold: activeTradeThreshold(),
    },
    dataQuality: state.dataQualityIssues.length ? state.dataQualityIssues.join(",") : "clean",
    timestamp: latest.time + timeframe * Core.MINUTE_MS,
    signalCandleTime: latest.time,
    price: latest.close,
    indicators: {
      rsi: finiteOrNull(latest.rsi),
      atr: finiteOrNull(latest.atr),
      vwap: finiteOrNull(latest.vwap),
      ema20: finiteOrNull(latest.ema20),
      ema50: finiteOrNull(latest.ema50),
      ema150: finiteOrNull(latest.ema150),
      sma20: finiteOrNull(latest.sma20),
      sma50: finiteOrNull(latest.sma50),
      sma150: finiteOrNull(latest.sma150),
    },
    trends: {
      selected: signal.selectedTrend.label,
      five: signal.trend5.label,
      fifteen: signal.trend15.label,
    },
    plan: {
      id,
      direction: signal.direction,
      setup: signal.setup,
      setupType: signal.setupType || setupType(signal.setup),
      watchOnly: Boolean(signal.watchOnly),
      score: signal.score,
      entry: signal.entry,
      stop: signal.stop,
      target: signal.target,
      target2: signal.target2,
      riskReward: signal.riskReward,
      reasons: signal.reasons,
      exitRules: signal.exitRules,
    },
  })
    .then((result) => {
      state.activePlanIds[timeframe] = result.id || result.duplicateOf || id;
      return refreshJournalStats(true);
    })
    .catch((error) => {
      state.lastJournalKeys[timeframe] = "";
      console.info("Journal save skipped.", error);
    });
}

async function refreshJournalStats(force = false) {
  const now = Date.now();
  if (!force && now - state.lastStatsAt < 8000) return;
  state.lastStatsAt = now;

  try {
    const response = await fetch(`/api/journal/stats?symbol=${encodeURIComponent(API_SYMBOL)}`);
    if (!response.ok) throw new Error(`stats failed: ${response.status}`);
    const data = await response.json();
    state.journalStats = data;
    const summary = data.summary || {};
    const targetHits = Number(summary.target1 || 0) + Number(summary.target2 || 0);
    const stopped = Number(summary.stopped || 0);
    const resolved = Number(summary.resolved || 0);
    const positiveRate = resolved ? (Number(summary.profitable || 0) / resolved) * 100 : null;
    const bestSetup = (data.bySetup || []).find((row) => Number(row.winners || 0) + Number(row.stopped || 0) >= 2);
    const bestTimeframe = (data.byTimeframe || []).find((row) => Number(row.winners || 0) + Number(row.stopped || 0) >= 2);

    els.journalTotal.textContent = summary.total || 0;
    els.journalTargets.textContent = targetHits;
    els.journalStops.textContent = stopped;
    els.journalOpen.textContent = summary.open || 0;
    els.journalWaiting.textContent = summary.waiting || 0;
    els.journalEntered.textContent = summary.entered || 0;
    els.journalExpired.textContent = summary.expired || 0;
    els.journalWinRate.textContent = positiveRate === null ? "--" : `${fmt(positiveRate, 0)}%`;
    els.journalExpectancy.textContent = resolved ? `${fmt(Number(summary.avg_realized_r || 0), 2)}R` : "--";
    els.journalBestSetup.textContent = bestSetup ? bestSetup.setup_type : "--";
    els.journalBestTimeframe.textContent = bestTimeframe ? `${bestTimeframe.timeframe}m` : "--";
    state.journalRecent = data.recent || [];
    Object.entries(state.activePlanIds).forEach(([timeframe, planId]) => {
      const activeRow = state.journalRecent.find((row) => row.id === planId);
      if (activeRow && !["waiting", "entered"].includes(activeRow.lifecycle_status)) {
        delete state.activePlanIds[timeframe];
      }
    });
    renderJournalRows();
    refreshReplayStats();
  } catch (error) {
    console.info("Journal stats unavailable.", error);
  }
}

async function refreshReplayStats() {
  try {
    const response = await fetch(`/api/backtest?symbol=${encodeURIComponent(API_SYMBOL)}`);
    if (!response.ok) throw new Error(`replay failed: ${response.status}`);
    state.replayStats = await response.json();
    renderReplaySummary(state.replayStats);
  } catch (error) {
    console.info("Replay stats unavailable.", error);
  }
}

function renderReplaySummary(data) {
  const summary = data.summary || {};
  const resolved = Number(summary.resolved || 0);
  if (!resolved) {
    els.replayBest.textContent = data.status === "error" ? "Error" : "Building";
    setTone(els.replayBest, data.status === "error" ? "negative" : "neutral");
    els.replayAvgTarget.textContent = "--";
    els.replayAvgStop.textContent = "--";
    els.replaySamples.textContent = "--";
    els.replayExcursion.textContent = "--";
    return;
  }
  els.replayBest.textContent = "Ready";
  setTone(els.replayBest, "positive");
  els.replayAvgTarget.textContent = Number.isFinite(Number(summary.probabilityT1)) ? `${fmt(Number(summary.probabilityT1) * 100, 0)}%` : "--";
  const expectedR = Number(summary.expectedR);
  els.replayAvgStop.textContent = Number.isFinite(expectedR) ? `${expectedR >= 0 ? "+" : ""}${fmt(expectedR, 2)}R` : "--";
  setTone(els.replayAvgStop, expectedR > 0 ? "positive" : expectedR < 0 ? "negative" : "neutral");
  els.replaySamples.textContent = resolved;
  els.replayExcursion.textContent = `${fmt(Number(summary.avgFavorableR || 0), 2)}R / ${fmt(Number(summary.avgAdverseR || 0), 2)}R`;
}

function renderJournalRows() {
  const filter = els.journalFilter.value;
  const rows = (state.journalRecent || []).filter((row) => {
    if (filter === "all") return true;
    if (filter === "target") return row.outcome_status === "target1" || row.outcome_status === "target2";
    if (filter === "open") return row.outcome_status === "open" || row.lifecycle_status === "waiting";
    if (filter === "long" || filter === "short") return row.direction === filter;
    return row.outcome_status === filter;
  });

  els.journalRows.innerHTML = rows.slice(0, 30).map((row) => {
    const time = new Date(Number(row.created_at)).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return `
      <tr>
        <td>${time}</td>
        <td>${Number(row.timeframe) === DAILY_TIMEFRAME ? "1D" : `${escapeHtml(row.timeframe)}m`}</td>
        <td class="${row.direction === "long" ? "positive" : "negative"}">${escapeHtml(row.direction)}</td>
        <td>${escapeHtml(row.setup_type || row.setup || "unknown")}</td>
        <td>${escapeHtml(row.score)}</td>
        <td>${escapeHtml(row.outcome_status === "open" ? row.lifecycle_status : row.outcome_status)}</td>
        <td>${fmt(Number(row.entry))}</td>
        <td>${fmt(Number(row.target1))}</td>
        <td>${fmt(Number(row.stop))}</td>
      </tr>
    `;
  }).join("");
}

function sendFeedback(feedback) {
  const activePlanId = state.activePlanIds[state.selectedTimeframe];
  if (!activePlanId) return;
  postJson("/api/journal/feedback", { id: activePlanId, feedback })
    .then(() => refreshJournalStats(true))
    .catch((error) => console.info("Feedback save skipped.", error));
}

function analyzeTimeframe(timeframe) {
  const previousTimeframe = state.selectedTimeframe;
  state.selectedTimeframe = timeframe;
  try {
    const indicators = calculateIndicators(selectedCandles(true));
    const serverSignal = state.serverRecommendations?.[timeframe];
    const signal = serverSignal || { ...neutralSignal("Waiting for the Python analysis engine.", indicators), timeframe };
    return { timeframe, indicators, signal };
  } finally {
    state.selectedTimeframe = previousTimeframe;
  }
}

function applyServerRecommendations(payload) {
  applyDataHealth(payload?.dataHealth);
  const recommendations = payload?.recommendations;
  if (recommendations && typeof recommendations === "object") {
    state.serverRecommendations = recommendations;
  }
  if (payload?.optionsOpportunity && typeof payload.optionsOpportunity === "object") {
    state.optionsOpportunity = payload.optionsOpportunity;
  }
}

function selectTimeframe(timeframe) {
  state.selectedTimeframe = Number(timeframe);
  els.timeframeButtons.forEach((item) => item.classList.toggle("active", Number(item.dataset.timeframe) === state.selectedTimeframe));
  syncVwapControl();
  refresh();
}

function refresh() {
  const selectedTimeframe = state.selectedTimeframe;
  const analyses = ALERT_TIMEFRAMES.map(analyzeTimeframe);
  state.timeframeAnalyses = Object.fromEntries(analyses.map((analysis) => [analysis.timeframe, analysis]));
  state.selectedTimeframe = selectedTimeframe;

  const actionable = analyses
    .filter((analysis) => analysis.timeframe !== DAILY_TIMEFRAME)
    .filter((analysis) => isActionableSignal(analysis.signal))
    .sort((a, b) => b.signal.score - a.signal.score || (b.signal.riskReward || 0) - (a.signal.riskReward || 0));
  const bestOpportunity = actionable[0] || null;
  const swingAnalysis = analyses.find((analysis) => analysis.timeframe === DAILY_TIMEFRAME) || null;
  const chartIndicators = calculateIndicators(selectedCandles(false));
  const selectedAnalysis = state.timeframeAnalyses[selectedTimeframe];
  const indicators = selectedAnalysis?.indicators || calculateIndicators(selectedCandles(true));
  const signal = selectedAnalysis?.signal;
  if (!signal) return;
  drawChart(chartIndicators, signal);
  render(signal, chartIndicators);
  renderBestOpportunity(bestOpportunity);
  renderBestSwing(swingAnalysis);
  renderOptionsOpportunity();
  maybeOptionsAlert();
  analyses.forEach((analysis) => {
    const latest = analysis.indicators[analysis.indicators.length - 1];
    if (!latest) return;
    maybeAlert(analysis.signal, analysis.timeframe);
    if (!state.serverOwnsSignals) savePlanToJournal(analysis.signal, latest, analysis.timeframe);
  });
}

function stopLatestPolling() {
  clearInterval(state.pollTimer);
  state.pollTimer = null;
}

function stopHistorySync() {
  clearInterval(state.historySyncTimer);
  state.historySyncTimer = null;
}

async function fetchLatestCandle() {
  if (state.feedMode !== "real" || state.latestRequestPending) return false;
  state.latestRequestPending = true;
  try {
    const response = await fetch(`/api/latest?symbol=${API_SYMBOL}&t=${Date.now()}`);
    if (!response.ok) throw new Error(`latest failed: ${response.status}`);
    const data = await response.json();
    applyDataHealth(data.dataHealth);
    if (data.candle) {
      state.providerErrors = Number(data.providerErrors || 0);
      state.lastTickAt = Number(data.lastSuccessAt || Date.now());
      mergeCandle(data.candle);
      els.sessionState.textContent = state.providerErrors
        ? `${state.providerLabel} provider issue`
        : `${state.providerLabel} live ${new Date().toLocaleTimeString([], { hour12: false })}`;
      return true;
    }
    return false;
  } catch (error) {
    state.providerErrors += 1;
    els.sessionState.textContent = `${state.providerLabel} polling issue`;
    console.info("Latest price refresh skipped.", error);
    return false;
  } finally {
    state.latestRequestPending = false;
  }
}

async function syncIntradayHistory() {
  if (state.feedMode !== "real" || state.historySyncPending) return false;
  state.historySyncPending = true;
  try {
    const response = await fetch(`/api/history?symbol=${API_SYMBOL}&t=${Date.now()}`);
    if (!response.ok) throw new Error(`History sync failed: ${response.status}`);
    const data = await response.json();
    applyDataHealth(data.dataHealth);
    const incoming = cleanCandles(data.candles || []);
    if (!incoming.length) return false;
    state.candles = Core.mergeCandles([...state.candles, ...incoming]).slice(-2500);
    await fetchFiveMinuteHistory();
    state.marketCandleAt = state.candles.at(-1)?.time || state.marketCandleAt;
    state.lastTickAt = Date.now();
    state.providerErrors = Number(data.providerErrors || 0);
    state.lastTickAt = Number(data.lastSuccessAt || state.lastTickAt);
    refreshCurrentDailyCandle();
    assessDataQuality();
    refresh();
    return true;
  } catch (error) {
    console.info("Intraday history resync skipped.", error);
    return false;
  } finally {
    state.historySyncPending = false;
  }
}

async function fetchDailyHistory() {
  const response = await fetch(`/api/daily?symbol=${API_SYMBOL}`);
  if (!response.ok) throw new Error(`Daily history request failed: ${response.status}`);
  const data = await response.json();
  state.dailyCandles = Core.resampleDaily(data.candles || [], ASSET_OPTIONS).slice(-520);
  refreshCurrentDailyCandle();
}

async function fetchFiveMinuteHistory() {
  const response = await fetch(`/api/five-minute?symbol=${API_SYMBOL}`);
  if (!response.ok) throw new Error(`Five-minute history request failed: ${response.status}`);
  const data = await response.json();
  const candles = cleanCandles(data.candles || []);
  if (candles.length < 160) throw new Error("Not enough five-minute candles returned");
  state.fiveMinuteCandles = candles.slice(-20_000);
}

async function fetchServerRecommendations() {
  if (!state.serverOwnsSignals) return;
  const response = await fetch(`/api/recommendations?symbol=${encodeURIComponent(API_SYMBOL)}`);
  if (!response.ok) throw new Error(`Recommendations request failed: ${response.status}`);
  applyServerRecommendations(await response.json());
}

async function refreshGraphData() {
  if (state.graphRefreshPending) return;
  state.graphRefreshPending = true;
  const button = els.graphRefreshButton;
  button.disabled = true;
  button.classList.add("refreshing");
  button.setAttribute("aria-busy", "true");
  button.textContent = "Refreshing...";

  try {
    if (state.feedMode !== "real") await bootFeed();
    if (state.feedMode !== "real") throw new Error("Market feed is unavailable");

    const results = await Promise.allSettled([
      fetchLatestCandle(),
      syncIntradayHistory(),
      fetchDailyHistory(),
      fetchServerRecommendations(),
    ]);
    const marketUpdated = results.slice(0, 3).some(
      (result) => result.status === "fulfilled" && result.value !== false,
    );
    if (!marketUpdated) throw new Error("No market data source completed the refresh");

    refreshCurrentDailyCandle();
    assessDataQuality();
    refresh();
    button.textContent = "Updated";
  } catch (error) {
    console.info("Manual graph refresh failed.", error);
    button.textContent = "Retry";
  } finally {
    button.classList.remove("refreshing");
    button.removeAttribute("aria-busy");
    state.graphRefreshPending = false;
    window.setTimeout(() => {
      if (state.graphRefreshPending) return;
      button.disabled = false;
      button.textContent = "Graph Refresh";
    }, 1200);
  }
}

function startLatestPolling(intervalMs) {
  stopLatestPolling();
  state.pollIntervalMs = intervalMs || 15000;
  state.pollTimer = setInterval(() => {
    const watchdogLimit = Math.max(30_000, state.pollIntervalMs * 2.5);
    const streamHealthy = state.stream
      && state.lastStreamAt
      && Date.now() - state.lastStreamAt < watchdogLimit;
    if (!streamHealthy) fetchLatestCandle();
  }, state.pollIntervalMs);
  fetchLatestCandle();
}

function startHistorySync() {
  stopHistorySync();
  state.historySyncTimer = setInterval(syncIntradayHistory, 5 * 60_000);
}

function providerLabel(config) {
  if (config.provider === "ibkr") return "IBKR TWS";
  if (config.provider === "alpaca") return `Alpaca ${String(config.feed || "iex").toUpperCase()}`;
  if (config.provider === "polygon") return "Polygon";
  if (config.provider === "yahoo") return "Yahoo chart";
  return "Provider";
}

function initializeAssetPage() {
  document.title = `${API_SYMBOL} Trader Alert Helper`;
  els.brandEyebrow.textContent = `${API_SYMBOL} alert assistant`;
  els.chartSymbol.textContent = API_SYMBOL;
  els.canvas.setAttribute("aria-label", `${API_SYMBOL} candlestick, volume, and RSI chart`);
  els.fearGreedTitle.textContent = ASSET_OPTIONS.continuous ? "CNN US Market Context" : "CNN Fear & Greed";
  els.marketConfirmationTile.hidden = API_SYMBOL !== "QQQ";
  try {
    state.lastOptionsAlertKey = window.sessionStorage.getItem(OPTIONS_ALERT_STORAGE_KEY) || "";
  } catch (error) {
    state.lastOptionsAlertKey = "";
  }
  if (ASSET_OPTIONS.continuous) {
    [...els.sessionMode.options].forEach((option) => {
      option.textContent = "All hours (24/7)";
    });
  }
  els.assetButtons.forEach((button) => {
    const active = button.dataset.symbol === API_SYMBOL;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
    button.addEventListener("click", () => {
      const symbol = button.dataset.symbol;
      if (!SUPPORTED_SYMBOLS.has(symbol) || symbol === API_SYMBOL) return;
      const url = new URL(window.location.href);
      url.searchParams.set("symbol", symbol);
      window.location.assign(url);
    });
  });
}

async function startRealFeed(config) {
  if (state.stream) state.stream.close();
  stopLatestPolling();
  stopHistorySync();
  state.feedMode = "real";
  state.analysisEngine = String(config.analysisEngine || (config.serverFeed ? "python-server" : "unavailable"));
  state.serverOwnsSignals = state.analysisEngine === "python-server";
  state.lastStreamAt = null;
  state.providerLabel = providerLabel(config);
  state.providerErrors = Number(config.providerErrors || 0);
  state.providerMessage = String(config.providerMessage || "");
  applyDataHealth(config.dataHealth);
  state.pollIntervalMs = config.pollIntervalMs || 15000;
  state.pollIntervalMs = Number(state.settings.pollIntervalMs || state.pollIntervalMs);
  els.sessionState.textContent = `Loading ${state.providerLabel}`;

  const historyResponse = await fetch(`/api/history?symbol=${API_SYMBOL}`);
  if (!historyResponse.ok) {
    throw new Error(`History request failed: ${historyResponse.status}`);
  }

  const history = await historyResponse.json();
  applyDataHealth(history.dataHealth);
  if (!history.candles || history.candles.length < 60) {
    throw new Error("Not enough provider minute candles returned");
  }

  state.candles = cleanCandles(history.candles);
  try {
    await fetchFiveMinuteHistory();
  } catch (error) {
    console.info("Native five-minute history unavailable; using resampled one-minute candles.", error);
    state.fiveMinuteCandles = Core.resample(state.candles, 5);
  }
  try {
    await fetchServerRecommendations();
  } catch (error) {
    console.info("Server recommendations are still starting.", error);
  }
  try {
    await fetchDailyHistory();
  } catch (error) {
    console.info("Daily history unavailable; using intraday daily aggregation.", error);
    state.dailyCandles = Core.resampleDaily(state.candles, ASSET_OPTIONS);
  }
  state.lastTickAt = Date.now();
  state.marketCandleAt = state.candles.at(-1)?.time || null;
  state.providerErrors = Math.max(state.providerErrors, Number(history.providerErrors || 0));
  assessDataQuality();
  els.sessionState.textContent = state.providerErrors ? `${state.providerLabel} provider issue` : `${state.providerLabel} live`;
  refresh();
  startLatestPolling(state.pollIntervalMs);
  startHistorySync();

  state.stream = new EventSource(`/api/stream?symbol=${API_SYMBOL}`);
  state.stream.addEventListener("candle", (event) => {
    state.lastStreamAt = Date.now();
    state.providerErrors = 0;
    state.lastTickAt = Date.now();
    mergeCandle(JSON.parse(event.data));
    els.sessionState.textContent = `${state.providerLabel} live`;
  });
  state.stream.addEventListener("status", (event) => {
    const status = JSON.parse(event.data || "{}");
    state.lastStreamAt = Date.now();
    state.lastTickAt = Number(status.lastSuccessAt || Date.now());
    state.providerErrors = Number(status.providerErrors || 0);
    applyDataHealth(status.dataHealth);
  });
  state.stream.addEventListener("provider_error", (event) => {
    const status = JSON.parse(event.data || "{}");
    state.lastStreamAt = Date.now();
    state.providerErrors = Number(status.count || state.providerErrors + 1);
    state.providerMessage = String(status.detail || state.providerMessage || "");
    els.sessionState.textContent = `${state.providerLabel} provider issue`;
  });
  state.stream.addEventListener("recommendations", (event) => {
    applyServerRecommendations(JSON.parse(event.data || "{}"));
    refresh();
  });
  state.stream.addEventListener("options_opportunity", (event) => {
    state.optionsOpportunity = JSON.parse(event.data || "{}");
    refresh();
  });
  state.stream.addEventListener("error", () => {
    state.providerErrors += 1;
    els.sessionState.textContent = `${state.providerLabel} reconnecting / polling`;
    fetchLatestCandle();
  });
}

async function bootFeed() {
  try {
    const response = await fetch(`/api/config?symbol=${encodeURIComponent(API_SYMBOL)}`);
    if (!response.ok) throw new Error("No local API server");
    const config = await response.json();
    if (config.realTimeEnabled) {
      await startRealFeed(config);
      return;
    }
  } catch (error) {
    console.info("Market feed unavailable.", error);
    state.feedMode = "offline";
    state.providerErrors += 1;
    state.providerLabel = "Unavailable";
    els.sessionState.textContent = "Market data unavailable";
  }
}

els.timeframeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    selectTimeframe(Number(button.dataset.timeframe));
  });
});

els.bestOpportunityView.addEventListener("click", () => {
  if (state.bestOpportunityTimeframe) {
    selectTimeframe(state.bestOpportunityTimeframe);
    els.canvas.scrollIntoView({ behavior: "smooth", block: "center" });
  }
});

els.bestSwingView.addEventListener("click", () => {
  selectTimeframe(DAILY_TIMEFRAME);
  els.canvas.scrollIntoView({ behavior: "smooth", block: "center" });
});

els.patternsToggle.addEventListener("click", () => {
  state.settings.chartLayers.patterns = !state.settings.chartLayers.patterns;
  if (!state.settings.chartLayers.patterns) state.patternProjectionVisible = false;
  els.patternsToggle.classList.toggle("active", state.settings.chartLayers.patterns);
  saveSettings();
  refresh();
});

els.zoomInButton.addEventListener("click", () => zoomChart(0.8));
els.zoomOutButton.addEventListener("click", () => zoomChart(1.25));
els.panOlderButton.addEventListener("click", () => panChart(true));
els.panNewerButton.addEventListener("click", () => panChart(false));
els.liveViewButton.addEventListener("click", resetChartView);
els.graphRefreshButton.addEventListener("click", refreshGraphData);

els.chartOverlay.addEventListener("click", handlePatternClick);
els.chartOverlay.addEventListener("wheel", handleChartWheel, { passive: false });
els.chartOverlay.addEventListener("pointerdown", handleChartPointerDown);
els.chartOverlay.addEventListener("pointermove", handleChartPointerMove);
els.chartOverlay.addEventListener("pointerup", finishChartPointerInteraction);
els.chartOverlay.addEventListener("pointercancel", finishChartPointerInteraction);
els.chartOverlay.addEventListener("pointerleave", clearChartHover);

els.notifyButton.addEventListener("click", async () => {
  if (!("Notification" in window)) return;
  const permission = await Notification.requestPermission();
  state.notifyEnabled = permission === "granted";
  els.notifyButton.classList.toggle("active", state.notifyEnabled);
});

els.clearLog.addEventListener("click", () => {
  state.alerts = [];
  renderAlertLog();
});

els.tradeMode.addEventListener("change", () => {
  state.settings.mode = els.tradeMode.value;
  saveSettings();
  refresh();
});

els.sessionMode.addEventListener("change", () => {
  state.settings.sessionMode = els.sessionMode.value;
  state.lastAlertsByTimeframe = {};
  saveSettings();
  refresh();
});

[
  [els.layerMAs, "movingAverages"],
  [els.layerVwap, "vwap"],
  [els.layerLevels, "levels"],
  [els.layerMarkers, "markers"],
  [els.layerVolume, "volume"],
  [els.layerRsi, "rsi"],
].forEach(([input, key]) => {
  input.addEventListener("change", () => {
    state.settings.chartLayers[key] = input.checked;
    saveSettings();
    refresh();
  });
});

els.journalFilter.addEventListener("change", renderJournalRows);

els.feedbackTook.addEventListener("click", () => sendFeedback("took"));
els.feedbackSkipped.addEventListener("click", () => sendFeedback("skipped"));
els.feedbackBad.addEventListener("click", () => sendFeedback("bad"));

window.addEventListener("resize", () => refresh());
window.addEventListener("online", () => {
  fetchLatestCandle();
  syncIntradayHistory();
  fetchFearGreed();
});
window.addEventListener("pageshow", () => {
  fetchLatestCandle();
  syncIntradayHistory();
  fetchFearGreed();
});
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") return;
  fetchLatestCandle();
  syncIntradayHistory();
  fetchFearGreed();
});

initializeAssetPage();
updateClock();
setInterval(updateClock, 1000);
if ("Notification" in window && Notification.permission === "granted") {
  state.notifyEnabled = true;
  els.notifyButton.classList.add("active");
}
loadSettings().then(() => {
  refreshJournalStats(true);
  fetchFearGreed();
  state.sentimentTimer = setInterval(fetchFearGreed, 5 * 60_000);
  bootFeed();
});
