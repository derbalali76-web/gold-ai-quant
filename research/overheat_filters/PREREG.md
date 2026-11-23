# overheat-filters-0.1 — pre-registration (written and committed BEFORE any run)

Owner request 2026-11-23 11:06: test all suitable "overheated" indicators, not RSI alone.
rsi-cooldown-0.1 (commit with results after 6f39a2e) found RSI alone NOT_SUPPORTED; it is kept as reported and RSI is
re-included here only as one member of the family, with the stricter multiple-testing correction below.

Everything not stated here is IDENTICAL to rsi-cooldown-0.1 PREREG.md (data, cut 2025-11-15, decision grid every 4 h,
production levels and trend, the app's BUY_NOW rule for a cash user, 72 h non-overlap, policies A / B1 / B2,
gain(B) = p0 / price_B − 1, calendar-month block bootstrap 10,000 reps). Seed 20261124.

## Overheat flags (each computed on closed H1 bars AND on closed H4 bars; the flag is ON if either frame is ON)
- F1 RSI(14, Wilder) >= 70
- F2 Stochastic %K(14) smoothed by SMA(3) >= 80
- F3 Bollinger %B(20, 2σ) >= 1 (close at or above the upper band)
- F4 (close − EMA20) / ATR14 >= 2
- F5 CCI(20) >= 100
- F6 rise over the last 24 bars >= 3 × ATR14
- F7 VOTE: at least 3 of F1–F6 ON

## Hypotheses
- For each flag Fk, policy P ∈ {B1, B2}, asset: on BUY_NOW events with Fk ON, mean gain(P) > 0 (one-sided).
- Holm correction across all 28 tests of the same policy (7 flags × 4 assets).
- Class EXPLORATORY_PROMISING only if ALL hold: n(ON events) >= 30; Holm p < 0.05; mean gain > 0; > 0 in both
  chronological halves; mean gain on OFF events lower. Otherwise NOT_SUPPORTED. No change after seeing results.

## Decision rule for the app (fixed now)
- A flag+policy enters the app only if it is EXPLORATORY_PROMISING on >= 2 of the 4 assets and its mean gain is not
  negative on any asset. If several qualify, the one with the most qualifying assets, then the highest mean gain.
  Otherwise the app rule stays as is.
