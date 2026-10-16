"""Build and query the local SQLite full-text search index."""

import argparse
import gc
import re
import sqlite3
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Protocol
from urllib.parse import quote

from pydantic import Field, HttpUrl

from fortran_mcp.config import data_directory
from fortran_mcp.documents import DocumentChunk
from fortran_mcp.sources import DocumentType, Source, SourceAuthority, StrictModel, load_registry

INDEX_FILENAME = "fortran-mcp-core.db"
DEFAULT_INDEX_PATH = Path("data") / INDEX_FILENAME
QUERY_TOKEN = re.compile(r"[\w.+-]+", re.UNICODE)
STOP_WORDS = frozenset(
    {
        "a",
        "add",
        "an",
        "as",
        "do",
        "for",
        "fpm",
        "how",
        "i",
        "in",
        "is",
        "it",
        "of",
        "on",
        "prefer",
        "should",
        "the",
        "to",
        "why",
    }
)


class SearchError(RuntimeError):
    """Raised when the search index cannot be built or queried."""


class SearchResult(StrictModel):
    """A ranked documentation result with a complete citation."""

    chunk_id: str
    score: float
    source_id: str
    source_title: str
    document_type: DocumentType
    authority: SourceAuthority
    topics: tuple[str, ...]
    compilers: tuple[str, ...] = ()
    fortran_versions: tuple[str, ...] = ()
    version: str
    revision: str
    path: str
    headings: tuple[str, ...]
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    text: str
    url: HttpUrl


class SearchProvider(Protocol):
    """Backend-independent access to indexed documentation."""

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        source_id: str | None = None,
        compiler: str | None = None,
        version: str | None = None,
        fortran_version: str | None = None,
    ) -> tuple[SearchResult, ...]: ...

    def get_chunk(self, chunk_id: str) -> SearchResult: ...


class SQLiteSearchProvider:
    """Local lexical search backed by an SQLite FTS5 index."""

    def __init__(self, index_path: Path | None = None) -> None:
        self.index_path = index_path or data_directory() / INDEX_FILENAME

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
        return search(
            query,
            limit=limit,
            source_id=source_id,
            compiler=compiler,
            version=version,
            fortran_version=fortran_version,
            index_path=self.index_path,
        )

    def get_chunk(self, chunk_id: str) -> SearchResult:
        return get_chunk(chunk_id, index_path=self.index_path)


def _result_from_row(row: tuple[Any, ...]) -> SearchResult:
    return SearchResult(
        chunk_id=row[0],
        score=row[1],
        source_id=row[2],
        source_title=row[3],
        document_type=row[4],
        authority=row[5],
        topics=tuple(filter(None, row[6].split(","))),
        compilers=tuple(filter(None, row[7].split(","))),
        fortran_versions=tuple(filter(None, row[8].split(","))),
        version=row[9],
        revision=row[10],
        path=row[11],
        headings=tuple(filter(None, row[12].split(" > "))),
        line_start=row[13],
        line_end=row[14],
        text=row[15],
        url=HttpUrl(row[16]),
    )


def _citation_url(source: Source, path: str) -> HttpUrl:
    relative = PurePosixPath(path)
    prefix = PurePosixPath(source.published_path_prefix)
    try:
        relative = relative.relative_to(prefix)
    except ValueError as error:
        raise SearchError(f"document path is outside its published prefix: {path}") from error

    if source.citation_format == "published-html":
        relative = relative.parent if relative.name == "index.md" else relative.with_suffix(".html")
    encoded_path = "/".join(quote(part) for part in relative.parts)
    base = str(source.citation_base_url).rstrip("/")
    trailing_slash = source.citation_format == "published-html" and not relative.suffix
    return HttpUrl(f"{base}/{encoded_path}{'/' if trailing_slash else ''}")


def _read_chunks(path: Path) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    chunks.append(DocumentChunk.model_validate_json(line))
    except (OSError, ValueError) as error:
        raise SearchError(f"could not read chunks from {path}: {error}") from error
    return chunks


