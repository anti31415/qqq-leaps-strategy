const fs = require("fs");
const https = require("https");
const path = require("path");

const SHORT_CALL_ENABLED = process.env.DISABLE_SHORT_CALLS !== "1";
const OUTPUT_PREFIX = SHORT_CALL_ENABLED ? "tiered_vix_calls" : "tiered_vix_no_short_calls";

const CONFIG = {
  symbol: "QQQ",
  vixSymbol: "^VIX",
  benchmarks: [
    { symbol: "^IXIC", label: "Nasdaq Composite" },
    { symbol: "^GSPC", label: "S&P 500" },
  ],
  dataStart: "2011-01-01",
  backtestStart: "2012-01-01",
  backtestEnd: "2026-03-31",
  compareStart: "2016-03-01",
  compareEnd: "2026-03-31",
  initialCapital: 20000,
  allowAdditionalCapital: false,
  rsiPeriod: 14,
  rsiBuyBelow: 35,
  targetDelta: 0.7,
  contractDays: 730,
  forceExitDaysToExpiry: 180,
  sigma1ExitRules: [
    { minAgeDays: 0, maxAgeDays: 364, profitTarget: 1.2, label: "take_profit_120_before_12m" },
    { minAgeDays: 365, maxAgeDays: 456, profitTarget: 0.6, label: "take_profit_60_12_to_15m" },
    { minAgeDays: 457, maxAgeDays: 548, profitTarget: 0.3, label: "take_profit_30_16_to_18m" },
  ],
  sigma2ExitRules: [
    { minAgeDays: 0, maxAgeDays: 364, profitTarget: 1.5, label: "take_profit_150_before_12m" },
    { minAgeDays: 365, maxAgeDays: 456, profitTarget: 0.8, label: "take_profit_80_12_to_15m" },
    { minAgeDays: 457, maxAgeDays: 548, profitTarget: 0.3, label: "take_profit_30_16_to_18m" },
  ],
  shortCall: {
    enabled: SHORT_CALL_ENABLED,
    dteDays: 30,
    otmPct: 0.1,
    roundStrikeTo: 1,
  },
  riskFreeRate: 0.03,
  ivLookbackDays: 252,
  ivMultiplier: 1.2,
  minIv: 0.15,
  maxIv: 0.75,
  contractMultiplier: 100,
  roundStrikeTo: 1,
  outputDir: path.join(__dirname, "outputs"),
  outputPrefix: OUTPUT_PREFIX,
};

function toUnix(date) {
  return Math.floor(Date.parse(`${date}T00:00:00Z`) / 1000);
}

function addUtcDays(date, days) {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

function dayDiff(a, b) {
  return Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86400000);
}

function weekKey(date) {
  const d = new Date(`${date}T00:00:00Z`);
  const day = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  const week = Math.ceil(((d - yearStart) / 86400000 + 1) / 7);
  return `${d.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
}

function round(value, digits = 6) {
  return Number(value.toFixed(digits));
}

function csvEscape(value) {
  if (value == null) return "";
  const text = typeof value === "number" ? String(value) : String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function writeCsv(file, rows) {
  if (!rows.length) {
    fs.writeFileSync(file, "");
    return;
  }
  const headers = Object.keys(rows[0]);
  const lines = [headers.join(",")];
  for (const row of rows) {
    lines.push(headers.map((header) => csvEscape(row[header])).join(","));
  }
  fs.writeFileSync(file, `${lines.join("\n")}\n`);
}

function httpsGetJson(url) {
  return new Promise((resolve, reject) => {
    https
      .get(url, { headers: { "User-Agent": "Mozilla/5.0" } }, (res) => {
        let data = "";
        res.setEncoding("utf8");
        res.on("data", (chunk) => {
          data += chunk;
        });
        res.on("end", () => {
          if (res.statusCode < 200 || res.statusCode >= 300) {
            reject(new Error(`HTTP ${res.statusCode}: ${data.slice(0, 300)}`));
            return;
          }
          try {
            resolve(JSON.parse(data));
          } catch (err) {
            reject(err);
          }
        });
      })
      .on("error", reject);
  });
}

async function fetchYahooChart(symbol, start, end) {
  const period1 = toUnix(start);
  const period2 = toUnix(addUtcDays(end, 1));
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?period1=${period1}&period2=${period2}&interval=1d&events=history%2Csplits&includeAdjustedClose=true`;
  const json = await httpsGetJson(url);
  const result = json.chart?.result?.[0];
  if (!result) {
    throw new Error(`No Yahoo chart result for ${symbol}: ${JSON.stringify(json.chart?.error || null)}`);
  }
  const quote = result.indicators?.quote?.[0];
  const adj = result.indicators?.adjclose?.[0]?.adjclose;
  return result.timestamp
    .map((ts, i) => {
      const close = quote?.close?.[i];
      const adjClose = adj?.[i] ?? close;
      if (!Number.isFinite(close) || !Number.isFinite(adjClose)) return null;
      return {
        date: new Date(ts * 1000).toISOString().slice(0, 10),
        close,
        adjClose,
      };
    })
    .filter(Boolean);
}

