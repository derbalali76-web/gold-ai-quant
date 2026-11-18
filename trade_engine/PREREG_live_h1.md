# Live paper record te-live-h1-0.1 — pre-registration (frozen 2026-11-18, before the first live decision)

Owner request 2026-11-18: show trades with entry and exit in the app, labelled experimental, with their real record.

- **Rule (unchanged from te-0.2.0, PREREG_v2.md):** H1_q0.1_E5d on BTCUSDT — 24 h return < 0 and the last funding
  settlement in the bottom 10 % of its trailing year; buy limit close − 0.25 ATR(4h) valid 12 h; stop − 2 ATR,
  target + 3 ATR from the limit; time exit after 30 4h bars; one position at a time; te-0.1.0 costs.
- **Status of the evidence:** this configuration FAILED te-0.2.0 selection (development mean +0.36 %/trade, PF 1.22,
  interval includes 0, Holm p = 1). It was chosen among the four H1-on-BTC configurations because it trades about
  twice as often as q0.05 (≈ 25 fills a year), not because it scored best. The live record is an openly declared
  exploration; it does not count as a pass of te-0.2.0 and the holdout stays sealed.
- **Recording:** ledger/te_live.py (copy in the public ledger, trade_engine/), run inside the hourly ledger workflow
  but with its own hash-chained file trade_engine/trades.jsonl. Every 4h decision inside its 75-minute window is
  written as a SCAN line (signal or not); an ORDER line is written before the order can fill and is live only from
  its record time. FILL and RESULT lines follow the research simulator's rules (equivalence: backend/tests/
  test_v31_te_live.py). A missing data stretch closes an order as NO_DATA, never as a guessed result.
- **Verdict (fixed now):** experimental until ≥ 60 filled trades AND ≥ 12 weeks. Then PASS only if profit factor
  > 1.2 with a 95 % block-bootstrap lower bound > 1.0 and mean net > 0 with interval excluding 0; otherwise FAIL and
  the card is withdrawn. Early stop: 20 consecutive filled losses or a drawdown > 30 % (compounded, full position).
- **App:** the card shows the levels, the reason, "not proven", the times, and the record (wins, losses, not filled,
  mean net after costs). No probability of success is shown. Not a recommendation, not automated, no user money.
- The range / HILO / outcome3 / advice engines and their ledger lines are unaffected.
