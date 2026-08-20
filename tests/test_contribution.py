"""Tests for leave-one-source-out contribution metrics."""

from fortran_mcp.benchmark import BenchmarkReport, CaseResult
from fortran_mcp.contribution import _compare_reports


def _report(results: tuple[CaseResult, ...]) -> BenchmarkReport:
    return BenchmarkReport(
        provider="test",
        cases=len(results),
        hit_at_1=0,
        hit_at_3=0,
        hit_at_5=0,
        hit_at_10=0,
        mean_reciprocal_rank=0,
        negative_accuracy=0,
        mean_latency_ms=0,
        categories={},
        results=results,
    )


def _case(case_id: str, *, passed: bool, rank: int | None) -> CaseResult:
    return CaseResult(
        id=case_id,
        category="paraphrase",
        query=case_id,
        answer_authority="guidance",
        passed=passed,
        rank=rank,
        latency_ms=1,
        returned=1,
        top_chunk_ids=(),
    )


def test_compare_reports_separates_unique_passes_interference_and_rank_changes() -> None:
    baseline = _report(
        (
            _case("unique", passed=True, rank=1),
            _case("interference", passed=False, rank=None),
            _case("worse", passed=True, rank=1),
            _case("better", passed=True, rank=3),
        )
    )
    omitted = _report(
        (
            _case("unique", passed=False, rank=None),
            _case("interference", passed=True, rank=2),
            _case("worse", passed=True, rank=4),
            _case("better", passed=True, rank=1),
        )
    )

    assert _compare_reports(baseline, omitted) == (
        ("unique",),
        ("interference",),
        1,
        1,
    )
