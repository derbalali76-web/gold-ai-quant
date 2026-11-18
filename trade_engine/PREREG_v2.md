# AI QUANT Trade Engine — pre-registration te-0.2.0 (DRAFT, not frozen)

Status: **DRAFT 2026-11-18 — awaiting owner approval. No outcome (return, fill, exit) of any te-0.2.0 rule has been
computed.** Only data quality and signal COUNTS were inspected. On approval this file is marked FROZEN in a commit
whose hash is recorded before the first test runs; after that nothing here changes for te-0.2.0.

te-0.1.0 (PREREG.md, rules.py, reports/phase1_*, reports/phase2_*, commit 36cc692) stays as it is. The range,
HILO, outcome3 and advice engines and their ledger are not touched.

## 1. Data audit and point-in-time availability (checked 2026-11-18)
| feature | source | history | quality | known at decision t when |
|---|---|---|---|---|
| price, volume | Binance spot 1h/15m | 2018 (BTC), 2020-09 (SOL) | < 0.25 % missing | the 1h bar closed ≤ t |
| taker-buy volume | Binance spot 1h klines | same | no missing, share within 0.32–0.67 | the 1h bar closed ≤ t |
| funding rate | USD-M perpetual, 8h settlements | 2020 | **every December missing (collector bug)** | settlement time < t (strict), ≤ 9 h old |
| open interest | USD-M futures metrics, 5-min → hourly | 2022-01 | 9 missing hours (2024) | hour closed ≥ 1 h before t |
| top-trader / taker long-short ratios | same | 2022 mostly empty | 18 % / 7 % missing (all in 2022) | **not used** |
| order-book spread / depth | — | not stored historically | — | **not used** (liquidity = volume) |
- December funding: the shared collector skips a year file once it has ≥ 1 000 rows, so each December, published
  after the year ends, was never fetched. te-0.2.0 does NOT patch the shared store (other engines read it): a rule
  that needs funding gives no signal when the last settlement is older than 9 h. Fixing the collector is a separate
  decision for the owner.
- Live availability: the same values exist in real time (spot klines, fundingRate, openInterestHist), so a live
  paper test can use exactly these inputs.
- All thresholds are percentiles over trailing windows ending at t; regimes use only the past 90 days of price.

## 2. Hypotheses (long spot only; why each could make money, not only predict direction)
**H1 — crowded shorts (funding).** Funding in the bottom q of its trailing year after a 24 h fall. Leveraged shorts
pay to hold; when they are crowded, a small up-move forces covering (buying) that overshoots. The edge is a
temporary price dislocation created by forced flows, which a patient limit buyer captures. Ablation: same, with the
funding condition replaced by "24 h return in its bottom q" (price only).

**H2 — forced deleveraging (open interest).** Open interest drops into the bottom q of its trailing 90-day 8 h
changes while price falls ≥ 1 ATR in 8 h. Liquidations sell regardless of value; liquidity providers are paid a
premium for absorbing them, and price tends to recover part of the move. Ablation: the 8 h drop in its bottom q
without the open-interest condition.

**H3 — absorption (taker flow).** The 12 h taker-buy share is in the bottom q of its trailing 90 days (aggressive
selling dominates), yet price has not fallen over those 12 h. Someone is absorbing the selling with resting bids —
typically better-informed or larger players; when the selling pressure exhausts, price is free to rise. Ablation:
same price condition with high volume (top q) instead of low taker-buy share.

H4 (compression breakout + aggressive buying) was drafted and **dropped before any outcome**: signal counts alone
(≤ 54 bars per asset in 3.9 years) cannot reach 40 filled trades, and it overlaps te-0.1.0 family B.

Thresholds q were set from signal counts only (feasibility, ≥ ~80 episodes per asset at the looser q).

## 3. Configurations — 12 per asset, 24 hypotheses in total
H1: q ∈ {0.10, 0.05}; H2: q ∈ {0.10, 0.05}; H3: q ∈ {0.10, 0.05}; × two exits:
- E5d: limit close − 0.25 ATR (12 h timeout), stop limit − 2 ATR, target limit + 3 ATR, max hold 5 days;
- E24h: same entry, stop − 1.5 ATR, target + 1.5 ATR, max hold 24 h (dislocations should repair quickly).
Simulator, costs, fills, intrabar order and one-position-per-asset: exactly te-0.1.0 (sim.py at 36cc692).

Signal frequency on development data 2022-01-01 .. 2025-11-08 (counts only):
| | BTC bars / episodes | SOL bars / episodes |
|---|---|---|
| H1 q0.10 / q0.05 | 366 / 144 · 143 / 64 | 640 / 163 · 350 / 97 |
| H2 q0.10 / q0.05 | 190 / 139 · 123 / 89 | 169 / 126 · 102 / 79 |
| H3 q0.10 / q0.05 | 180 / 122 · 88 / 61 | 138 / 93 · 64 / 47 |

## 4. Evaluation (development data only; holdout bars removed before anything is built)
- Windows: 2022, 2023, 2024, 2025-01-01..2025-11-08. Regimes at t: up (90-day return > +15 %), down (< −15 %),
  range (otherwise). Every metric is reported per window and per regime, not only pooled.
- Three probabilities, separately: P(fill), P(target before stop | fill), P(net > 0 | fill); Wilson intervals;
  walk-forward logistic model (inputs: ATR/close, 24 h return, 90-day return, the hypothesis' own percentile
  feature), Brier skill vs the training base rate, reliability curves.
- Intervals: circular block bootstrap of 3 calendar months (as te-0.1.0 A1).
- Baselines, same simulator and costs: cash; buy-and-hold; every-bar limit; (a) matched random entry (timing pool =
  all eval bars, the rule's own geometry, matched count, 1 000 draws); (b) **regime-matched random** — random bars
  drawn with the same mix of regime × ATR-tercile as the rule's orders; (c) the hypothesis' **price-only ablation**,
  evaluated exactly like a rule.

## 5. Selection criteria (all required; frozen with this file)
1. ≥ 40 filled trades.
2. Mean net return > 0 and profit factor > 1.15.
3. Positive mean in ≥ 3 of 4 windows.
4. Beats matched random: p < 0.05 after Holm over 24.
5. Beats regime-matched random: p < 0.05 after Holm over 24.
6. Beats its price-only ablation: higher mean overall AND in ≥ 3 of 4 windows (the new data must add value).
7. Positive mean in every regime that has ≥ 20 filled trades.
8. Profit factor > 1.0 with costs × 2.
9. Brier skill > 0 for P(target first) or P(net > 0).
At most 2 configurations per asset go on. None qualifying → "no edge found", stated as such.

## 6. Holdout and live paper test
- Holdout 2025-11-15 .. 2026-11-14 is still sealed (te-0.1.0 never opened it). It is opened once, only for the
  configurations selected above, with the te-0.1.0 phase-3 acceptance rules (≥ 30 filled, PF > 1.2 with lower
  bound > 1, mean > 0 with interval excluding 0, beats random after Holm, Brier skill > 0), reported per regime.
  Its results are never used to change te-0.2.0 or to design a later version's rules.
- Live paper test, separate ledger, rules as in PREREG.md phase 4. Nothing is shown to users as a recommendation;
  any screen is shown as a mockup for approval first.

## 7. Disclosed limits
- My general market knowledge reaches mid-2026 and overlaps the first ~7 months of the holdout.
- Funding hypotheses cannot fire in Decembers (missing data); about 7 % of development bars.
- No historical spread or depth: liquidity enters only through volume; slippage stays a fixed assumption (×2 test).
