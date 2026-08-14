"""Build and query a local dense-vector documentation index."""

from __future__ import annotations

import argparse
import hashlib
import heapq
import importlib
import math
import sqlite3
import tempfile
from array import array
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from fortran_mcp.config import data_directory
from fortran_mcp.search import (
    INDEX_FILENAME,
    SearchError,
    SearchProvider,
    SearchResult,
    applicable_source_ids,
)

SEMANTIC_INDEX_FILENAME = "fortran-mcp-semantic.db"
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
SEMANTIC_SCHEMA_VERSION = "2"


@dataclass(frozen=True)
class SemanticBuildResult:
    """Summary of an incremental semantic-index build."""

    total: int
    embedded: int
    reused: int
    removed: int


class EmbeddingModel(Protocol):
    """Minimal model contract used by semantic indexing and retrieval."""

    @property
    def name(self) -> str: ...

    def embed_passages(self, texts: Sequence[str]) -> Iterable[Sequence[float]]: ...

    def embed_query(self, text: str) -> Sequence[float]: ...


class FastEmbedModel:
    """Local ONNX embedding model loaded through the optional FastEmbed extra."""

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        try:
            module = importlib.import_module("fast" + "embed")
        except ImportError as error:
            raise SearchError(
                "semantic search requires the optional dependency: uv sync --extra semantic"
            ) from error
        self._name = model_name
        self._model: Any = module.TextEmbedding(model_name=model_name)

    @property
    def name(self) -> str:
        return self._name

    def embed_passages(self, texts: Sequence[str]) -> Iterable[Sequence[float]]:
        return cast(Iterable[Sequence[float]], self._model.passage_embed(list(texts)))

    def embed_query(self, text: str) -> Sequence[float]:
        return cast(Sequence[float], next(iter(self._model.query_embed([text]))))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalized(values: Sequence[float]) -> array[float]:
    vector = array("f", values)
    if not vector or not all(math.isfinite(value) for value in vector):
        raise SearchError("embedding model returned an empty or non-finite vector")
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        raise SearchError("embedding model returned a zero vector")
    return array("f", (value / magnitude for value in vector))


def _vector_from_blob(blob: bytes) -> array[float]:
    vector = array("f")
    vector.frombytes(blob)
    return vector


