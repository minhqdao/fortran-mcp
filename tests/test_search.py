"""Tests for local lexical documentation search."""

import json
from pathlib import Path

import pytest

from fortran_mcp.documents import DocumentChunk
from fortran_mcp.search import SearchError, build_index, search


def _chunk(
    chunk_id: str,
    *,
    headings: tuple[str, ...],
    text: str,
    path: str = "pages/spec/manifest.md",
) -> DocumentChunk:
    return DocumentChunk(
        id=chunk_id,
        source_id="fpm-0.13.0-docs",
        revision="5097350c24ea7b5ceec233714f5a2604f79d0c02",
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
    ]
    chunk_dir = tmp_path / "chunks"
    chunk_dir.mkdir()
    (chunk_dir / "fpm-0.13.0-docs.jsonl").write_text(
        "".join(json.dumps(chunk.model_dump(mode="json")) + "\n" for chunk in chunks),
        encoding="utf-8",
    )
    index_path = tmp_path / "search.db"
    assert build_index(tmp_path, index_path) == 2
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
    assert not search("OpenMP", source_id="missing-source", index_path=_index(tmp_path))


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
