# AI QUANT Trade Engine — pre-registration te-0.2.0

Status: **FROZEN 2026-11-18** (owner approval of the plan with eight amendments, 2026-11-18 13:24 Algiers).
Frozen before any outcome (fill, exit, return) of any te-0.2.0 rule was computed; only data quality and signal
counts were inspected. Code: rules_v2.py, phase2_v2.py, sim.py, metrics.py, data.py, collect.py at the freeze commit.
After freezing, only crash fixes that cannot change a computed number are allowed; each would be listed in an
erratum with its commit. No criterion, threshold, window or test changes for te-0.2.0.

te-0.1.0 (PREREG.md, rules.py, phase2.py, reports/phase1_*, reports/phase2_*) and the range / HILO / outcome3 /
advice engines, their collectors and ledgers are untouched.

## 1. Data (audit: reports/audit_v2.json)
| input | store | dev coverage | checks |
|---|---|---|---|
| spot 1h/15m OHLCV + taker-buy volume | shared market_data (read only) | 2021–2025 | < 0.25 % missing, no bad OHLC, taker share 0.32–0.67 |
| funding | **trade_engine/data** (own collector, collect.py) | 2020-01 → 2026-10, every month incl. Decembers | 0 duplicates, all intervals 8 h (SOL: some 2 h/4 h in 2020–22), equal to the shared store on all 6 930 / 6 328 common settlements (max diff 0) |
| open interest | shared metrics (read only) | 2022-01 → | 9 missing hours (2024-02-16); zeros = missing snapshots → treated as missing; 12 hours present twice (2026-11 only) → treated as missing |
The December fix lives only in trade_engine/data; the shared store and its collector are unchanged.

## 2. Decision time and point-in-time rules
- Decision times t: UTC 00, 04, 08, 12, 16, 20 (the close of a 4h bar). A 4h bar exists only if all four 1h bars exist.
- Spot values of a 1h bar are used when the bar closed at or before t.
- Funding: rate f_k with settlement time τ_k is used only if τ_k < t (strict); F(t) = f_k for the latest such k,
  and is missing if t − τ_k > 9 h. (The exchange fixes and publishes the rate at τ_k; archives copy it later.)
- Open interest: hourly value OI_h = last 5-min snapshot of hour h (published by the exchange API within minutes);
  used only if h + 2 h ≤ t. OI(t) = latest usable OI_h, missing if older than 3 h.
- Percentile P_W(x, t) = share of the values of x in the trailing window (t − W, t] that are ≤ x(t); computed only
  with ≥ 30 values; nothing is normalised on the full sample.

## 3. Definitions
With C_t the 4h close at t, ATR_t = Wilder 14-bar ATR of 4h bars, a_t = ATR_t / C_t:
- r8 = C_t / C_{t−8h} − 1, r12, r24 likewise, r90d = C_t / C_{t−90 days} − 1.
- TBS12_t = Σ taker-buy volume / Σ volume over the last 3 4h bars; ΔOI8_t = OI(t) / OI(t − 8h) − 1.
- Regime at t: up if r90d > +15 %, down if r90d < −15 %, range otherwise.
- Volatility tercile at t: P_180d(a, t) < 1/3 low, < 2/3 mid, else high.

**H1 crowded shorts:** r24 < 0 and P_365d(F, t) ≤ q. Ablation: r24 < 0 and P_365d(r24, t) ≤ q.
**H2 forced deleveraging:** r8 ≤ −a_t and P_90d(ΔOI8, t) ≤ q. Ablation: r8 ≤ −a_t and P_90d(r8, t) ≤ q.
**H3 absorption:** r12 ≥ 0 and P_90d(TBS12, t) ≤ q. Ablation: r12 ≥ 0 and P_90d(volume, t) ≥ 1 − q.
q ∈ {0.10, 0.05} for each hypothesis (set from signal counts only).

## 4. Orders (simulator sim.py unchanged from te-0.1.0)
- Entry: buy limit L = C_t − 0.25·ATR_t, live from t for 3 4h bars; filled only if price trades strictly below L
  (or opens below → filled at the open); otherwise cancelled at no cost.
- Exit E5d: stop S = L − 2·ATR_t (stop-market, slippage), target T = L + 3·ATR_t (limit, strictly through),
  time exit at the close of the 30th 4h bar after the fill. Exit E24h: S = L − 1.5·ATR_t, T = L + 1.5·ATR_t, 6 bars.