def _batches(values: Sequence[Any], size: int) -> Iterator[Sequence[Any]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _reusable_vectors(
    destination: Path,
    model_name: str,
    lexical_index_sha256: str,
) -> tuple[dict[str, tuple[str, bytes]], int | None]:
    """Load compatible vectors keyed by chunk ID and embedded-text hash."""
    if not destination.is_file():
        return {}, None
    try:
        with sqlite3.connect(f"file:{destination}?mode=ro", uri=True) as database:
            metadata = dict(database.execute("SELECT key, value FROM metadata").fetchall())
            if metadata.get("model") != model_name:
                return {}, None
            if metadata.get("schema_version") == SEMANTIC_SCHEMA_VERSION:
                rows = database.execute(
                    "SELECT chunk_id, content_sha256, embedding FROM vectors"
                ).fetchall()
            elif (
                metadata.get("schema_version") == "1"
                and metadata.get("lexical_index_sha256") == lexical_index_sha256
            ):
                rows = [
                    (chunk_id, "", embedding)
                    for chunk_id, embedding in database.execute(
                        "SELECT chunk_id, embedding FROM vectors"
                    ).fetchall()
                ]
            else:
                return {}, None
            return (
                {
                    chunk_id: (content_sha256, embedding)
                    for chunk_id, content_sha256, embedding in rows
                },
                int(metadata["dimensions"]),
            )
    except (KeyError, ValueError, sqlite3.Error):
        return {}, None


def build_semantic_index(
    model: EmbeddingModel,
    *,
    lexical_index: Path | None = None,
    destination: Path | None = None,
    batch_size: int = 64,
    progress: Callable[[int, int], None] | None = None,
    incremental: bool = True,
) -> SemanticBuildResult:
    """Build an atomic dense-vector index, reusing unchanged compatible vectors."""
    lexical_index = lexical_index or data_directory() / INDEX_FILENAME
    destination = destination or data_directory() / SEMANTIC_INDEX_FILENAME
    if not lexical_index.is_file():
        raise SearchError(f"search index not found: {lexical_index}")
    if batch_size < 1:
        raise SearchError("batch size must be positive")
    try:
        with sqlite3.connect(f"file:{lexical_index}?mode=ro", uri=True) as database:
            rows = database.execute(
                "SELECT chunk_id, source_id, headings, text FROM chunks ORDER BY chunk_id"
            ).fetchall()
    except sqlite3.Error as error:
        raise SearchError(f"could not read lexical index: {error}") from error
    if not rows:
        raise SearchError("lexical index contains no chunks")

    lexical_index_sha256 = _sha256(lexical_index)
    reusable, dimensions = (
        _reusable_vectors(destination, model.name, lexical_index_sha256)
        if incremental
        else ({}, None)
    )
    prepared = [
        (
            chunk_id,
            source_id,
            heading.replace(" > ", "\n") + "\n\n" + text,
        )
        for chunk_id, source_id, heading, text in rows
    ]
    current_ids = {chunk_id for chunk_id, _, _ in prepared}
    removed = len(reusable.keys() - current_ids)

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=destination.parent,
        prefix=f".{destination.name}-",
        suffix=".tmp",
        delete=False,
    ) as stream:
        temporary_path = Path(stream.name)
    try:
        reused = 0
        embedded = 0
        with sqlite3.connect(temporary_path) as database:
            database.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            database.execute(
                "CREATE TABLE vectors("
                "chunk_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, "
                "content_sha256 TEXT NOT NULL, embedding BLOB NOT NULL)"
            )
            database.execute("CREATE INDEX vectors_source ON vectors(source_id)")
            completed = 0
            pending: list[tuple[str, str, str, str]] = []
            for chunk_id, source_id, text in prepared:
                content_sha256 = _text_hash(text)
                cached = reusable.get(chunk_id)
                if cached is not None and cached[0] in {"", content_sha256}:
                    database.execute(
                        "INSERT INTO vectors VALUES (?, ?, ?, ?)",
                        (chunk_id, source_id, content_sha256, cached[1]),
                    )
                    reused += 1
                    completed += 1
                    if progress is not None and (
                        completed % batch_size == 0 or completed == len(rows)
                    ):
                        progress(completed, len(rows))
                else:
                    pending.append((chunk_id, source_id, text, content_sha256))

            for batch in _batches(pending, batch_size):
                embeddings = list(model.embed_passages([text for _, _, text, _ in batch]))
                if len(embeddings) != len(batch):
                    raise SearchError("embedding model returned the wrong number of vectors")
                for (chunk_id, source_id, _, content_sha256), values in zip(
                    batch, embeddings, strict=True
                ):
                    vector = _normalized(values)
                    dimensions = dimensions or len(vector)
                    if len(vector) != dimensions:
                        raise SearchError("embedding model returned inconsistent dimensions")
                    database.execute(
                        "INSERT INTO vectors VALUES (?, ?, ?, ?)",
                        (chunk_id, source_id, content_sha256, vector.tobytes()),
                    )
                    embedded += 1
                completed += len(batch)
                if progress is not None:
                    progress(completed, len(rows))
            metadata = {
                "schema_version": SEMANTIC_SCHEMA_VERSION,
                "model": model.name,
                "dimensions": str(dimensions),
                "lexical_index_sha256": lexical_index_sha256,
            }
            database.executemany("INSERT INTO metadata VALUES (?, ?)", metadata.items())
        temporary_path.replace(destination)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return SemanticBuildResult(
        total=len(rows),
        embedded=embedded,
        reused=reused,
        removed=removed,
    )


