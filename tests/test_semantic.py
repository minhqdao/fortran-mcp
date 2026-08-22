"""Tests for local semantic indexing and retrieval."""

import json
import sqlite3
from array import array
from collections.abc import Iterable, Sequence
from pathlib import Path

import pytest

from fortran_mcp.documents import DocumentChunk
from fortran_mcp.search import SearchError, SQLiteSearchProvider, build_index
from fortran_mcp.semantic import SemanticSearchProvider, build_semantic_index


class FakeEmbeddingModel:
    name = "fake-embedding-model"

    def __init__(self) -> None:
        self.embedded: list[str] = []

    def _embed(self, text: str) -> tuple[float, float]:
        lowered = text.casefold()
        return (1.0, 0.0) if "openmp" in lowered else (0.0, 1.0)

    def embed_passages(self, texts: Sequence[str]) -> Iterable[Sequence[float]]:
        self.embedded.extend(texts)
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
    result = build_semantic_index(
        FakeEmbeddingModel(),
        lexical_index=lexical_index,
        destination=semantic_index,
        batch_size=1,
    )
    assert result.total == result.embedded == 2
    assert result.reused == result.removed == 0
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
    assert provider.search("OpenMP", version="0.13.0")
    assert not provider.search("OpenMP", version="99.0")
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


def test_incremental_build_reuses_unchanged_vectors(tmp_path: Path) -> None:
    lexical_index, semantic_index = _indexes(tmp_path)
    model = FakeEmbeddingModel()

    result = build_semantic_index(
        model,
        lexical_index=lexical_index,
        destination=semantic_index,
    )

    assert result.total == result.reused == 2
    assert result.embedded == result.removed == 0
    assert model.embedded == []


def test_incremental_build_embeds_changes_and_removes_old_chunks(tmp_path: Path) -> None:
    lexical_index, semantic_index = _indexes(tmp_path)
    chunk_dir = tmp_path / "chunks"
    changed = _chunk("1" * 32, "Dependencies", "Changed OpenMP guidance.")
    replacement = _chunk("3" * 32, "Profiles", "Configure a build profile.")
    (chunk_dir / "fpm.jsonl").write_text(
        "".join(
            json.dumps(chunk.model_dump(mode="json")) + "\n" for chunk in (changed, replacement)
        ),
        encoding="utf-8",
    )
    build_index(tmp_path, lexical_index)
    model = FakeEmbeddingModel()

    result = build_semantic_index(
        model,
        lexical_index=lexical_index,
        destination=semantic_index,
    )

    assert result.total == result.embedded == 2
    assert result.reused == 0
    assert result.removed == 1
    assert len(model.embedded) == 2


def test_build_batches_by_length_and_keeps_vectors_keyed(tmp_path: Path) -> None:
    class RecordingModel(FakeEmbeddingModel):
        def __init__(self) -> None:
            super().__init__()
            self.batches: list[list[str]] = []

        def embed_passages(self, texts: Sequence[str]) -> Iterable[Sequence[float]]:
            self.batches.append(list(texts))
            return super().embed_passages(texts)

    filler = "filler " * 400
    chunks = (
        _chunk("1" * 32, "Dependencies", "Use an OpenMP metapackage."),
        _chunk("2" * 32, "Parallelism", f"OpenMP program examples. {filler}"),
        _chunk("3" * 32, "Installation", "Install fpm with a package manager."),
        _chunk("4" * 32, "Packaging", f"Package metadata reference. {filler}"),
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
    model = RecordingModel()

    result = build_semantic_index(
        model,
        lexical_index=lexical_index,
        destination=semantic_index,
        batch_size=2,
    )

    assert result.total == result.embedded == 4
    # Chunk-id order interleaves short and long passages; embedding must regroup them.
    assert [sum("filler" in text for text in batch) for batch in model.batches] == [0, 2]
    with sqlite3.connect(f"file:{semantic_index}?mode=ro", uri=True) as database:
        vectors = dict(database.execute("SELECT chunk_id, embedding FROM vectors"))
    mentions_openmp = {"1" * 32: True, "2" * 32: True, "3" * 32: False, "4" * 32: False}
    for chunk_id, expected in mentions_openmp.items():
        vector = array("f")
        vector.frombytes(vectors[chunk_id])
        assert (vector[0] > vector[1]) is expected
