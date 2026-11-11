#!/usr/bin/env bash
# Inspect the app and print the decoded report(s).  usage: scripts/inspect.sh stats
set -euo pipefail
BASE_URL="${BASE_URL:-http://127.0.0.1:6751}"
APP="${APP:-duckdb-cartesi-poc}"
curl -s -X POST "$BASE_URL/inspect/$APP" --data-binary "${1:-info}" | python3 -c '
import json, sys
res = json.load(sys.stdin)
for r in res.get("reports", []):
    print(json.dumps(json.loads(bytes.fromhex(r["payload"][2:])), indent=2))
'
