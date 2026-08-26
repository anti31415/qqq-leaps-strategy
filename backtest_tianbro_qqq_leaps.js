const fs = require("fs");
const https = require("https");
const path = require("path");

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
  regimes: [
    {
      name: "sigma2_daily_2lot",
      vixStdMultiplier: 2,
      quantity: 2,
      allowPartialFill: true,
      buyLimit: "daily",
      exitRules: [
        { minAgeDays: 0, maxAgeDays: 364, profitTarget: 1.5, label: "take_profit_150_before_12m" },
        { minAgeDays: 365, maxAgeDays: 456, profitTarget: 0.75, label: "take_profit_75_12_to_15m" },
        { minAgeDays: 457, maxAgeDays: 548, profitTarget: 0.3, label: "take_profit_30_16_to_18m" },
      ],
    },
    {
      name: "sigma1_weekly_1lot",
      vixStdMultiplier: 1,
      quantity: 1,
      allowPartialFill: false,
      buyLimit: "weekly",
      exitRules: [
        { minAgeDays: 0, maxAgeDays: 364, profitTarget: 1.0, label: "take_profit_100_before_12m" },
        { minAgeDays: 365, maxAgeDays: 456, profitTarget: 0.5, label: "take_profit_50_12_to_15m" },
        { minAgeDays: 457, maxAgeDays: 548, profitTarget: 0.3, label: "take_profit_30_16_to_18m" },
      ],
    },
  ],
  riskFreeRate: 0.03,
  ivLookbackDays: 252,
  ivMultiplier: 1.2,
  minIv: 0.15,
  maxIv: 0.75,
  contractMultiplier: 100,
  roundStrikeTo: 1,
  outputDir: path.join(__dirname, "outputs"),
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

function pricePosition(row, position, config) {
  const daysLeft = Math.max(0, dayDiff(row.date, position.expiryDate));
  const t = daysLeft / 365.25;
  const sigma = row.iv || position.entryIv;
  const pricePerContract = callPrice(row.adjClose, position.strike, t, config.riskFreeRate, sigma) * config.contractMultiplier;
  return pricePerContract * position.quantity;
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
  if (code === "take_profit_100_before_12m") return "held <12 months and reached +100% profit";
  if (code === "take_profit_50_12_to_15m") return "held 12-15 months and reached +50% profit";
  if (code === "take_profit_120_before_12m") return "held <12 months and reached +120% profit";
  if (code === "take_profit_65_12_to_15m") return "held 12-15 months and reached +65% profit";
  if (code === "take_profit_150_before_12m") return "held <12 months and reached +150% profit";
  if (code === "take_profit_75_12_to_15m") return "held 12-15 months and reached +75% profit";
  if (code === "take_profit_30_16_to_18m") return "held 16-18 months and reached +30% profit";
  if (code === "force_exit_180d_to_expiry") return "forced exit with 180 days left to expiry";
  return code;
}

function describeRegime(regimeName) {
  if (regimeName === "sigma2_daily_2lot") return "VIX >= mean + 2*std, buy 2 contracts per signal day, or 1 if cash is insufficient for 2";
  if (regimeName === "sigma1_weekly_1lot") return "mean + 1*std <= VIX < mean + 2*std, buy 1 contract max once per week";
  return regimeName;
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
    entryUnderlying: "",
    exitUnderlying: "",
    strike: "",
    entryCost: "",
    exitValue: "",
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
    const vixThreshold = trade.entryVixMean + trade.vixStdMultiplier * trade.entryVixStd;
    addRow({
      recordType: "trade",
      section: "trade_log",
      entryDate: trade.entryDate,
      exitDate: trade.exitDate,
      regime: trade.regime,
      quantity: trade.quantity,
      vixStdBand: trade.vixStdMultiplier,
      entryUnderlying: trade.entryUnderlying,
      exitUnderlying: trade.exitUnderlying,
      strike: trade.strike,
      entryCost: trade.entryCost,
      exitValue: trade.exitValue,
      pnl: trade.pnl,
      pnlPct: trade.pnlPct,
      ageDays: trade.ageDays,
      entryRsi: trade.entryRsi,
      entryVix: trade.entryVix,
      entryVixMean: trade.entryVixMean,
      entryVixStd: trade.entryVixStd,
      vixThreshold: round(vixThreshold, 6),
      buyReason: `RSI(${config.rsiPeriod}) ${trade.entryRsi} < ${config.rsiBuyBelow}; VIX ${trade.entryVix} >= ${round(vixThreshold, 4)}; ${describeRegime(trade.regime)}; qty=${trade.quantity}`,
      sellReason: describeSellReason(trade.reason),
      rawReason: trade.reason,
    });
  }

  return rows;
}

function matchRegime(row, config) {
  for (const regime of config.regimes) {
    const threshold = row.vixMean + row.vixStd * regime.vixStdMultiplier;
    if (row.vix >= threshold) {
      return {
        regime,
        threshold,
      };
    }
  }
  return null;
}

