# Recording the demo

Tooling used to produce `demo/demo.mp4` and `demo/demo.gif`. Run everything from
the repository root.

## In your own terminal (screen recorder)

```bash
./.demo/live.sh
```

It starts a fresh devnet off camera, seeds one ETH trade (`price 3000`,
`qty 2`), and waits for Enter. Start the screen recorder, press Enter, and the
script types each command at your real zsh prompt and runs it against the
devnet. Tune it with `TYPE_DELAY`, `STEP_PAUSE` or `DEMO_PROMPT='$ '`, reuse a
running devnet with `--reuse`, and stop the devnet with `./.demo/live.sh --stop`.

Then turn the exported recording into the README assets:

```bash
./.demo/from-video.sh ~/Downloads/recording.mp4
```

This writes `demo/demo.mp4` (no audio) and `demo/demo.gif` (960 px, 12 fps;
override with `./.demo/from-video.sh <file> <width> <fps>`).

## Headless (asciicast)

On a fresh devnet seeded with the same ETH trade:

```bash
python3 .demo/record.py
```

```bash
./.demo/render.sh
```

`record.py` runs the commands for real in a pseudo-terminal and writes
`.demo/demo.cast` (only the typing is simulated). `render.sh` turns it into
`demo/demo.gif` with [agg](https://github.com/asciinema/agg) and `demo/demo.mp4`
with ffmpeg.

## Files

```
live.sh         types and runs the demo at your zsh prompt
from-video.sh   screen recording -> demo/demo.mp4 + demo/demo.gif
record.py       headless recorder (pty -> asciicast)
render.sh       asciicast -> demo/demo.gif + demo/demo.mp4
Dockerfile      image with agg and ffmpeg, used by both render scripts
demo.cast       headless recording from 2026-11-11
```

Nothing here is installed on the host: agg and ffmpeg run in Docker.
