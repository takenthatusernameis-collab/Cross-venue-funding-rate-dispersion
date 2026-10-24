# Free public source candidates

No source is assumed available until preflight and historical-coverage gates pass.

| Source | Candidate use | Public endpoint/docs | Limitation |
|---|---|---|---|
| Binance USD-M Futures | Metadata, funding history, hourly prices | `https://fapi.binance.com/fapi/v1/time`; [funding history](https://binance-docs.github.io/apidocs/futures/en/#get-funding-rate-history) | Regional/network restrictions and history limits must be checked. |
| Bybit V5 | Linear contract metadata, funding, klines | `https://api.bybit.com/v5/market/time`; [funding history](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate) | Pagination and per-symbol retention must be audited. |
| OKX | Swap metadata, funding, candles | `https://www.okx.com/api/v5/public/time`; [API docs](https://www.okx.com/docs-v5/en/) | Instrument IDs, settlement intervals, pagination and retention require verification. |
| Hyperliquid | Public perpetual metadata, funding, candles | `https://api.hyperliquid.xyz/info`; [API docs](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api) | Public POST interface and history coverage require verification. |
| CoinGecko public API | Candidate discovery; possible cap history | [API docs](https://docs.coingecko.com/reference/introduction) | Current rank is not historical point-in-time rank; free historical availability must be proven. |

The manual preflight checks bounded endpoint reachability only. It does not establish historical completeness, pagination exhaustion, delisted coverage, contract mapping, or point-in-time market-cap availability. If no credible free historical cap source meets the gate, mark BLOCKED_DATA_GATE and do not run the empirical grid.