class SemanticSearchProvider:
    """Exact cosine search over locally stored dense embeddings."""

    def __init__(
        self,
        model: EmbeddingModel | None = None,
        *,
        semantic_index: Path | None = None,
        lexical_provider: SearchProvider | None = None,
        lexical_index: Path | None = None,
    ) -> None:
        from fortran_mcp.search import SQLiteSearchProvider

        self.model = model or FastEmbedModel()
        self.semantic_index = semantic_index or data_directory() / SEMANTIC_INDEX_FILENAME
        lexical_index = lexical_index or data_directory() / INDEX_FILENAME
        self._validate_lexical_index = lexical_provider is None
        self.lexical_provider = lexical_provider or SQLiteSearchProvider(lexical_index)
        self.lexical_index = lexical_index

    def _metadata(self, database: sqlite3.Connection) -> dict[str, str]:
        try:
            return dict(database.execute("SELECT key, value FROM metadata").fetchall())
        except sqlite3.Error as error:
            raise SearchError(f"could not read semantic index metadata: {error}") from error

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
        if not query.strip():
            raise SearchError("query must contain searchable text")
        if not 1 <= limit <= 20:
            raise SearchError("limit must be between 1 and 20")
        if not self.semantic_index.is_file():
            raise SearchError(f"semantic index not found: {self.semantic_index}")
        source_ids = applicable_source_ids(
            source_id=source_id,
            compiler=compiler,
            version=version,
            fortran_version=fortran_version,
        )
        if source_ids == ():
            return ()
        query_vector = _normalized(self.model.embed_query(query))
        try:
            with sqlite3.connect(f"file:{self.semantic_index}?mode=ro", uri=True) as database:
                metadata = self._metadata(database)
                if metadata.get("model") != self.model.name:
                    raise SearchError("semantic index was built with a different embedding model")
                if self._validate_lexical_index and metadata.get("lexical_index_sha256") != _sha256(
                    self.lexical_index
                ):
                    raise SearchError("semantic index is stale; rebuild it from the lexical index")
                if int(metadata.get("dimensions", "0")) != len(query_vector):
                    raise SearchError("query embedding dimensions do not match the semantic index")
                sql = "SELECT chunk_id, embedding FROM vectors"
                parameters: tuple[str, ...] = ()
                if source_ids is not None:
                    placeholders = ", ".join("?" for _ in source_ids)
                    sql += f" WHERE source_id IN ({placeholders})"
                    parameters = source_ids
                rows = database.execute(sql, parameters)
                scored = heapq.nlargest(
                    limit,
                    (
                        (
                            sum(
                                left * right
                                for left, right in zip(
                                    query_vector, _vector_from_blob(embedding), strict=True
                                )
                            ),
                            chunk_id,
                        )
                        for chunk_id, embedding in rows
                    ),
                )
        except sqlite3.Error as error:
            raise SearchError(f"could not query semantic index: {error}") from error
        return tuple(
            self.lexical_provider.get_chunk(chunk_id).model_copy(update={"score": score})
            for score, chunk_id in scored
        )

    def get_chunk(self, chunk_id: str) -> SearchResult:
        return self.lexical_provider.get_chunk(chunk_id)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the local semantic search index")
    parser.add_argument("--lexical-index", type=Path)
    parser.add_argument("--index", type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--rebuild", action="store_true", help="do not reuse existing embeddings")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run the semantic index-building command."""
    parser = _parser()
    args = parser.parse_args(argv)

    def show_progress(completed: int, total: int) -> None:
        print(f"\rIndexing chunks: {completed}/{total}", end="", flush=True)

    try:
        result = build_semantic_index(
            FastEmbedModel(args.model),
            lexical_index=args.lexical_index,
            destination=args.index,
            batch_size=args.batch_size,
            progress=show_progress,
            incremental=not args.rebuild,
        )
    except SearchError as error:
        parser.error(str(error))
    print(
        f"\rIndexed {result.total} chunks "
        f"({result.embedded} embedded, {result.reused} reused, {result.removed} removed)" + " " * 10
    )


if __name__ == "__main__":
    main()
