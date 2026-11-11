#!/usr/bin/env zsh
# Live demo for screen recording (e.g. Screen Studio) in your own terminal.
#
# 1. Prepares a fresh devnet off camera (cartesi run in the background, one
#    seed trade of ETH at 3000 x 2), then waits for you to press Enter.
# 2. Clears the screen and, using your real zsh prompt, types and RUNS each
#    command for real: inspect, cartesi send, app logs, inspect again.
#
# usage:  .demo/live.sh                full run (fresh devnet)
#         .demo/live.sh --reuse        use the devnet that is already running
#         .demo/live.sh --stop         just stop the devnet
# env:    TYPE_DELAY=0.04 STEP_PAUSE=1.5 DEMO_PROMPT='$ ' NO_ENTER=1
set -eo pipefail
cd "${0:A:h}/.."

TYPE_DELAY=${TYPE_DELAY:-0.04}
STEP_PAUSE=${STEP_PAUSE:-1.5}
APP=duckdb-cartesi-poc
RUN_LOG=logs/live-cartesi-run.log
mkdir -p logs

if [[ "$1" == "--stop" ]]; then
  docker compose -p "$APP" down >/dev/null 2>&1 || true
  echo "devnet stopped"; exit 0
fi

# Your interactive prompt (unexpanded), so the recording shows your shell.
# (quoted: unquoted ${..:-$(..)} would drop the prompt's trailing space)
RAW_PROMPT="${DEMO_PROMPT:-$(zsh -i -c 'print -r -- "$PS1"' 2>/dev/null | tail -1)}"
show_prompt() { print -nP -- "$RAW_PROMPT" }

type_line() {
  local text=$1 i
  for (( i = 1; i <= ${#text}; i++ )); do
    print -n -- "${text[i]}"
    sleep "$TYPE_DELAY"
  done
  sleep 0.3
  print
}

say() { show_prompt; print -n -- $'\e[90m'; type_line "$1"; print -n -- $'\e[0m'; sleep 0.4 }
run() { show_prompt; type_line "$1"; eval "$1"; sleep "$STEP_PAUSE" }

wait_log() {  # off camera: block until the app logged a line containing $1
  local i
  for i in {1..90}; do
    ./scripts/applog.sh 50 | grep -qF -- "$1" && return 0
    sleep 1
  done
  echo "timed out waiting for: $1" >&2; exit 1
}

########################################################################## prep
if [[ "$1" != "--reuse" ]]; then
  echo "preparing a fresh devnet (off camera)..."
  docker compose -p "$APP" down >/dev/null 2>&1 || true
  [[ -d .cartesi/image ]] || cartesi build
  cartesi run > "$RUN_LOG" 2>&1 &
  for i in {1..120}; do grep -q 'contract deployed' "$RUN_LOG" 2>/dev/null && break; sleep 2; done
  grep -q 'contract deployed' "$RUN_LOG" || { cat "$RUN_LOG"; exit 1; }
  cartesi send --encoding string '{"op":"trade","asset":"ETH","price":"3000","qty":"2"}' >/dev/null
  wait_log "input 0 from"
fi
rows=$(./scripts/inspect.sh info | python3 -c 'import json,sys; print(json.load(sys.stdin)["rows"])')
# the new trade will be the next input; find its index from the node
next_input=$(curl -s -X POST http://127.0.0.1:6751/rpc -H 'Content-Type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"cartesi_listInputs\",\"params\":{\"application\":\"$APP\",\"limit\":1}}" |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["pagination"]["total_count"])')

if [[ -z "$NO_ENTER" ]]; then
  print -n "ready ($rows row(s) in the db). Start recording, then press Enter. "
  read -r _
fi
clear 2>/dev/null || print -n $'\e[H\e[2J'
sleep 1

########################################################################## show
say "# DuckDB 2.0 (cross-compiled for riscv64) running inside a Cartesi Machine"
run "./scripts/inspect.sh info"
say "# 1) current database state"
run "./scripts/inspect.sh stats"
say "# 2) send a new trade with the Cartesi CLI (goes to the on-chain InputBox)"
run "cartesi send --encoding string '{\"op\":\"trade\",\"asset\":\"ETH\",\"price\":\"3150\",\"qty\":\"1\"}'"
wait_log "input $next_input from"
say "# 3) app logs: the input was written to DuckDB"
run "./scripts/applog.sh 2"
say "# 4) inspect queries the database again: VWAP and trade count changed"
run "./scripts/inspect.sh stats"
say "# 5) and the app log shows the SELECT that answered that inspect"
run "./scripts/applog.sh 1"
sleep 2

exit 0
