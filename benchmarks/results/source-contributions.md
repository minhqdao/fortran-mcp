# Source contribution report

Measured 2026-08-20 against the 134-case lexical suite after structural metadata merging. The
complete corpus contains 4,589 chunks, produces an 11,673,600-byte installed lexical index and a
3,547,754-byte compressed core bundle, and passes 118 cases. Baseline hit@10 is 0.952, MRR is 0.789,
and mean local query latency was 7.24 ms.

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
| `beliavsky-fortran-packages-list` | 59 | 99064 | 249856 | 8 | 8 | 0 | 1 | 0 | 6.492 |
| `cmake-4.4.0-fortran-docs` | 94 | 74084 | 237568 | 6 | 6 | 0 | 0 | 1 | 6.067 |
| `codee-open-catalog-fortran-subset` | 35 | 31592 | 81920 | 5 | 5 | 0 | 0 | 1 | 5.900 |
| `fortitude-0.9.2-reference` | 470 | 184017 | 643072 | 8 | 8 | 0 | 3 | 4 | 5.612 |
| `fortran-lang-best-practices` | 25 | 40871 | 102400 | 1 | 1 | 0 | 1 | 0 | 5.984 |
| `fortran-lang-build-and-link-guide` | 30 | 74131 | 184320 | 1 | 1 | 0 | 1 | 2 | 5.833 |
| `fortran-lang-floating-point-guide` | 6 | 4150 | 4096 | 1 | 1 | 0 | 0 | 0 | 5.883 |
| `fortran-lang-fortran-95-reference` | 73 | 75194 | 204800 | 1 | 1 | 0 | 2 | 2 | 5.859 |
| `fortran-lang-intrinsics-reference` | 272 | 429202 | 1417216 | 3 | 3 | 0 | 2 | 6 | 5.394 |
| `fortran-lang-object-oriented-programming` | 35 | 70636 | 180224 | 1 | 1 | 0 | 2 | 0 | 5.975 |
| `fortran-lang-package-index-additions` | 19 | 40852 | 94208 | 7 | 7 | 0 | 0 | 3 | 5.892 |
| `fortran-lang-python-rosetta-stone` | 15 | 25286 | 69632 | 1 | 1 | 0 | 0 | 1 | 5.922 |
| `fortran-lang-quickstart` | 39 | 48115 | 118784 | 1 | 1 | 0 | 2 | 1 | 5.855 |
| `fpm-0.13.0-docs` | 229 | 145256 | 446464 | 8 | 8 | 0 | 2 | 0 | 5.813 |
| `fypp-3.2-manual` | 52 | 61122 | 163840 | 5 | 5 | 0 | 0 | 3 | 5.809 |
| `gfortran-16.2.0-manual` | 557 | 685926 | 2113536 | 9 | 9 | 0 | 3 | 9 | 5.009 |
| `gnu-make-4.4.1-build-reference` | 29 | 69832 | 196608 | 5 | 5 | 0 | 2 | 2 | 5.840 |
| `numpy-2.5.2-f2py-docs` | 103 | 137227 | 376832 | 5 | 5 | 0 | 1 | 3 | 5.748 |
| `old-fortran-programming-idioms` | 58 | 96839 | 270336 | 2 | 2 | 0 | 2 | 5 | 5.810 |
| `openmp-6.0.1-fortran-examples` | 269 | 480181 | 1433600 | 5 | 5 | 0 | 2 | 7 | 5.329 |
| `openmpi-5.0.10-fortran-reference` | 323 | 171822 | 708608 | 10 | 10 | 0 | 2 | 1 | 5.710 |
| `prima-modernization-case-study` | 3 | 5070 | 4096 | 1 | 1 | 0 | 1 | 0 | 6.040 |
| `stdlib-0.8.1-docs` | 1794 | 553812 | 2310144 | 8 | 9 | 0 | 7 | 5 | 4.711 |

## Unique cases

- `beliavsky-fortran-packages-list`: `ecosystem-automatic-differentiation`,
  `ecosystem-command-line-parser`, `ecosystem-date-time`, `ecosystem-json-parser`,
  `ecosystem-matplotlib-plotting`, `ecosystem-ode-solver`, `ecosystem-sqlite-bindings`,
  `ecosystem-unit-testing`
