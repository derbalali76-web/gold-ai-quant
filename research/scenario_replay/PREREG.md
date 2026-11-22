# scenario-replay-0.1 — does the app's «الأرجح هبوط» justify «sell now, buy back lower»? (pre-registered 2026-11-22)

Status: EXPLORATORY, historical. Separate from the live pre-registered studies (advice-units-0.1, te-live): their rules
are not changed by anything here. A pass here can at most be labelled EXPLORATORY_PROMISING and must then go through a
new live pre-registration before the app may show it as a qualified recommendation.

Owner's question (2026-11-22): the hours card says «سيناريو الهبوط — الأرجح: إذا نزل تحت S1 قد يكمل نحو S2» while
the price is above S1. Can the app issue «sell now and buy back at S2», non-randomly?

## The signal = the app's own engine, replayed point-in-time (no look-ahead)
- Decision time t: every UTC day at 00:00. Information: only bars closed before t.
- Levels: backend `levels.compute_levels(bars, t, p0)` (M15, H1, H4 bars closed before t; H4 resampled from H1).
  S1 = nearest support below p0, S2 = the next one, R1 = nearest resistance above p0 (exactly `brief.build`).
- «الأرجح»: backend `brief.outcome_table` (outcome3-0.1.0, unchanged) rebuilt walk-forward: on the first day of each
  month from the two years of H1 bars closed before that day (window 24 h crypto, 23 h gold), then `attach_outcome3`
  logic: usable cell, DOWN leads the second outcome by >= 5 points. (In production the table is built in CI over the
  last two years; this replay never lets a table see bars after the month it is used in.)
- Event = likely DOWN with S1 < p0 < R1 (the screenshot situation). p0 = open of the first H1 bar at or after t.

## Policies (identical scoring code: ledger/advice_units.score, units after fees vs holding 1 unit)
- P1 «sell now, buy back at S2» (= the app's advice-0.1.0: at = target or trigger, exit = R1):
  sell at p0; buy back at S2 (S1 if no S2), or protective buy-back above R1; otherwise marked at the last close.
- P2 «sell now, buy back at S1» (the level the table actually says is reached first). Same protection R1.
- AFTER_BREAK: first H1 close below S1, sell at the next open, then buy back at the P1 level (only if below the sale)
  or protection above R1.
- HOLD.
- Partial sales (30 %, 50 %): the units result scales exactly with the fraction (f x full), so they are reported as
  scaled numbers and never change a classification.

## Windows, assets, costs, data
- Primary window 168 H1 bars from t (same as advice-units-0.1); secondary 24 bars.
- XAU (Dukascopy H1/M15), BTC, ETH, SOL (Binance 1h/15m), each from its first date with two years of history.
- Hard cut: every bar used, outcome window included, is before 2025-11-15 (te holdout sealed).
- Costs per round trip, % of p0 (half per side): BTC 0.32, ETH 0.32, SOL 0.44; XAU 0.10 (also shown at 0 and 0.30).

## Baseline (does «الأرجح» add anything?)
- Same policy on every decision day with S1 < p0 < R1, whatever the table says (unconditioned).

## Inference and classification (fixed now, never relaxed)
- Calendar-month block bootstrap of the mean (10,000 reps, seed 20261122), one-sided p for mean > 0; Holm across
  P1 and P2 per asset (primary window, primary cost).
- EXPLORATORY_PROMISING only if ALL hold: n >= 30; mean > 0; Holm p < 0.05; beat-HOLD rate >= 0.5; mean > AFTER_BREAK
  mean; mean > unconditioned mean; mean > 0 in both halves (split at the median event date). Else NOT_SUPPORTED
  (TOO_FEW if n < 30). Secondary window and other costs: reported only.
- Always reported: NO_REBUY, PROTECTION, ROSE_NO_RETURN counts; how often S1 was actually reached first in 24 h when
  the table said DOWN (calibration of «الأرجح»).
