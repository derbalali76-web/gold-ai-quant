# AI QUANT Trade Engine — pre-registration te-0.1.0

Status: **registered 2026-11-18, before any rule of the family below was evaluated on any data.**
Changing anything here after results are seen requires a new version (te-0.2.0) and a NEW untouched test period.
The existing range / HILO / outcome3 / advice engines, their ledger and their criteria are not affected.

## Scope
Spot, long only. BTCUSDT and SOLUSDT, 4h decisions (UTC grid 00/04/08/12/16/20). ETH and gold only after this
version passes. Research and paper only: no real buy instruction to users, no automation, no user money.

## Data (audited 2026-11-18)
Binance spot bars stored in `market_data/crypto/{SYMBOL}/{1h,15m}`; 4h built from complete groups of four 1h bars.
| asset | 1h from | 15m from | missing 1h | missing 15m | bad OHLC |
|---|---|---|---|---|---|
| BTC | 2018-01 | 2021-01 | 0.21 % (max gap 75 h, 2018) | 0.034 % | 0 |
| SOL | 2020-09 | 2021-01 | 0.035 % | 0.034 % | 0 |
Every report records the sha256 of the files it read (`data.fingerprint`).

## Periods
- Development: decisions 2021-01-01 .. 2025-11-08 (7-day embargo before the holdout).
- Walk-forward test windows inside development: 2022, 2023, 2024, 2025-01-01..2025-11-15.
  The probability model for a window is fitted only on decisions that ended ≥ 7 days before it starts.
- **Holdout (sealed): 2025-11-15 .. 2026-11-14.** The code refuses it unless `TE_UNSEAL_HOLDOUT=te-0.1.0`;
  it is opened once, in phase 3, for the configurations selected in phase 2, and never again for this version.

## Simulator (trade_engine/sim.py, tests: backend/tests/test_v30_trade_sim.py)
- Decision at the 4h close; order live from that moment. Entry: resting limit, filled only when price trades
  strictly below it (or opens below → filled at the open). Entry timeout 3 bars (12 h; family B also 6 bars).
- Exits: take-profit limit (strictly through), stop-market (slippage), time exit after 30 bars (5 days).
- Intrabar order resolved on 15m bars (1h before 2021); stop wins when both levels are reachable in one bar;
  no take-profit in the fill bar.
- Costs: maker = taker = 0.10 % (Binance regular tier, checked 2026-11-18); half-spread 0.01 % BTC / 0.02 % SOL on
  market orders; slippage 0.05 % BTC / 0.10 % SOL on market, stop and time exits. Sensitivity ×0.75 and ×2.
- One position per asset at a time; signals while an order is pending or open are skipped.

## Rule family (trade_engine/rules.py) — 24 configurations × 2 assets = 48 hypotheses
- A — pullback in uptrend: close > EMA200, EMA50 > EMA200, RSI14 < 40. Limit = close − k·ATR14, k ∈ {0.25, 0.75};
  stop = limit − m·ATR, m ∈ {1.5, 2.5}; target = limit + r·(limit − stop), r ∈ {1, 2}.
- B — breakout retest: close > highest high of the prior 20 bars and volume > 1.5 × its 20-bar mean.
  Limit = that prior high; timeout ∈ {3, 6} bars; m ∈ {1.5, 2.5}; r ∈ {1, 2}.
- C — oversold bounce: close < SMA20 − 2·SD20 and RSI14 < 30. Limit = close − k·ATR, k ∈ {0, 0.5};
  m ∈ {1.5, 2.5}; target ∈ {SMA20 (structure), 1.5 R}.

## Three separate probabilities (never derived from the range or HILO engines)
1. P(fill) — the limit is filled within the timeout.
2. P(target before stop | filled).
3. P(net profit > 0 | filled), after all costs.
Each is reported as an empirical rate with a Wilson 95 % interval, and as a model probability: logistic
regression on four inputs fixed now (ATR/close, RSI14, close/EMA200 − 1, entry distance in ATR), fitted per
walk-forward window. Calibration: Brier score, Brier skill vs the training base rate, 10-bin reliability curve.

## Baselines (same simulator, same costs)
Cash; buy-and-hold; every-bar limit order (generic geometry); every-bar market order; trend-only (close > EMA200);
**random entry with the configuration's own geometry**, matched count, 1 000 draws — the main comparison.

## Phase 2 selection (development data only)
A configuration goes to the holdout only if, pooled over the four walk-forward windows:
- ≥ 40 filled trades; mean net return > 0; profit factor > 1.1; positive mean in ≥ 3 of 4 windows;
- one-sided p < 0.05 vs its random-entry distribution after **Holm correction over all 48 hypotheses**;
- Brier skill > 0 for probability 2 or 3.
At most 3 configurations per asset (ranked by the lower bound of the mean-return interval).
If none qualify, the result is "no edge found" and the engine stops at research.

## Phase 3 acceptance (holdout, evaluated once)
A configuration PASSES only if all hold: ≥ 30 filled trades (fewer → INCONCLUSIVE, not pass);
profit factor > 1.2 and its 95 % block-bootstrap lower bound > 1.0; mean net return > 0 with interval excluding 0;
beats its random-entry distribution at p < 0.05 after Holm over the configurations tested; Brier skill > 0.
Max drawdown is reported next to buy-and-hold over the same months.

## Phase 4 live paper test (separate ledger)
- Own hash-chained file `trade_engine/trades.jsonl` in the public ledger repository, daily OpenTimestamps anchor,
  independent of `ledger.jsonl`. Each ORDER line is written before the order can fill and carries: engine version,
  configuration id, decision time, recorded time, data sha, limit/stop/target/timeouts, cost assumptions,
  and the three probabilities. The simulation starts at the recorded time, not the bar close.
- Fills and exits resolved from Binance 15m bars by the same simulator code (pinned commit).
- PASS: ≥ 60 filled trades AND ≥ 12 weeks, profit factor > 1.2 with lower bound > 1.0, mean net > 0,
  Brier skill > 0, and in every reliability bin with n ≥ 15 the observed rate within 10 points of the forecast.
- FAIL: any criterion missed at that point. Early stop: drawdown > 2 × the holdout's maximum drawdown.
- Until PASS the app may only show these trades labelled «تجريبي» (experimental), never as buy instructions;
  any screen change is shown as a mockup for approval first.
