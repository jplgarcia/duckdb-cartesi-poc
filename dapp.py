"""DuckDB inside a Cartesi Machine (Rollups v2) - proof of concept.

Advance inputs (JSON, UTF-8):
  {"op": "trade", "asset": "ETH", "price": "3012.50", "qty": "1.5"}
  {"op": "batch", "trades": [{"asset": ..., "price": ..., "qty": ...}, ...]}
Each accepted advance emits a notice with the updated stats of the touched assets.

Inspect routes (payload is a plain UTF-8 path):
  info            DuckDB version and engine settings
  stats           per-asset count / VWAP / min / max / volume
  top/<n>         top n senders by notional volume
  candles/<asset> OHLC per 10-block bucket
"""
import json
import logging
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from os import environ
from typing import Callable

import duckdb

logger = logging.getLogger("dapp")

MAX_BATCH = 500
ROUTES = ["info", "stats", "top/<n>", "candles/<asset>"]

# Emitter signature: emit(kind, obj) with kind in {"notice", "report"}.
Emit = Callable[[str, object], None]

################################################################################
# Database


def open_db() -> duckdb.DuckDBPyConnection:
    # In-memory: the Cartesi Machine snapshot already persists RAM between
    # inputs, and a rejected input rolls the whole machine back, DB included.
    db = duckdb.connect(":memory:")
    for stmt in (
        # One thread: the machine has a single hart, and a fixed reduction
        # order keeps aggregates bit-for-bit reproducible.
        "SET threads = 1",
        "SET memory_limit = '256MB'",
        # Inputs never get to touch the filesystem or network, and no extension
        # is ever downloaded (there is no network in the machine anyway).
        "SET autoinstall_known_extensions = false",
        "SET autoload_known_extensions = false",
        "SET enable_external_access = false",
        "SET lock_configuration = true",
    ):
        db.execute(stmt)
    db.execute(
        """
        CREATE TABLE trades (
            input_index  UBIGINT       NOT NULL,
            seq          UINTEGER      NOT NULL,
            block_number UBIGINT       NOT NULL,
            sender       VARCHAR       NOT NULL,
            asset        VARCHAR       NOT NULL,
            price        DECIMAL(18,6) NOT NULL,
            qty          DECIMAL(18,6) NOT NULL,
            PRIMARY KEY (input_index, seq)
        )
        """
    )
    logger.info("[db] duckdb %s ready, table 'trades' created", duckdb.__version__)
    return db


################################################################################
# Codecs


def hex_to_str(hexstr: str) -> str:
    return bytes.fromhex(hexstr[2:] if hexstr.startswith("0x") else hexstr).decode("utf-8")


def str_to_hex(s: str) -> str:
    return "0x" + s.encode("utf-8").hex()


def to_json(obj) -> str:
    return json.dumps(obj, separators=(",", ":"))


################################################################################
# Domain


class BadInput(ValueError):
    pass


def parse_decimal(value, field: str) -> Decimal:
    # Strings (or ints) only: JSON floats would round before reaching the DB.
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise BadInput(f"{field} must be a decimal string")
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        raise BadInput(f"{field} is not a decimal: {value!r}")
    if not d.is_finite() or d <= 0 or d >= Decimal("1e12"):
        raise BadInput(f"{field} out of range: {value!r}")
    if d.as_tuple().exponent < -6:
        raise BadInput(f"{field} has more than 6 decimals: {value!r}")
    return d


def parse_trade(t) -> tuple[str, Decimal, Decimal]:
    if not isinstance(t, dict):
        raise BadInput("trade must be an object")
    asset = t.get("asset")
    if not isinstance(asset, str) or not (1 <= len(asset) <= 16) or not asset.isalnum():
        raise BadInput("asset must be 1-16 alphanumeric chars")
    return asset.upper(), parse_decimal(t.get("price"), "price"), parse_decimal(t.get("qty"), "qty")


def parse_advance(payload_hex: str) -> list[tuple[str, Decimal, Decimal]]:
    try:
        body = json.loads(hex_to_str(payload_hex))
    except (UnicodeDecodeError, ValueError) as e:
        raise BadInput(f"payload is not UTF-8 JSON: {e}")
    if not isinstance(body, dict):
        raise BadInput("payload must be a JSON object")
    op = body.get("op")
    if op == "trade":
        return [parse_trade(body)]
    if op == "batch":
        raw = body.get("trades")
        if not isinstance(raw, list) or not (1 <= len(raw) <= MAX_BATCH):
            raise BadInput(f"trades must be a list of 1..{MAX_BATCH}")
        return [parse_trade(t) for t in raw]
    raise BadInput(f"unknown op {op!r}")


STATS_SQL = """
    SELECT asset,
           count(*)                                           AS trades,
           CAST(sum(price * qty) / sum(qty) AS DECIMAL(18,6)) AS vwap,
           min(price)                                         AS low,
           max(price)                                         AS high,
           sum(qty)                                           AS volume
    FROM trades
    {where}
    GROUP BY asset
    ORDER BY asset
"""


def rows_as_dicts(rel) -> list[dict]:
    cols = [d[0] for d in rel.description]
    return [
        {c: (str(v) if isinstance(v, Decimal) else v) for c, v in zip(cols, row)}
        for row in rel.fetchall()
    ]


