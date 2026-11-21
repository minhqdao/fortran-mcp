# Docker

The repository `Dockerfile` builds an Ubuntu 26.04 LTS image that serves Fortran MCP with hybrid
search by default. The image contains the server, the semantic runtime, the
`BAAI/bge-small-en-v1.5` embedding model, and both data packages, so it needs no network access at
runtime. It runs as an unprivileged user.

## Build

```bash
docker build -t fortran-mcp .
```

By default the build installs the published core and semantic bundles from the latest data
release, verifying their checksums. Pin a specific release with
`--build-arg FORTRAN_MCP_CATALOG=https://github.com/minhqdao/fortran-mcp/releases/download/<tag>/catalog.json`.

To build both indexes from the pinned sources in `docs/sources.toml` instead, as the data release
workflow does:

```bash
docker build --build-arg FORTRAN_MCP_DATA=source -t fortran-mcp .
```

This downloads every reviewed source and embeds the corpus, so it takes several minutes. The
build compiles GNU Texinfo 7.3, verified by checksum, because the gfortran and GNU Make converters
require exactly that version and Ubuntu ships an older `makeinfo`. Set
`--build-arg FORTRAN_MCP_DATA_VERSION=YYYY.MM.N` to label the locally built bundles.

## Run over HTTP

```bash
docker run -d --name fortran-mcp -p 127.0.0.1:1957:1957 fortran-mcp
claude mcp add --scope user --transport http fortran-mcp http://localhost:1957/mcp
```

The HTTP transport has no authentication. Keep the port bound to localhost or put the container
behind a reverse proxy that provides TLS and access control.

DNS-rebinding protection accepts only `localhost` and `127.0.0.1` Host headers, on any port, and
rejects others with HTTP 421. To serve another hostname, replace the default command. This also
replaces the default hosts, so list every host you need:

```bash
docker run -d -p 1957:1957 fortran-mcp \
  fortran-mcp serve --host 0.0.0.0 --port 1957 \
  --allowed-host mcp.example.org --allowed-host 'localhost:*'
```

The health check probes port 1957 inside the container. If you change `--port`, the container
reports as unhealthy.

## Run over stdio

MCP clients can launch the container directly:

```bash
claude mcp add --scope user fortran-mcp -- \
  docker run -i --rm --network none fortran-mcp fortran-mcp
```

## Options

- Select another provider with `-e FORTRAN_MCP_SEARCH_PROVIDER=lexical` or `semantic`.
- For a read-only root filesystem, add `--read-only --tmpfs /tmp`. The embedding runtime needs a
  writable temporary directory.
- Run other commands with `docker run --rm fortran-mcp fortran-mcp doctor` or
  `fortran-mcp data verify`.

The data packages' license notices are in `/opt/fortran-mcp/data/licenses/`. Keep them with any
redistributed image.

## Test an image

```bash
FORTRAN_MCP_DOCKER_IMAGE=fortran-mcp uv run pytest tests/test_docker.py
```

These opt-in tests check unprivileged startup, data readiness, offline stdio search for each
provider on a read-only root, and HTTP search, hybrid abstention, and Host-header rejection.
Without `FORTRAN_MCP_DOCKER_IMAGE`, pytest skips them.
