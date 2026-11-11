#!/usr/bin/env bash
# Turn a screen recording (e.g. a Screen Studio MP4 export) into
# demo/demo.mp4 and demo/demo.gif for the README. ffmpeg runs in Docker.
# usage: .demo/from-video.sh ~/Downloads/recording.mp4 [gif_width=960] [gif_fps=12]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="$HERE/../demo"
SRC="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
W="${2:-960}"; FPS="${3:-12}"
mkdir -p "$OUT"
docker build -q -t duckdb-cartesi-poc-render "$HERE" >/dev/null
docker run --rm -v "$OUT:/work" -v "$SRC:/in/src:ro" duckdb-cartesi-poc-render sh -c "
  ffmpeg -loglevel error -y -i /in/src -c:v libx264 -crf 23 -preset slow -pix_fmt yuv420p \
         -vf 'scale=trunc(iw/2)*2:trunc(ih/2)*2' -movflags faststart -an demo.mp4 &&
  ffmpeg -loglevel error -y -i demo.mp4 \
         -vf 'fps=$FPS,scale=$W:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer' \
         demo.gif"
ls -la "$OUT/demo.mp4" "$OUT/demo.gif"