function computeRsi(rows, period) {
  let gains = 0;
  let losses = 0;
  for (let i = 1; i <= period; i++) {
    const change = rows[i].adjClose - rows[i - 1].adjClose;
    if (change >= 0) gains += change;
    else losses -= change;
  }
  let avgGain = gains / period;
  let avgLoss = losses / period;
  rows[period].rsi = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  for (let i = period + 1; i < rows.length; i++) {
    const change = rows[i].adjClose - rows[i - 1].adjClose;
    const gain = Math.max(change, 0);
    const loss = Math.max(-change, 0);
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    rows[i].rsi = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  }
}

function computeRealizedIv(rows, lookback, multiplier, minIv, maxIv) {
  const returns = rows.map((row, i) => {
    if (i === 0) return null;
    return Math.log(row.adjClose / rows[i - 1].adjClose);
  });
  for (let i = lookback; i < rows.length; i++) {
    const window = returns.slice(i - lookback + 1, i + 1).filter(Number.isFinite);
    const mean = window.reduce((sum, x) => sum + x, 0) / window.length;
    const variance = window.reduce((sum, x) => sum + (x - mean) ** 2, 0) / Math.max(window.length - 1, 1);
    const realized = Math.sqrt(variance) * Math.sqrt(252);
    rows[i].iv = Math.min(maxIv, Math.max(minIv, realized * multiplier));
  }
}

function computeExpandingStats(rows, sourceKey, meanKey, stdKey) {
  let count = 0;
  let mean = 0;
  let m2 = 0;
  for (const row of rows) {
    const value = row[sourceKey];
    if (!Number.isFinite(value)) continue;
    count += 1;
    const delta = value - mean;
    mean += delta / count;
    const delta2 = value - mean;
    m2 += delta * delta2;
    row[meanKey] = mean;
    row[stdKey] = count > 1 ? Math.sqrt(m2 / (count - 1)) : 0;
  }
}

function erf(x) {
  const sign = x < 0 ? -1 : 1;
  const a1 = 0.254829592;
  const a2 = -0.284496736;
  const a3 = 1.421413741;
  const a4 = -1.453152027;
  const a5 = 1.061405429;
  const p = 0.3275911;
  const ax = Math.abs(x);
  const t = 1 / (1 + p * ax);
  const y = 1 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Math.exp(-ax * ax);
  return sign * y;
}

function normCdf(x) {
  return 0.5 * (1 + erf(x / Math.SQRT2));
}

function invNorm(p) {
  if (p <= 0 || p >= 1) throw new Error("p must be between 0 and 1");
  const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239];
  const b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
  const c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
  const d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
  const plow = 0.02425;
  const phigh = 1 - plow;
  if (p < plow) {
    const q = Math.sqrt(-2 * Math.log(p));
    return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
      ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  }
  if (p > phigh) {
    const q = Math.sqrt(-2 * Math.log(1 - p));
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
      ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  }
  const q = p - 0.5;
  const r = q * q;
  return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q /
    (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
}

function callPrice(s, k, t, r, sigma) {
  if (t <= 0) return Math.max(s - k, 0);
  const sqrtT = Math.sqrt(t);
  const d1 = (Math.log(s / k) + (r + 0.5 * sigma * sigma) * t) / (sigma * sqrtT);
  const d2 = d1 - sigma * sqrtT;
  return s * normCdf(d1) - k * Math.exp(-r * t) * normCdf(d2);
}

function strikeForDelta(s, targetDelta, t, r, sigma, roundTo) {
  const d1 = invNorm(targetDelta);
  const raw = s / Math.exp(d1 * sigma * Math.sqrt(t) - (r + 0.5 * sigma * sigma) * t);
  return Math.max(roundTo, Math.round(raw / roundTo) * roundTo);
}

function roundToStrike(value, roundStep) {
  return Math.max(roundStep, Math.round(value / roundStep) * roundStep);
}

function priceLongLeaps(row, position, config) {
  const daysLeft = Math.max(0, dayDiff(row.date, position.expiryDate));
  const t = daysLeft / 365.25;
  const sigma = row.iv || position.entryIv;
  const pricePerContract = callPrice(row.adjClose, position.strike, t, config.riskFreeRate, sigma) * config.contractMultiplier;
  return pricePerContract * position.quantity;
}

function priceShortCall(row, shortCall, config) {
  const daysLeft = Math.max(0, dayDiff(row.date, shortCall.expiryDate));
  const t = daysLeft / 365.25;
  const sigma = row.iv || shortCall.entryIv;
  const pricePerContract = callPrice(row.adjClose, shortCall.strike, t, config.riskFreeRate, sigma) * config.contractMultiplier;
  return pricePerContract * shortCall.quantity;
}

function maxDrawdownFromSeries(series, key) {
  let peak = -Infinity;
  let maxDrawdown = 0;
  for (const point of series) {
    peak = Math.max(peak, point[key]);
    if (peak > 0) maxDrawdown = Math.min(maxDrawdown, (point[key] - peak) / peak);
  }
  return maxDrawdown;
}

