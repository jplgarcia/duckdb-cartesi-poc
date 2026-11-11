# syntax=docker.io/docker/dockerfile:1
#
# Unit-test image: same riscv64 base as the Cartesi Machine, same offline
# install of the cross-compiled DuckDB wheel. Runs under QEMU on x86/arm hosts.
# Build context: repository root.

FROM --platform=linux/riscv64 cartesi/python:3.13.2-slim-noble

WORKDIR /app
COPY requirements.txt .
COPY riscv-wheel-index/ /opt/riscv-wheel-index/
RUN pip install --no-cache --root-user-action=ignore \
      --no-index --find-links=/opt/riscv-wheel-index/wheels/cp313/duckdb \
      -r requirements.txt
# Test-only deps are pure Python, so PyPI is fine here (never in the dapp image).
COPY tests/requirements.txt tests/requirements.txt
RUN pip install --no-cache --root-user-action=ignore -r tests/requirements.txt

COPY dapp.py .
COPY tests/ tests/
ENV PYTHONDONTWRITEBYTECODE=1
CMD ["python3", "-m", "pytest", "-p", "no:cacheprovider", "-v", "tests/"]
