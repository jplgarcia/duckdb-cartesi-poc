#!/usr/bin/env bash
# Unit tests inside linux/riscv64 (QEMU on non-RISC-V hosts), against the
# cross-compiled DuckDB wheel. Nothing is installed on the host.
# Extra args go to pytest, e.g. scripts/test.sh -k inspect
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
docker buildx build -q --platform linux/riscv64 --load -t duckdb-cartesi-poc-tests \
  -f "$ROOT/tests/Dockerfile" "$ROOT" >/dev/null 2>&1 \
  || docker buildx build --platform linux/riscv64 --load -t duckdb-cartesi-poc-tests -f "$ROOT/tests/Dockerfile" "$ROOT"
docker run --rm --platform linux/riscv64 duckdb-cartesi-poc-tests \
  python3 -m pytest -p no:cacheprovider tests/ "${@:--v}"