- `cmake-4.4.0-fortran-docs`: `cmake-check-fortran-source`, `cmake-fortran-c-interface`,
  `cmake-fortran-modules`, `cmake-fortran-preprocess-source`, `cmake-openmp-fortran`,
  `cmake-source-filter`
- `codee-open-catalog-fortran-subset`: `codee-array-bounds`,
  `codee-conditional-initialization`, `codee-loop-unswitching`, `codee-uninitialized-output`,
  `codee-uninitialized-variable`
- `fortitude-0.9.2-reference`: `fortitude-common-block`, `fortitude-config-discovery`,
  `fortitude-fixed-form`, `fortitude-implicit-external`, `fortitude-invalid-tab`,
  `fortitude-mpi-module`, `fortitude-old-array-literal`, `fortitude-target-standard`
- `fortran-lang-best-practices`: `fortran-lang-allocatable-practice`
- `fortran-lang-build-and-link-guide`: `fortran-lang-link-objects`
- `fortran-lang-floating-point-guide`: `fortran-lang-floating-tolerance`
- `fortran-lang-fortran-95-reference`: `fortran-lang-assumed-shape`
- `fortran-lang-intrinsics-reference`: `fortran-lang-intrinsic-c-pointer`,
  `fortran-lang-intrinsics-source-filter`, `fortran-lang-move-alloc`
- `fortran-lang-object-oriented-programming`: `fortran-lang-type-extension`
- `fortran-lang-package-index-additions`: `ecosystem-automatic-differentiation-tool`,
  `ecosystem-design-patterns`, `ecosystem-netcdf-interface`, `ecosystem-parquet-io`,
  `ecosystem-pytorch-interface`, `ecosystem-source-formatter`, `ecosystem-yaml-parser`
- `fortran-lang-python-rosetta-stone`: `fortran-lang-python-array-indexing`
- `fortran-lang-quickstart`: `fortran-lang-do-concurrent`
- `fpm-0.13.0-docs`: `fpm-clean-output`, `fpm-compile-commands`, `fpm-create-project`,
  `fpm-features-profiles`, `fpm-git-dependency`, `fpm-openmp-dependency`,
  `fpm-preprocessor-configuration`, `fpm-source-filter`
- `fypp-3.2-manual`: `fypp-command-line`, `fypp-include-path`,
  `fypp-line-folding-comments`, `fypp-line-number-markers`, `fypp-template-loop`
- `gfortran-16.2.0-manual`: `gfortran-argument-mismatch`, `gfortran-c-pointer`,
  `gfortran-coarray-events`, `gfortran-convert-unit`, `gfortran-dec-structures`,
  `gfortran-preprocessor-include`, `gfortran-source-filter`, `language-coarray-teams`,
  `legacy-dec-structure-derived-type`
- `gnu-make-4.4.1-build-reference`: `gnu-make-automatic-variables`,
  `gnu-make-disable-parallel`, `gnu-make-fortran-implicit-rule`, `gnu-make-missing-separator`,
  `gnu-make-pattern-rule`
- `numpy-2.5.2-f2py-docs`: `f2py-array-copy`, `f2py-callback`, `f2py-meson-build`,
  `f2py-quick-wrap`, `f2py-signature-intent`
- `old-fortran-programming-idioms`: `legacy-alternate-return`, `legacy-assigned-goto`
- `openmp-6.0.1-fortran-examples`: `openmp-atomic-capture-fortran`,
  `openmp-collapse-fortran`, `openmp-fixed-form-sentinel`, `openmp-target-map-fortran`,
  `openmp-task-depend-fortran`
- `openmpi-5.0.10-fortran-reference`: `openmpi-allreduce`, `openmpi-cartesian-shift`,
  `openmpi-derived-struct`, `openmpi-f08-hello`, `openmpi-file-view`, `openmpi-legacy-mpifh`,
  `openmpi-legacy-use-mpi`, `openmpi-nonblocking-send`, `openmpi-rma-flush`,
  `openmpi-source-filter`
- `prima-modernization-case-study`: `legacy-differential-testing`
- `stdlib-0.8.1-docs`: `stdlib-dynamic-text`, `stdlib-hashmap`, `stdlib-linear-system`,
  `stdlib-normal-random`, `stdlib-quadrature`, `stdlib-source-filter`, `stdlib-string-number`,
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
