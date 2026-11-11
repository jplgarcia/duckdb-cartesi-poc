# duckdb-cartesi-poc

A Python **Cartesi Rollups v2** app that uses **DuckDB 2.0.0** as its analytical
database inside the Cartesi Machine (RISC-V). DuckDB does not ship a
`linux_riscv64` wheel, so the Python module is **cross-compiled**: the compiler
runs natively on the host (arm64 or amd64) and emits riscv64 code. The build
uses no QEMU, and nothing DuckDB-related gets installed on the host.

![demo](demo/demo.gif)

> In the video: a trade is sent with the Cartesi CLI, the app log shows the
> `INSERT` into DuckDB, and an inspect queries the database again and returns the
> updated VWAP. MP4 version: [demo/demo.mp4](demo/demo.mp4).
>
> The recording is real: [demo/record.py](demo/record.py) runs every command
> against a live devnet and captures its actual output. Only the typing is
> simulated, idle gaps are shortened, and the wait for the node to process the
> input happens off camera.

Tested on 2026-11-11 with Cartesi CLI `2.0.0-alpha.35`, machine-guest-tools
`0.18.0`, base image `cartesi/python:3.13.2-slim-noble`, Docker Desktop with 4 GB, arm64 Mac.

## Requirements

- Docker with buildx (Docker Desktop already ships QEMU for riscv64)
- [Cartesi CLI](https://docs.cartesi.io/cartesi-rollups/2.0/development/installation/) `2.0.0-alpha.35`
- `python3` 3.9+ with only the standard library (for the e2e test and the demo recorder)

The riscv64 wheel is committed under `riscv-wheel-index/`, so you do not need to
compile DuckDB to run the app.

## Running

```bash
cartesi build
```

```bash
cartesi run
```

In another terminal, query the state, send a trade, and query again.

```console
$ ./scripts/inspect.sh stats
[
  {
    "asset": "ETH",
    "trades": 1,
    "vwap": "3000.000000",
    "low": "3000.000000",
    "high": "3000.000000",
    "volume": "2.000000"
  }
]
$ cartesi send --encoding string '{"op":"trade","asset":"ETH","price":"3150","qty":"1"}'
✔ Input sent: 0xc58f344561c7f36d2080302c04f93d5ccd5e4938ab70eed6788017423b178fce
$ ./scripts/applog.sh 2
[dapp] [db] input 1 from 0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266: INSERT INTO trades (ETH, price=3150, qty=1)
[dapp] [db] trades now has 2 row(s); ETH vwap=3050.000000 trades=2
$ ./scripts/inspect.sh stats
[
  {
    "asset": "ETH",
    "trades": 2,
    "vwap": "3050.000000",
    "low": "3000.000000",
    "high": "3150.000000",
    "volume": "3.000000"
  }
]
$ ./scripts/applog.sh 1
[dapp] [db] inspect 'stats': SELECT from trades -> 1 row(s): [{"asset":"ETH","trades":2,"vwap":"3050.000000","low":"3000.000000","high":"3150.000000","volume":"3.000000"}]
```

VWAP = (3000·2 + 3150·1) / 3 = 3050. The `info` route shows what is running:

```console
$ ./scripts/inspect.sh info
{
  "duckdb": "2.0.0",
  "platform": "linux_riscv64",
  "settings": {
    "enable_external_access": "false",
    "memory_limit": "244.1 MiB",
    "threads": "1"
  },
  "rows": 1
}
```

Helpers: `scripts/inspect.sh <route>` sends an inspect and decodes the reports,
and `scripts/applog.sh [n]` prints the last `[dapp] [db]` lines from
`cartesi logs`. Both honor `BASE_URL` and `APP` (defaults
`http://127.0.0.1:6751` and `duckdb-cartesi-poc`).

## The app

A trade ledger with SQL statistics.

| Advance (UTF-8 JSON) | Effect |
| --- | --- |
| `{"op":"trade","asset":"ETH","price":"3000.00","qty":"2"}` | inserts 1 trade and emits a notice with the asset's stats |
| `{"op":"batch","trades":[...]}` | up to 500 trades in one input |
| anything else | `reject` plus a report with the reason |

| Inspect (raw payload) | Response |
| --- | --- |
| `info` | version, platform, engine settings, row count |
| `stats` | count, VWAP, min, max and volume per asset |
| `top/<n>` | senders with the highest notional |
| `candles/<asset>` | OHLC per 10-block bucket |

Design choices (in [dapp.py](dapp.py)):

- **In-memory database.** The machine snapshot already keeps RAM between
  inputs, and a `reject` rolls back the whole machine, database included.
- **`threads = 1`.** The machine has a single hart, and a fixed reduction order
  keeps aggregates bit-for-bit reproducible.
- **`DECIMAL(18,6)` with prices as strings.** A JSON float would be rounded
  before reaching the database, so numeric prices are rejected.
- **Sandbox.** `enable_external_access=false`, `autoload/autoinstall=false` and
  `lock_configuration=true`. No input can read files, open network connections,
  download extensions, or undo these settings. The 4 extensions in use
  (core_functions, json, parquet, icu) are statically linked into the module.
- **Parameterized queries.** No input string is ever spliced into SQL.
- [cartesi.toml](cartesi.toml) raises the machine RAM to 512 MiB. DuckDB is capped at 256 MB.

## Tests

### Unit tests (inside riscv64)

```bash
./scripts/test.sh
```

This builds a `linux/riscv64` image from the same base as the Cartesi Machine,
installs the same cross-compiled wheel, and runs pytest in it (through QEMU on
non-RISC-V hosts). So it tests the real artifact, not a host build of DuckDB.
Extra arguments are passed to pytest (`./scripts/test.sh -k inspect`).

```console
$ ./scripts/test.sh
platform linux -- Python 3.13.2, pytest-8.3.5, pluggy-1.7.0 -- /usr/local/bin/python3
collecting ... collected 38 items

tests/test_dapp.py::test_runs_on_riscv64_with_static_extensions PASSED   [  2%]
tests/test_dapp.py::test_sandbox_blocks_extension_dir PASSED             [  5%]
tests/test_dapp.py::test_hex_roundtrip[] PASSED                          [  7%]
...
tests/test_dapp.py::test_invalid_inputs_are_rejected_without_writes[body0-price must be a decimal string] PASSED [ 23%]
...
tests/test_dapp.py::test_replay_is_deterministic PASSED                  [ 65%]
...
tests/test_dapp.py::test_no_filesystem_access PASSED                     [ 94%]
tests/test_dapp.py::test_configuration_is_locked PASSED                  [ 97%]
tests/test_dapp.py::test_finish_loop_propagates_status_and_outputs PASSED [100%]

============================== 38 passed in 9.74s ==============================
```

What they cover ([tests/test_dapp.py](tests/test_dapp.py)):

- the module runs on riscv64, reports itself as `linux_riscv64`, and has the 4 static extensions;
- an accepted advance writes to the database and the notice carries the right stats (VWAP checked by hand);
- 15 kinds of invalid input are rejected without writing anything;
- replaying the same inputs into fresh databases gives byte-identical outputs;
- every inspect route, and inspect never changes the database;
- sandbox: `read_csv('/etc/passwd')`, `COPY ... TO` and `SET enable_external_access=true` all fail;
- the `/finish` loop against a fake rollup server: accept/reject status is
  propagated and outputs come out in the right order.

### End-to-end (on the devnet)

With `cartesi run` up:

```bash
python3 tests/e2e.py
```

Standard library only. It sends 4 inputs with `cartesi send` (2 valid, 2
invalid, from two accounts), waits for the node to process them, and checks
statuses, notices and inspect results. Each run uses a randomly named asset, so
it works on a devnet that already has inputs.

```console
$ python3 tests/e2e.py
app=duckdb-cartesi-poc base=http://127.0.0.1:6751 asset=T2BD87548

[1] devnet is up and the app runs the riscv64 build
  PASS platform is linux_riscv64
  PASS threads = 1
  PASS external access disabled

[2] send 2 valid and 2 invalid inputs
  sent  {"op": "trade", "asset": "T2BD87548", "price": "100.50", "qty": "2"}
  sent  {"op": "batch", "trades": [{"asset": "T2BD87548", "price": "101", "qty": "1"}, {"asset": "t2bd87548", "price": "99.25", "qty": "3"}]}
  sent  {"op": "trade", "asset": "T2BD87548", "price": 100.1, "qty": "1"}
  sent  {"op": "drop", "table": "trades"}

[3] node processes them
  PASS statuses ['ACCEPTED', 'ACCEPTED', 'REJECTED', 'REJECTED']

[4] notices carry the stats computed by DuckDB
  PASS notices only for accepted inputs [2, 3]
  PASS after input 2: {'asset': 'T2BD87548', 'trades': 1, 'vwap': '100.500000', 'low': '100.500000', 'high': '100.500000', 'volume': '2.000000'}
  PASS after input 3: {'asset': 'T2BD87548', 'trades': 3, 'vwap': '99.958333', 'low': '99.250000', 'high': '101.000000', 'volume': '6.000000'}

[5] inspect reads the same state back
  PASS stats [{'asset': 'T2BD87548', 'trades': 3, 'vwap': '99.958333', 'low': '99.250000', 'high': '101.000000', 'volume': '6.000000'}]
  PASS rows 1 -> 4
  PASS candles [{'bucket': 60, 'open': '100.500000', 'high': '101.000000', 'low': '99.250000', 'close': '99.250000', 'volume': '6.000000'}]
  PASS both senders ranked
  PASS unknown route answered with an error report

[6] reports of rejected inputs (informative, not asserted)
  INFO cartesi_listReports returned 0 report(s) for rejected inputs [4, 5]

OK
```

### CI

[.github/workflows/ci.yml](.github/workflows/ci.yml) runs the unit tests
(riscv64 through QEMU) and then the full e2e: it installs the Cartesi CLI, runs
`cartesi build`, starts `cartesi run`, and runs `tests/e2e.py`.
[.github/workflows/wheel.yml](.github/workflows/wheel.yml) (manual) rebuilds the
wheel on an amd64 runner and uploads it as an artifact.

## How the cross-compile works

```
host (arm64/amd64, Docker)                         Cartesi Machine (riscv64)
┌──────────────────────────────────────┐          ┌───────────────────────────┐
│ wheel-builder/Dockerfile             │          │ Dockerfile (v2 template)  │
│  python 3.13.2 (host) + numpy,       │  .whl    │  pip install --no-index   │
│  nanobind, scikit-build-core         ├────────► │   riscv-wheel-index/      │
│  g++-12 riscv64-linux-gnu (cross)    │          │  python3 dapp.py          │
│  TARGET Python headers (riscv64)     │          │   └─ import duckdb        │
└──────────────────────────────────────┘          └───────────────────────────┘
```

To rebuild the wheel (only needed when changing the DuckDB version):

```bash
./scripts/build-duckdb-wheel.sh
```

The script downloads the sdist from PyPI (sha256 checked), builds
`duckdb-<ver>-cp312-abi3-linux_riscv64.whl` into
`riscv-wheel-index/wheels/cp313/duckdb/`, and checks that the result is a RISC-V
ELF with no unresolved `__atomic_*` symbols. It takes about 12 minutes with 2
jobs. With more memory in Docker, use `JOBS=4`. For another version, set
`DUCKDB_VERSION=x.y.z` and update `requirements.txt` and
`riscv-wheel-index/index.json`. The build directory lives in a BuildKit cache,
so an interrupted build resumes where it stopped.

### Problems hit and how they were solved

| Symptom | Cause | Fix |
| --- | --- | --- |
| pip tried to build numpy from source and failed | `_PYTHON_HOST_PLATFORM=linux-riscv64` also applied to the build dependencies, so pip looked for riscv64 wheels | install the build deps natively first, use `--no-build-isolation`, set the variable only for `pip wheel` |
| `cc1plus` killed (out of memory) | DuckDB's unity sources take 1 to 1.5 GB each, and 4 jobs do not fit in 4 GB of Docker memory | `JOBS=2` by default |
| `undefined symbol: __atomic_exchange_1` on import | GCC 12 does not inline 1- and 2-byte atomics on RISC-V (GCC 13+ does), and the target image has no `libatomic1` | link `libatomic.a` (position independent) statically at the end of the link line, with its symbols hidden |
| `-latomic` in `CMAKE_SHARED_LINKER_FLAGS` had no effect | the module is a CMake `MODULE` (nanobind), not `SHARED`, and the flag came before the objects | use `CMAKE_CXX_STANDARD_LIBRARIES` |
| `PRAGMA platform` said `linux_amd64` | DuckDB labels every non-ARM 64-bit build as amd64 | `DUCKDB_EXPLICIT_PLATFORM=linux_riscv64` |
| inspect answered "unknown route" with the whole JSON body | on the v2 node the inspect POST body is the raw payload, not `{"payload":"0x.."}` | `curl --data-binary "<route>"` |

Binary compatibility: the builder uses glibc 2.36 (bookworm), older than the
target's 2.39 (noble). The target's `libstdc++` (GCC 14) is newer than the
compiler's (GCC 12). The Python headers come from the riscv64 target image itself.

## Note on reports from rejected inputs

For a rejected input, the app does `POST /report` (the rollup server answers 202)
and the advancer logs `status=REJECTED outputs=0 reports=1`. Even so,
`cartesi_listReports` returns `total_count: 0`. The e2e test only records this
behavior and asserts nothing about it. Whether it is intended on the v2 node is
still unconfirmed.

## Recording the demo again

On a fresh devnet, seed one ETH trade (`price 3000`, `qty 2`), then:

```bash
python3 demo/record.py demo/demo.cast
```

```bash
./demo/render.sh
```

`record.py` runs the commands for real in a pseudo-terminal and writes an
asciicast (only the typing is simulated). `render.sh` produces `demo.gif` with
[agg](https://github.com/asciinema/agg) and `demo.mp4` with ffmpeg, both inside Docker.

## Layout

```
dapp.py                     app: handlers, DuckDB, /finish loop
Dockerfile                  Cartesi Machine image (v2 template + local wheel index)
cartesi.toml                machine RAM
requirements.txt            duckdb == 2.0.0
riscv-wheel-index/          cross-compiled riscv64 wheel + index.json
wheel-builder/              Dockerfile, CMake toolchain, sdist download
scripts/                    build-duckdb-wheel.sh, test.sh, inspect.sh, applog.sh
tests/                      test_dapp.py (pytest on riscv64), e2e.py, Dockerfile
demo/                       record.py, render.sh, demo.cast/.gif/.mp4
.github/workflows/          ci.yml, wheel.yml
```

## Limitations

- The wheel (22 MB) is committed to the repo.
- Base images are pinned by tag, not by digest.
- Cycles per advance were not measured. Measure before putting heavy work in a single input.
