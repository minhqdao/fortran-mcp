"""Measure the retrieval and byte contribution of every indexed source."""

import argparse
import json
import os
import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path

from fortran_mcp.benchmark import BenchmarkReport, load_suite, run_benchmark
from fortran_mcp.bundle import BundleError, build_bundle
from fortran_mcp.config import data_directory
from fortran_mcp.search import INDEX_FILENAME, SearchError, SQLiteSearchProvider, build_index
from fortran_mcp.sources import StrictModel


class SourceContribution(StrictModel):
    """Effect of removing one source from an otherwise identical lexical corpus."""

    source_id: str
    chunks: int
    semantic_vectors: int
    chunk_bytes: int
    installed_index_bytes: int
    compressed_core_bytes: int
    unique_passes: tuple[str, ...]
    passes_lost_without_source: tuple[str, ...]
    recovered_passes_without_source: tuple[str, ...]
    rank_regressions_without_source: int
    rank_improvements_without_source: int
    mean_latency_ms_without_source: float


class ContributionBaseline(StrictModel):
    """Compact retrieval metrics for the complete corpus."""

    passed: int
    hit_at_1: float
    hit_at_3: float
    hit_at_5: float
    hit_at_10: float
    mean_reciprocal_rank: float
    negative_accuracy: float
    mean_latency_ms: float


class ContributionReport(StrictModel):
    """Baseline sizes and leave-one-source-out measurements."""

    cases: int
    chunks: int
    installed_index_bytes: int
    compressed_core_bytes: int
    baseline: ContributionBaseline
    sources: tuple[SourceContribution, ...]


def _compare_reports(
    baseline: BenchmarkReport, omitted: BenchmarkReport
) -> tuple[tuple[str, ...], tuple[str, ...], int, int]:
    baseline_results = {result.id: result for result in baseline.results}
    omitted_results = {result.id: result for result in omitted.results}
    passes_lost = tuple(
        sorted(
            case_id
            for case_id, result in baseline_results.items()
            if result.passed and not omitted_results[case_id].passed
        )
    )
    recovered = tuple(
        sorted(
            case_id
            for case_id, result in baseline_results.items()
            if not result.passed and omitted_results[case_id].passed
        )
    )
    regressions = 0
    improvements = 0
    for case_id, result in baseline_results.items():
        omitted_result = omitted_results[case_id]
        if result.rank is None or omitted_result.rank is None:
            continue
        regressions += omitted_result.rank > result.rank
        improvements += omitted_result.rank < result.rank
    return passes_lost, recovered, regressions, improvements


def _link_chunks(paths: Sequence[Path], destination: Path, excluded: str | None = None) -> int:
    destination.mkdir(parents=True)
    count = 0
    for path in paths:
        if path.stem == excluded:
            continue
        target = destination / path.name
        try:
            os.link(path, target)
        except OSError:
            shutil.copy2(path, target)
        with path.open(encoding="utf-8") as stream:
            count += sum(bool(line.strip()) for line in stream)
    return count


def analyze_contributions(
    data_dir: Path,
    *,
    suite_path: Path = Path("benchmarks/retrieval.toml"),
    license_dir: Path = Path("docs/licenses"),
) -> ContributionReport:
    """Build one lexical corpus per omission and report retrieval and storage deltas."""
    chunk_paths = sorted((data_dir / "chunks").glob("*.jsonl"))
    if not chunk_paths:
        raise ValueError(f"no generated chunks found in {data_dir}")
    suite = load_suite(suite_path)
    with tempfile.TemporaryDirectory(prefix="fortran-mcp-contributions-") as temporary:
        workspace = Path(temporary)
        baseline_dir = workspace / "baseline"
        total_chunks = _link_chunks(chunk_paths, baseline_dir / "chunks")
        build_index(baseline_dir)
        baseline_index = baseline_dir / INDEX_FILENAME
        baseline = run_benchmark(suite, SQLiteSearchProvider(baseline_index))
        baseline_provider = SQLiteSearchProvider(baseline_index)
        winning_sources = {
            result.id: baseline_provider.get_chunk(result.top_chunk_ids[result.rank - 1]).source_id
            for result in baseline.results
            if result.passed and result.rank is not None
        }
        baseline_bundle = workspace / "baseline.zip"
        build_bundle(
            "core",
            baseline_bundle,
            data_dir=baseline_dir,
            license_dir=license_dir,
            data_version="contribution-analysis",
        )
        baseline_index_bytes = baseline_index.stat().st_size
        baseline_core_bytes = baseline_bundle.stat().st_size

        contributions: list[SourceContribution] = []
        for chunk_path in chunk_paths:
            source_id = chunk_path.stem
            omitted_dir = workspace / source_id
            remaining_chunks = _link_chunks(chunk_paths, omitted_dir / "chunks", excluded=source_id)
            build_index(omitted_dir)
            omitted_index = omitted_dir / INDEX_FILENAME
            omitted = run_benchmark(suite, SQLiteSearchProvider(omitted_index))
            omitted_bundle = workspace / f"{source_id}.zip"
            build_bundle(
                "core",
                omitted_bundle,
                data_dir=omitted_dir,
                license_dir=license_dir,
                data_version="contribution-analysis",
            )
            lost, recovered, regressions, improvements = _compare_reports(baseline, omitted)
            unique = tuple(case_id for case_id in lost if winning_sources.get(case_id) == source_id)
            chunks = total_chunks - remaining_chunks
            contributions.append(
                SourceContribution(
                    source_id=source_id,
                    chunks=chunks,
                    semantic_vectors=chunks,
                    chunk_bytes=chunk_path.stat().st_size,
                    installed_index_bytes=baseline_index_bytes - omitted_index.stat().st_size,
                    compressed_core_bytes=baseline_core_bytes - omitted_bundle.stat().st_size,
                    unique_passes=unique,
                    passes_lost_without_source=lost,
                    recovered_passes_without_source=recovered,
                    rank_regressions_without_source=regressions,
                    rank_improvements_without_source=improvements,
                    mean_latency_ms_without_source=omitted.mean_latency_ms,
                )
            )
        return ContributionReport(
            cases=len(suite.cases),
            chunks=total_chunks,
            installed_index_bytes=baseline_index_bytes,
            compressed_core_bytes=baseline_core_bytes,
            baseline=ContributionBaseline(
                passed=sum(result.passed for result in baseline.results),
                hit_at_1=baseline.hit_at_1,
                hit_at_3=baseline.hit_at_3,
                hit_at_5=baseline.hit_at_5,
                hit_at_10=baseline.hit_at_10,
                mean_reciprocal_rank=baseline.mean_reciprocal_rank,
                negative_accuracy=baseline.negative_accuracy,
                mean_latency_ms=baseline.mean_latency_ms,
            ),
            sources=tuple(contributions),
        )


def main(argv: Sequence[str] | None = None) -> None:
    """Run leave-one-source-out analysis and write a machine-readable report."""
    parser = argparse.ArgumentParser(description="Measure each source's retrieval and byte value")
    parser.add_argument("--data-dir", type=Path, default=data_directory())
    parser.add_argument("--suite", type=Path, default=Path("benchmarks/retrieval.toml"))
    parser.add_argument("--license-dir", type=Path, default=Path("docs/licenses"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = analyze_contributions(
            args.data_dir,
            suite_path=args.suite,
            license_dir=args.license_dir,
        )
    except (BundleError, OSError, SearchError, ValueError) as error:
        parser.error(str(error))
    rendered = json.dumps(report.model_dump(mode="json"), indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
