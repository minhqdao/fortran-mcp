"""Tests for local lexical documentation search."""

import json
from pathlib import Path

import pytest

from fortran_mcp.documents import DocumentChunk
from fortran_mcp.search import SearchError, build_index, get_chunk, search


def _chunk(
    chunk_id: str,
    *,
    headings: tuple[str, ...],
    text: str,
    path: str = "pages/spec/manifest.md",
    source_id: str = "fpm-0.13.0-docs",
    revision: str = "5097350c24ea7b5ceec233714f5a2604f79d0c02",
) -> DocumentChunk:
    return DocumentChunk(
        id=chunk_id,
        source_id=source_id,
        revision=revision,
        path=path,
        headings=headings,
        line_start=10,
        line_end=20,
        text=text,
        sha256="a" * 64,
    )


def _index(tmp_path: Path) -> Path:
    chunks = [
        _chunk(
            "1" * 32,
            headings=("Manifest reference", "OpenMP"),
            text="Add OpenMP as a built-in metapackage dependency in fpm.toml.",
        ),
        _chunk(
            "2" * 32,
            headings=("Installation",),
            text="Install the Fortran Package Manager using pipx.",
            path="pages/install/index.md",
        ),
        _chunk(
            "3" * 32,
            headings=("The `stdlib_sorting` module", "`sort`"),
            text="Sort an input array using the stdlib sort procedure.",
            path="doc/specs/stdlib_sorting.md",
            source_id="stdlib-0.8.1-docs",
            revision="v0.8.1",
        ),
        _chunk(
            "4" * 32,
            headings=("Options controlling Fortran dialect",),
            text="Use -std=f2018 to request conformance warnings for Fortran 2018.",
            path="manual/Fortran-Dialect-Options.md",
            source_id="gfortran-16.2.0-manual",
            revision="gcc-16.2.0",
        ),
    ]
    chunk_dir = tmp_path / "chunks"
    chunk_dir.mkdir()
    (chunk_dir / "fpm-0.13.0-docs.jsonl").write_text(
        "".join(json.dumps(chunk.model_dump(mode="json")) + "\n" for chunk in chunks),
        encoding="utf-8",
    )
    index_path = tmp_path / "search.db"
    assert build_index(tmp_path, index_path) == 4
    return index_path


def test_search_returns_ranked_passage_with_citation(tmp_path: Path) -> None:
    results = search("use openmp dependency", index_path=_index(tmp_path))

    assert results[0].chunk_id == "1" * 32
    assert results[0].headings == ("Manifest reference", "OpenMP")
    assert str(results[0].url) == "https://fpm.fortran-lang.org/spec/manifest.html"
    assert results[0].line_start == 10


def test_natural_language_prefers_all_meaningful_terms(tmp_path: Path) -> None:
    results = search("How do I use OpenMP as a dependency?", index_path=_index(tmp_path))

    assert results[0].chunk_id == "1" * 32
    assert results[0].score > 0


def test_search_can_filter_by_source(tmp_path: Path) -> None:
    index_path = _index(tmp_path)
    assert not search("OpenMP", source_id="missing-source", index_path=index_path)

    results = search("sort array", source_id="stdlib-0.8.1-docs", index_path=index_path)
    assert [result.source_id for result in results] == ["stdlib-0.8.1-docs"]
    assert str(results[0].url) == (
        "https://github.com/fortran-lang/stdlib/blob/v0.8.1/doc/specs/stdlib_sorting.md"
    )

    compiler_results = search(
        "f2018 conformance",
        source_id="gfortran-16.2.0-manual",
        index_path=index_path,
    )
    assert str(compiler_results[0].url) == (
        "https://gcc.gnu.org/onlinedocs/gcc-16.2.0/gfortran/Fortran-Dialect-Options.html"
    )


def test_get_chunk_returns_an_exact_passage(tmp_path: Path) -> None:
    result = get_chunk("2" * 32, index_path=_index(tmp_path))

    assert result.headings == ("Installation",)
    assert str(result.url) == "https://fpm.fortran-lang.org/install/"


def test_get_chunk_rejects_unknown_or_invalid_ids(tmp_path: Path) -> None:
    index_path = _index(tmp_path)

    with pytest.raises(SearchError, match="32 lowercase hexadecimal"):
        get_chunk("invalid", index_path=index_path)
    with pytest.raises(SearchError, match="chunk not found"):
        get_chunk("f" * 32, index_path=index_path)


@pytest.mark.parametrize(("query", "limit"), [("", 5), ("OpenMP", 0), ("OpenMP", 21)])
def test_search_rejects_invalid_input(tmp_path: Path, query: str, limit: int) -> None:
    with pytest.raises(SearchError):
        search(query, limit=limit, index_path=_index(tmp_path))


def test_index_rejects_stale_chunks(tmp_path: Path) -> None:
    chunk = _chunk("3" * 32, headings=("Old",), text="Old docs").model_copy(
        update={"revision": "old"}
    )
    chunk_dir = tmp_path / "chunks"
    chunk_dir.mkdir()
    (chunk_dir / "stale.jsonl").write_text(chunk.model_dump_json() + "\n", encoding="utf-8")

    with pytest.raises(SearchError, match="stale chunks"):
        build_index(tmp_path, tmp_path / "search.db")
