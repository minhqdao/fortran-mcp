# Connect an MCP client

Install the published server and compact core data before connecting a client:

```bash
uv tool install fortran-mcp
fortran-mcp data install core
fortran-mcp data status
```

The server uses stdio and needs no working-directory setting.
If a graphical client cannot find the command, run `command -v fortran-mcp` and use that absolute
path as the configured `command`; graphical applications do not always inherit the shell's `PATH`.

## Codex

Add the server from the command line:

```bash
codex mcp add fortran-docs -- fortran-mcp
```

Alternatively, add this to `~/.codex/config.toml` or a trusted project's `.codex/config.toml`:

```toml
[mcp_servers.fortran_docs]
command = "fortran-mcp"
```

Restart the Codex client after changing the configuration. Use `/mcp` in the CLI to inspect the
connection.

## Claude Desktop and JSON-based clients

Add this entry to the client's MCP configuration:

```json
{
  "mcpServers": {
    "fortran-docs": {
      "command": "fortran-mcp"
    }
  }
}
```

Completely restart the client after saving the configuration. The server communicates over
standard input and output, so an idle process is normal while the client is connected.

Set `FORTRAN_MCP_DATA_DIR` in the client's server environment only when data was installed outside
the platform default directory.

## Local Streamable HTTP

For transport testing, start the same server over HTTP:

```bash
FORTRAN_MCP_DATA_DIR=/absolute/path/to/fortran-mcp/data \
  uv --directory /absolute/path/to/fortran-mcp run fortran-mcp \
  --transport streamable-http
```

Connect an HTTP-capable MCP client to `http://127.0.0.1:1957/mcp`. Use `--host`, `--port`, and
`--path` to change the listener. DNS-rebinding protection is enabled; repeat `--allowed-host` to
declare accepted Host headers when the externally visible host differs from the bind address.
This development listener does not configure TLS or authentication and should not be exposed to an
untrusted network directly.

## Verify

Ask the client:

```text
How do I add OpenMP as an fpm dependency? Use the Fortran documentation server and cite the source.
```

The leading result should cite `Computing PI with OpenMP → Using OpenMP as a dependency` in the
published fpm documentation.
