# syntax=docker/dockerfile:1
#
# Fortran MCP server with lexical, semantic, and hybrid search (hybrid by default).
#
#   docker build -t fortran-mcp .
#   docker run --rm -p 127.0.0.1:1957:1957 fortran-mcp
#
# See docs/docker.md for data modes, stdio use, and accepted Host headers.

# Ubuntu 26.04 LTS is ubuntu:latest; pinned for reproducible builds.
ARG UBUNTU_VERSION=26.04
ARG UV_VERSION=0.13.9
# release: install the published, checksum-verified core and semantic bundles.
# source:  rebuild both indexes from the pinned sources in docs/sources.toml.
ARG FORTRAN_MCP_DATA=release

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM ubuntu:${UBUNTU_VERSION} AS base
ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates python3 tini \
    && rm -rf /var/lib/apt/lists/*

# The gfortran and GNU Make converters require exactly GNU Texinfo 7.3, but Ubuntu
# ships an older makeinfo. Build the release tarball, pinned by its SHA-256 (the
# upstream GPG signature from the Texinfo maintainer was checked when pinning).
# libcrypt-dev lets the Perl XS extensions build, as in the data release workflow.
FROM base AS texinfo
ARG TEXINFO_VERSION=7.3
ARG TEXINFO_SHA256=51f74eb0f51cfa9873b85264dfdd5d46e8957ec95b88f0fb762f63d9e164c72e
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl gcc libc6-dev libcrypt-dev libncurses-dev make perl xz-utils \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /tmp/texinfo
RUN curl -fsSLo texinfo.tar.xz \
        "https://ftp.gnu.org/gnu/texinfo/texinfo-${TEXINFO_VERSION}.tar.xz" \
    && echo "${TEXINFO_SHA256}  texinfo.tar.xz" | sha256sum -c - \
    && tar -xf texinfo.tar.xz --strip-components=1 \
    && ./configure --prefix=/opt/texinfo --disable-nls \
    && make -j"$(nproc)" \
    && make install \
    && /opt/texinfo/bin/makeinfo --version | head -n 1 | grep -Fx "texi2any (GNU texinfo) ${TEXINFO_VERSION}"

# Lean server environment: the package and its semantic extra, plus the embedding model.
FROM base AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON=/usr/bin/python3 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/fortran-mcp/venv \
    FASTEMBED_CACHE_PATH=/opt/fortran-mcp/models \
    PATH=/opt/fortran-mcp/venv/bin:$PATH
WORKDIR /src
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --locked --no-dev --no-install-project --extra semantic
# Download the embedding model before copying the sources so code changes reuse this layer.
ARG EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
RUN python -c "import sys; from fastembed import TextEmbedding; TextEmbedding(sys.argv[1])" \
        "${EMBEDDING_MODEL}"
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
COPY docs/sources.toml ./docs/sources.toml
COPY docs/licenses ./docs/licenses
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --extra semantic
# Fail the build if the server's default model differs from the baked-in one.
RUN HF_HUB_OFFLINE=1 python -c \
        "from fortran_mcp.semantic import FastEmbedModel; FastEmbedModel().embed_query('fortran')" \
    && chmod -R a+rX,go-w /opt/fortran-mcp

FROM builder AS data-release
ARG FORTRAN_MCP_CATALOG=https://github.com/minhqdao/fortran-mcp/releases/latest/download/catalog.json
RUN fortran-mcp data install core --catalog "${FORTRAN_MCP_CATALOG}" --data-dir /opt/fortran-mcp/data \
    && fortran-mcp data install semantic --catalog "${FORTRAN_MCP_CATALOG}" \
        --data-dir /opt/fortran-mcp/data \
    && fortran-mcp data verify --data-dir /opt/fortran-mcp/data \
    && chmod -R a+rX,go-w /opt/fortran-mcp/data

# Mirrors the data release workflow: sync every reviewed source, build both indexes,
# package them as bundles with their license notices, and install the bundles.
FROM builder AS data-source
ARG FORTRAN_MCP_DATA_VERSION=0000.00.0
RUN apt-get update \
    && apt-get install -y --no-install-recommends perl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=texinfo /opt/texinfo /opt/texinfo
# Converters need the ingest extra; keep it out of the runtime environment.
RUN --mount=type=cache,target=/root/.cache/uv \
    UV_PROJECT_ENVIRONMENT=/opt/ingest \
    uv sync --locked --no-dev --no-editable --extra ingest --extra semantic
ENV PATH=/opt/texinfo/bin:$PATH \
    FORTRAN_MCP_DATA_DIR=/work/data
RUN set -eux; \
    /opt/ingest/bin/fortran-mcp source sync --all --data-dir /work/data; \
    /opt/ingest/bin/fortran-mcp-semantic-index; \
    for role in core semantic; do \
        /opt/ingest/bin/fortran-mcp-bundle build "$role" \
            --output "/work/fortran-mcp-$role.zip" --data-dir /work/data \
            --license-dir docs/licenses --data-version "${FORTRAN_MCP_DATA_VERSION}"; \
        fortran-mcp data install "$role" --bundle "/work/fortran-mcp-$role.zip" \
            --data-dir /opt/fortran-mcp/data; \
    done; \
    fortran-mcp data verify --data-dir /opt/fortran-mcp/data; \
    chmod -R a+rX,go-w /opt/fortran-mcp/data

FROM data-${FORTRAN_MCP_DATA} AS data

FROM base AS runtime
LABEL org.opencontainers.image.title="Fortran MCP" \
      org.opencontainers.image.description="MCP server for cited Fortran documentation" \
      org.opencontainers.image.source="https://github.com/minhqdao/fortran-mcp" \
      org.opencontainers.image.licenses="MIT"
RUN groupadd --system fortran-mcp \
    && useradd --system --gid fortran-mcp --no-create-home --home-dir /nonexistent \
        --shell /usr/sbin/nologin fortran-mcp
COPY --from=builder /opt/fortran-mcp/venv /opt/fortran-mcp/venv
COPY --from=builder /opt/fortran-mcp/models /opt/fortran-mcp/models
COPY --from=data /opt/fortran-mcp/data /opt/fortran-mcp/data
COPY LICENSE /usr/share/doc/fortran-mcp/LICENSE
ENV PATH=/opt/fortran-mcp/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    FORTRAN_MCP_DATA_DIR=/opt/fortran-mcp/data \
    FORTRAN_MCP_SEARCH_PROVIDER=hybrid \
    FASTEMBED_CACHE_PATH=/opt/fortran-mcp/models \
    HF_HUB_OFFLINE=1
USER fortran-mcp
WORKDIR /tmp
EXPOSE 1957
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --start-interval=2s --retries=3 \
    CMD ["python3", "-c", "import socket; socket.create_connection(('127.0.0.1', 1957), 3).close()"]
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["fortran-mcp", "serve", "--host", "0.0.0.0", "--port", "1957", \
     "--allowed-host", "localhost:*", "--allowed-host", "127.0.0.1:*"]
