# Source contribution report

Measured 2026-08-22 against the 134-case lexical suite after lowering the rendered chunk-size cap
to 1,600 characters with expansion-aware literal-include sizing and fence-preserving splits. The
complete corpus contains 5,877 chunks, produces a 12,464,128-byte
installed lexical index and a 3,700,642-byte compressed core bundle, and passes
116 cases. Baseline hit@10 is 0.935, MRR is 0.776,
and mean local query latency was 9.23 ms.

The reproducible command is:

```bash
uv run fortran-mcp-contributions --data-dir data \
  --output benchmarks/results/source-contributions.json
```

The JSON report is intentionally generated on demand: it includes all case IDs and exact floating
point timings. This reviewed summary records the decisions and stable measurements without checking
in machine-specific timing noise.

`Core bytes` is the deterministic compressed core-bundle reduction when the source and its license
notice are omitted. `Index bytes` is the installed SQLite reduction. One semantic vector is stored
per chunk. `Unique` counts cases lost on omission whose matching baseline passage came from that
source. `Lost` also includes indirect cutoff/ranking losses. `Recovered` counts previously failing
cases that pass without the source. Rank changes count cases that still pass but move within the top
ten. Latency is the mean with that source omitted and is machine-specific.

| Source | Chunks/vectors | Core bytes | Index bytes | Unique | Lost | Recovered | Rank worse | Rank better | Omitted ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `beliavsky-fortran-packages-list` | 90 | 105650 | 278528 | 8 | 8 | 1 | 4 | 0 | 7.072 |
| `cmake-4.4.0-fortran-docs` | 117 | 77629 | 245760 | 5 | 5 | 0 | 0 | 1 | 7.017 |
| `codee-open-catalog-fortran-subset` | 43 | 29457 | 98304 | 5 | 5 | 0 | 0 | 1 | 6.903 |
| `fortitude-0.9.2-reference` | 488 | 186128 | 647168 | 8 | 8 | 0 | 1 | 5 | 6.762 |
| `fortran-lang-best-practices` | 42 | 40454 | 114688 | 1 | 1 | 1 | 0 | 0 | 6.946 |
| `fortran-lang-build-and-link-guide` | 59 | 76693 | 208896 | 1 | 1 | 1 | 2 | 1 | 6.942 |
| `fortran-lang-floating-point-guide` | 6 | 2291 | 8192 | 1 | 1 | 0 | 0 | 0 | 7.069 |
| `fortran-lang-fortran-95-reference` | 87 | 76870 | 217088 | 1 | 1 | 0 | 1 | 0 | 7.604 |
| `fortran-lang-intrinsics-reference` | 533 | 475914 | 1556480 | 3 | 3 | 1 | 4 | 4 | 6.357 |
| `fortran-lang-object-oriented-programming` | 63 | 72843 | 208896 | 1 | 1 | 0 | 2 | 0 | 6.898 |
| `fortran-lang-package-index-additions` | 34 | 42319 | 114688 | 7 | 7 | 1 | 3 | 4 | 6.969 |
| `fortran-lang-python-rosetta-stone` | 29 | 28885 | 81920 | 1 | 1 | 1 | 0 | 0 | 7.011 |
| `fortran-lang-quickstart` | 51 | 50894 | 139264 | 1 | 1 | 1 | 2 | 1 | 6.968 |
| `fpm-0.13.0-docs` | 252 | 152322 | 454656 | 8 | 8 | 1 | 2 | 1 | 6.856 |
| `fypp-3.2-manual` | 75 | 62006 | 184320 | 5 | 5 | 1 | 0 | 1 | 6.934 |
| `gfortran-16.2.0-manual` | 817 | 687315 | 2252800 | 8 | 9 | 1 | 6 | 5 | 6.001 |
| `gnu-make-4.4.1-build-reference` | 64 | 73497 | 217088 | 5 | 5 | 0 | 2 | 0 | 6.951 |
| `numpy-2.5.2-f2py-docs` | 149 | 144653 | 405504 | 5 | 5 | 1 | 1 | 1 | 6.730 |
| `old-fortran-programming-idioms` | 88 | 103373 | 286720 | 2 | 2 | 1 | 1 | 5 | 6.931 |
| `openmp-6.0.1-fortran-examples` | 571 | 532383 | 1691648 | 5 | 5 | 1 | 3 | 7 | 6.443 |
| `openmpi-5.0.10-fortran-reference` | 362 | 178568 | 712704 | 10 | 10 | 1 | 1 | 1 | 6.618 |
| `prima-modernization-case-study` | 3 | 4802 | 8192 | 2 | 2 | 0 | 0 | 0 | 7.047 |
| `stdlib-0.8.1-docs` | 1854 | 566077 | 2342912 | 8 | 8 | 1 | 6 | 6 | 5.633 |

## Unique cases

- `beliavsky-fortran-packages-list`: `ecosystem-automatic-differentiation`,
  `ecosystem-command-line-parser`,
  `ecosystem-date-time`,
  `ecosystem-json-parser`,
  `ecosystem-matplotlib-plotting`,
  `ecosystem-ode-solver`,
  `ecosystem-sqlite-bindings`,
  `ecosystem-unit-testing`
- `cmake-4.4.0-fortran-docs`: `cmake-check-fortran-source`,
  `cmake-fortran-c-interface`,
  `cmake-fortran-preprocess-source`,
  `cmake-openmp-fortran`,
  `cmake-source-filter`
