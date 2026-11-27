# idea-replay-0.1 — the «ماذا أفعل؟» rule replayed on history

Pre-registered 2026-11-27 (owner request: «اختبار القاعدة على التاريخ»), written before the replay was run.
Nothing below is changed after results exist; a change gets a new name and the reason.

## Question
Do the beginner ideas of the app (rule beginner-ideas-0.3 in `ledger/ideas.py` = `SimpleAdvice.kt`) beat the obvious
alternative after fees, on past data, for gold, bitcoin, ether and solana? And does the bitcoin filter help?

## What is replayed
- Horizon HOURS only (the app's default; it uses the decision's own trend and levels).
- Sample times: every 4 hours on the hour (00, 04, … 20 UTC), from 2024-12-01 to the last bar available
  (crypto 2026-11-20). For each asset and each sample time t, only data closed by t is used.
- Trend at t: `trend.market_trend` on the last closed row of `features.frame_features` for M15, M30, H1, H4 (the
  engines' own code; M30 and H4 resampled from M15 / H1; vol regime "RANGE", which affects strength, not direction).
- Levels at t: `levels.compute_levels` (the engines' own code, point-in-time by construction) without the strength
  model (strength does not change prices); the first two supports and resistances, as the public snapshot records;
  ATR = its `atr_h1`.
- Price at t: the close of the last closed M15 bar.
- Idea: `ideas.decide(trend, price, supports, resistances, hold, asset, atr, btc_trend)` for cash and holder;
  btc_trend = bitcoin's trend at the same t computed the same way. When the bitcoin filter changes an idea, the
  unfiltered idea (shadow) is scored too.
- Skipped: gold when the last H1 bar closed more than 2 h before t (market closed); any t with fewer than 600 M15,
  300 M30, 200 H1, 100 H4 bars (engine minimums); ideas of kind NONE.
- Data: the repository's own archives (`market_data/crypto/*` Binance spot, `market_data/bars/Dukascopy/XAUUSD`).

## How each idea is scored
Exactly `ideas.score` (24 h window of closed H1 bars after t, fees XAU 0.05 %, BTC/ETH 0.16 %, SOL 0.22 % per side,
alternatives and edge as written in `ledger/ideas.py`). Samples 4 h apart have overlapping 24 h windows; the
confidence interval below accounts for that.

## Split
- Development: t < 2026-06-01. Holdout: t ≥ 2026-06-01. Nothing is tuned on either: the rule is fixed. Both are
  reported; the holdout is the confirmation.

## Verdict per idea kind (all assets together, and per asset), in each period
n, success rate, mean edge (percentage points), and a 95 % interval of the mean edge from a moving-block bootstrap
(blocks of 7 days, 2 000 resamples, seed 0).
- USEFUL: mean edge > 0, success rate ≥ 50 %, and the interval's lower end > 0, in BOTH periods.
- HARMFUL: the interval's upper end < 0 in both periods.
- UNCLEAR: anything else, or n < 30 in a period.
WAIT ideas compare «stay in cash» with buying; they are reported but are not a trade.

## Bitcoin filter
For ETH and SOL cash ideas changed by the filter: mean edge shown vs shadow, share where the filter did better,
the same bootstrap interval of (shown − shadow). HELPS when the interval's lower end > 0 in both periods; HURTS when
the upper end < 0 in both; else UNCLEAR.

## Known limits (reported with the result)
- The live engines read live bars of their providers; the archives may differ slightly (gold: Dukascopy instead of
  the live feed). Levels are computed without the strength model. The calendar, crowding and the tested «most
  likely» side are not replayed (the conflict filter and the event hold are display rules, not scored).
- A past result is evidence, not a promise.
