"""Unit tests for dapp.py.

Meant to run inside linux/riscv64 against the cross-compiled DuckDB wheel
(scripts/test.sh), so they also prove the artifact itself works.
"""
import json
import platform
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import duckdb
import pytest

import dapp

ALICE = "0xF39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
BOB = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"


class Outputs:
    """Collects emitted notices/reports instead of POSTing them."""

    def __init__(self):
        self.items: list[tuple[str, object]] = []

    def __call__(self, kind, obj):
        # Round-trip through the real wire codec, like the rollup server would.
        self.items.append((kind, json.loads(dapp.hex_to_str(dapp.str_to_hex(dapp.to_json(obj))))))

    def of(self, kind):
        return [o for k, o in self.items if k == kind]


@pytest.fixture
def db():
    return dapp.open_db()


@pytest.fixture
def out():
    return Outputs()


def advance(db, out, body, sender=ALICE, index=0, block=10):
    payload = body if isinstance(body, str) else json.dumps(body)
    data = {
        "metadata": {"input_index": index, "msg_sender": sender, "block_number": block},
        "payload": dapp.str_to_hex(payload),
    }
    return dapp.handle_advance(db, data, out)


def inspect(db, out, route):
    status = dapp.handle_inspect(db, {"payload": dapp.str_to_hex(route)}, out)
    assert status == "accept"
    return out.of("report")[-1]


# --------------------------------------------------------------------------- runtime


def test_runs_on_riscv64_with_static_extensions(db):
    if platform.machine() != "riscv64":
        pytest.skip("only meaningful inside the riscv64 container")
    assert db.execute("PRAGMA platform").fetchone()[0] == "linux_riscv64"
    # duckdb_extensions() scans the extension dir on disk, which the dapp's
    # sandboxed connection refuses, so list them from a plain connection.
    plain = duckdb.connect(config={"autoload_known_extensions": False, "autoinstall_known_extensions": False})
    loaded = {r[0] for r in plain.execute("SELECT extension_name FROM duckdb_extensions() WHERE loaded").fetchall()}
    assert {"json", "parquet", "icu", "core_functions"} <= loaded


def test_sandbox_blocks_extension_dir(db):
    with pytest.raises(duckdb.PermissionException):
        db.execute("SELECT * FROM duckdb_extensions()").fetchall()


# --------------------------------------------------------------------------- codecs


@pytest.mark.parametrize("s", ["", "stats", '{"op":"trade"}', "ação ✓"])
def test_hex_roundtrip(s):
    assert dapp.hex_to_str(dapp.str_to_hex(s)) == s
    assert dapp.hex_to_str(dapp.str_to_hex(s)[2:]) == s


# --------------------------------------------------------------------------- advance


def test_trade_is_stored_and_noticed(db, out):
    assert advance(db, out, {"op": "trade", "asset": "eth", "price": "3000.5", "qty": "2"}) == "accept"
    assert db.execute("SELECT asset, price, qty, sender FROM trades").fetchall() == [
        ("ETH", dapp.Decimal("3000.500000"), dapp.Decimal("2.000000"), ALICE.lower())
    ]
    (notice,) = out.of("notice")
    assert notice == {
        "input_index": 0,
        "inserted": 1,
        "stats": [{"asset": "ETH", "trades": 1, "vwap": "3000.500000", "low": "3000.500000",
                   "high": "3000.500000", "volume": "2.000000"}],
    }


def test_batch_updates_vwap(db, out):
    advance(db, out, {"op": "trade", "asset": "ETH", "price": "3000.00", "qty": "2"}, index=0)
    advance(db, out, {"op": "batch", "trades": [
        {"asset": "ETH", "price": "3010.5", "qty": "1"},
        {"asset": "BTC", "price": "64000", "qty": "0.25"},
        {"asset": "eth", "price": "2995.25", "qty": "3"},
    ]}, sender=BOB, index=1)
    notice = out.of("notice")[-1]
    assert notice["inserted"] == 3
    eth = next(s for s in notice["stats"] if s["asset"] == "ETH")
    # (3000*2 + 3010.5*1 + 2995.25*3) / 6
    assert eth["vwap"] == "2999.375000"
    assert eth["trades"] == 3 and eth["volume"] == "6.000000"


