# frame-divergence-0.1 — pre-registration (written and committed BEFORE any run)

Trigger: SOL/USD 2026-11-23 07:03 Algiers — the app marked «الأرجح» UP on HOURS and DOWN on WEEK at the same time.
Question: when the HOURS trend and the WEEK trend disagree, is that informative (e.g. a short bounce inside a
weekly fall), and does any simple, executable spot policy built on it beat holding after costs?
The study does not assume the bounce-then-drop path; it measures it.

## Data (no look-ahead, sealed holdout untouched)
- BTC, ETH, SOL: Binance spot 15m and 1d (`market_data/crypto/<A>USDT`); XAU: Dukascopy M15 and daily built from H1
  (same construction as trend-follow-0.1). Start: BTC/ETH 2019-01-01, SOL 2021-01-01, XAU 2016-01-01.
- Every bar used opens AND closes before the decision time t. Data cut: all forward windows end before 2025-11-15.

## Decision times
- t = every day at 00:00 UTC (XAU: weekdays where the previous UTC day has >= 6 H1 bars).

## The two views (exactly the production code, imported from backend/goldquant)
- HOURS trend = `trend.market_trend` on `features.frame_features` last closed rows of M15, M30, H1, H4
  (M30/H1/H4 resampled from 15m, left-labelled, complete bars only), vol regime "RANGE" (direction does not depend on it).
- WEEK trend = `outlook.daily_trend_block(daily closed before t, "WEEK")` (close vs SMA20/50/200 all agree).
- Groups: D1 = HOURS UP & WEEK DOWN (the SOL case); D2 = HOURS DOWN & WEEK UP; AU = both UP; AD = both DOWN;
  OTHER = anything with SIDEWAYS/UNKNOWN.

## Forecast metrics (forecast evaluation, kept apart from trading)
- F_h: hit rate of the HOURS direction on sign(close[t+24h] − close[t]), per group.
- F_w: hit rate of the WEEK direction on sign(close[t+7d] − close[t]), per group.
- BTD (bounce then drop): max high in (t, t+48h] >= close[t] + 0.5·ATR20d  AND  close[t+7d] < close[t].
  ATR20d = daily ATR20 at the last closed day. Frequency per group and on ALL days.

## Hypotheses (one-sided; Holm across the 4 assets within each hypothesis; alpha 0.05)
- H1 (forecast): P(BTD | D1) − P(BTD | ALL) > 0, and the difference >= 5 percentage points.
- H2 (trading, holder, units after costs): on a D1 day, sell at close[t], buy back at close[t+7d].
  gain = close[t]·(1−f) / (close[t+7d]·(1+f)) − 1. Events non-overlapping (after an event, the next eligible
  D1 day is >= 7 days later). Compared with the SAME policy on every eligible day (non-overlapping, same spacing).
- H3 (trading, holder, bounce sale): on a D1 day place a limit SELL at close[t] + 0.5·ATR20d valid 48 h; if filled,
  buy back at close[t+7d]; if not filled, no trade (gain 0, counted). Same comparison as H2.
- Costs f per side (%): BTC 0.16, ETH 0.16, SOL 0.22, XAU 0.05 (sensitivity XAU 0.00 / 0.15 reported only).

## Inference
- Calendar-month block bootstrap, 10,000 reps, seed 20261122, on the per-event values (H1: per-day indicator
  differences D1 vs ALL with days resampled in month blocks).
- Class EXPLORATORY_PROMISING for an asset/hypothesis only if ALL hold: n(D1 events) >= 30; Holm-adjusted p < 0.05;
  effect > 0 (H1: >= 5 pp; H2/H3: mean gain > 0 AND > the all-days policy); sign holds in both chronological
  halves. Otherwise NOT_SUPPORTED. No criterion is changed after seeing results.
- Even EXPLORATORY_PROMISING is not a recommendation: it would need its own live pre-registered test.

## Reported descriptively (no inference)
- Group counts, F_h and F_w for every group, BTD for D2/AU/AD, mean 24h and 7d returns per group.
