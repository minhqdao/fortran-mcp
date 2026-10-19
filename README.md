# Fortran MCP

[![CI](https://github.com/minhqdao/fortran-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/minhqdao/fortran-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/fortran-mcp.svg)](https://pypi.org/project/fortran-mcp/)
[![MCP](https://img.shields.io/badge/MCP-2.0-2F4F8G?labelColor=1a1a2e&color=0f4c81)](https://spec.modelcontextprotocol.io/)
[![RAG](https://img.shields.io/badge/RAG-cited%20retrieval-0e7c7b)](https://github.com/minhqdao/fortran-mcp)
[![Search](https://img.shields.io/badge/search-lexical%20+%20semantic%20+%20hybrid-0f4c81)](https://github.com/minhqdao/fortran-mcp/blob/main/benchmarks/results/)
[![Sources](https://img.shields.io/badge/sources-23-c88603?logo=gitbook&logoColor=white)](https://github.com/minhqdao/fortran-mcp/blob/main/docs/sources.toml)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](https://github.com/minhqdao/fortran-mcp/blob/main/LICENSE)

Use Fortran MCP to improve AI-assisted Fortran development with cited documentation on language features, compiler behavior, build systems, and the wider ecosystem.

It supports lexical search (matching words), semantic search (matching meaning), and hybrid search (combining both), returning relevant passages with source attribution, version information, and links to the original documentation.

## Installation

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv tool install fortran-mcp
```

Semantic and hybrid search require additional dependencies:

```bash
uv tool install "fortran-mcp[semantic]"
```

Data bundles are installed automatically on first run. You can also install them beforehand to avoid an initial delay:

```bash
fortran-mcp data install core       # for lexical search
fortran-mcp data install semantic   # for semantic and hybrid search
```

Check installation:

```bash
fortran-mcp doctor
```

## Client Setup

<details>
<summary>Claude Code</summary>

Use lexical search (default):

```bash
claude mcp add --scope user fortran-mcp -- fortran-mcp
```

Use semantic search:

```bash
claude mcp add --scope user fortran-mcp --env FORTRAN_MCP_SEARCH_PROVIDER=semantic -- fortran-mcp
```

Use hybrid search:

```bash
claude mcp add --scope user fortran-mcp --env FORTRAN_MCP_SEARCH_PROVIDER=hybrid -- fortran-mcp
```

To change the search mode, remove the existing entry first:

```bash
claude mcp remove --scope user fortran-mcp
```

</details>

<details>
<summary>Codex</summary>

Use lexical search (default):

```bash
codex mcp add fortran-mcp -- fortran-mcp
```

Use semantic search:

```bash
codex mcp add fortran-mcp --env FORTRAN_MCP_SEARCH_PROVIDER=semantic -- fortran-mcp
```

Use hybrid search:

```bash
codex mcp add fortran-mcp --env FORTRAN_MCP_SEARCH_PROVIDER=hybrid -- fortran-mcp
```

</details>

<details>
<summary>OpenCode</summary>

Use lexical search (default):

```bash
opencode mcp add fortran-mcp --global -- fortran-mcp
```

Use semantic search:

```bash
opencode mcp add fortran-mcp --global --env FORTRAN_MCP_SEARCH_PROVIDER=semantic -- fortran-mcp
```

Use hybrid search:

```bash
opencode mcp add fortran-mcp --global --env FORTRAN_MCP_SEARCH_PROVIDER=hybrid -- fortran-mcp
```

</details>

## Command reference

| Command                               | Description                                                                                                                     |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `fortran-mcp`                         | Start the stdio MCP server.                                                                                                     |
| `fortran-mcp serve`                   | Start the HTTP server (`--host`, `--port`, `--path`, `--allowed-host`).                                                         |
| `fortran-mcp doctor`                  | Show configuration and installed data. Use `--json` for machine-readable output.                                                |
| `fortran-mcp data install <package>`  | Download and install `core` or `semantic` from the release catalog or a local bundle (`--catalog`, `--bundle`, `--data-dir`).   |
| `fortran-mcp data remove <package>`   | Remove an installed `core` or `semantic` package (`--data-dir`).                                                                |
| `fortran-mcp data verify`             | Verify installed data packages (`--data-dir`).                                                                                  |
| `fortran-mcp source list`             | List reviewed sources with versions and provenance. Use `--json` for machine-readable output.                                   |
| `fortran-mcp source sync <source>...` | Download reviewed sources and rebuild their chunks and lexical index. Accepts one or more source IDs or `--all` (`--data-dir`). |

## Development

```bash
git clone https://github.com/minhqdao/fortran-mcp.git
cd fortran-mcp
uv sync
uv run fortran-mcp
```

The server uses stdio by default. To test the Streamable HTTP transport, run:

```bash
uv run fortran-mcp serve
```

The endpoint is available at `http://127.0.0.1:1957/mcp`.

Run quality checks with:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

## Sources

Fortran MCP uses a curated collection of Fortran documentation, references,
examples, and tools. Each source is pinned to a specific revision and included
under its applicable license.

| Source | License |
| --- | --- |
| [Fortran Package Manager documentation website](https://github.com/fortran-lang/fpm-docs/tree/5097350c24ea7b5ceec233714f5a2604f79d0c02/pages) | MIT |
| [Fortran Standard Library specifications and guides](https://github.com/fortran-lang/stdlib/tree/v0.8.1/doc) | MIT |
| [GNU Fortran Compiler manual](https://gcc.gnu.org/git/?p=gcc.git;a=tree;f=gcc/fortran;hb=releases/gcc-16.2.0) | GFDL-1.3-or-later |
| [CMake documentation for Fortran projects](https://github.com/Kitware/CMake/tree/v4.4.0/Help) | BSD-3-Clause |
| [Fortran-lang intrinsic procedures reference](https://github.com/fortran-lang/webpage/tree/36d35714a4bc4e7d77183ecdfe09ed7107f3fff2/source/learn/intrinsics) | MIT AND GFDL-1.2-or-later |
| [Fortran-lang quickstart tutorial](https://github.com/fortran-lang/webpage/tree/36d35714a4bc4e7d77183ecdfe09ed7107f3fff2/source/learn/quickstart) | MIT |
| [Fortran-lang best practices](https://github.com/fortran-lang/webpage/tree/36d35714a4bc4e7d77183ecdfe09ed7107f3fff2/source/learn/best_practices) | MIT |
| [Fortran-lang object-oriented programming guide](https://github.com/fortran-lang/webpage/tree/36d35714a4bc4e7d77183ecdfe09ed7107f3fff2/source/learn/oop_features_in_fortran) | MIT |
| [Fortran-lang Fortran 95 language reference](https://github.com/fortran-lang/webpage/tree/36d35714a4bc4e7d77183ecdfe09ed7107f3fff2/source/learn/f95_features) | CC-BY-SA-4.0 |
| [Fortran-lang build, link, and distribution guide](https://github.com/fortran-lang/webpage/tree/36d35714a4bc4e7d77183ecdfe09ed7107f3fff2/source/learn/building_programs) | MIT |
| [Fortran-lang Python–Fortran Rosetta Stone](https://github.com/fortran-lang/webpage/blob/36d35714a4bc4e7d77183ecdfe09ed7107f3fff2/source/learn/rosetta_stone.md) | MIT |
| [Fortran-lang floating-point comparison guide](https://github.com/fortran-lang/webpage/blob/36d35714a4bc4e7d77183ecdfe09ed7107f3fff2/source/learn/Floating_Point_Numbers_comparison.md) | MIT |
| [OpenMP 6.0.1 Fortran examples](https://github.com/OpenMP/Examples/tree/v6.0.1) | OpenMP-Examples |
| [Fortran-focused GNU Make 4.4.1 manual extracts](https://git.savannah.gnu.org/cgit/make.git/tree/doc/make.texi?h=4.4.1) | GFDL-1.3-or-later |
| [NumPy 2.5.2 F2PY user guide and reference](https://github.com/numpy/numpy/tree/v2.5.2/doc/source/f2py) | BSD-3-Clause |
| [Fypp 3.2 documentation](https://github.com/aradi/fypp/tree/b8dd58b946a0165a95f5630bfa8b45b1509d0dac/docs) | BSD-2-Clause |
| [Open MPI 5.0.10 Fortran routine reference](https://github.com/open-mpi/ompi/tree/v5.0.10/docs/man-openmpi/man3) | BSD-3-Clause-Open-MPI |
| [Fortitude 0.9.2 linter rules and usage reference](https://github.com/PlasmaFAIR/fortitude/tree/eb0f0c464859c6a6c4f91e4f97e36d26ddcb6947/docs) | MIT |
| [Selected Codee Open Catalog Fortran safety and performance guidelines](https://github.com/codee-com/open-catalog/tree/12c507e3f4136093139c8b004233b6001ed6963e/Checks) | Apache-2.0 |
| [Old programming idioms explained](https://github.com/arjenmarkus/old-programming-idioms/tree/bcb10375153bcdd104f247d23eb1f32ee6c1424d/src) | MIT |
| [PRIMA behavior-preserving Fortran modernization case study](https://github.com/libprima/prima/blob/1d76fb88aeffb427cd17ed1e9d0d3b34f414913f/README.md) | BSD-3-Clause |
| [Beliavsky list of fpm-compatible Fortran projects](https://github.com/Beliavsky/Fortran-packages-list/tree/13f715138fd1640b44d4d13ef4818f7d8b9340e0) | MIT |
| [Fortran-lang package index additions](https://github.com/fortran-lang/webpage/blob/36d35714a4bc4e7d77183ecdfe09ed7107f3fff2/data/package_index.yml) | MIT |

New sources should address gaps in coverage or improve retrieval quality on
realistic benchmark questions. They must be legally redistributable and justify
their storage costs and impact on search results.

Public availability alone does not grant redistribution rights, particularly
for standards, books, and vendor manuals.

The source inventory is maintained in [`docs/sources.toml`](docs/sources.toml).

## Publishing

### Fortran MCP Releases

Before publishing `fortran-mcp` to PyPI, bump the version in `pyproject.toml` and update `CHANGELOG.md`. Commit, push to `main`, and wait for CI to turn green. Then create and push a matching `v<version>` tag to trigger the `Publish PyPI` workflow (`.github/workflows/publish-pypi.yml`) which builds and publishes the `fortran-mcp` package.

### Data Bundle Releases

To publish data packages to GitHub Releases, make sure all commits are pushed to `main` and CI is
green. Then manually trigger the `Publish Data` GitHub Actions workflow
(`.github/workflows/publish-data.yml`) and enter a `data_version` in the
`YYYY.MM.N` format, where `N` is a sequential number for releases within the same
month. The workflow rebuilds the corpus from `docs/sources.toml` and publishes both
the `core` and `semantic` bundles under the same version.

## License

The server software is available under the
[MIT License](LICENSE).

[Sources](docs/sources.toml) retain their
original copyrights and [licenses](docs/licenses/).
