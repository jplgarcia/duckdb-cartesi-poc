#!/usr/bin/env bash
# Render demo/demo.cast into demo/demo.gif and demo/demo.mp4 (inside Docker).
set -euo pipefail
DEMO="$(cd "$(dirname "$0")" && pwd)"
docker build -q -t duckdb-cartesi-poc-render "$DEMO" >/dev/null
docker run --rm -v "$DEMO:/work" duckdb-cartesi-poc-render sh -c '
  agg --font-family "DejaVu Sans Mono,Noto Color Emoji" --font-size 18 --line-height 1.3 \
      --theme monokai --idle-time-limit 2 --last-frame-duration 4 demo.cast demo.gif &&
  ffmpeg -loglevel error -y -i demo.gif -movflags faststart -pix_fmt yuv420p \
      -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" -r 30 demo.mp4'
ls -la "$DEMO"/demo.*
