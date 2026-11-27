# entry-0.1 — better entries for the owner's spot method (owner request 2026-11-27)

Pre-registered before running. Same «اشترِ الآن» moments (cash BUY_NOW of idea-replay-0.1), same owner method
(spot, no stop, sell the whole position at +0.65 % digital / +15 USD gold over its average cost), same costs
(digital 0.15 % of the amount per round trip; gold 2 USD per ounce per round trip, so splitting does not change it),
same periods and valuation of open positions as spot-hold-0.1.

Variants (each signal = one unit of money):
- S0  buy everything at p (current).
- L04 limit buy at p × 0.996 (both kinds of assets), valid 24 h; filled when an H1 low reaches it; not filled = no
      trade (net 0). Target from the fill price.
- D2  half at p, half by a limit at p × 0.99 valid 24 h; the target is +0.65 % / +15 USD over the average cost of
      what was bought (the second half joins only if filled before the target is reached).
- TB  digital assets only: buy at p only if buyers dominated the last 4 closed H1 bars (taker-buy volume / volume
      ≥ 0.5); otherwise no trade. Gold is unchanged (no volume data).

Reported per variant, period and asset: signals, entries, mean net per signal (no trade = 0), mean net per entry,
stuck share (open > 30 days), total.
Verdict: a variant is BETTER than S0 when its mean net per signal is higher in BOTH periods (all assets together)
and its stuck share is not higher in either. Only a BETTER variant may reach the app.
