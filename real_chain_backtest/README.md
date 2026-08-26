# Real EOD Chain Backtest

这部分用于在真实的 QQQ 日终期权链上复核 LEAPS 策略。脚本会生成并验证 `outputs/` 下的情景指标、权益曲线、交易记录和数据质量报告。

## 数据准备

原始数据不随 Git 仓库分发：`QQQ_options.parquet` 约 387 MB，超过 GitHub 普通仓库的单文件限制。请从 `lambdaclass/options_portfolio_backtester` 的 `data-v1` release 获取以下文件并放入 `data/`：

- `QQQ_options.parquet`：15,345,882 行，覆盖 `2011-03-23` 至 `2025-12-15`
- `QQQ_underlying.parquet`
- `VIX_History.csv`：Cboe VIX 历史数据

`QQQ_options.parquet` 的已知 SHA-256：

```text
1F831556CD87EC9D7AF43D3B47A69A829FFB2FB199CFCEF4FF55D289BADF8734
```

## 运行

```powershell
python -m pip install -r requirements.txt
python profile_chain.py
python backtest_real_chain.py
python validate_outputs.py
```

回测窗口是 `2020-12-16` 至 `2025-12-15`。成交情景包括 mid、半点差 25%/50% 和 ask-buy/bid-sell。结果是研究级 EOD 模型，不是盘中 NBBO 或真实成交保证。