def _atomic_replace_temporary(temporary_path: Path, destination: Path) -> None:
    """Replace destination on platforms where immediate atomic rename may be delayed."""
    last_error: PermissionError | None = None
    gc.collect()
    for _ in range(20):
        try:
            temporary_path.replace(destination)
            return
        except PermissionError as error:
            last_error = error
            gc.collect()
            time.sleep(0.05)
    if last_error is not None:
        raise last_error


def _unlink_temporary(temporary_path: Path) -> None:
    gc.collect()
    for _ in range(20):
        try:
            temporary_path.unlink(missing_ok=True)
            return
        except PermissionError:
            gc.collect()
            time.sleep(0.05)


def build_index(data_dir: Path | None = None, index_path: Path | None = None) -> int:
    """Build a fresh, atomic FTS5 index from every generated chunk file."""
    data_dir = data_dir or data_directory()
    destination = index_path or data_dir / INDEX_FILENAME
    chunk_paths = sorted((data_dir / "chunks").glob("*.jsonl"))
    if not chunk_paths:
        raise SearchError("no generated chunk files found")
    sources = {source.id: source for source in load_registry().sources}
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        dir=destination.parent,
        prefix=f".{destination.name}-",
        suffix=".tmp",
        delete=False,
    ) as stream:
        temporary_path = Path(stream.name)
    try:
        with sqlite3.connect(temporary_path) as database:
            database.execute("PRAGMA journal_mode = DELETE")
            database.execute(
                """CREATE VIRTUAL TABLE chunks USING fts5(
                    chunk_id UNINDEXED,
                    source_id UNINDEXED,
                    source_title UNINDEXED,
                    document_type UNINDEXED,
                    authority UNINDEXED,
                    topics UNINDEXED,
                    compilers UNINDEXED,
                    fortran_versions UNINDEXED,
                    version UNINDEXED,
                    revision UNINDEXED,
                    path UNINDEXED,
                    headings,
                    line_start UNINDEXED,
                    line_end UNINDEXED,
                    text,
                    url UNINDEXED,
                    tokenize = 'porter unicode61 remove_diacritics 2'
                )"""
            )
            count = 0
            seen_ids: set[str] = set()
            for chunk_path in chunk_paths:
                for chunk in _read_chunks(chunk_path):
                    if chunk.id in seen_ids:
                        raise SearchError(f"duplicate chunk ID: {chunk.id}")
                    seen_ids.add(chunk.id)
                    source = sources.get(chunk.source_id)
                    if source is None:
                        raise SearchError(f"chunk refers to unknown source: {chunk.source_id}")
                    if chunk.revision != source.revision:
                        raise SearchError(f"stale chunks for source: {chunk.source_id}")
                    database.execute(
                        "INSERT INTO chunks VALUES "
                        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            chunk.id,
                            chunk.source_id,
                            source.title,
                            source.document_type,
                            source.authority,
                            ",".join(source.topics),
                            ",".join(source.compilers),
                            ",".join(source.fortran_versions),
                            source.version,
                            chunk.revision,
                            chunk.path,
                            " > ".join(chunk.headings),
                            chunk.line_start,
                            chunk.line_end,
                            chunk.text,
                            str(_citation_url(source, chunk.path)),
                        ),
                    )
                    count += 1
            database.execute("INSERT INTO chunks(chunks) VALUES ('optimize')")
        del database
        gc.collect()
        _atomic_replace_temporary(temporary_path, destination)
    except BaseException as error:
        _unlink_temporary(temporary_path)
        raise error from None
    return count


def _fts_queries(query: str) -> tuple[str, str]:
    tokens = list(dict.fromkeys(QUERY_TOKEN.findall(query.casefold())))
    meaningful_tokens = [token for token in tokens if token not in STOP_WORDS]
    tokens = meaningful_tokens or tokens
    if not tokens:
        raise SearchError("query must contain searchable text")
    escaped = [f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens]
    return " AND ".join(escaped), " OR ".join(escaped)


