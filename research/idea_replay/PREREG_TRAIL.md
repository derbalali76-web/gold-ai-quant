# trail-0.1 — sell at +0.65 % or let a strong rise run (owner's idea, 2026-11-27)

Pre-registered before running. Same buys as spot-hold-0.1 (S0: every replayed cash BUY_NOW, spot, no stop, costs
crypto 0.15 % / gold 2 USD per round trip, same periods and valuation of open buys).

- E0 (current): sell at the first H1 high ≥ target (crypto +0.65 %, gold +15 USD).
- E1 (owner): when the target is first touched, look at the trend (engine `market_trend` on M15/M30/H1/H4 bars closed
  by the start of that H1 bar). Not UP → sell at the target (= E0). UP → keep, with a floor at the target: sell at the
  floor when a later low reaches it; at each later H1 close the floor rises to max(floor, highest close − 1 × ATR(H1));
  sell at that close when the trend there is no longer UP. Open at the period end → valued like S0 (cannot be below
  the floor only if sold; open ones are valued at the last close).

Verdict: E1 is BETTER when its mean net per buy is higher than E0's in BOTH periods (all assets together). Also
reported: mean net of closed buys, median extra hours held, share of buys where E1 sold above the target.
