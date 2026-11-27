# spot-hold-0.1 — the owner's spot method, and two ways to avoid stuck buys

Pre-registered 2026-11-27 (owner request), before these variants were run. Builds on idea-replay-0.1 (same replayed
«اشترِ الآن» moments: `samples.jsonl.gz`, kind BUY_NOW, mode cash). Nothing below changes after results exist.

## The owner's method (S0)
Spot, no stop. At every replayed BUY_NOW moment t (every 4 h, HOURS rule beginner-ideas-0.3) buy one equal unit at
the price p; sell it at the first later H1 high ≥ target; if never reached, it stays open.
- Target: crypto p × 1.0065; gold p + 15 USD. Costs (owner's, 2026-11-27): crypto 0.15 % of p per round trip, gold
  2 USD per round trip (per ounce assumed). Net of a closed buy = target − p − cost, in % of p.
- Open buys are valued at the last H1 close of their period, minus the cost, and counted as stuck when open > 30 days.

## Variants
- F1 trend filter: buy only if p ≥ the 50-day EMA of daily closes known at t (last daily bar closed before t).
- C3 position cap: per asset, skip a buy while 3 bought units are still open.
- F1+C3: both.

## Periods
Development: buys at t < 2026-06-01, valued at the last H1 close before 2026-06-01. Holdout: buys at t ≥ 2026-06-01,
valued at the last available close (2026-11-20). A buy belongs to the period of its t.

## Reported per asset and all assets together, per period and variant
buys, closed share, median hours to close, mean net per buy (closed + open valued), stuck share (open > 30 days),
worst open buy, total net (sum of % per unit).

## Verdict
- A variant is BETTER than S0 when, in BOTH periods and over all assets together, its mean net per buy is higher AND
  its stuck share is not higher.
- A variant is PROFITABLE when its mean net per buy over all assets is > 0 in BOTH periods.
- The app may only adopt a variant that is BETTER; it says PROFITABLE only if it is.

## Limits
Same as idea-replay-0.1 (archives, levels without the strength model). One unit per buy ignores the owner's real
sizes; capital locked in open buys is reported, not optimised. Past results are evidence, not a promise.