function describeSellReason(code) {
  if (code === "take_profit_120_before_12m") return "held <12 months and reached +120% profit";
  if (code === "take_profit_60_12_to_15m") return "held 12-15 months and reached +60% profit";
  if (code === "take_profit_150_before_12m") return "held <12 months and reached +150% profit";
  if (code === "take_profit_80_12_to_15m") return "held 12-15 months and reached +80% profit";
  if (code === "take_profit_30_16_to_18m") return "held 16-18 months and reached +30% profit";
  if (code === "force_exit_180d_to_expiry") return "forced exit with 180 days left to expiry";
  return code;
}

function describeRegime(regimeName) {
  if (regimeName === "sigma1_weekly_1lot") return "mean + 1*std <= VIX < mean + 2*std, buy 1 contract max once per week";
  if (regimeName === "sigma2_first_60d_1lot") return "first RSI<35 and VIX >= mean + 2*std signal in the last 60 trading days, buy 1 contract";
  if (regimeName === "sigma2_repeat_20d_2lot") return "second or later RSI<35 and VIX >= mean + 2*std signal in the last 20 trading days, buy 2 contracts, or 1 if cash is insufficient for 2";
  return regimeName;
}

function overlayLabel(config) {
  return config.shortCall.enabled ? "short call overlay active" : "no short call overlay";
}

function buildNormalizedSeries(rows, key, start, end, label) {
  const filtered = rows.filter((row) => row.date >= start && row.date <= end);
  if (!filtered.length) {
    throw new Error(`No rows available for ${label} in ${start} -> ${end}`);
  }
  const base = filtered[0][key];
  return filtered.map((row) => ({
    date: row.date,
    label,
    value: row[key],
    normalized: row[key] / base,
  }));
}

function computePerformanceMetrics(series, riskFreeRate) {
  if (series.length < 2) {
    throw new Error(`Series too short for metrics: ${series[0]?.label || "unknown"}`);
  }
  const returns = [];
  for (let i = 1; i < series.length; i++) {
    returns.push(series[i].normalized / series[i - 1].normalized - 1);
  }
  const meanDaily = returns.reduce((sum, value) => sum + value, 0) / returns.length;
  const variance = returns.reduce((sum, value) => sum + (value - meanDaily) ** 2, 0) / Math.max(returns.length - 1, 1);
  const dailyVol = Math.sqrt(variance);
  const annualizedVolatility = dailyVol * Math.sqrt(252);
  const years = dayDiff(series[0].date, series.at(-1).date) / 365.25;
  const totalReturn = series.at(-1).normalized - 1;
  const cagr = series.at(-1).normalized ** (1 / years) - 1;
  const sharpe = annualizedVolatility > 0 ? ((meanDaily * 252) - riskFreeRate) / annualizedVolatility : null;
  return {
    label: series[0].label,
    startDate: series[0].date,
    endDate: series.at(-1).date,
    tradingDays: series.length,
    totalReturn,
    cagr,
    annualizedVolatility,
    sharpe,
    maxDrawdown: maxDrawdownFromSeries(series, "normalized"),
  };
}

function buildCombinedCsvRows(strategyResult, comparisonMetrics, config) {
  const rows = [];
  const summary = strategyResult.summary;
  const baseColumns = {
    recordType: "",
    section: "",
    metric: "",
    value: "",
    label: "",
    startDate: "",
    endDate: "",
    tradingDays: "",
    totalReturn: "",
    cagr: "",
    annualizedVolatility: "",
    sharpe: "",
    maxDrawdown: "",
    entryDate: "",
    exitDate: "",
    regime: "",
    quantity: "",
    vixStdBand: "",
    sigma2SignalTag: "",
    sigma2Count60: "",
    sigma2Count20: "",
    entryUnderlying: "",
    exitUnderlying: "",
    strike: "",
    entryCost: "",
    leapsExitValue: "",
    shortCallPremiumCollected: "",
    shortCallSettlements: "",
    shortCallCloseCost: "",
    shortCallNetCash: "",
    totalExitValue: "",
    pnl: "",
    pnlPct: "",
    ageDays: "",
    entryRsi: "",
    entryVix: "",
    entryVixMean: "",
    entryVixStd: "",
    vixThreshold: "",
    buyReason: "",
    sellReason: "",
    rawReason: "",
  };
  const addRow = (row) => rows.push({ ...baseColumns, ...row });

  for (const [metric, value] of Object.entries(summary)) {
    if (metric === "assumptions") continue;
    addRow({
      recordType: "summary",
      section: "strategy_summary",
      metric,
      value: typeof value === "number" ? round(value, 8) : value,
    });
  }

  for (const [metric, value] of Object.entries(summary.assumptions || {})) {
    addRow({
      recordType: "summary",
      section: "strategy_assumptions",
      metric,
      value,
    });
  }

  for (const metricRow of comparisonMetrics) {
    addRow({
      recordType: "summary",
      section: "comparison_metrics",
      label: metricRow.label,
      startDate: metricRow.startDate,
      endDate: metricRow.endDate,
      tradingDays: metricRow.tradingDays,
      totalReturn: round(metricRow.totalReturn, 8),
      cagr: round(metricRow.cagr, 8),
      annualizedVolatility: round(metricRow.annualizedVolatility, 8),
      sharpe: metricRow.sharpe == null ? "" : round(metricRow.sharpe, 8),
      maxDrawdown: round(metricRow.maxDrawdown, 8),
    });
  }

  for (const trade of strategyResult.trades) {
    addRow({
      recordType: "trade",
      section: "trade_log",
      entryDate: trade.entryDate,
      exitDate: trade.exitDate,
      regime: trade.regime,
      quantity: trade.quantity,
      vixStdBand: trade.vixStdBand,
      sigma2SignalTag: trade.sigma2SignalTag,
      sigma2Count60: trade.sigma2Count60,
      sigma2Count20: trade.sigma2Count20,
      entryUnderlying: trade.entryUnderlying,
      exitUnderlying: trade.exitUnderlying,
      strike: trade.strike,
      entryCost: trade.entryCost,
      leapsExitValue: trade.leapsExitValue,
      shortCallPremiumCollected: trade.shortCallPremiumCollected,
      shortCallSettlements: trade.shortCallSettlements,
      shortCallCloseCost: trade.shortCallCloseCost,
      shortCallNetCash: trade.shortCallNetCash,
      totalExitValue: trade.totalExitValue,
      pnl: trade.pnl,
      pnlPct: trade.pnlPct,
      ageDays: trade.ageDays,
      entryRsi: trade.entryRsi,
      entryVix: trade.entryVix,
      entryVixMean: trade.entryVixMean,
      entryVixStd: trade.entryVixStd,
      vixThreshold: trade.vixThreshold,
      buyReason: trade.buyReason,
      sellReason: describeSellReason(trade.reason),
      rawReason: trade.reason,
    });
  }

  return rows;
}

