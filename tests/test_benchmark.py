"""Tests for retrieval benchmark metrics."""

from pathlib import Path

from fortran_mcp.benchmark import BenchmarkCase, BenchmarkSuite, load_suite, run_benchmark
from fortran_mcp.search import SearchResult


class FakeProvider:
    def __init__(self, results: dict[str, tuple[SearchResult, ...]]) -> None:
        self.results = results

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        source_id: str | None = None,
        compiler: str | None = None,
        version: str | None = None,
        fortran_version: str | None = None,
    ) -> tuple[SearchResult, ...]:
        return self.results.get(query, ())[:limit]

    def get_chunk(self, chunk_id: str) -> SearchResult:
        raise NotImplementedError


def _result(path: str) -> SearchResult:
    return SearchResult.model_validate(
        {
            "chunk_id": "a" * 32,
            "score": 1,
            "source_id": "source",
            "source_title": "Source",
            "document_type": "ecosystem-guide",
            "authority": "official",
            "topics": ["test"],
            "version": "1",
            "revision": "v1",
            "path": path,
            "headings": ["Heading"],
            "line_start": 1,
            "line_end": 2,
            "text": "Text",
            "url": "https://example.com",
        }
    )


def test_benchmark_calculates_positive_and_negative_metrics() -> None:
    suite = BenchmarkSuite(
        schema_version=1,
        cases=(
            BenchmarkCase(
                id="positive",
                category="exact",
                query="found",
                expected_source="source",
                expected_path="expected.md",
            ),
            BenchmarkCase(
                id="negative",
                category="negative",
                query="absent",
                expect_no_results=True,
            ),
        ),
    )
    provider = FakeProvider({"found": (_result("other.md"), _result("expected.md"))})

    report = run_benchmark(suite, provider)

    assert report.hit_at_1 == 0
    assert report.hit_at_3 == 1
    assert report.mean_reciprocal_rank == 0.5
    assert report.negative_accuracy == 1
    assert all(result.passed for result in report.results)


def test_reviewed_benchmark_suite_is_valid() -> None:
    suite = load_suite(Path("benchmarks/retrieval.toml"))

    assert len(suite.cases) == 47
    assert {case.category for case in suite.cases} == {
        "exact",
        "filter",
        "negative",
        "paraphrase",
    }
