# duckdb-cartesi-poc

App Python para **Cartesi Rollups v2** que usa **DuckDB 2.0.0** como banco
analítico dentro da Cartesi Machine (RISC-V). A DuckDB não publica wheel
`linux_riscv64`, então o módulo Python é **compilado por cross compile**: o
compilador roda nativo no host (arm64 ou amd64) e gera código riscv64. Não usa
QEMU no build, e nada da DuckDB é instalado no host.

![demo](demo/demo.gif)

> No vídeo: um trade é enviado pela CLI da Cartesi, o log do app mostra o
> `INSERT` no DuckDB, e o inspect consulta o banco de novo com o VWAP alterado.
> Versão em MP4: [demo/demo.mp4](demo/demo.mp4).

Testado em 2026-11-11 com Cartesi CLI `2.0.0-alpha.35`, machine-guest-tools
`0.18.0`, base `cartesi/python:3.13.2-slim-noble`, Docker Desktop 4 GB, Mac arm64.

## Requisitos

- Docker (com buildx; o Docker Desktop já traz QEMU para riscv64)
- [Cartesi CLI](https://docs.cartesi.io/cartesi-rollups/2.0/development/installation/) `2.0.0-alpha.35`
- `python3` 3.9+ só com a biblioteca padrão (para o e2e e para gravar o demo)

O wheel riscv64 já vem versionado em `riscv-wheel-index/`, então não precisa
compilar a DuckDB para rodar o app.

## Rodando

```bash
cartesi build
```

```bash
cartesi run
```

Em outro terminal, consulte o estado, envie um trade e consulte de novo.

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
✔ Input sent: 0xe6d68c31f97d65c30b1083bec17f9c2b92ed1803bb294aefb6594b45113c79a9
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

VWAP = (3000·2 + 3150·1) / 3 = 3050. `info` mostra o que está rodando:

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

Helpers: `scripts/inspect.sh <rota>` faz o inspect e decodifica os reports, e
`scripts/applog.sh [n]` mostra as últimas linhas `[dapp] [db]` de `cartesi logs`.
Ambos aceitam `BASE_URL` e `APP` (padrão `http://127.0.0.1:6751` e `duckdb-cartesi-poc`).

## O app

Um registro de trades com estatísticas em SQL.

| Advance (JSON em UTF-8) | Efeito |
| --- | --- |
| `{"op":"trade","asset":"ETH","price":"3000.00","qty":"2"}` | insere 1 trade e emite notice com as stats do ativo |
| `{"op":"batch","trades":[...]}` | até 500 trades num input |
| qualquer outra coisa | `reject` + report com o motivo |

| Inspect (payload cru) | Resposta |
| --- | --- |
| `info` | versão, plataforma, settings do engine, total de linhas |
| `stats` | count, VWAP, min, max e volume por ativo |
| `top/<n>` | senders com maior notional |
| `candles/<asset>` | OHLC por bucket de 10 blocos |

Escolhas de projeto (em [dapp.py](dapp.py)):

- **Banco em memória.** O snapshot da máquina já persiste a RAM entre inputs, e
  um `reject` reverte a máquina inteira, banco incluído.
- **`threads = 1`.** A máquina tem um hart só, e uma ordem fixa de redução
  deixa os agregados reproduzíveis bit a bit.
- **`DECIMAL(18,6)` e preço como string.** Float em JSON seria arredondado
  antes de chegar ao banco, por isso preço numérico é rejeitado.
- **Sandbox.** `enable_external_access=false`, `autoload/autoinstall=false` e
  `lock_configuration=true`. Nenhum input consegue ler arquivo, abrir rede,
  baixar extensão ou desfazer essas configurações. As 4 extensões usadas
  (core_functions, json, parquet, icu) vêm linkadas estaticamente no módulo.
- **Queries parametrizadas.** Nenhuma string de input entra no SQL.
- [cartesi.toml](cartesi.toml) sobe a RAM da máquina para 512 MiB. A DuckDB fica limitada a 256 MB.

## Testes

### Unitários (dentro de riscv64)

```bash
./scripts/test.sh
```

Monta uma imagem `linux/riscv64` com a mesma base da Cartesi Machine e o mesmo
wheel cross-compilado, e roda o pytest nela (via QEMU em hosts que não são
RISC-V). Ou seja, testa o artefato real e não uma DuckDB do host. Argumentos
extras vão para o pytest (`./scripts/test.sh -k inspect`).

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

O que cobrem ([tests/test_dapp.py](tests/test_dapp.py)):

- o módulo roda em riscv64, se identifica como `linux_riscv64` e tem as 4 extensões estáticas;
- advance aceito grava no banco e o notice traz as stats certas (VWAP conferido à mão);
- 15 formas de input inválido são rejeitadas sem escrever nada;
- replay das mesmas entradas em bancos novos dá saídas idênticas byte a byte;
- todas as rotas de inspect, e inspect nunca altera o banco;
- sandbox: `read_csv('/etc/passwd')`, `COPY ... TO` e `SET enable_external_access=true` falham;
- o loop `/finish` contra um rollup server falso: status de accept/reject propagado
  e outputs na ordem certa.

### End-to-end (no devnet)

Com `cartesi run` no ar:

```bash
python3 tests/e2e.py
```

Usa só a biblioteca padrão. Envia 4 inputs pela `cartesi send` (2 válidos, 2
inválidos, de duas contas), espera o node processar e confere status, notices e
inspect. Cada execução usa um ativo com nome aleatório, então funciona num
devnet que já tem inputs.

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

[.github/workflows/ci.yml](.github/workflows/ci.yml) roda os testes unitários
(riscv64 via QEMU) e depois o e2e completo: instala a Cartesi CLI, faz
`cartesi build`, sobe `cartesi run` e roda `tests/e2e.py`.
[.github/workflows/wheel.yml](.github/workflows/wheel.yml) (manual) recompila o
wheel num runner amd64 e publica como artefato.

## Como o cross compile funciona

```
host (arm64/amd64, Docker)                         Cartesi Machine (riscv64)
┌──────────────────────────────────────┐          ┌───────────────────────────┐
│ wheel-builder/Dockerfile             │          │ Dockerfile (template v2)  │
│  python 3.13.2 (host) + numpy,       │  .whl    │  pip install --no-index   │
│  nanobind, scikit-build-core         ├────────► │   riscv-wheel-index/      │
│  g++-12 riscv64-linux-gnu (cross)    │          │  python3 dapp.py          │
│  headers do Python ALVO (riscv64)    │          │   └─ import duckdb        │
└──────────────────────────────────────┘          └───────────────────────────┘
```

Para recompilar o wheel (só quando mudar a versão da DuckDB):

```bash
./scripts/build-duckdb-wheel.sh
```

O script baixa o sdist do PyPI (sha256 conferido), compila
`duckdb-<ver>-cp312-abi3-linux_riscv64.whl` em
`riscv-wheel-index/wheels/cp313/duckdb/` e confere que o resultado é ELF RISC-V
sem símbolos `__atomic_*` pendentes. Leva uns 12 min com 2 jobs. Com mais
memória no Docker, use `JOBS=4`, e para outra versão use `DUCKDB_VERSION=x.y.z`
(atualize `requirements.txt` e `riscv-wheel-index/index.json`). O diretório de
build fica num cache do BuildKit, então um build interrompido continua de onde parou.

### Problemas encontrados e como foram resolvidos

| Sintoma | Causa | Solução |
| --- | --- | --- |
| pip tentou compilar o numpy do zero e falhou | `_PYTHON_HOST_PLATFORM=linux-riscv64` valia também para as deps de build, e o pip procurou wheels riscv64 | deps de build instaladas nativas antes, `--no-build-isolation`, variável só no `pip wheel` |
| `cc1plus` morto por falta de memória | arquivos unity da DuckDB usam 1 a 1,5 GB cada, e 4 jobs não cabem em 4 GB de Docker | `JOBS=2` por padrão |
| `undefined symbol: __atomic_exchange_1` no import | GCC 12 não gera inline os atômicos de 1 e 2 bytes em RISC-V (o 13+ gera) e a imagem alvo não tem `libatomic1` | `libatomic.a` (PIC) linkada estática no fim da linha de link, com os símbolos escondidos |
| `-latomic` em `CMAKE_SHARED_LINKER_FLAGS` não fez efeito | o módulo é `MODULE` (nanobind), não `SHARED`, e o flag entrava antes dos objetos | usar `CMAKE_CXX_STANDARD_LIBRARIES` |
| `PRAGMA platform` dizia `linux_amd64` | a DuckDB rotula todo 64-bit que não é ARM como amd64 | `DUCKDB_EXPLICIT_PLATFORM=linux_riscv64` |
| inspect respondia "unknown route" com o JSON inteiro | no node v2 o corpo do POST de inspect é o payload cru, não `{"payload":"0x.."}` | `curl --data-binary "<rota>"` |

Compatibilidade binária: o builder usa glibc 2.36 (bookworm), mais antiga que a
2.39 do alvo (noble). A `libstdc++` do alvo (GCC 14) é mais nova que a do
compilador (GCC 12). Os headers do Python vêm da própria imagem riscv64 alvo.

## Observação sobre reports de inputs rejeitados

No input rejeitado, o app faz `POST /report` (o rollup server responde 202) e o
advancer registra `status=REJECTED outputs=0 reports=1`. Mesmo assim,
`cartesi_listReports` devolve `total_count: 0`. O e2e só registra esse
comportamento, sem afirmar nada. Falta confirmar se é intencional no node v2.

## Gravando o demo de novo

Com um devnet novo e um trade inicial de ETH (`price 3000`, `qty 2`):

```bash
python3 demo/record.py demo/demo.cast
```

```bash
./demo/render.sh
```

`record.py` roda os comandos de verdade num pseudo-terminal e grava um asciicast
(só a digitação é simulada). `render.sh` gera `demo.gif` com o
[agg](https://github.com/asciinema/agg) e `demo.mp4` com o ffmpeg, os dois dentro do Docker.

## Estrutura

```
dapp.py                     app: handlers, DuckDB, loop /finish
Dockerfile                  imagem da Cartesi Machine (template v2 + índice local)
cartesi.toml                RAM da máquina
requirements.txt            duckdb == 2.0.0
riscv-wheel-index/          wheel riscv64 cross-compilado + index.json
wheel-builder/              Dockerfile, toolchain CMake e download do sdist
scripts/                    build-duckdb-wheel.sh, test.sh, inspect.sh, applog.sh
tests/                      test_dapp.py (pytest em riscv64), e2e.py, Dockerfile
demo/                       record.py, render.sh, demo.cast/.gif/.mp4
.github/workflows/          ci.yml, wheel.yml
```

## Limitações

- O wheel (22 MB) está versionado no repo.
- Imagens base fixadas por tag, não por digest.
- Ciclos por advance não foram medidos. Para cargas pesadas por input, meça antes.
- O CI ainda não rodou no GitHub. Foi escrito para os mesmos passos validados localmente.
