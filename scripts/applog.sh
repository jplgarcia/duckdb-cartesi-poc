#!/usr/bin/env bash
# Show the app's database log lines from the local node.  usage: scripts/applog.sh [n]
set -euo pipefail
cartesi logs 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g' | grep -F '[dapp] [db]' | tail -n "${1:-5}"