def applicable_source_ids(
    *,
    source_id: str | None = None,
    compiler: str | None = None,
    version: str | None = None,
    fortran_version: str | None = None,
) -> tuple[str, ...] | None:
    """Resolve explicit applicability filters to registered source IDs."""
    if all(value is None for value in (source_id, compiler, version, fortran_version)):
        return None

    def matches(value: str, expected: str) -> bool:
        return value.casefold() == expected.casefold()

    return tuple(
        source.id
        for source in load_registry().sources
        if (source_id is None or source.id == source_id)
        and (compiler is None or any(matches(item, compiler) for item in source.compilers))
        and (version is None or matches(source.version, version))
        and (
            fortran_version is None
            or any(matches(item, fortran_version) for item in source.fortran_versions)
        )
    )


def search(
    query: str,
    *,
    limit: int = 5,
    source_id: str | None = None,
    compiler: str | None = None,
    version: str | None = None,
    fortran_version: str | None = None,
    index_path: Path = DEFAULT_INDEX_PATH,
) -> tuple[SearchResult, ...]:
    """Search documentation chunks using FTS5 BM25 ranking."""
    if not 1 <= limit <= 20:
        raise SearchError("limit must be between 1 and 20")
    if not index_path.is_file():
        raise SearchError(
            f"Fortran MCP core data is not installed at {index_path}. "
            "Run 'fortran-mcp data install core'."
        )
    source_ids = applicable_source_ids(
        source_id=source_id,
        compiler=compiler,
        version=version,
        fortran_version=fortran_version,
    )
    if source_ids == ():
        return ()
    strict_query, fallback_query = _fts_queries(query)
    sql = """SELECT chunk_id,
                    -bm25(chunks, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0,
                                  1.0, 1.0, 1.0, 1.0, 8.0, 1.0, 1.0, 1.0, 1.0) AS score,
                    source_id, source_title, document_type, authority, topics,
                    compilers, fortran_versions, version, revision, path, headings,
                    line_start, line_end, text, url
             FROM chunks WHERE chunks MATCH ?"""
    try:
        with sqlite3.connect(f"file:{index_path}?mode=ro", uri=True) as database:

            def execute(match_query: str) -> list[tuple[Any, ...]]:
                filtered_sql = sql
                parameters: list[str | int] = [match_query]
                if source_ids is not None:
                    placeholders = ", ".join("?" for _ in source_ids)
                    filtered_sql += f" AND source_id IN ({placeholders})"
                    parameters.extend(source_ids)
                filtered_sql += " ORDER BY score DESC, chunk_id LIMIT ?"
                parameters.append(limit)
                return database.execute(filtered_sql, parameters).fetchall()

            rows = execute(strict_query)
            if len(rows) < limit and fallback_query != strict_query:
                seen = {row[0] for row in rows}
                rows.extend(row for row in execute(fallback_query) if row[0] not in seen)
                rows = rows[:limit]
    except sqlite3.Error as error:
        raise SearchError(f"could not query search index: {error}") from error
    return tuple(_result_from_row(row) for row in rows)


def get_chunk(chunk_id: str, index_path: Path = DEFAULT_INDEX_PATH) -> SearchResult:
    """Retrieve one exact indexed chunk by its stable ID."""
    if not re.fullmatch(r"[0-9a-f]{32}", chunk_id):
        raise SearchError("chunk ID must be 32 lowercase hexadecimal characters")
    if not index_path.is_file():
        raise SearchError(
            f"Fortran MCP core data is not installed at {index_path}. "
            "Run 'fortran-mcp data install core'."
        )
    sql = """SELECT chunk_id, 0.0, source_id, source_title,
                    document_type, authority, topics, compilers, fortran_versions,
                    version, revision,
                    path, headings, line_start, line_end, text, url
             FROM chunks WHERE chunk_id = ?"""
    try:
        with sqlite3.connect(f"file:{index_path}?mode=ro", uri=True) as database:
            row = database.execute(sql, (chunk_id,)).fetchone()
    except sqlite3.Error as error:
        raise SearchError(f"could not query search index: {error}") from error
    if row is None:
        raise SearchError(f"chunk not found: {chunk_id}")
    return _result_from_row(row)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the local documentation search index")
    parser.add_argument("--data-dir", type=Path, default=data_directory())
    parser.add_argument("--index", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run the index-building command."""
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        count = build_index(args.data_dir, args.index)
    except SearchError as error:
        parser.error(str(error))
    print(f"Indexed {count} chunks")


if __name__ == "__main__":
    main()
