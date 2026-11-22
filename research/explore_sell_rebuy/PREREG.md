# explore-sell-rebuy-0.1 — exploratory historical study (pre-registered 2026-11-22, before any run)

Status: EXPLORATORY. It is separate from the live pre-registered study advice-units-0.1 (ledger/advice_units.py),
whose rules, population and verdict are NOT changed by anything here. A result of this study can never be shown
as a qualified recommendation; at best it is labelled EXPLORATORY_PROMISING and waits for the live study.

## Question
For a holder of 1 unit, does selling *before* a nearby support breaks, then buying back lower (or protecting above),
end with more units after fees than (a) holding and (b) selling only after the support breaks?

## Data (no look-ahead, holdout sealed)
- XAU: Dukascopy XAUUSD H1 (market_data/bars/Dukascopy/XAUUSD/H1), 2016-01 onward.
- BTC, ETH, SOL: Binance spot 1h (market_data/crypto/<SYM>/1h), from each file's start.
- Hard cut: every bar used, including the full 168 h outcome window, is before 2025-11-15 00:00 UTC (the te holdout
  2025-11-15..2026-11-14 stays sealed). Decision days after 2025-11-07 are therefore impossible.

## Event definition (information = only bars closed before decision time t)
- Decision time t = each UTC day 00:00; p0 = open of the first H1 bar at or after t (must start within 1 h of t).
- ATR = mean of the last 14 complete UTC-day true ranges, built from H1 bars closed before t.
- Support S = lowest low of the 72 H1 bars closed before t.
- Signal (the SELL_NOW analogue) when: S < p0 <= S + prox * ATR AND the 24 h return to t (last close / close 24 bars
  earlier − 1) is negative.
- Levels: buy-back `at` = S − k * ATR; protection `exit` = p0 + 1 * ATR.
- Grid (4 variants, no others will be run or reported as primary): k in {0.5, 1.0} x prox in {0.5, 1.0}.

## Outcome (identical code to the live study)
- ledger/advice_units.score with the 168 H1 bars from t (t <= bar < t + 168 h): policies HOLD, PRE_EMPTIVE,
  AFTER_BREAK, units gain % after fees, rebuy_reached, max_after_pct, rose_no_return.
- Costs, one round trip in % of p0 (each side pays half): BTC 0.32, ETH 0.32, SOL 0.44 (0.10 % fee + half-spread +
  slippage per side, as trade_engine/sim.py). XAU instrument not chosen: primary 0.10, shown also at 0.00 and 0.30.

## Baseline
- Unconditioned: the same levels (S, ATR, k) applied on every decision day of the asset (prox condition and 24 h
  condition removed). Reported: conditioned mean − unconditioned mean (does the signal add anything over selling
  on any day?).

## Inference
- Calendar-month block bootstrap of the mean PRE_EMPTIVE gain (10,000 reps, seed 20261122); one-sided p for mean > 0.
- Holm correction across the 4 variants, per asset.

## Classification per asset x variant (fixed now, never relaxed)
EXPLORATORY_PROMISING only if ALL hold: n >= 30 events; mean gain > 0 after primary costs; Holm-adjusted p < 0.05;
beat-HOLD rate >= 0.5; mean > AFTER_BREAK mean; conditioned mean > unconditioned mean; mean > 0 in both halves of
the asset's period (split at the median event date). Otherwise NOT_SUPPORTED (or TOO_FEW if n < 30).
Always reported: counts of NO_REBUY, PROTECTION and ROSE_NO_RETURN (price rose after the sale and never came back).
