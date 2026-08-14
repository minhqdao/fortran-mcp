"""Tests for hybrid rank fusion."""

from pydantic import HttpUrl

from fortran_mcp.hybrid import HybridSearchProvider
from fortran_mcp.search import SearchResult
from fortran_mcp.sources import DocumentType, SourceAuthority


def _result(chunk_id: str) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id * 32,
        score=1,
        source_id="source",
        source_title="Source",
        document_type=DocumentType.ECOSYSTEM_GUIDE,
        authority=SourceAuthority.OFFICIAL,
        topics=("test",),
        compilers=("gfortran",),
        fortran_versions=("Fortran 2018",),
        version="1",
        revision="v1",
        path=f"{chunk_id}.md",
        headings=(chunk_id,),
        line_start=1,
        line_end=2,
        text=chunk_id,
        url=HttpUrl(f"https://example.com/{chunk_id}"),
    )


class FakeProvider:
    def __init__(self, results: tuple[SearchResult, ...]) -> None:
        self.results = results
        self.call: tuple[str, int, str | None, str | None, str | None, str | None] | None = None

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
        self.call = (query, limit, source_id, compiler, version, fortran_version)
        return self.results[:limit]

    def get_chunk(self, chunk_id: str) -> SearchResult:
        return next(result for result in self.results if result.chunk_id == chunk_id)


def test_hybrid_fusion_rewards_results_found_by_both_providers() -> None:
    shared = _result("a")
    lexical = FakeProvider((_result("b"), shared))
    semantic = FakeProvider((_result("c"), shared))
    provider = HybridSearchProvider(lexical, semantic)

    results = provider.search(
        "question",
        limit=2,
        source_id="source",
        compiler="gfortran",
        version="1",
        fortran_version="Fortran 2018",
    )

    assert [result.chunk_id for result in results] == [shared.chunk_id, _result("b").chunk_id]
    assert results[0].score > results[1].score
    assert (
        lexical.call
        == semantic.call
        == (
            "question",
            10,
            "source",
            "gfortran",
            "1",
            "Fortran 2018",
        )
    )


def test_hybrid_get_chunk_uses_lexical_source_of_truth() -> None:
    expected = _result("a")
    provider = HybridSearchProvider(FakeProvider((expected,)), FakeProvider(()))

    assert provider.get_chunk(expected.chunk_id) == expected


def test_hybrid_abstains_below_threshold_unless_source_is_explicit() -> None:
    result = _result("a").model_copy(update={"score": 0.7})
    provider = HybridSearchProvider(FakeProvider((result,)), FakeProvider((result,)))

    assert not provider.search("unsupported")
    assert provider.search("question", source_id="source")