function determineRegime(row, config, sigma2Count60, sigma2Count20) {
  const sigma1Threshold = row.vixMean + row.vixStd;
  const sigma2Threshold = row.vixMean + row.vixStd * 2;

  if (row.vix >= sigma2Threshold) {
    if (sigma2Count60 === 1) {
      return {
        name: "sigma2_first_60d_1lot",
        quantity: 1,
        allowPartialFill: false,
        buyLimit: "daily",
        exitRules: config.sigma2ExitRules,
        sigma2SignalTag: "first_in_60d",
        sigma2Count60,
        sigma2Count20,
        vixThreshold: sigma2Threshold,
        vixStdBand: 2,
      };
    }
    if (sigma2Count20 >= 2) {
      return {
        name: "sigma2_repeat_20d_2lot",
        quantity: 2,
        allowPartialFill: true,
        buyLimit: "daily",
        exitRules: config.sigma2ExitRules,
        sigma2SignalTag: "second_or_later_in_20d",
        sigma2Count60,
        sigma2Count20,
        vixThreshold: sigma2Threshold,
        vixStdBand: 2,
      };
    }
    return null;
  }

  if (row.vix >= sigma1Threshold && row.vix < sigma2Threshold) {
    return {
      name: "sigma1_weekly_1lot",
      quantity: 1,
      allowPartialFill: false,
      buyLimit: "weekly",
      exitRules: config.sigma1ExitRules,
      sigma2SignalTag: "",
      sigma2Count60: "",
      sigma2Count20: "",
      vixThreshold: sigma1Threshold,
      vixStdBand: 1,
    };
  }

  return null;
}

function maybeSellShortCall(row, position, config, shortCallEvents) {
  if (!config.shortCall.enabled) return 0;
  if (position.shortCall) return 0;
  const daysToLeapsExpiry = dayDiff(row.date, position.expiryDate);
  if (daysToLeapsExpiry <= config.forceExitDaysToExpiry) return 0;
  const strike = roundToStrike(row.adjClose * (1 + config.shortCall.otmPct), config.shortCall.roundStrikeTo);
  const t = config.shortCall.dteDays / 365.25;
  const premium = callPrice(row.adjClose, strike, t, config.riskFreeRate, row.iv) * config.contractMultiplier * position.quantity;
  position.shortCall = {
    entryDate: row.date,
    expiryDate: addUtcDays(row.date, config.shortCall.dteDays),
    strike,
    quantity: position.quantity,
    entryIv: row.iv,
    premium,
  };
  position.shortCallPremiumCollected += premium;
  position.shortCallNetCash += premium;
  shortCallEvents.push({
    eventDate: row.date,
    eventType: "sell_short_call",
    positionEntryDate: position.entryDate,
    regime: position.regime,
    quantity: position.quantity,
    underlying: round(row.adjClose, 4),
    shortCallStrike: strike,
    shortCallExpiry: position.shortCall.expiryDate,
    cashFlow: round(premium, 4),
  });
  return premium;
}

