# trend-follow-0.1 — «hold while the trend is up, step aside when it turns» (pre-registered 2026-11-22)

Status: EXPLORATORY, historical. Separate from every live study; their rules are untouched. A pass here can at most be
EXPLORATORY_PROMISING and must then go through a new live pre-registration before the app may call it qualified.
Source school: trend following / time-series momentum (the school with the strongest published evidence; strongest on
weekly-monthly horizons, so this study uses weekly decisions, not hours).

## Rules (no look-ahead)
- Decision: every Monday 00:00 UTC, from daily closes of days that ended before that time. Execution: the open of the
  first daily bar at or after the decision (crypto: Binance 1d; gold: UTC days built from Dukascopy H1, weekend-free).
- Trend signals (3 variants only, Holm across them per asset):
  V1 TSMOM-12: last close / close 252 trading days earlier − 1 > 0  (crypto: 365 calendar days of 1d bars)
  V2 TSMOM-6 : the same over 126 trading days (crypto 182 days)
  V3 SMA 50/200: SMA(50) of daily closes > SMA(200)
- Holder policy: trend up → hold the asset; trend down → sell into cash; buy back when it is up again. Starts holding.
  Result in UNITS of the asset vs simply holding 1 unit (the owner's yardstick), after fees.
- Costs per switch (one side): BTC 0.16 %, ETH 0.16 %, SOL 0.22 %; XAU 0.05 % (instrument not chosen; also shown at
  0 and 0.15).
- Data: XAU from 2016-01, BTC/ETH from 2018-01, SOL from 2020-09 (first decision after the warm-up of each variant).
  Hard cut: nothing on or after 2025-11-15 (te holdout sealed).

## Measures
- Monthly units change: log(units_strategy_end_of_month / units_start_of_month) relative to holding (holding = 0).
- Total units multiple at the end, worst drawdown in units, number of switches, time in the market, per-year results.

## Inference and classification (fixed now, never relaxed)
- Mean monthly units change; calendar-month block bootstrap (10,000 reps, seed 20261122), one-sided p for mean > 0;
  Holm across V1–V3 per asset at primary cost.
- EXPLORATORY_PROMISING only if ALL hold: >= 36 months; mean > 0; Holm p < 0.05; mean > 0 in both halves of the
  period; final units multiple > 1. Otherwise NOT_SUPPORTED.
- Reported, never classifying: the same rule for a cash user (buy when the trend is up), cost sensitivity, drawdowns.
