# AI QUANT — public trust ledger

This repository is the **public, append-only record** of every recommendation the AI QUANT app publishes for
gold (XAU/USD) and crypto (BTC, ETH, SOL — each with its own record in `stats.json` → `assets`), written **before** its outcome is known, and of every result — **losses included**.

## How it works
- Every hour, `.github/workflows/record.yml` fetches the app server's public snapshot and runs `ledger.py`.
- A new validated recommendation becomes a `REC` line with its entry, stop, target, expiry, cost and model version.
- The day's analysis (bias UP / DOWN / SIDEWAYS) becomes one `BRIEF` line per day, recorded before that day closes.
- When the price later reaches the stop, the target or the time limit, a `RESULT` / `BRIEF_RESULT` line is appended.
- Lines are never edited or deleted. Each line contains the SHA-256 of the previous line, so changing any old line
  breaks every hash after it. Each line also sits in a git commit whose time GitHub records independently.

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