@pytest.mark.parametrize("body, reason", [
    ({"op": "trade", "asset": "ETH", "price": 3000.1, "qty": "1"}, "price must be a decimal string"),
    ({"op": "trade", "asset": "ETH", "price": "1.1234567", "qty": "1"}, "more than 6 decimals"),
    ({"op": "trade", "asset": "ETH", "price": "-1", "qty": "1"}, "out of range"),
    ({"op": "trade", "asset": "ETH", "price": "NaN", "qty": "1"}, "out of range"),
    ({"op": "trade", "asset": "ETH", "price": "abc", "qty": "1"}, "not a decimal"),
    ({"op": "trade", "asset": "ETH", "price": "1", "qty": True}, "qty must be a decimal string"),
    ({"op": "trade", "asset": "E-TH", "price": "1", "qty": "1"}, "alphanumeric"),
    ({"op": "trade", "asset": "X" * 17, "price": "1", "qty": "1"}, "alphanumeric"),
    ({"op": "batch", "trades": []}, "trades must be a list"),
    ({"op": "batch", "trades": [{"asset": "A", "price": "1", "qty": "1"}] * 501}, "trades must be a list"),
    ({"op": "batch", "trades": ["nope"]}, "trade must be an object"),
    ({"op": "drop", "table": "trades"}, "unknown op"),
    ("[1, 2]", "must be a JSON object"),
    ("not json", "not UTF-8 JSON"),
])
def test_invalid_inputs_are_rejected_without_writes(db, out, body, reason):
    assert advance(db, out, body) == "reject"
    assert dapp.row_count(db) == 0
    assert out.of("notice") == []
    (report,) = out.of("report")
    assert reason in report["error"]


def test_invalid_utf8_is_rejected(db, out):
    data = {"metadata": {"input_index": 0, "msg_sender": ALICE, "block_number": 1}, "payload": "0xfffe"}
    assert dapp.handle_advance(db, data, out) == "reject"


def test_duplicate_input_index_is_rejected(db, out):
    body = {"op": "trade", "asset": "ETH", "price": "1", "qty": "1"}
    assert advance(db, out, body, index=7) == "accept"
    assert advance(db, out, body, index=7) == "reject"
    assert out.of("report")[-1]["error"] == "insert failed"


def test_replay_is_deterministic():
    inputs = [
        {"op": "trade", "asset": "ETH", "price": "3000.123456", "qty": "0.333333"},
        {"op": "batch", "trades": [{"asset": "ETH", "price": str(1000 + i), "qty": "0.1"} for i in range(200)]},
        {"op": "trade", "asset": "BTC", "price": "64000", "qty": "0.000001"},
    ]
    runs = []
    for _ in range(2):
        db, out = dapp.open_db(), Outputs()
        for i, body in enumerate(inputs):
            advance(db, out, body, index=i, block=i * 7)
        inspect(db, out, "stats")
        inspect(db, out, "candles/ETH")
        runs.append(out.items)
    assert runs[0] == runs[1]


# --------------------------------------------------------------------------- inspect


@pytest.fixture
def seeded(db, out):
    advance(db, out, {"op": "trade", "asset": "ETH", "price": "3000", "qty": "2"}, ALICE, 0, block=31)
    advance(db, out, {"op": "trade", "asset": "ETH", "price": "3100", "qty": "1"}, BOB, 1, block=35)
    advance(db, out, {"op": "trade", "asset": "BTC", "price": "64000", "qty": "1"}, BOB, 2, block=42)
    return db


def test_inspect_info(seeded, out):
    info = inspect(seeded, out, "info")
    assert info["duckdb"] == duckdb.__version__
    assert info["rows"] == 3
    assert info["settings"]["threads"] == "1"
    assert info["settings"]["enable_external_access"] == "false"