- `codee-open-catalog-fortran-subset`: `codee-array-bounds`,
  `codee-conditional-initialization`,
  `codee-loop-unswitching`,
  `codee-uninitialized-output`,
  `codee-uninitialized-variable`
- `fortitude-0.9.2-reference`: `fortitude-common-block`,
  `fortitude-config-discovery`,
  `fortitude-fixed-form`,
  `fortitude-implicit-external`,
  `fortitude-invalid-tab`,
  `fortitude-mpi-module`,
  `fortitude-old-array-literal`,
  `fortitude-target-standard`
- `fortran-lang-best-practices`: `fortran-lang-allocatable-practice`
- `fortran-lang-build-and-link-guide`: `fortran-lang-link-objects`
- `fortran-lang-floating-point-guide`: `fortran-lang-floating-tolerance`
- `fortran-lang-fortran-95-reference`: `fortran-lang-assumed-shape`
- `fortran-lang-intrinsics-reference`: `fortran-lang-intrinsic-c-pointer`,
  `fortran-lang-intrinsics-source-filter`,
  `fortran-lang-move-alloc`
- `fortran-lang-object-oriented-programming`: `fortran-lang-type-extension`
- `fortran-lang-package-index-additions`: `ecosystem-automatic-differentiation-tool`,
  `ecosystem-design-patterns`,
  `ecosystem-netcdf-interface`,
  `ecosystem-parquet-io`,
  `ecosystem-pytorch-interface`,
  `ecosystem-source-formatter`,
  `ecosystem-yaml-parser`
- `fortran-lang-python-rosetta-stone`: `fortran-lang-python-array-indexing`
- `fortran-lang-quickstart`: `fortran-lang-do-concurrent`
- `fpm-0.13.0-docs`: `fpm-clean-output`,
  `fpm-compile-commands`,
  `fpm-create-project`,
  `fpm-features-profiles`,
  `fpm-git-dependency`,
  `fpm-openmp-dependency`,
  `fpm-preprocessor-configuration`,
  `fpm-source-filter`
- `fypp-3.2-manual`: `fypp-command-line`,
  `fypp-include-path`,
  `fypp-line-folding-comments`,
  `fypp-line-number-markers`,
  `fypp-template-loop`
- `gfortran-16.2.0-manual`: `gfortran-argument-mismatch`,
  `gfortran-c-pointer`,
  `gfortran-coarray-events`,
  `gfortran-convert-unit`,
  `gfortran-dec-structures`,
  `gfortran-preprocessor-include`,
  `gfortran-source-filter`,
  `legacy-dec-structure-derived-type`
- `gnu-make-4.4.1-build-reference`: `gnu-make-automatic-variables`,
  `gnu-make-disable-parallel`,
  `gnu-make-fortran-implicit-rule`,
  `gnu-make-missing-separator`,
  `gnu-make-pattern-rule`
- `numpy-2.5.2-f2py-docs`: `f2py-array-copy`,
  `f2py-callback`,
  `f2py-meson-build`,
  `f2py-quick-wrap`,
  `f2py-signature-intent`
- `old-fortran-programming-idioms`: `legacy-alternate-return`,
  `legacy-assigned-goto`
- `openmp-6.0.1-fortran-examples`: `openmp-atomic-capture-fortran`,
  `openmp-collapse-fortran`,
  `openmp-fixed-form-sentinel`,
  `openmp-target-map-fortran`,
  `openmp-task-depend-fortran`
- `openmpi-5.0.10-fortran-reference`: `openmpi-allreduce`,
  `openmpi-cartesian-shift`,
  `openmpi-derived-struct`,
  `openmpi-f08-hello`,
  `openmpi-file-view`,
  `openmpi-legacy-mpifh`,
  `openmpi-legacy-use-mpi`,
  `openmpi-nonblocking-send`,
  `openmpi-rma-flush`,
  `openmpi-source-filter`
- `prima-modernization-case-study`: `legacy-differential-testing`,
  `legacy-incremental-migration`
- `stdlib-0.8.1-docs`: `stdlib-dynamic-text`,
  `stdlib-hashmap`,
  `stdlib-linear-system`,
  `stdlib-normal-random`,
  `stdlib-quadrature`,
  `stdlib-source-filter`,
  `stdlib-string-number`,
  `stdlib-string-type`

## Decision

Keep all 23 sources in the first core. Every source owns at least one matching benchmark answer,
and most own several. Small sources such as the floating-point guide and PRIMA case study deliver a
unique pass for negligible byte cost. The two largest installed-index contributors, gfortran and
stdlib, also supply broad unique coverage.

The first run placed `language-coarray-teams` just outside the lexical top ten and recovered it after
several unrelated omissions. Removing gfortran's generated, link-only keyword index eliminated 114
redundant chunks and moved the actual `GET_TEAM` explanation to rank seven without a regression.
This is a general boilerplate-ranking improvement, not query-specific boosting. The report also
shows that source-neutral cases can be lost through corpus-wide ranking interaction; therefore
`unique_passes` is a more defensible content-attribution measure than raw losses alone.

The 2026-08-22 re-measure lowered the rendered chunk-size cap from 4,000 to 1,600 characters.
Lexical retrieval traded two marginal passes (`language-coarray-teams`, `cmake-fortran-modules`) and
1.6 points of hit@1; semantic and hybrid retrieval improved materially because chunks no longer
exceed the embedding model's 512-token budget, and the hybrid abstention threshold was reswept from
0.785 to 0.79 to restore negative-query accuracy under the new score distribution.
