# AI QUANT Trade Engine (experimental, research only)

Spot long-only trade research on BTCUSDT and SOLUSDT, 4h decisions. Separate from the range / HILO / advice
engines and from their ledger. Pre-registration: `PREREG.md` (te-0.1.0). Holdout 2025-11-15..2026-11-14 is sealed.

- `data.py` — loads stored Binance 1h/15m bars, builds 4h, audits gaps, fingerprints files.
- `sim.py` — order simulator (limit/market entry, timeout, TP limit, stop-market, time exit, costs, 15m intrabar).
- `rules.py` — features and the 24 pre-registered configurations; refuses the holdout.
- `metrics.py` — rates with Wilson intervals, mean/PF with block-bootstrap intervals, drawdown.
- `baselines.py` — phase 1 reference strategies on development data → `reports/phase1_baselines.json`.

Reproduce: `python -m trade_engine.data` (audit), `python -m trade_engine.baselines` (baselines).
Tests: `backend/tests/test_v30_trade_sim.py`.