def test_inspect_stats(seeded, out):
    assert [s["asset"] for s in inspect(seeded, out, "stats")] == ["BTC", "ETH"]


def test_inspect_top(seeded, out):
    top = inspect(seeded, out, "/top/1/")
    assert top == [{"sender": BOB.lower(), "trades": 2, "notional": "67100.000000"}]


def test_inspect_candles(seeded, out):
    assert inspect(seeded, out, "candles/eth") == [
        {"bucket": 30, "open": "3000.000000", "high": "3100.000000", "low": "3000.000000",
         "close": "3100.000000", "volume": "3.000000"},
    ]


@pytest.mark.parametrize("route", ["bogus", "top/x", "top", "candles", ""])
def test_inspect_unknown_route(db, out, route):
    report = inspect(db, out, route)
    assert "unknown route" in report["error"]
    assert report["routes"] == dapp.ROUTES


def test_inspect_does_not_mutate(seeded, out):
    before = seeded.execute("SELECT * FROM trades ORDER BY ALL").fetchall()
    for r in ["info", "stats", "top/5", "candles/ETH"]:
        inspect(seeded, out, r)
    assert seeded.execute("SELECT * FROM trades ORDER BY ALL").fetchall() == before


# --------------------------------------------------------------------------- sandboxing


def test_no_filesystem_access(db):
    with pytest.raises(duckdb.Error):
        db.execute("SELECT * FROM read_csv('/etc/passwd')").fetchall()
    with pytest.raises(duckdb.Error):
        db.execute("COPY trades TO '/tmp/leak.csv'")


def test_configuration_is_locked(db):
    with pytest.raises(duckdb.Error):
        db.execute("SET enable_external_access = true")
    with pytest.raises(duckdb.Error):
        db.execute("SET threads = 4")


# --------------------------------------------------------------------------- finish loop


class FakeRollupServer:
    """Minimal rollup HTTP server: hands out queued requests on /finish and
    records every finish status and emitted output."""

    def __init__(self, requests):
        self.queue = list(requests)
        self.finish_statuses: list[str] = []
        self.outputs: list[tuple[str, dict]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/finish":
                    outer.finish_statuses.append(body["status"])
                    if outer.queue:
                        self._send(200, outer.queue.pop(0))
                    else:
                        self._send(202, {})
                else:
                    outer.outputs.append((self.path.strip("/"), json.loads(dapp.hex_to_str(body["payload"]))))
                    self._send(200, {"index": len(outer.outputs) - 1})

            def _send(self, code, obj):
                raw = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()


def adv_req(index, body):
    return {"request_type": "advance_state", "data": {
        "metadata": {"input_index": index, "msg_sender": ALICE, "block_number": 1},
        "payload": dapp.str_to_hex(json.dumps(body))}}


def test_finish_loop_propagates_status_and_outputs():
    server = FakeRollupServer([
        adv_req(0, {"op": "trade", "asset": "ETH", "price": "10", "qty": "1"}),
        adv_req(1, {"op": "nope"}),
        {"request_type": "inspect_state", "data": {"payload": dapp.str_to_hex("stats")}},
        {"request_type": "mystery", "data": {}},
        adv_req(2, {"op": "trade", "asset": "ETH", "price": "20", "qty": "1"}),
    ])
    try:
        # 6 finishes: 5 that fetch a request + 1 that reports the last status.
        dapp.run(server.url, should_stop=lambda: len(server.finish_statuses) >= 6)
    finally:
        server.close()

    assert server.finish_statuses == ["accept", "accept", "reject", "accept", "reject", "accept"]
    kinds = [k for k, _ in server.outputs]
    assert kinds == ["notice", "report", "report", "notice"]
    assert server.outputs[2][1][0]["trades"] == 1          # inspect saw only the accepted trade
    assert server.outputs[3][1]["stats"][0]["vwap"] == "15.000000"
