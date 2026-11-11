#!/usr/bin/env python3
"""End-to-end test against a running `cartesi run` devnet.

Standard library only, runs on the host with any python3 >= 3.9:
    cartesi build && cartesi run          # other terminal
    python3 tests/e2e.py                  # BASE_URL / APP to override

Uses a fresh random asset name on every run, so it works on a devnet that
already has inputs. Exits non-zero on the first failed check.
"""
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request

APP = os.environ.get("APP", "duckdb-cartesi-poc")
BASE = os.environ.get("BASE_URL", "http://127.0.0.1:6751")
ALICE = "0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266"
BOB = "0x70997970c51812dc3a010c7d01b50e0d17dc79c8"

failures = 0


def check(cond, msg):
    global failures
    print(("  PASS " if cond else "  FAIL ") + msg)
    if not cond:
        failures += 1


def http(url, data: bytes, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def rpc(method, **params):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": {"application": APP, **params}}
    res = http(f"{BASE}/rpc", json.dumps(body).encode(), {"Content-Type": "application/json"})
    if "error" in res:
        raise RuntimeError(res["error"])
    return res["result"]


def list_all(method):
    items, offset = [], 0
    while True:
        page = rpc(method, limit=50, offset=offset)
        items += page["data"]
        offset += len(page["data"])
        if not page["data"] or offset >= page["pagination"]["total_count"]:
            return items


def inspect(route: str):
    res = http(f"{BASE}/inspect/{APP}", route.encode())
    assert res["status"] == "Accepted", res
    return [json.loads(bytes.fromhex(r["payload"][2:])) for r in res["reports"]]


def wait_ready(timeout=300):
    """`cartesi run` reports the contract as deployed before the node has
    loaded the machine; until then inspect answers 503. Slow CI runners hit
    that window, so poll `info` until the app answers."""
    deadline = time.time() + timeout
    while True:
        try:
            return inspect("info")
        except (urllib.error.HTTPError, urllib.error.URLError, ConnectionError) as e:
            if time.time() > deadline:
                raise
            print(f"  waiting for the app ({e})")
            time.sleep(5)


def send(body, sender):
    payload = body if isinstance(body, str) else json.dumps(body)
    subprocess.run(["cartesi", "send", "--encoding", "string", "--from", sender, payload],
                   check=True, capture_output=True)
    print(f"  sent  {payload}")


def hexint(v):
    return int(v, 16) if isinstance(v, str) else v


def main():
    asset = "T" + secrets.token_hex(4).upper()
    print(f"app={APP} base={BASE} asset={asset}")

    print("\n[1] devnet is up and the app runs the riscv64 build")
    (info,) = wait_ready()
    check(info["platform"] == "linux_riscv64", f"platform is {info['platform']}")
    check(info["settings"]["threads"] == "1", "threads = 1")
    check(info["settings"]["enable_external_access"] == "false", "external access disabled")
    rows_before = info["rows"]
    n0 = len(list_all("cartesi_listInputs"))

    print("\n[2] send 2 valid and 2 invalid inputs")
    send({"op": "trade", "asset": asset, "price": "100.50", "qty": "2"}, ALICE)
    send({"op": "batch", "trades": [{"asset": asset, "price": "101", "qty": "1"},
                                    {"asset": asset.lower(), "price": "99.25", "qty": "3"}]}, BOB)
    send({"op": "trade", "asset": asset, "price": 100.1, "qty": "1"}, ALICE)   # float price
    send({"op": "drop", "table": "trades"}, BOB)                               # unknown op

    print("\n[3] node processes them")
    deadline = time.time() + 180
    while True:
        new = [i for i in list_all("cartesi_listInputs") if hexint(i["index"]) >= n0]
        if len(new) >= 4 and all(i["status"] not in ("NONE", None) for i in new):
            break
        if time.time() > deadline:
            check(False, f"timed out waiting for inputs, got {[(i['index'], i['status']) for i in new]}")
            return
        time.sleep(2)
    new.sort(key=lambda i: hexint(i["index"]))
    statuses = [i["status"] for i in new[:4]]
    check(statuses == ["ACCEPTED", "ACCEPTED", "REJECTED", "REJECTED"], f"statuses {statuses}")

    print("\n[4] notices carry the stats computed by DuckDB")
    idx = [hexint(i["index"]) for i in new[:4]]
    notices = {}
    for o in list_all("cartesi_listOutputs"):
        d = o.get("decoded_data") or {}
        if d.get("type") == "Notice" and hexint(o["input_index"]) in idx:
            notices[hexint(o["input_index"])] = json.loads(bytes.fromhex(d["payload"][2:]))
    check(set(notices) == set(idx[:2]), f"notices only for accepted inputs {sorted(notices)}")
    first = notices.get(idx[0], {}).get("stats", [{}])[0]
    check(first.get("vwap") == "100.500000" and first.get("trades") == 1, f"after input {idx[0]}: {first}")
    second = notices.get(idx[1], {}).get("stats", [{}])[0]
    # (100.5*2 + 101*1 + 99.25*3) / 6 = 99.958333...
    check(second.get("vwap") == "99.958333" and second.get("trades") == 3, f"after input {idx[1]}: {second}")

    print("\n[5] inspect reads the same state back")
    (stats,) = inspect("stats")
    mine = [s for s in stats if s["asset"] == asset]
    check(mine == [{"asset": asset, "trades": 3, "vwap": "99.958333", "low": "99.250000",
                    "high": "101.000000", "volume": "6.000000"}], f"stats {mine}")
    (info,) = inspect("info")
    check(info["rows"] == rows_before + 3, f"rows {rows_before} -> {info['rows']}")
    (candles,) = inspect(f"candles/{asset}")
    check(len(candles) >= 1 and candles[0]["open"] == "100.500000" and candles[-1]["close"] == "99.250000",
          f"candles {candles}")
    (top,) = inspect("top/100")
    check({t["sender"] for t in top} >= {ALICE, BOB}, "both senders ranked")
    (bad,) = inspect("nope")
    check("unknown route" in bad.get("error", ""), "unknown route answered with an error report")

    print("\n[6] reports of rejected inputs (informative, not asserted)")
    reports = [r for r in list_all("cartesi_listReports") if hexint(r["input_index"]) in idx[2:]]
    print(f"  INFO cartesi_listReports returned {len(reports)} report(s) for rejected inputs {idx[2:]}")

    print(f"\n{'OK' if failures == 0 else f'{failures} FAILED'}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        check(False, f"error: {e!r}")
    sys.exit(1 if failures else 0)
