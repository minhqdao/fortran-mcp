# Publishing

Before publishing, make sure CI is green.

## Fortran MCP Releases

Bump the version in `pyproject.toml` and `CHANGELOG.md`, commit, push to `main`,
and wait for CI. Then create and push a matching `v<version>` tag to trigger the
`Publish PyPI` workflow (`.github/workflows/publish-pypi.yml`).

## Data Bundle Releases

Trigger the `Publish Data` workflow (`.github/workflows/publish-data.yml`) with a
`data_version` in `YYYY.MM.N` format. It rebuilds the corpus from
`docs/sources.toml` and publishes both bundles.

See [Data bundle format](bundles.md) for the artifact contract.