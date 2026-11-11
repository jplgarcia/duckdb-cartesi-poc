# syntax=docker.io/docker/dockerfile:1
# Renders demo/demo.cast to GIF (agg) and MP4 (ffmpeg) without installing
# anything on the host.
FROM debian:bookworm-slim
ARG TARGETARCH
ARG AGG_VERSION=v1.9.0
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl ffmpeg fonts-dejavu-core fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*
RUN case "$TARGETARCH" in \
      arm64) a=aarch64-unknown-linux-gnu ;; \
      amd64) a=x86_64-unknown-linux-gnu ;; \
      *) echo "unsupported $TARGETARCH" >&2; exit 1 ;; \
    esac \
    && curl -fsSL -o /usr/local/bin/agg "https://github.com/asciinema/agg/releases/download/${AGG_VERSION}/agg-$a" \
    && chmod +x /usr/local/bin/agg && agg --version
WORKDIR /work
