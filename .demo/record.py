#!/usr/bin/env python3
"""Record the demo as an asciinema v2 cast, running the commands for real.

Standard library only. Each command runs in a pseudo-terminal (so colors and
spinners look like a real shell); typing is simulated, output timing is real
but idle gaps are capped so the video stays short.

usage: python3 .demo/record.py [.demo/demo.cast]    (devnet must be running)
"""
import fcntl
import json
import os
import pty
import select
import struct
import subprocess
import sys
import termios
import time

WIDTH, HEIGHT = 112, 34
TYPE_DELAY = 0.035
MAX_GAP = 0.8
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PROMPT = "\x1b[1;32m$\x1b[0m "
SEND = "cartesi send --encoding string '{\"op\":\"trade\",\"asset\":\"ETH\",\"price\":\"3150\",\"qty\":\"1\"}'"

STEPS = [
    ("say", "# DuckDB 2.0 (cross-compiled for riscv64) running inside a Cartesi Machine"),
    ("run", "./scripts/inspect.sh info"),
    ("say", "# 1) current database state: 1 ETH trade at 3000"),
    ("run", "./scripts/inspect.sh stats"),
    ("say", "# 2) send a new trade with the Cartesi CLI (goes to the on-chain InputBox)"),
    ("run", SEND),
    ("wait", "input 1 from"),
    ("say", "# 3) app logs: the input was written to DuckDB"),
    ("run", "./scripts/applog.sh 2"),
    ("say", "# 4) inspect queries the database again: VWAP and trade count changed"),
    ("run", "./scripts/inspect.sh stats"),
    ("say", "# 5) and the app log shows the SELECT that answered that inspect"),
    ("run", "./scripts/applog.sh 1"),
]


class Cast:
    def __init__(self):
        self.t = 0.0
        self.events = []

    def out(self, text, dt=0.0):
        self.t += dt
        self.events.append([round(self.t, 3), "o", text.replace("\r\n", "\n").replace("\n", "\r\n")])

    def type(self, text, color=""):
        self.out(color)
        for ch in text:
            self.out(ch, TYPE_DELAY)
        self.out("\x1b[0m\r\n" if color else "\r\n", 0.25)

    def run(self, cmd):
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", HEIGHT, WIDTH, 0, 0))
        env = dict(os.environ, COLUMNS=str(WIDTH), LINES=str(HEIGHT), TERM="xterm-256color", FORCE_COLOR="1")
        proc = subprocess.Popen(cmd, shell=True, cwd=ROOT, stdin=slave, stdout=slave, stderr=slave, env=env)
        os.close(slave)
        last = time.monotonic()
        while True:
            r, _, _ = select.select([master], [], [], 0.05)
            if r:
                try:
                    data = os.read(master, 4096)
                except OSError:
                    data = b""
                if not data:
                    break
                now = time.monotonic()
                self.out(data.decode("utf-8", "replace"), min(now - last, MAX_GAP))
                last = now
            elif proc.poll() is not None:
                # drain anything left, then stop
                r, _, _ = select.select([master], [], [], 0.1)
                if not r:
                    break
        proc.wait()
        os.close(master)
        if proc.returncode:
            raise SystemExit(f"command failed ({proc.returncode}): {cmd}")

    def save(self, path):
        with open(path, "w") as f:
            f.write(json.dumps({"version": 2, "width": WIDTH, "height": HEIGHT,
                                "timestamp": int(time.time()), "env": {"TERM": "xterm-256color"}}) + "\n")
            for e in self.events:
                f.write(json.dumps(e) + "\n")


def wait_for_log(needle, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        logs = subprocess.run("./scripts/applog.sh 50", shell=True, cwd=ROOT,
                              capture_output=True, text=True).stdout
        if needle in logs:
            return
        time.sleep(1)
    raise SystemExit(f"timed out waiting for log line {needle!r}")


def main(path):
    cast = Cast()
    for kind, arg in STEPS:
        if kind == "say":
            cast.out(PROMPT, 0.6)
            cast.type(arg, "\x1b[90m")
        elif kind == "run":
            cast.out(PROMPT, 0.6)
            cast.type(arg)
            cast.run(arg)
        elif kind == "wait":
            wait_for_log(arg)       # off camera: the node needs a few blocks
            cast.out("", 0.8)
    cast.out(PROMPT, 0.6)
    cast.out("", 3.0)
    cast.save(path)
    print(f"wrote {path} ({cast.t:.1f}s, {len(cast.events)} events)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, ".demo", "demo.cast"))
