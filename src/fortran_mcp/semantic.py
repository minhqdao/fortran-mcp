"""Build and query a local dense-vector documentation index."""

import argparse
import hashlib
import heapq
import importlib
import math
import sqlite3
import tempfile
from array import array
from collections.abc import Callable, Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any, Protocol, cast

from fortran_mcp.config import data_directory
from fortran_mcp.search import INDEX_FILENAME, SearchError, SearchProvider, SearchResult

SEMANTIC_INDEX_FILENAME = "fortran-mcp-semantic.db"
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"


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


def build_semantic_index(
    model: EmbeddingModel,
    *,
    lexical_index: Path | None = None,
    destination: Path | None = None,
    batch_size: int = 64,
    progress: Callable[[int, int], None] | None = None,
) -> int:
    """Build an atomic dense-vector index from the lexical index."""
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

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=destination.parent,
        prefix=f".{destination.name}-",
        suffix=".tmp",
        delete=False,
    ) as stream:
        temporary_path = Path(stream.name)
    try:
        dimensions: int | None = None
        with sqlite3.connect(temporary_path) as database:
            database.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            database.execute(
                "CREATE TABLE vectors("
                "chunk_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, embedding BLOB NOT NULL)"
            )
            database.execute("CREATE INDEX vectors_source ON vectors(source_id)")
            completed = 0
            for batch in _batches(rows, batch_size):
                texts = [
                    heading.replace(" > ", "\n") + "\n\n" + text for _, _, heading, text in batch
                ]
                embeddings = list(model.embed_passages(texts))
                if len(embeddings) != len(batch):
                    raise SearchError("embedding model returned the wrong number of vectors")
                for (chunk_id, source_id, _, _), values in zip(batch, embeddings, strict=True):
                    vector = _normalized(values)
                    dimensions = dimensions or len(vector)
                    if len(vector) != dimensions:
                        raise SearchError("embedding model returned inconsistent dimensions")
                    database.execute(
                        "INSERT INTO vectors VALUES (?, ?, ?)",
                        (chunk_id, source_id, vector.tobytes()),
                    )
                completed += len(batch)
                if progress is not None:
                    progress(completed, len(rows))
            metadata = {
                "schema_version": "1",
                "model": model.name,
                "dimensions": str(dimensions),
                "lexical_index_sha256": _sha256(lexical_index),
            }
            database.executemany("INSERT INTO metadata VALUES (?, ?)", metadata.items())
        temporary_path.replace(destination)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return len(rows)


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
    ) -> tuple[SearchResult, ...]:
        if not query.strip():
            raise SearchError("query must contain searchable text")
        if not 1 <= limit <= 20:
            raise SearchError("limit must be between 1 and 20")
        if not self.semantic_index.is_file():
            raise SearchError(f"semantic index not found: {self.semantic_index}")
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
                if source_id is not None:
                    sql += " WHERE source_id = ?"
                    parameters = (source_id,)
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
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run the semantic index-building command."""
    parser = _parser()
    args = parser.parse_args(argv)

    def show_progress(completed: int, total: int) -> None:
        print(f"\rEmbedding chunks: {completed}/{total}", end="", flush=True)

    try:
        count = build_semantic_index(
            FastEmbedModel(args.model),
            lexical_index=args.lexical_index,
            destination=args.index,
            batch_size=args.batch_size,
            progress=show_progress,
        )
    except SearchError as error:
        parser.error(str(error))
    print(f"\rEmbedded {count} chunks" + " " * 20)


if __name__ == "__main__":
    main()
