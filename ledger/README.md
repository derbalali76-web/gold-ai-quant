# AI QUANT — public trust ledger

This repository is the **public, append-only record** of every recommendation the AI QUANT app publishes for
gold (XAU/USD) and crypto (BTC, ETH, SOL — each with its own record in `stats.json` → `assets`), written **before** its outcome is known, and of every result — **losses included**.

## How it works
- Every hour, `.github/workflows/record.yml` runs `issue.py` (independent computation, see below), fetches the app server's public snapshot and runs `ledger.py`.
- A new validated recommendation becomes a `REC` line with its entry, stop, target, expiry, cost and model version.
- The day's analysis (bias UP / DOWN / SIDEWAYS) becomes one `BRIEF` line per day, recorded before that day closes.
- When the price later reaches the stop, the target or the time limit, a `RESULT` / `BRIEF_RESULT` line is appended.
- Lines are never edited or deleted. Each line contains the SHA-256 of the previous line, so changing any old line
  breaks every hash after it. Each line also sits in a git commit whose time GitHub records independently.
- **What the chain does not do by itself:** whoever controls this repository could rewrite the whole file and every
  hash after it. So once a day the current head hash is written to `anchors/YYYY-MM-DD.txt` and timestamped with
  [OpenTimestamps](https://opentimestamps.org) (anchored in the Bitcoin blockchain, outside GitHub). A rewritten
  history would no longer match an anchor that already exists. Check an anchor: `pip install opentimestamps-client`
  then `ots verify anchors/YYYY-MM-DD.txt.ots` (proofs become verifiable a few hours after stamping).
- Since 2026-11-15 (rule 2) a snapshot is recorded only if it is at most 20 minutes old (was 2 hours): the recorded
  price must be one that could still be traded at recording time. Older lines keep the rule they were written under.

## Check it yourself
```
git clone https://github.com/derbalali76-web/ai-quant-ledger && cd ai-quant-ledger
python3 ledger.py verify
```
`verify` re-checks the whole chain and recomputes `stats.json` from the lines alone (standard Python, no packages).
You can also compare any recorded price with any independent XAU/USD chart.

## Scoring rules (conservative by design)
- Market entry = the price at the recording time. A limit entry counts only if a later bar trades into its zone
  before expiry; otherwise it is `NOT_FILLED` and excluded from wins and losses.
- Only bars that open **after** the recording time are used.
- If one bar touches both the stop and the target, it counts as a **stop**.
- Results are in R (multiples of the initial risk) after the published cost per ounce.
- **Baseline**: the same distances taken as a BUY every time — does choosing the direction beat gold's upward drift?
- Analysis accuracy is scored at the day's close against "always UP" on the same days.
- Results are grouped by model version, so a new model never inherits an old model's record.

An empty record is an honest record: the app publishes a recommendation only after a model passes out-of-sample
validation. Nothing here is investment advice.

## Strategy scenarios (experimental layer)
With every daily analysis (`BRIEF`), three `SCENARIO` lines are written **in the same run**, linked to it by
`fid` (forecast id) and with their own `sid`:

| sid suffix | position | fixed rule | compared with |
|---|---|---|---|
| `CASH_BUY_DIP` | cash | limit buy at S1, target R1, stop S2, else exit at expiry | buying now · staying in cash |
| `CASH_WAIT_LOWER` | cash | wait to buy at S2 | buying now |
| `HOLD_SELL_REBUY` | holder | sell on an H1 close below S1, buy back at S2, else forced buy-back at expiry | holding |

- Life: 24 hours (gold: 24 trading hours). H1 bars that open after registration; same-bar stop first.
- The asset's published round-trip cost (spread + slippage + fees) is charged per in/out pair.
- A falling price is **not** a success for sell-and-rebuy: only a buy-back cheaper than the sale after costs is.
- Every scenario ends `TRIGGERED` (with its result) or `NOT_TRIGGERED`; both are kept.
- `stats.json → scenarios` is marked `experimental` and is never mixed with validated recommendations.
- The user's own position choice stays on their phone; the ledger computes both sides for everyone.

## Price ranges and high / low bounds (experimental, live validation)
- `RANGE`: an 80 % interval for the **close** 4 h / 1 day / 1 week ahead (backend `goldquant/price_range.py`, pre-registered).
  Issued on a fixed cadence (4 h: 00/04/08/12/16/20 UTC; 1 day: 00 UTC; 1 week: Monday 00 UTC) and recorded only within
  75 minutes of its issue time, before any outcome. `RANGE_RESULT` = INSIDE / ABOVE / BELOW from the target bar's close.
- `HILO`: how far above and below the price is likely to trade within 4 h / 24 h — BTC and ETH only, the four cases
  that passed the backtest (backend `goldquant/hilo.py`, `LIVE_PREREG`). Each line carries the model bounds **and both
  baselines** computed at the same moment. `HILO_RESULT` = the actual highest high and lowest low of the next H hourly
  bars, each side exceeded or not, path inside or not, and the pinball / path scores of the model and the baselines.
- Nothing here is a recommendation, a target or a stop. The verdict rules are fixed in advance (30 days and 150 settled
  forecasts per case; day-block bootstrap; Holm across the four cases) and are not changed after seeing results.

## Who computes an issue (since 2026-11-16 20:00 UTC)
- The free app server sleeps, restarts and is redeployed, and a missed issue time can never be recorded later. So the
  crypto ranges and the high / low bounds are computed **inside this workflow** by `issue.py` (standard library only):
  the last 1000 closed hourly bars from Binance's public market-data mirror and the published weekly parameters
  (`models/range_models.json`, `models/hilo_models.json` in the app repository). Same formulas as the server; the app
  repository tests that both give identical numbers.
- Gold ranges (since 2026-11-17): computed here too when the repository secret `TWELVEDATA_API_KEY` is set — the same
  Twelve Data hourly feed as the server, one request at a gold issue time that is due and not yet recorded (the key's
  daily quota is shared with the server). The key travels in a request header and never appears in a log or an alert.
- The server's snapshot is still read: the daily analysis, gold when the secret is missing, and a second computation
  of the same issues. **The first recorded value stands** and is never overwritten; each line says
  who computed it (`source`: `ledger-action` or `server`) and from which parameters (`params_sha`, `trained_until`).
- `crosscheck.json` lists every case where both computed the same issue: they must agree within 0.2 %. A disagreement
  opens the alert issue.
- `stats.json → completeness`: expected vs recorded issue times per case since 2026-11-16 20:00 UTC (gold only when the
  market was open). Every verdict reports it; any missed issue time in the last 24 h opens the alert issue.
- If a push is rejected because another run pushed first, the run starts again from the fresh head with the same inputs
  (`record.sh`). Triggers: an external scheduler at :00 every hour, GitHub's own schedule at :17 and :41 as a backup.

## advice-0.1.0 — «ماذا أفعل؟» (pre-registered 2026-11-17, before any outcome)

From this version on, the ledger records once per asset per UTC day the app's beginner instruction for a holder and
for cash (kind `ADVICE`), built from the HOURS and WEEK views exactly as the app builds them, and scores it after
168 hours on closed H1 bars (kind `ADVICE_RESULT`). The rules, costs, fill conventions and pass/fail criteria are
written in `advice.py` (module docstring) and do not change after results are seen; a change is a new version.
