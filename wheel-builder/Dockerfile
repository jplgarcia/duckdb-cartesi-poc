# syntax=docker.io/docker/dockerfile:1
#
# Cross-compiles the DuckDB Python package (sdist from PyPI) into a
# linux_riscv64 wheel for the Cartesi Machine, WITHOUT emulation:
# the compiler runs natively on the build host (arm64 or amd64) and emits
# riscv64 code through the Debian cross toolchain.
#
# Usage: scripts/build-duckdb-wheel.sh  (exports the wheel via --output)

ARG DUCKDB_VERSION=2.0.0
ARG DUCKDB_SDIST_SHA256=

################################################################################
# Target Python headers: taken from the exact riscv64 image the dapp runs on.
# Nothing is executed in this stage, so no emulation is involved.
FROM --platform=linux/riscv64 cartesi/python:3.13.2-slim-noble AS target-python

################################################################################
# Native builder. Same CPython version as the target (3.13.2). Bookworm glibc
# (2.36) is older than the target's noble glibc (2.39), so the output runs there.
FROM --platform=$BUILDPLATFORM python:3.13.2-slim-bookworm AS builder

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      gcc-riscv64-linux-gnu g++-riscv64-linux-gnu binutils-riscv64-linux-gnu \
      ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=target-python /usr/local/include/python3.13 /opt/riscv64-python/include/python3.13
COPY riscv64-toolchain.cmake /opt/riscv64-toolchain.cmake

ARG DUCKDB_VERSION
ARG DUCKDB_SDIST_SHA256
WORKDIR /src
COPY fetch_sdist.py /usr/local/bin/fetch_sdist.py
RUN python3 /usr/local/bin/fetch_sdist.py "${DUCKDB_VERSION}" "${DUCKDB_SDIST_SHA256}" /src/duckdb.tar.gz \
    && tar xzf duckdb.tar.gz && mv "duckdb-${DUCKDB_VERSION}" duckdb && rm duckdb.tar.gz

# Build-time Python deps run on the HOST (they generate code and headers, they
# never end up in the riscv64 binary), so install them natively and build
# without isolation. The numpy headers are arch-independent on 64-bit LE Linux.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install "scikit-build-core>=0.11.4" "nanobind>=3.0" "numpy>=2.0" \
                "cmake>=3.29" "ninja>=1.10" setuptools_scm

# Each DuckDB unity translation unit can take 1-1.5 GB in cc1plus. 2 jobs fits
# Docker Desktop's default 4 GB; raise JOBS if Docker has more memory.
ARG JOBS=2
ENV CMAKE_TOOLCHAIN_FILE=/opt/riscv64-toolchain.cmake \
    CMAKE_BUILD_PARALLEL_LEVEL=${JOBS}

# _PYTHON_HOST_PLATFORM is set only here: it makes the wheel tag linux_riscv64.
# /build is a cache mount so an interrupted build resumes where it stopped.
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/build,id=duckdb-riscv64-build \
    _PYTHON_HOST_PLATFORM=linux-riscv64 \
    CC=riscv64-linux-gnu-gcc CXX=riscv64-linux-gnu-g++ \
    pip wheel ./duckdb --no-deps --no-build-isolation -w /out -v \
      -Ccmake.define.Python_INCLUDE_DIR=/opt/riscv64-python/include/python3.13 \
      -Ccmake.define.DUCKDB_EXPLICIT_PLATFORM=linux_riscv64 \
      "-Ccmake.define.CMAKE_CXX_STANDARD_LIBRARIES=-Wl,--exclude-libs,libatomic.a -Wl,--push-state,-Bstatic -latomic -Wl,--pop-state" \
      -Cbuild-dir=/build \
    && ls -la /out
# DUCKDB_EXPLICIT_PLATFORM: DuckDB labels every non-ARM 64-bit build as
#   linux_amd64, which would make it fetch amd64 extensions if loading were on.
# GCC 12 does not inline 1/2-byte atomics on RISC-V (GCC 13+ does), so they
#   come from libatomic. The target image has no libatomic1, so link the static
#   archive (it is position independent) into the module, at the END of the
#   link line, and keep its symbols private.

# Sanity: 64-bit RISC-V ELF, shared-lib deps, and no unresolved atomics.
RUN cd /tmp && python3 -m zipfile -e /out/*.whl w \
    && so=$(find w -name '_duckdb*.so') && echo "$so" \
    && riscv64-linux-gnu-readelf -h "$so" | grep -E 'Class|Machine' \
    && riscv64-linux-gnu-readelf -d "$so" | grep NEEDED \
    && if riscv64-linux-gnu-nm -D --undefined-only "$so" | grep -E ' U __atomic_'; then \
         echo "unresolved libatomic symbols" >&2; exit 1; fi

FROM scratch AS export
COPY --from=builder /out/ /