function settleExpiredShortCall(row, position, config, shortCallEvents) {
  if (!position.shortCall) return 0;
  if (row.date < position.shortCall.expiryDate) return 0;
  const settlement = Math.max(0, row.adjClose - position.shortCall.strike) * config.contractMultiplier * position.shortCall.quantity;
  position.shortCallSettlements += settlement;
  position.shortCallNetCash -= settlement;
  shortCallEvents.push({
    eventDate: row.date,
    eventType: "short_call_settlement",
    positionEntryDate: position.entryDate,
    regime: position.regime,
    quantity: position.shortCall.quantity,
    underlying: round(row.adjClose, 4),
    shortCallStrike: position.shortCall.strike,
    shortCallExpiry: position.shortCall.expiryDate,
    cashFlow: round(-settlement, 4),
  });
  position.shortCall = null;
  return settlement;
}

function closeActiveShortCall(row, position, config, shortCallEvents) {
  if (!position.shortCall) return 0;
  const closeCost = priceShortCall(row, position.shortCall, config);
  position.shortCallCloseCost += closeCost;
  position.shortCallNetCash -= closeCost;
  shortCallEvents.push({
    eventDate: row.date,
    eventType: "close_short_call",
    positionEntryDate: position.entryDate,
    regime: position.regime,
    quantity: position.shortCall.quantity,
    underlying: round(row.adjClose, 4),
    shortCallStrike: position.shortCall.strike,
    shortCallExpiry: position.shortCall.expiryDate,
    cashFlow: round(-closeCost, 4),
  });
  position.shortCall = null;
  return closeCost;
}

function currentPositionNetValue(row, position, config) {
  const leapsValue = priceLongLeaps(row, position, config);
  const shortCallLiability = position.shortCall ? priceShortCall(row, position.shortCall, config) : 0;
  return leapsValue + position.shortCallNetCash - shortCallLiability;
}

