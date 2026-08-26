# QuantConnect 云端迁移：QQQ/TQQQ

`main.py` 对应本机部署版的核心规则：

- QQQ 日线收盘低于前一日；
- QQQ 高于 SMA(200)；
- QQQ Wilder RSI(14) < 35；
- 无 TQQQ 持仓及期权持仓时，卖出约 30 DTE、执行价接近 TQQQ 现价 90% 的现金担保 Put；
- Put 被指派得到至少 100 股 TQQQ 后，卖出约 30 DTE、执行价不低于现价和持仓均价的 Covered Call；
- 期权到期和指派由 LEAN 处理。

回测区间为 2021-08-13 至 2026-08-12，初始资金 $20,000。该项目不含 API token、Alpaca 密钥或 QuantConnect 凭据。

云端命令（需要 QuantConnect 付费组织账户）：

```powershell
lean login
lean init
lean cloud backtest "quantconnect_tqqq" --push --name "QQQ-TQQQ 5Y real options"
```
