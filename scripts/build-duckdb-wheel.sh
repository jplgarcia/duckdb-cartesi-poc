#!/usr/bin/env bash
# Cross-compile the DuckDB Python wheel for linux/riscv64 and drop it into the
# local wheel index used by the Cartesi image build.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DUCKDB_VERSION="${DUCKDB_VERSION:-2.0.0}"
JOBS="${JOBS:-2}"
OUT="$ROOT/riscv-wheel-index/wheels/cp313/duckdb"

mkdir -p "$OUT"
docker buildx build \
  --build-arg DUCKDB_VERSION="$DUCKDB_VERSION" \
  --build-arg JOBS="$JOBS" \
  --target export \
  --output "type=local,dest=$OUT" \
  --progress plain \
  "$ROOT/wheel-builder"

ls -la "$OUT"
