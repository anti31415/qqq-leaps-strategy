# Tianbro QQQ LEAPS Strategy

本目录整理了“天哥 QQQ LEAPS 期权复利引擎”视频对应的本地化研究结果，包括字幕清洗、策略总结、近似回测和近十年对比分析。

## 文件说明

- `01_清洗字幕.md`：清洗后的字幕稿
- `02_策略总结.md`：结构化策略说明
- `03_回测结果.md`：基础版 `QQQ LEAPS` 近似回测结果
- `04_近十年收益_夏普_波动率对比.md`：`2016-03-01` 到 `2026-03-31` 的策略、纳指、标普对比
- `backtest_tianbro_qqq_leaps.js`：回测脚本
- `outputs/strategy_summary.json`：总结果摘要
- `outputs/strategy_trades.csv`：逐笔交易记录
- `outputs/strategy_equity_curve.csv`：策略日度权益曲线
- `outputs/comparison_curve.csv`：策略与基准的标准化净值曲线
- `outputs/comparison_metrics.csv`：收益、夏普、波动率等指标表

## 回测说明

这不是逐笔真实期权链复盘，而是按视频规则加上 `VIX` 极端过滤做的近似建模：

- 标的价格来自 `Yahoo Finance`
- `VIX` 过滤条件为：`VIX >= 历史扩展均值 + 2σ`
- 初始本金固定为 `$20,000`，中间不追加资金
- 止盈条件为：`<12m +150%`、`12-15m +75%`、`16-18m +30%`
- 波动率使用历史实现波动率近似
- 期权价格使用 `Black-Scholes`
- `Covered Call` 进阶增强未纳入主回测

## 重新运行

```powershell
& 'C:\Users\antiz\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' `
  'C:\Users\antiz\OneDrive\Desktop\Codex\量化研究\tianbro_qqq_leaps_strategy\backtest_tianbro_qqq_leaps.js'
```