function runBacktest(rows, config) {
  const positions = [];
  const trades = [];
  const shortCallEvents = [];
  const equityCurve = [];
  let availableCash = config.initialCapital;
  let skippedSignalsInsufficientCash = 0;
  let lastSigma1Week = null;
  const sigma2SignalRowIndexes = [];

  for (let rowIndex = 0; rowIndex < rows.length; rowIndex++) {
    const row = rows[rowIndex];
    if (row.date < config.backtestStart || row.date > config.backtestEnd) continue;
    if (
      !Number.isFinite(row.rsi) ||
      !Number.isFinite(row.iv) ||
      !Number.isFinite(row.vix) ||
      !Number.isFinite(row.vixMean) ||
      !Number.isFinite(row.vixStd)
    ) continue;

    for (const position of positions) {
      if (position.shortCall && row.date >= position.shortCall.expiryDate) {
        availableCash -= settleExpiredShortCall(row, position, config, shortCallEvents);
      }
    }

    for (let i = positions.length - 1; i >= 0; i--) {
      const position = positions[i];
      const netValue = currentPositionNetValue(row, position, config);
      const pnlPct = (netValue - position.entryCost) / position.entryCost;
      const ageDays = dayDiff(position.entryDate, row.date);
      const daysToExpiry = dayDiff(row.date, position.expiryDate);
      let reason = null;

      for (const rule of position.exitRules) {
        if (ageDays >= rule.minAgeDays && ageDays <= rule.maxAgeDays && pnlPct >= rule.profitTarget) {
          reason = rule.label;
          break;
        }
      }
      if (!reason && daysToExpiry <= config.forceExitDaysToExpiry) {
        reason = "force_exit_180d_to_expiry";
      }

      if (reason) {
        const shortCallCloseCost = closeActiveShortCall(row, position, config, shortCallEvents);
        if (shortCallCloseCost > 0) {
          availableCash -= shortCallCloseCost;
        }
        const leapsExitValue = priceLongLeaps(row, position, config);
        availableCash += leapsExitValue;
        const totalExitValue = leapsExitValue + position.shortCallNetCash;
        const pnl = totalExitValue - position.entryCost;
        trades.push({
          entryDate: position.entryDate,
          exitDate: row.date,
          regime: position.regime,
          vixStdBand: position.vixStdBand,
          sigma2SignalTag: position.sigma2SignalTag,
          sigma2Count60: position.sigma2Count60,
          sigma2Count20: position.sigma2Count20,
          quantity: position.quantity,
          entryUnderlying: round(position.entryUnderlying, 4),
          exitUnderlying: round(row.adjClose, 4),
          entryRsi: round(position.entryRsi, 4),
          entryIv: round(position.entryIv, 4),
          entryVix: round(position.entryVix, 4),
          entryVixMean: round(position.entryVixMean, 4),
          entryVixStd: round(position.entryVixStd, 4),
          vixThreshold: round(position.vixThreshold, 4),
          strike: position.strike,
          entryCost: round(position.entryCost, 4),
          leapsExitValue: round(leapsExitValue, 4),
          shortCallPremiumCollected: round(position.shortCallPremiumCollected, 4),
          shortCallSettlements: round(position.shortCallSettlements, 4),
          shortCallCloseCost: round(position.shortCallCloseCost, 4),
          shortCallNetCash: round(position.shortCallNetCash, 4),
          totalExitValue: round(totalExitValue, 4),
          pnl: round(pnl, 4),
          pnlPct: round(pnl / position.entryCost, 6),
          ageDays,
          reason,
          buyReason: `RSI(${config.rsiPeriod}) ${round(position.entryRsi, 4)} < ${config.rsiBuyBelow}; VIX ${round(position.entryVix, 4)} >= ${round(position.vixThreshold, 4)}; ${describeRegime(position.regime)}; ${overlayLabel(config)}`,
          win: pnl > 0,
        });
        positions.splice(i, 1);
      }
    }

    const eligibleRsi = row.rsi < config.rsiBuyBelow;
    const sigma2Threshold = row.vixMean + row.vixStd * 2;
    const sigma2TriggeredToday = eligibleRsi && row.vix >= sigma2Threshold;
    const priorSigma2Count60 = sigma2SignalRowIndexes.filter((index) => index >= rowIndex - 59).length;
    const priorSigma2Count20 = sigma2SignalRowIndexes.filter((index) => index >= rowIndex - 19).length;
    const sigma2Count60 = sigma2TriggeredToday ? priorSigma2Count60 + 1 : priorSigma2Count60;
    const sigma2Count20 = sigma2TriggeredToday ? priorSigma2Count20 + 1 : priorSigma2Count20;
    const regime = eligibleRsi ? determineRegime(row, config, sigma2Count60, sigma2Count20) : null;

    let canBuy = false;
    if (regime) {
      if (regime.buyLimit === "daily") {
        canBuy = true;
      } else if (regime.buyLimit === "weekly") {
        canBuy = weekKey(row.date) !== lastSigma1Week;
      }
    }

    if (eligibleRsi && regime && canBuy) {
      const t = config.contractDays / 365.25;
      const strike = strikeForDelta(row.adjClose, config.targetDelta, t, config.riskFreeRate, row.iv, config.roundStrikeTo);
      const perContractCost = callPrice(row.adjClose, strike, t, config.riskFreeRate, row.iv) * config.contractMultiplier;
      let actualQuantity = regime.quantity;
      let entryCost = perContractCost * actualQuantity;

      if (regime.allowPartialFill && availableCash < entryCost && availableCash >= perContractCost) {
        actualQuantity = 1;
        entryCost = perContractCost;
      }

      if (availableCash >= entryCost) {
        availableCash -= entryCost;
      } else if (config.allowAdditionalCapital) {
        availableCash = 0;
      } else {
        skippedSignalsInsufficientCash += 1;
      }

      if (availableCash >= 0 && (actualQuantity > 0) && (entryCost <= config.initialCapital + Math.abs(config.initialCapital))) {
        if (!(entryCost > availableCash + entryCost)) {
          const position = {
            entryDate: row.date,
            expiryDate: addUtcDays(row.date, config.contractDays),
            regime: regime.name,
            vixStdBand: regime.vixStdBand,
            sigma2SignalTag: regime.sigma2SignalTag,
            sigma2Count60: regime.sigma2Count60,
            sigma2Count20: regime.sigma2Count20,
            quantity: actualQuantity,
            exitRules: regime.exitRules,
            entryUnderlying: row.adjClose,
            entryRsi: row.rsi,
            entryIv: row.iv,
            entryVix: row.vix,
            entryVixMean: row.vixMean,
            entryVixStd: row.vixStd,
            vixThreshold: regime.vixThreshold,
            strike,
            entryCost,
            shortCall: null,
            shortCallPremiumCollected: 0,
            shortCallSettlements: 0,
            shortCallCloseCost: 0,
            shortCallNetCash: 0,
          };
          if (entryCost <= availableCash + entryCost && entryCost <= config.initialCapital + Math.abs(config.initialCapital)) {
            positions.push(position);
            if (regime.name === "sigma1_weekly_1lot") {
              lastSigma1Week = weekKey(row.date);
            }
          }
        }
      }
    }

    if (sigma2TriggeredToday) {
      sigma2SignalRowIndexes.push(rowIndex);
    }

    for (const position of positions) {
      const premium = maybeSellShortCall(row, position, config, shortCallEvents);
      if (premium > 0) availableCash += premium;
    }

    const openLeapsValue = positions.reduce((sum, position) => sum + priceLongLeaps(row, position, config), 0);
    const shortCallLiability = positions.reduce((sum, position) => sum + (position.shortCall ? priceShortCall(row, position.shortCall, config) : 0), 0);
    const equity = availableCash + openLeapsValue - shortCallLiability;
    equityCurve.push({
      date: row.date,
      equity: round(equity, 6),
      openLeapsValue: round(openLeapsValue, 6),
      shortCallLiability: round(shortCallLiability, 6),
      availableCash: round(availableCash, 6),
      openContracts: positions.reduce((sum, position) => sum + position.quantity, 0),
      qqqAdjClose: round(row.adjClose, 6),
      qqqRsi: round(row.rsi, 6),
      qqqIv: round(row.iv, 6),
      vixClose: round(row.vix, 6),
      vixMean: round(row.vixMean, 6),
      vixStd: round(row.vixStd, 6),
    });
  }

  const lastRow = rows.filter((row) => row.date <= config.backtestEnd).at(-1);
  const endingOpenLeapsValue = positions.reduce((sum, position) => sum + priceLongLeaps(lastRow, position, config), 0);
  const endingShortCallLiability = positions.reduce((sum, position) => sum + (position.shortCall ? priceShortCall(lastRow, position.shortCall, config) : 0), 0);
  const endingEquity = availableCash + endingOpenLeapsValue - endingShortCallLiability;
  const years = dayDiff(config.backtestStart, config.backtestEnd) / 365.25;
  const totalPnl = endingEquity - config.initialCapital;
  const cagr = config.initialCapital > 0 ? (endingEquity / config.initialCapital) ** (1 / years) - 1 : 0;
  const contractsEntered = trades.reduce((sum, trade) => sum + trade.quantity, 0) + positions.reduce((sum, position) => sum + position.quantity, 0);

  return {
    trades,
    shortCallEvents,
    openPositions: positions.map((position) => ({
      entryDate: position.entryDate,
      expiryDate: position.expiryDate,
      regime: position.regime,
      vixStdBand: position.vixStdBand,
      sigma2SignalTag: position.sigma2SignalTag,
      sigma2Count60: position.sigma2Count60,
      sigma2Count20: position.sigma2Count20,
      quantity: position.quantity,
      entryUnderlying: round(position.entryUnderlying, 4),
      entryRsi: round(position.entryRsi, 4),
      entryIv: round(position.entryIv, 4),
      entryVix: round(position.entryVix, 4),
      entryVixMean: round(position.entryVixMean, 4),
      entryVixStd: round(position.entryVixStd, 4),
      vixThreshold: round(position.vixThreshold, 4),
      strike: position.strike,
      entryCost: round(position.entryCost, 4),
      shortCallPremiumCollected: round(position.shortCallPremiumCollected, 4),
      shortCallSettlements: round(position.shortCallSettlements, 4),
      shortCallCloseCost: round(position.shortCallCloseCost, 4),
      shortCallNetCash: round(position.shortCallNetCash, 4),
      activeShortCallStrike: position.shortCall ? position.shortCall.strike : "",
      activeShortCallExpiry: position.shortCall ? position.shortCall.expiryDate : "",
    })),
    equityCurve,
    summary: {
      symbol: config.symbol,
      backtestStart: config.backtestStart,
      backtestEnd: config.backtestEnd,
      model: config.shortCall.enabled
        ? "Approximate Black-Scholes LEAPS + monthly short OTM call overlay using Yahoo adjusted close and trailing realized volatility"
        : "Approximate Black-Scholes LEAPS without short call overlay using Yahoo adjusted close and trailing realized volatility",
      entries: trades.length + positions.length,
      contractsEntered,
      closedTrades: trades.length,
      openPositions: positions.length,
      wins: trades.filter((trade) => trade.win).length,
      losses: trades.filter((trade) => !trade.win).length,
      winRate: trades.length ? trades.filter((trade) => trade.win).length / trades.length : 0,
      initialCapital: config.initialCapital,
      skippedSignalsInsufficientCash,
      endingEquity,
      totalPnl,
      multipleOnInitialCapital: config.initialCapital > 0 ? endingEquity / config.initialCapital : 0,
      cagr,
      maxDrawdown: maxDrawdownFromSeries(equityCurve, "equity"),
      availableCash,
      endingOpenLeapsValue,
      endingShortCallLiability,
      assumptions: {
        signal: `RSI(${config.rsiPeriod}) < ${config.rsiBuyBelow} with tiered VIX entry filters`,
        option: `~${config.contractDays} days to expiry, target delta ${config.targetDelta}`,
        sigma1: "mean+1std <= VIX < mean+2std -> buy 1 contract max once per week, exits <12m +120%, 12-15m +60%, 16-18m +30%",
        sigma2First: "first RSI<35 and VIX >= mean+2std signal in the last 60 trading days -> buy 1 contract, exits <12m +150%, 12-15m +80%, 16-18m +30%",
        sigma2Repeat: "second or later RSI<35 and VIX >= mean+2std signal in the last 20 trading days -> buy 2 contracts, or 1 if cash only covers one, exits <12m +150%, 12-15m +80%, 16-18m +30%",
        sigma2GapAssumption: "if a sigma2 day is not the first sigma2 signal in the last 60 trading days and also not the second-or-later sigma2 signal in the last 20 trading days, no sigma2 entry is taken",
        shortCallOverlay: config.shortCall.enabled
          ? `while a LEAPS is open and has >${config.forceExitDaysToExpiry} days left, sell a ${config.shortCall.dteDays}-calendar-day call ${Math.round(config.shortCall.otmPct * 100)}% OTM, 1 short call per LEAPS contract, roll on expiry`
          : "disabled for comparison run",
        shortCallIvAssumption: config.shortCall.enabled
          ? "short OTM calls use the same realized-vol proxy as the LEAPS leg"
          : "not applicable because short call overlay is disabled",
        forcedExit: config.shortCall.enabled
          ? "force exit LEAPS at 180 days to expiry and buy back any still-open short call the same day"
          : "force exit LEAPS at 180 days to expiry",
        capital: "start with $20000 and do not add capital later",
        sizingAssumption: "sigma1 requires enough cash for 1 contract; sigma2 repeat buys 2 if possible, otherwise 1 if cash covers one contract; otherwise the signal is skipped",
        riskFreeRate: config.riskFreeRate,
      },
    },
  };
}