function runBacktest(rows, config) {
  const positions = [];
  const trades = [];
  const equityCurve = [];
  let availableCash = config.initialCapital;
  let skippedSignalsInsufficientCash = 0;
  let lastSigma1Week = null;

  for (const row of rows) {
    if (row.date < config.backtestStart || row.date > config.backtestEnd) continue;
    if (
      !Number.isFinite(row.rsi) ||
      !Number.isFinite(row.iv) ||
      !Number.isFinite(row.vix) ||
      !Number.isFinite(row.vixMean) ||
      !Number.isFinite(row.vixStd)
    ) continue;

    for (let i = positions.length - 1; i >= 0; i--) {
      const pos = positions[i];
      const value = pricePosition(row, pos, config);
      const pnlPct = (value - pos.entryCost) / pos.entryCost;
      const ageDays = dayDiff(pos.entryDate, row.date);
      const daysToExpiry = dayDiff(row.date, pos.expiryDate);
      let reason = null;

      for (const rule of pos.exitRules) {
        if (ageDays >= rule.minAgeDays && ageDays <= rule.maxAgeDays && pnlPct >= rule.profitTarget) {
          reason = rule.label;
          break;
        }
      }
      if (!reason && daysToExpiry <= config.forceExitDaysToExpiry) {
        reason = "force_exit_180d_to_expiry";
      }

      if (reason) {
        const pnl = value - pos.entryCost;
        availableCash += value;
        trades.push({
          entryDate: pos.entryDate,
          exitDate: row.date,
          regime: pos.regime,
          vixStdMultiplier: pos.vixStdMultiplier,
          quantity: pos.quantity,
          entryUnderlying: round(pos.entryUnderlying, 4),
          exitUnderlying: round(row.adjClose, 4),
          entryRsi: round(pos.entryRsi, 4),
          entryIv: round(pos.entryIv, 4),
          entryVix: round(pos.entryVix, 4),
          entryVixMean: round(pos.entryVixMean, 4),
          entryVixStd: round(pos.entryVixStd, 4),
          exitIv: round(row.iv, 4),
          strike: pos.strike,
          entryCost: round(pos.entryCost, 4),
          exitValue: round(value, 4),
          pnl: round(pnl, 4),
          pnlPct: round(pnlPct, 6),
          ageDays,
          reason,
          win: pnl > 0,
        });
        positions.splice(i, 1);
      }
    }

    const regimeMatch = matchRegime(row, config);
    const vixThreshold = regimeMatch ? regimeMatch.threshold : NaN;

    let canBuy = false;
    if (regimeMatch) {
      if (regimeMatch.regime.buyLimit === "daily") {
        canBuy = true;
      } else if (regimeMatch.regime.buyLimit === "weekly") {
        canBuy = weekKey(row.date) !== lastSigma1Week;
      }
    }

    if (row.rsi < config.rsiBuyBelow && regimeMatch && canBuy) {
      const t = config.contractDays / 365.25;
      const strike = strikeForDelta(row.adjClose, config.targetDelta, t, config.riskFreeRate, row.iv, config.roundStrikeTo);
      const perContractCost = callPrice(row.adjClose, strike, t, config.riskFreeRate, row.iv) * config.contractMultiplier;
      let actualQuantity = regimeMatch.regime.quantity;
      let entryCost = perContractCost * actualQuantity;

      if (regimeMatch.regime.allowPartialFill && availableCash < entryCost && availableCash >= perContractCost) {
        actualQuantity = 1;
        entryCost = perContractCost;
      }

      if (availableCash >= entryCost) {
        availableCash -= entryCost;
      } else if (config.allowAdditionalCapital) {
        availableCash = 0;
      } else {
        skippedSignalsInsufficientCash += 1;
        const openValue = positions.reduce((sum, pos) => sum + pricePosition(row, pos, config), 0);
        const equity = availableCash + openValue;
        equityCurve.push({
          date: row.date,
          equity: round(equity, 6),
          openValue: round(openValue, 6),
          availableCash: round(availableCash, 6),
          openContracts: positions.reduce((sum, pos) => sum + pos.quantity, 0),
          qqqAdjClose: round(row.adjClose, 6),
          qqqRsi: round(row.rsi, 6),
          qqqIv: round(row.iv, 6),
          vixClose: round(row.vix, 6),
          vixMean: round(row.vixMean, 6),
          vixStd: round(row.vixStd, 6),
          vixThreshold: round(vixThreshold, 6),
        });
        continue;
      }

      positions.push({
        entryDate: row.date,
        expiryDate: addUtcDays(row.date, config.contractDays),
        regime: regimeMatch.regime.name,
        vixStdMultiplier: regimeMatch.regime.vixStdMultiplier,
        quantity: actualQuantity,
        exitRules: regimeMatch.regime.exitRules,
        entryUnderlying: row.adjClose,
        entryRsi: row.rsi,
        entryIv: row.iv,
        entryVix: row.vix,
        entryVixMean: row.vixMean,
        entryVixStd: row.vixStd,
        strike,
        entryCost,
      });

      if (regimeMatch.regime.buyLimit === "weekly") {
        lastSigma1Week = weekKey(row.date);
      }
    }

    const openValue = positions.reduce((sum, pos) => sum + pricePosition(row, pos, config), 0);
    const equity = availableCash + openValue;
    equityCurve.push({
      date: row.date,
      equity: round(equity, 6),
      openValue: round(openValue, 6),
      availableCash: round(availableCash, 6),
      openContracts: positions.reduce((sum, pos) => sum + pos.quantity, 0),
      qqqAdjClose: round(row.adjClose, 6),
      qqqRsi: round(row.rsi, 6),
      qqqIv: round(row.iv, 6),
      vixClose: round(row.vix, 6),
      vixMean: round(row.vixMean, 6),
      vixStd: round(row.vixStd, 6),
      vixThreshold: Number.isFinite(vixThreshold) ? round(vixThreshold, 6) : "",
    });
  }

  const lastRow = rows.filter((row) => row.date <= config.backtestEnd).at(-1);
  const endingOpenValue = positions.reduce((sum, pos) => sum + pricePosition(lastRow, pos, config), 0);
  const endingEquity = availableCash + endingOpenValue;
  const years = dayDiff(config.backtestStart, config.backtestEnd) / 365.25;
  const totalPnl = endingEquity - config.initialCapital;
  const cagr = config.initialCapital > 0 ? (endingEquity / config.initialCapital) ** (1 / years) - 1 : 0;
  const contractsEntered = trades.reduce((sum, trade) => sum + trade.quantity, 0) + positions.reduce((sum, pos) => sum + pos.quantity, 0);

  return {
    trades,
    openPositions: positions.map((pos) => ({
      entryDate: pos.entryDate,
      expiryDate: pos.expiryDate,
      regime: pos.regime,
      vixStdMultiplier: pos.vixStdMultiplier,
      quantity: pos.quantity,
      entryUnderlying: round(pos.entryUnderlying, 4),
      entryRsi: round(pos.entryRsi, 4),
      entryIv: round(pos.entryIv, 4),
      entryVix: round(pos.entryVix, 4),
      entryVixMean: round(pos.entryVixMean, 4),
      entryVixStd: round(pos.entryVixStd, 4),
      strike: pos.strike,
      entryCost: round(pos.entryCost, 4),
    })),
    equityCurve,
    summary: {
      symbol: config.symbol,
      backtestStart: config.backtestStart,
      backtestEnd: config.backtestEnd,
      model: "Approximate Black-Scholes LEAPS model using Yahoo adjusted close and trailing realized volatility",
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
      endingOpenValue,
      assumptions: {
        signal: `RSI(${config.rsiPeriod}) < ${config.rsiBuyBelow} with tiered VIX entry filters`,
        option: `~${config.contractDays} days to expiry, target delta ${config.targetDelta}`,
        sigma1: "expanding mean + 1 std <= VIX < expanding mean + 2 std -> buy 1 contract, max once per week, exits: <12m +100%, 12-15m +50%, 16-18m +30%",
        sigma2: "VIX >= expanding mean + 2 std -> buy 2 contracts, max once per day; if cash is insufficient for 2 but enough for 1, buy 1 instead; exits: <12m +150%, 12-15m +75%, 16-18m +30%",
        forcedExit: "force exit at 180 days to expiry",
        iv: `${config.ivLookbackDays}d realized volatility * ${config.ivMultiplier}, clamped to ${config.minIv}-${config.maxIv}`,
        capital: config.allowAdditionalCapital
          ? `start with $${config.initialCapital} and allow extra capital if needed`
          : `start with $${config.initialCapital} and do not add capital later`,
        sizingAssumption: "sigma1 requires enough cash for 1 contract; sigma2 buys 2 if possible, otherwise 1 if cash covers one contract, otherwise the signal is skipped",
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
    benchmarkCharts.push({
      ...benchmark,
      rows,
    });
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
    path.join(CONFIG.outputDir, "tiered_vix_strategy_summary.json"),
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

  writeCsv(path.join(CONFIG.outputDir, "tiered_vix_strategy_trades.csv"), strategyResult.trades);
  writeCsv(path.join(CONFIG.outputDir, "tiered_vix_strategy_open_positions.csv"), strategyResult.openPositions);
  writeCsv(path.join(CONFIG.outputDir, "tiered_vix_strategy_equity_curve.csv"), strategyResult.equityCurve);
  writeCsv(path.join(CONFIG.outputDir, "tiered_vix_comparison_curve.csv"), comparisonRows);
  writeCsv(
    path.join(CONFIG.outputDir, "tiered_vix_comparison_metrics.csv"),
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
    path.join(CONFIG.outputDir, "combined_backtest_and_trades_tiered_vix_v2.csv"),
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
