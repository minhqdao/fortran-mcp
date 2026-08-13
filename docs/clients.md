# Connect an MCP client

Build the local data before connecting a client:

```bash
uv sync
uv run fortran-mcp-ingest fpm-0.13.0-docs
uv run fortran-mcp-ingest stdlib-0.8.1-docs
uv run fortran-mcp-build fpm-0.13.0-docs
uv run fortran-mcp-build stdlib-0.8.1-docs
uv run fortran-mcp-index
```

Use absolute paths in client configuration. Replace `/absolute/path/to/fortran-mcp` below with
this repository's absolute path.

## Codex

Add the server from the command line:

```bash
codex mcp add fortran-docs -- uv --directory /absolute/path/to/fortran-mcp run fortran-mcp
```

Alternatively, add this to `~/.codex/config.toml` or a trusted project's `.codex/config.toml`:

```toml
[mcp_servers.fortran_docs]
command = "uv"
args = ["run", "fortran-mcp"]
cwd = "/absolute/path/to/fortran-mcp"
```

Restart the Codex client after changing the configuration. Use `/mcp` in the CLI to inspect the
connection.

## Claude Desktop and JSON-based clients

Add this entry to the client's MCP configuration:

```json
{
  "mcpServers": {
    "fortran-docs": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/fortran-mcp",
        "run",
        "fortran-mcp"
      ]
    }
  }
}
```

Completely restart the client after saving the configuration. The server communicates over
standard input and output, so an idle process is normal while the client is connected.

## Verify

Ask the client:

```text
How do I add OpenMP as an fpm dependency? Use the Fortran documentation server and cite the source.
```

The leading result should cite `Computing PI with OpenMP → Using OpenMP as a dependency` in the
published fpm documentation.
