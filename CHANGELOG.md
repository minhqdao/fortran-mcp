# Changelog

## 0.2.0

- Breaking: `--transport` is gone. `fortran-mcp` serves stdio and `fortran-mcp serve` serves
  Streamable HTTP.
- Breaking: bundle and catalog schema 2 replaces the per-bundle `bundle_version` with the release
  `data_version`, so a catalog and its bundles must record the same data version.
- Breaking: the core index is `fortran-mcp-core.db`. Installations made with 0.1.0 are not
  recognised; remove them with `fortran-mcp data remove semantic` and `fortran-mcp data remove
  core`, then let them download again.
- Added automatic data installation on first run when no data is present, downloading semantic
  data only when the configured provider needs it and the embedding runtime is available.
  `FORTRAN_MCP_AUTO_INSTALL` and `FORTRAN_MCP_CATALOG` control it.
- Added `fortran-mcp data install --bundle` to install a local or explicit-URL bundle without a
  catalog.
- Added `fortran-mcp data verify` detail and an actionable message when an installed manifest is
  invalid; `doctor` now summarises and points to `data verify`.
- Changed `fortran-mcp data remove` to run without a confirmation prompt.

## 0.1.0

First public release.

- Added the compact 23-source cited Fortran corpus and measured retrieval benchmark.
- Added lexical, optional semantic, and hybrid search providers.
- Added deterministic core and semantic bundles with verified catalog installation.
- Added first-run diagnostics, installed-client guidance, and a reviewed source synchronization
  workflow.
- Compacted low-information documentation sections and excluded a redundant generated keyword
  index, reducing chunk count by 28% while preserving the original benchmark passes.
- Expanded the retrieval suite with compiler-neutral modern-language cases and authority labels,
  and added reproducible leave-one-source-out contribution analysis.