async function main() {
  const qqqRows = await fetchYahooChart(CONFIG.symbol, CONFIG.dataStart, CONFIG.backtestEnd);
  const vixRows = await fetchYahooChart(CONFIG.vixSymbol, CONFIG.dataStart, CONFIG.backtestEnd);
  const vixMap = new Map(vixRows.map((row) => [row.date, row]));

  for (const row of qqqRows) {
    const vixRow = vixMap.get(row.date);
    row.vix = vixRow?.close;
  }

  computeRsi(qqqRows, CONFIG.rsiPeriod);
  computeRealizedIv(qqqRows, CONFIG.ivLookbackDays, CONFIG.ivMultiplier, CONFIG.minIv, CONFIG.maxIv);
  computeExpandingStats(qqqRows, "vix", "vixMean", "vixStd");

  const strategyResult = runBacktest(qqqRows, CONFIG);

  const benchmarkCharts = [];
  for (const benchmark of CONFIG.benchmarks) {
    const rows = await fetchYahooChart(benchmark.symbol, CONFIG.compareStart, CONFIG.compareEnd);
    benchmarkCharts.push({ ...benchmark, rows });
  }

  const strategyCompareSeries = buildNormalizedSeries(
    strategyResult.equityCurve,
    "equity",
    CONFIG.compareStart,
    CONFIG.compareEnd,
    "Strategy",
  );

  const benchmarkSeries = benchmarkCharts.map((chart) =>
    buildNormalizedSeries(chart.rows, "adjClose", CONFIG.compareStart, CONFIG.compareEnd, chart.label)
  );

  const metrics = [
    computePerformanceMetrics(strategyCompareSeries, CONFIG.riskFreeRate),
    ...benchmarkSeries.map((series) => computePerformanceMetrics(series, CONFIG.riskFreeRate)),
  ];

  const comparisonRows = strategyCompareSeries.map((point) => ({
    date: point.date,
    strategyNormalized: round(point.normalized, 8),
    nasdaqCompositeNormalized: round(benchmarkSeries[0].find((row) => row.date === point.date)?.normalized ?? NaN, 8),
    sp500Normalized: round(benchmarkSeries[1].find((row) => row.date === point.date)?.normalized ?? NaN, 8),
  }));

  fs.mkdirSync(CONFIG.outputDir, { recursive: true });

  fs.writeFileSync(
    path.join(CONFIG.outputDir, `${CONFIG.outputPrefix}_strategy_summary.json`),
    JSON.stringify(
      {
        config: {
          backtestStart: CONFIG.backtestStart,
          backtestEnd: CONFIG.backtestEnd,
          compareStart: CONFIG.compareStart,
          compareEnd: CONFIG.compareEnd,
        },
        strategySummary: strategyResult.summary,
        comparisonMetrics: metrics,
      },
      null,
      2,
    ),
  );

  writeCsv(path.join(CONFIG.outputDir, `${CONFIG.outputPrefix}_strategy_trades.csv`), strategyResult.trades);
  writeCsv(path.join(CONFIG.outputDir, `${CONFIG.outputPrefix}_short_call_events.csv`), strategyResult.shortCallEvents);
  writeCsv(path.join(CONFIG.outputDir, `${CONFIG.outputPrefix}_strategy_open_positions.csv`), strategyResult.openPositions);
  writeCsv(path.join(CONFIG.outputDir, `${CONFIG.outputPrefix}_strategy_equity_curve.csv`), strategyResult.equityCurve);
  writeCsv(path.join(CONFIG.outputDir, `${CONFIG.outputPrefix}_comparison_curve.csv`), comparisonRows);
  writeCsv(
    path.join(CONFIG.outputDir, `${CONFIG.outputPrefix}_comparison_metrics.csv`),
    metrics.map((row) => ({
      label: row.label,
      startDate: row.startDate,
      endDate: row.endDate,
      tradingDays: row.tradingDays,
      totalReturn: round(row.totalReturn, 8),
      cagr: round(row.cagr, 8),
      annualizedVolatility: round(row.annualizedVolatility, 8),
      sharpe: row.sharpe == null ? "" : round(row.sharpe, 8),
      maxDrawdown: round(row.maxDrawdown, 8),
    })),
  );
  writeCsv(
    path.join(CONFIG.outputDir, `combined_backtest_and_trades_${CONFIG.outputPrefix}.csv`),
    buildCombinedCsvRows(strategyResult, metrics, CONFIG),
  );

  console.log(
    JSON.stringify(
      {
        strategySummary: strategyResult.summary,
        comparisonMetrics: metrics,
      },
      null,
      2,
    ),
  );
}

main().catch((err) => {
  console.error(err.stack || err.message);
  process.exit(1);
});
