#!/usr/bin/env bash
# One hourly recording pass: ledger update -> verify -> monitor -> daily anchor -> commit -> push.
# If another run (or a manual change) pushed first, start again from the fresh head with the SAME inputs instead of
# losing the hour: an issue can only be recorded within 75 minutes, so a rejected push must never drop it.
# usage: record.sh INPUT_DIR REPO_DIR   (issue_*.json from issue.py, snap_*.json from the server, issuer.txt)
# Run a COPY of this script (the workflow copies it out of the repository): a reset to the fresh head may change it.
set -u
IN="$1"
cd "${2:-$(dirname "$0")}"
git config user.name ai-quant-ledger
git config user.email ledger@users.noreply.github.com
ots_ready=0
for attempt in 1 2 3 4; do
  if [ "$attempt" -gt 1 ]; then
    echo "push rejected: retrying from the fresh head (attempt $attempt)"
    sleep $((attempt * 5))
    git fetch -q origin main && git reset -q --hard origin/main || continue
  fi
  python3 ledger.py update "$IN"/issue_*.json "$IN"/snap_XAU.json "$IN"/snap_BTC.json "$IN"/snap_ETH.json \
    "$IN"/snap_SOL.json || exit 1
  python3 ledger.py verify || exit 1
  # trade engine live paper record (own files trade_engine/*; a failure here never blocks the range ledger)
  [ -f "$IN/te_input.json" ] && { python3 te_live.py update "$IN/te_input.json" . || echo "trade engine: update failed"; }
  # are the files running here the canonical ones (gold-ai-quant ledger/MANIFEST.json)? reported, never blocking
  [ -f verify_copy.py ] && { python3 verify_copy.py || true; }
  # Render server life (restarts, outages, memory) kept here, because the server's own disk is wiped on restart
  [ -f "$IN/health.json" ] && { python3 server_watch.py apply "$IN/health.json" . || true; }
  # one decision state per asset for the app (decision-state-1), after the day's ADVICE and the trade engine
  [ -f decision_state.py ] && { python3 decision_state.py apply "$IN" . || true; }
  # study advice-units-0.1 (pre-registered): pre-emptive sell vs hold vs sell-after-break, in units after fees
  [ -f advice_units.py ] && { python3 advice_units.py . || true; }
  # beginner-ideas-0.1 (pre-registered): every «ماذا أفعل؟» idea and what happened after it
  [ -f ideas.py ] && { python3 ideas.py "$IN" . || true; }
  python3 monitor.py --issuer "$IN/issuer.txt" "$IN"/snap_XAU.json "$IN"/snap_BTC.json "$IN"/snap_ETH.json \
    "$IN"/snap_SOL.json | tee monitor.txt
  # daily external anchor (OpenTimestamps -> Bitcoin; best effort, never blocks the record)
  d=$(date -u +%F); mkdir -p anchors
  if [ ! -f "anchors/$d.txt" ]; then
    printf '%s  ledger.jsonl head at %s (lines: %s)\n' \
      "$(tail -n1 ledger.jsonl | python3 -c 'import json,sys;print(json.loads(sys.stdin.read())["hash"])')" \
      "$(date -u +%FT%TZ)" "$(wc -l < ledger.jsonl)" > "anchors/$d.txt"
  fi
  if [ "$ots_ready" = 0 ]; then pip install -q opentimestamps-client >/dev/null 2>&1 && ots_ready=1; fi
  if [ "$ots_ready" = 1 ]; then
    [ -f "anchors/$d.txt.ots" ] || timeout 120 ots stamp "anchors/$d.txt" || rm -f "anchors/$d.txt.ots"
    for f in anchors/*.ots; do [ -f "$f" ] && timeout 60 ots upgrade "$f" >/dev/null 2>&1 || true; done
  fi
  if [ "${DRY_RUN:-false}" = "true" ]; then echo "dry run: nothing committed"; git status --short; exit 0; fi
  git add -A
  git diff --cached --quiet && { echo "nothing new"; exit 0; }
  git commit -q -m "ledger: $(date -u +%Y-%m-%dT%H:%MZ) head $(tail -c 80 ledger.jsonl | grep -o '"hash":"[0-9a-f]\{12\}' | cut -d'"' -f4)"
  if git push -q origin HEAD:main; then echo "recorded on attempt $attempt"; exit 0; fi
done
echo "could not push after 4 attempts"
exit 1
