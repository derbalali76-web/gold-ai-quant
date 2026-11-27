# rsi-0.1 — does a very high 4-hour RSI(6) spoil a «buy now»? (owner question 2026-11-27)

Pre-registered before running. Same BUY_NOW cash buys and owner's spot method as spot-hold-0.1 (S0).
Split each buy by RSI(6) of H4 closes known at t (Wilder smoothing, last closed H4 bar): HOT = RSI ≥ 80, else NORMAL.
Report per group and period: buys, share reaching the target within 24 h, median dip (%) before the target,
share dipping ≥ 1 % before the target, mean net per buy (S0 valuation).
Verdict: «HOT is worse» only if HOT's mean net per buy is lower than NORMAL's AND its 24 h target share is lower,
in BOTH periods; «HOT is better» symmetrically; else «no clear difference».