- Intrabar order on 15m bars; stop wins when both are reachable in one bar; no target in the fill bar.
- Costs: 0.10 % maker and taker; half-spread 0.01 % BTC / 0.02 % SOL and slippage 0.05 % / 0.10 % on market,
  stop and time exits. One position per asset at a time.
- 12 configurations per asset (3 hypotheses × 2 q × 2 exits), 24 in total.

## 5. Evaluation (development only)
- Bars at or after 2025-11-15 are deleted before features or the market are built. Evaluation decisions:
  2022-01-01 ≤ t < 2025-11-08 in four windows (2022, 2023, 2024, 2025-01-01..2025-11-08). Orders from 2021 serve
  only to train the probability model for the first window.
- Reported for every configuration: orders, fills, three probabilities, mean net, profit factor, drawdown, per
  window, per regime (up / down / range) and per cost level (× 0.75, × 1, × 2), and the same for its ablation.

### Statistical tests (one-sided)
- Intervals: circular block bootstrap of 3 calendar months, 2 000 draws, percentile 95 % (mean net, PF).
- (a) Random entry: pool = every evaluation bar with the configuration's own order formula; one draw = as many pool
  orders as the rule placed, without replacement; statistic = mean net per filled trade; 1 000 draws;
  p = (1 + #draws ≥ rule) / (1 + draws).
- (b) Regime-matched random: for each rule order one pool bar from the same stratum (regime × volatility tercile).
- (c) Price-only ablation: difference of means (rule − ablation), joint circular 3-month block bootstrap over the
  same calendar months, 2 000 draws, p = (1 + #diff ≤ 0) / (1 + draws).
- Multiple testing: Holm within each family of 24 p-values (a, b, c separately); a configuration must pass all three.

### Probabilities (three separate models, never a single score)
P(fill) on all orders; P(target before stop | fill) and P(net > 0 | fill) on filled orders. Logistic regression
(L2, C = 1, standardised inputs: a_t, r24, r90d, the hypothesis' own percentile feature), refitted per window on
orders that ended ≥ 7 days before the window (fewer than 30, or one class → training base rate). Reported:
Brier, Brier skill vs base rate, calibration-in-the-large, 10-bin reliability with Wilson intervals.
A probability counts as usable only with Brier skill > 0 AND |mean forecast − observed| ≤ 0.05 AND every
reliability bin with ≥ 20 cases within 10 points. Skill alone is not evidence.

## 6. Selection — all ten required
1. ≥ 40 filled trades (a minimum for evaluation, not evidence of sufficiency).
2. Mean net > 0 and profit factor > 1.15.
3. Lower bound of the 95 % interval of mean net > 0.
4. Positive mean in ≥ 3 of 4 windows.
5. Random entry: Holm p < 0.05.
6. Regime-matched random: Holm p < 0.05.
7. Price-only ablation: Holm p < 0.05 and higher mean than the ablation in ≥ 3 of 4 windows.
8. Positive mean in every regime with ≥ 20 filled trades.
9. Profit factor > 1.0 with costs × 2.
10. P(target first) or P(net > 0) usable (section 5).
At most 2 configurations per asset, ranked by criterion 3's lower bound. None → "no edge found".

## 7. Holdout policy (2025-11-15 .. 2026-11-14)
- Sealed: no te-0.2.0 code loads it before selection; te-0.1.0 never opened it.
- Opened at most ONCE for this version, only if ≥ 1 configuration is selected, and only after a commit that records
  the selected configurations and the sha256 of every engine file ("final version"). The unsealing run writes its
  report and a marker file in the same commit; the code refuses to run the holdout again once the marker exists.
- Acceptance (each selected configuration): ≥ 30 filled; PF > 1.2 with 95 % lower bound > 1; mean net > 0 with
  interval excluding 0; random-entry and regime-matched p < 0.05 after Holm over the configurations tested;
  usable probability as in section 5; results per regime published.
- Holdout results are never used to modify te-0.2.0 or to design any later version. A later version would need new
  untouched data (data after 2026-11-14 or the live paper test).

## 8. Live paper test
As PREREG.md phase 4 (separate hash-chained ledger, orders recorded before they can fill, ≥ 60 fills and ≥ 12
weeks, PF > 1.2 with lower bound > 1, calibration within 10 points). Nothing is shown to users as a
recommendation; any screen is shown as a mockup for approval first.

## 9. Disclosed limits
My general market knowledge reaches mid-2026 (first ~7 months of the holdout). No historical spread or depth:
slippage is a fixed assumption, stressed × 2. Open interest starts 2022-01: H2 has fewer early observations.
