# rsi-cooldown-0.1 — pre-registration (written and committed BEFORE any run)

Trigger: SOL/USD 2026-11-23 10:49 Algiers — «ماذا أفعل؟» (cash) said «اشترِ الآن» while RSI(14) on H1 was ~71.
Question: when the beginner rule says BUY NOW to a cash user and RSI is hot, does waiting give MORE UNITS than
buying immediately? (A cash user buys in every policy; only the price differs.)

## Data (no look-ahead, sealed holdout untouched)
- BTC, ETH, SOL: Binance spot 15m (H1, H4 resampled, complete bars only). XAU: Dukascopy M15 and H1 (H4 resampled).
- Every bar used closes at or before the decision time t. All forward windows end before 2025-11-15.
- Start: two years after each asset's first H1 bar, as in scenario-replay-0.1 (level engine warm-up).

## Decision times and the rule being tested (exactly the app's rule)
- t = every 4 hours on the UTC grid (00, 04, …, 20). XAU: only when the market traded in the hour before t.
- Price p0 = last closed 15m close before t.
- Levels = production `goldquant.levels.compute_levels(bars, t, p0)` with the same bar windows as scenario-replay-0.1.
  S = nearest support below p0, R = nearest resistance above p0.
- Trend = production `goldquant.trend.market_trend` on the last closed M15, M30, H1, H4 feature rows, regime "RANGE".
- BUY_NOW event = the app's `SimpleAdvice` cash rule: trend UP and (p0 − S)/(R − S) <= 0.66.
- HOT = Wilder RSI(14) on closed H1 closes >= 70 OR on closed H4 closes >= 70.
- Events non-overlapping: after an event, the next one is taken >= 72 h later.

## Policies (cash user, units per dollar; the same buy fee on every policy, so fees cancel)
- A (today's app): buy at p0.
- B1 (wait for support): limit BUY at S valid 72 h; if not filled, buy at the close at t+72h.
- B2 (wait a day): buy at the close at t+24h.
- gain(B) = p0 / price_B − 1 (> 0 = more units than A).

## Hypotheses (one-sided; Holm across the 4 assets within each; alpha 0.05)
- H1: on HOT events, mean gain(B1) > 0.   H2: on HOT events, mean gain(B2) > 0.
- Calendar-month block bootstrap, 10,000 reps, seed 20261123.
- Class EXPLORATORY_PROMISING only if ALL hold: n(HOT events) >= 30; Holm-adjusted p < 0.05; mean gain > 0;
  mean gain > 0 in both chronological halves; and the same policy on NOT-HOT events has a lower mean gain
  (the filter must add something beyond "waiting is generally better"). Otherwise NOT_SUPPORTED.
- No criterion changes after seeing results.

## Decision rule for the app (fixed now)
- Add the RSI cool-down to the app only if H1 or H2 is EXPLORATORY_PROMISING on at least 2 of the 4 assets and on
  none of them is the mean gain negative. Otherwise the app rule stays as is and the result is reported.

## Reported descriptively
- Counts of BUY_NOW, HOT and NOT-HOT events; mean 24h and 72h return after each; fill rate of B1.