def asset_stats(db, assets: list[str] | None = None) -> list[dict]:
    if assets:
        where = "WHERE asset IN (SELECT unnest(?::VARCHAR[]))"
        return rows_as_dicts(db.execute(STATS_SQL.format(where=where), [assets]))
    return rows_as_dicts(db.execute(STATS_SQL.format(where="")))


def row_count(db) -> int:
    return db.execute("SELECT count(*) FROM trades").fetchone()[0]


def handle_advance(db, data: dict, emit: Emit) -> str:
    md = data["metadata"]
    idx = md["input_index"]
    try:
        trades = parse_advance(data["payload"])
    except BadInput as e:
        logger.warning("[db] input %s rejected, nothing written: %s", idx, e)
        emit("report", {"input_index": idx, "error": str(e)})
        return "reject"

    sender = md["msg_sender"].lower()
    rows = [(idx, i, md["block_number"], sender, a, p, q) for i, (a, p, q) in enumerate(trades)]
    try:
        db.executemany("INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    except duckdb.Error as e:
        # The machine rolls back on reject, so a half-applied batch never sticks.
        logger.error("[db] input %s insert failed: %s", idx, e)
        emit("report", {"input_index": idx, "error": "insert failed"})
        return "reject"

    for a, p, q in trades:
        logger.info("[db] input %s from %s: INSERT INTO trades (%s, price=%s, qty=%s)", idx, sender, a, p, q)
    touched = sorted({a for a, _, _ in trades})
    stats = asset_stats(db, touched)
    logger.info("[db] trades now has %d row(s); %s", row_count(db),
                ", ".join(f"{s['asset']} vwap={s['vwap']} trades={s['trades']}" for s in stats))
    emit("notice", {"input_index": idx, "inserted": len(rows), "stats": stats})
    return "accept"


def query_route(db, route: str):
    parts = route.split("/")
    if route == "info":
        settings = db.execute(
            "SELECT name, value FROM duckdb_settings() "
            "WHERE name IN ('threads','memory_limit','enable_external_access') ORDER BY name"
        ).fetchall()
        return {
            "duckdb": duckdb.__version__,
            "platform": db.execute("PRAGMA platform").fetchone()[0],
            "settings": dict(settings),
            "rows": row_count(db),
        }
    if route == "stats":
        return asset_stats(db)
    if parts[0] == "top" and len(parts) == 2 and parts[1].isdigit():
        return rows_as_dicts(db.execute(
            """
            SELECT sender, count(*) AS trades,
                   CAST(sum(price * qty) AS DECIMAL(24,6)) AS notional
            FROM trades GROUP BY sender
            ORDER BY notional DESC, sender
            LIMIT ?
            """, [min(int(parts[1]), 100)]))
    if parts[0] == "candles" and len(parts) == 2:
        return rows_as_dicts(db.execute(
            """
            SELECT block_number // 10 * 10            AS bucket,
                   arg_min(price, (input_index, seq)) AS open,
                   max(price)                         AS high,
                   min(price)                         AS low,
                   arg_max(price, (input_index, seq)) AS close,
                   sum(qty)                           AS volume
            FROM trades WHERE asset = ?
            GROUP BY bucket ORDER BY bucket
            """, [parts[1].upper()]))
    return None


def handle_inspect(db, data: dict, emit: Emit) -> str:
    route = hex_to_str(data["payload"]).strip().strip("/")
    try:
        result = query_route(db, route)
    except Exception as e:  # inspect must never kill the loop
        logger.exception("[db] inspect %r failed", route)
        emit("report", {"error": str(e)})
        return "accept"
    if result is None:
        logger.info("[db] inspect %r: unknown route", route)
        emit("report", {"error": f"unknown route {route!r}", "routes": ROUTES})
    else:
        n = len(result) if isinstance(result, list) else 1
        preview = to_json(result)
        preview = preview if len(preview) <= 200 else preview[:200] + "..."
        logger.info("[db] inspect %r: SELECT from trades -> %d row(s): %s", route, n, preview)
        emit("report", result)
    return "accept"


################################################################################
# Rollup HTTP server glue


def post(server: str, route: str, body: dict) -> tuple[int, bytes]:
    req = urllib.request.Request(
        server + route,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def http_emitter(server: str) -> Emit:
    def emit(kind: str, obj) -> None:
        status, body = post(server, f"/{kind}", {"payload": str_to_hex(to_json(obj))})
        if status >= 300:
            logger.error("/%s failed: %s %r", kind, status, body)
    return emit


def run(server: str, db=None, should_stop: Callable[[], bool] = lambda: False) -> None:
    db = db if db is not None else open_db()
    emit = http_emitter(server)
    handlers = {"advance_state": handle_advance, "inspect_state": handle_inspect}
    finish = {"status": "accept"}
    while not should_stop():
        status, body = post(server, "/finish", finish)
        if status == 202:
            logger.debug("no pending rollup request")
            continue
        req = json.loads(body)
        handler = handlers.get(req["request_type"])
        if handler is None:
            logger.error("unknown request type %r", req["request_type"])
            finish["status"] = "reject"
            continue
        finish["status"] = handler(db, req["data"], emit)


if __name__ == "__main__":
    logging.basicConfig(level="INFO", format="[dapp] %(message)s")
    server = environ["ROLLUP_HTTP_SERVER_URL"]
    logger.info("rollup http server: %s", server)
    run(server)
