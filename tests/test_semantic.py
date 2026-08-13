"""Tests for local semantic indexing and retrieval."""

import json
from collections.abc import Iterable, Sequence
from pathlib import Path

import pytest

from fortran_mcp.documents import DocumentChunk
from fortran_mcp.search import SearchError, SQLiteSearchProvider, build_index
from fortran_mcp.semantic import SemanticSearchProvider, build_semantic_index


class FakeEmbeddingModel:
    name = "fake-embedding-model"

    def _embed(self, text: str) -> tuple[float, float]:
        lowered = text.casefold()
        return (1.0, 0.0) if "openmp" in lowered else (0.0, 1.0)

    def embed_passages(self, texts: Sequence[str]) -> Iterable[Sequence[float]]:
        return (self._embed(text) for text in texts)

    def embed_query(self, text: str) -> Sequence[float]:
        return self._embed(text)


def _chunk(chunk_id: str, heading: str, text: str) -> DocumentChunk:
    return DocumentChunk(
        id=chunk_id,
        source_id="fpm-0.13.0-docs",
        revision="5097350c24ea7b5ceec233714f5a2604f79d0c02",
        path="pages/spec/manifest.md",
        headings=(heading,),
        line_start=1,
        line_end=2,
        text=text,
        sha256="a" * 64,
    )


def _indexes(tmp_path: Path) -> tuple[Path, Path]:
    chunks = (
        _chunk("1" * 32, "Dependencies", "Use an OpenMP metapackage."),
        _chunk("2" * 32, "Installation", "Install fpm with a package manager."),
    )
    chunk_dir = tmp_path / "chunks"
    chunk_dir.mkdir()
    (chunk_dir / "fpm.jsonl").write_text(
        "".join(json.dumps(chunk.model_dump(mode="json")) + "\n" for chunk in chunks),
        encoding="utf-8",
    )
    lexical_index = tmp_path / "lexical.db"
    semantic_index = tmp_path / "semantic.db"
    build_index(tmp_path, lexical_index)
    assert (
        build_semantic_index(
            FakeEmbeddingModel(),
            lexical_index=lexical_index,
            destination=semantic_index,
            batch_size=1,
        )
        == 2
    )
    return lexical_index, semantic_index


def test_semantic_search_returns_closest_cited_chunk(tmp_path: Path) -> None:
    lexical_index, semantic_index = _indexes(tmp_path)
    provider = SemanticSearchProvider(
        FakeEmbeddingModel(),
        semantic_index=semantic_index,
        lexical_index=lexical_index,
    )

    results = provider.search("parallel OpenMP programming", limit=1)

    assert results[0].chunk_id == "1" * 32
    assert results[0].score == pytest.approx(1.0)
    assert str(results[0].url) == "https://fpm.fortran-lang.org/spec/manifest.html"


def test_semantic_search_filters_sources_and_rejects_stale_index(tmp_path: Path) -> None:
    lexical_index, semantic_index = _indexes(tmp_path)
    provider = SemanticSearchProvider(
        FakeEmbeddingModel(),
        semantic_index=semantic_index,
        lexical_index=lexical_index,
    )

    assert not provider.search("OpenMP", source_id="unknown")
    lexical_index.write_bytes(lexical_index.read_bytes() + b"stale")
    with pytest.raises(SearchError, match="stale"):
        provider.search("OpenMP")


def test_semantic_search_rejects_wrong_model(tmp_path: Path) -> None:
    lexical_index, semantic_index = _indexes(tmp_path)
    model = FakeEmbeddingModel()
    model.name = "different-model"
    provider = SemanticSearchProvider(
        model,
        semantic_index=semantic_index,
        lexical_provider=SQLiteSearchProvider(lexical_index),
    )

    with pytest.raises(SearchError, match="different embedding model"):
        provider.search("OpenMP")
