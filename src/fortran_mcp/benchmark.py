"""Evaluate retrieval providers against reviewed documentation questions."""

import argparse
import json
import time
import tomllib
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from fortran_mcp.search import SearchProvider, SearchResult, SQLiteSearchProvider
from fortran_mcp.sources import StrictModel

DEFAULT_BENCHMARK_PATH = Path("benchmarks/retrieval.toml")


class BenchmarkCase(StrictModel):
    """One reviewed retrieval expectation."""

    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    category: Literal["exact", "paraphrase", "filter", "negative"]
    query: str = Field(min_length=1)
    source_filter: str | None = None
    expected_source: str | None = None
    expected_path: str | None = None
    expected_heading: str | None = None
    expect_no_results: bool = False

    @model_validator(mode="after")
    def expectation_is_complete(self) -> Self:
        positive = self.expected_source is not None and self.expected_path is not None
        if self.expect_no_results == positive:
            raise ValueError("case must define either a positive result or expect_no_results")
        return self


class BenchmarkSuite(StrictModel):
    """Versioned retrieval benchmark."""

    schema_version: Literal[1]
    cases: tuple[BenchmarkCase, ...]

    @model_validator(mode="after")
    def case_ids_are_unique(self) -> Self:
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("benchmark case IDs must be unique")
        return self


class CaseResult(StrictModel):
    """Measured outcome for one benchmark case."""

    id: str
    category: str
    query: str
    passed: bool
    rank: int | None
    latency_ms: float
    returned: int
    top_chunk_ids: tuple[str, ...]


class CategoryMetrics(StrictModel):
    """Aggregate retrieval metrics for one category."""

    cases: int
    passed: int
    pass_rate: float
    mrr: float


class BenchmarkReport(StrictModel):
    """Machine-readable retrieval benchmark report."""

    provider: str
    cases: int
    hit_at_1: float
    hit_at_3: float
    hit_at_5: float
    hit_at_10: float
    mean_reciprocal_rank: float
    negative_accuracy: float
    mean_latency_ms: float
    categories: dict[str, CategoryMetrics]
    results: tuple[CaseResult, ...]


def load_suite(path: Path = DEFAULT_BENCHMARK_PATH) -> BenchmarkSuite:
    """Load and validate a retrieval benchmark suite."""
    with path.open("rb") as stream:
        return BenchmarkSuite.model_validate(tomllib.load(stream))


def _rank(case: BenchmarkCase, results: tuple[SearchResult, ...]) -> int | None:
    if case.expect_no_results:
        return None
    for rank, result in enumerate(results, start=1):
        heading_matches = case.expected_heading is None or any(
            case.expected_heading.casefold() in heading.casefold() for heading in result.headings
        )
        if (
            result.source_id == case.expected_source
            and result.path == case.expected_path
            and heading_matches
        ):
            return rank
    return None


def run_benchmark(
    suite: BenchmarkSuite,
    provider: SearchProvider,
    *,
    limit: int = 10,
    provider_name: str = "sqlite-fts5",
) -> BenchmarkReport:
    """Run a benchmark suite against a search provider."""
    outcomes: list[CaseResult] = []
    category_ranks: dict[str, list[int | None]] = defaultdict(list)
    positive_ranks: list[int | None] = []
    negative_passes: list[bool] = []

    for case in suite.cases:
        started = time.perf_counter()
        results = provider.search(
            case.query,
            limit=limit,
            source_id=case.source_filter,
        )
        latency_ms = (time.perf_counter() - started) * 1_000
        rank = _rank(case, results)
        passed = not results if case.expect_no_results else rank is not None
        outcomes.append(
            CaseResult(
                id=case.id,
                category=case.category,
                query=case.query,
                passed=passed,
                rank=rank,
                latency_ms=round(latency_ms, 3),
                returned=len(results),
                top_chunk_ids=tuple(result.chunk_id for result in results),
            )
        )
        category_ranks[case.category].append(1 if passed and case.expect_no_results else rank)
        if case.expect_no_results:
            negative_passes.append(passed)
        else:
            positive_ranks.append(rank)

    def hit_at(cutoff: int) -> float:
        return sum(rank is not None and rank <= cutoff for rank in positive_ranks) / len(
            positive_ranks
        )

    categories = {
        category: CategoryMetrics(
            cases=len(ranks),
            passed=sum(rank is not None for rank in ranks),
            pass_rate=sum(rank is not None for rank in ranks) / len(ranks),
            mrr=sum(1 / rank for rank in ranks if rank is not None) / len(ranks),
        )
        for category, ranks in sorted(category_ranks.items())
    }
    return BenchmarkReport(
        provider=provider_name,
        cases=len(outcomes),
        hit_at_1=hit_at(1),
        hit_at_3=hit_at(3),
        hit_at_5=hit_at(5),
        hit_at_10=hit_at(10),
        mean_reciprocal_rank=sum(1 / rank for rank in positive_ranks if rank is not None)
        / len(positive_ranks),
        negative_accuracy=(sum(negative_passes) / len(negative_passes) if negative_passes else 1.0),
        mean_latency_ms=sum(outcome.latency_ms for outcome in outcomes) / len(outcomes),
        categories=categories,
        results=tuple(outcomes),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark documentation retrieval")
    parser.add_argument("--suite", type=Path, default=DEFAULT_BENCHMARK_PATH)
    parser.add_argument("--index", type=Path)
    parser.add_argument("--provider", choices=("lexical", "semantic", "hybrid"), default="lexical")
    parser.add_argument("--semantic-index", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run the lexical retrieval benchmark."""
    args = _parser().parse_args(argv)
    provider: SearchProvider
    if args.provider in {"semantic", "hybrid"}:
        from fortran_mcp.semantic import DEFAULT_MODEL, FastEmbedModel, SemanticSearchProvider

        model = FastEmbedModel(args.model or DEFAULT_MODEL)
        semantic: SearchProvider = SemanticSearchProvider(
            model,
            semantic_index=args.semantic_index,
            lexical_index=args.index,
        )
        if args.provider == "hybrid":
            from fortran_mcp.hybrid import HybridSearchProvider

            provider = HybridSearchProvider(SQLiteSearchProvider(args.index), semantic)
            provider_name = f"hybrid:sqlite-fts5+{model.name}"
        else:
            provider = semantic
            provider_name = f"semantic:{model.name}"
    else:
        provider = SQLiteSearchProvider(args.index)
        provider_name = "sqlite-fts5"
    report = run_benchmark(
        load_suite(args.suite),
        provider,
        provider_name=provider_name,
    )
    rendered = json.dumps(report.model_dump(mode="json"), indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
