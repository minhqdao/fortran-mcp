# Security policy

The latest released version receives security fixes. Before the first public release, report issues
against the current `main` branch.

For vulnerabilities involving downloads, archive extraction, catalog or bundle verification, path
handling, subprocess execution, or the HTTP transport, use GitHub's private vulnerability reporting
on the repository Security page. If private reporting is unavailable, open a non-sensitive issue
asking the maintainer for a private contact channel; do not include exploit details in the issue.

Ordinary bugs, documentation problems, and retrieval-quality issues can use the public issue
tracker. Include the `fortran-mcp doctor --json` output when it is relevant, after removing any local
paths you do not want to share.
