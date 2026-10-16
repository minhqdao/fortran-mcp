# Data bundle format

Fortran MCP data bundles are deterministic ZIP archives rooted at `fortran-mcp-bundle/`.

```text
fortran-mcp-bundle/
├── manifest.json
├── indexes/
│   └── fortran-mcp.db
└── licenses/
    └── <source-id>.txt
```

Semantic bundles contain `indexes/fortran-mcp-semantic.db` instead. They do not duplicate source
licenses because they require a compatible core bundle.

The versioned manifest records:

- bundle identity, role, data version, and compatible server versions;
- source IDs, revisions, document types, authority, topics, compiler and Fortran-version
  applicability, and licenses;
- every payload path, byte size, and SHA-256 checksum;
- the embedding model and dimensions for semantic bundles; and
- the exact lexical-index checksum required by a semantic bundle.

Paths use POSIX separators and are relative to the bundle root. Entries are ordered by path, use a
fixed ZIP timestamp and permissions, and contain no build timestamp or machine-specific metadata.
Given identical input files and tool versions, bundle bytes are identical.

`core` is the default distribution role. `semantic` is an optional companion and cannot be paired
with a core bundle whose lexical-index checksum differs from its declared requirement. Future
optional source bundles will use a later manifest schema once their composition rules are defined.

Bundle verification rejects invalid manifests, unsafe or duplicate paths, undeclared files, missing
files, size mismatches, and checksum mismatches. For v0.1, publisher authenticity relies on HTTPS
delivery from the project's GitHub Release location. Catalog and bundle assets must be uploaded to a
draft release and the release published only after every asset is present. Signing can be added later
without changing the bundle's internal integrity checks.

Installation accepts local files and explicit HTTPS URLs. It verifies an archive before extraction,
checks the manifest's server-version constraint, writes payloads through temporary files, and records
the installed manifest last. Semantic installation additionally checks its required lexical-index
checksum against the installed core manifest. The default destination is the platform's per-user
application-data directory; `FORTRAN_MCP_DATA_DIR` overrides it.

## Catalog format

A catalog is a deterministic JSON discovery document for one data release. Its `data_version` uses
`YYYY.MM.N`, independently of the Python server version. Each role appears at most once and records
the relative bundle path, compressed byte size, whole-archive SHA-256 checksum, and bundle ID.

Catalog paths are relative to the catalog file and cannot escape its directory. The normal data
command loads `catalog.json` from the latest GitHub Release over HTTPS; `--catalog` overrides it with
another HTTPS URL or a local path. Remote paths resolve against the requested catalog URL; this lets
GitHub redirect each named release asset independently through its download service.
Installation verifies the advertised archive size and whole-archive SHA-256, then verifies that the
bundle ID matches the internal manifest before invoking normal installation.
