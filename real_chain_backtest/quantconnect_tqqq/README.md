# QuantConnect TQQQ Research Scaffold

`main.py` represents the deployed research rules:

- QQQ closes below the prior day.
- QQQ remains above SMA(200).
- QQQ Wilder RSI(14) is below 35.
- With no TQQQ or option position, sell an approximately 30-DTE cash-secured put near 90% of TQQQ spot.
- After assignment of at least 100 TQQQ shares, sell an approximately 30-DTE covered call at or above spot and average cost.
- LEAN handles expiry and assignment events.

The modeled window is `2021-08-13` through `2026-08-12` with $20,000 initial capital. No API tokens, broker keys, or QuantConnect credentials are included.

