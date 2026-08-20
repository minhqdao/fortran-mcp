"""Normalize ingested documents into deterministic, citation-ready chunks."""

import argparse
import hashlib
import json
import re
import tempfile
from collections.abc import Iterator, Sequence
from pathlib import Path
from posixpath import normpath
from typing import Self

from pydantic import Field, model_validator

from fortran_mcp.config import data_directory
from fortran_mcp.ingest import IngestionError
from fortran_mcp.sources import IngestionRecord, StrictModel, load_registry

MAX_CHUNK_CHARS = 4_000
HEADING = re.compile(r"^(#{1,6})\s+(.+?)(?:\s+#+)?$")
LITERAL_INCLUDE = re.compile(r"^```\{literalinclude\}\s+(.+?)\s*$")
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
INLINE_SECTION_TITLES = frozenset(
    {
        "argument",
        "arguments",
        "class",
        "input parameter",
        "input parameters",
        "input/output parameter",
        "input/output parameters",
        "output parameter",
        "output parameters",
        "result",
        "result value",
        "return value",
        "status",
    }
)


class DocumentChunk(StrictModel):
    """A stable piece of source text with citation coordinates."""

    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    source_id: str
    revision: str
    path: str
    headings: tuple[str, ...]
    included_paths: tuple[str, ...] = ()
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    text: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def line_range_is_ordered(self) -> Self:
        if self.line_end < self.line_start:
            raise ValueError("line_end must not precede line_start")
        return self


class DocumentBuildError(RuntimeError):
    """Raised when ingested documents cannot be built safely."""


def _content_start(lines: list[str]) -> int:
    if not lines or lines[0].strip() != "---":
        return 0
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return index + 1
    return 0


def _has_substantive_body(lines: list[str]) -> bool:
    """Return whether a section contains more than headings, comments, and whitespace."""
    without_comments = HTML_COMMENT.sub("", "\n".join(lines))
    return any(
        line.strip() and HEADING.match(line) is None for line in without_comments.splitlines()
    )


def _sections(lines: list[str]) -> Iterator[tuple[tuple[str, ...], int, int]]:
    start = _content_start(lines)
    section_start = start
    headings: list[str] = []
    section_headings: tuple[str, ...] = ()
    in_fence = False

    for index in range(start, len(lines)):
        stripped = lines[index].lstrip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
        match = None if in_fence else HEADING.match(lines[index])
        if match is None:
            continue
        level = len(match.group(1))
        title = match.group(2).strip()
        headings[level - 1 :] = [title]
        if title.casefold() in INLINE_SECTION_TITLES:
            continue
        if index > section_start and _has_substantive_body(lines[section_start:index]):
            yield section_headings, section_start, index - 1
            section_start = index
        else:
            # Keep structural container headings in the text, but use the nearest one as metadata.
            section_start = min(section_start, index)
        section_headings = tuple(headings)

    if section_start < len(lines) and _has_substantive_body(lines[section_start:]):
        yield section_headings, section_start, len(lines) - 1


def _bounded_ranges(lines: list[str], start: int, end: int) -> Iterator[tuple[int, int]]:
    chunk_start = start
    size = 0
    last_blank: int | None = None
    index = start
    while index <= end:
        line_size = len(lines[index]) + 1
        if size and size + line_size > MAX_CHUNK_CHARS:
            chunk_end = (
                last_blank if last_blank is not None and last_blank > chunk_start + 1 else index - 1
            )
            yield chunk_start, chunk_end
            chunk_start = chunk_end + 1
            while chunk_start <= end and not lines[chunk_start].strip():
                chunk_start += 1
            index = chunk_start
            size = 0
            last_blank = None
            continue
        size += line_size
        if not lines[index].strip():
            last_blank = index
        index += 1
    if chunk_start <= end:
        yield chunk_start, end


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    candidate = Path(path)
    return any(
        candidate.is_relative_to(Path(pattern.removesuffix("/**")))
        if pattern.endswith("/**")
        else candidate == Path(pattern)
        for pattern in patterns
    )


def _render_range(
    lines: list[str],
    start: int,
    end: int,
    *,
    page_path: str,
    documents: dict[str, str],
) -> tuple[str, tuple[str, ...]]:
    rendered: list[str] = []
    included_paths: list[str] = []
    index = start
    while index <= end:
        match = LITERAL_INCLUDE.match(lines[index])
        if match is None:
            rendered.append(lines[index])
            index += 1
            continue

        relative_target = match.group(1)
        target = normpath((Path(page_path).parent / relative_target).as_posix())
        if target.startswith("../") or target not in documents:
            raise DocumentBuildError(f"literal include not found: {page_path}: {relative_target}")
        suffix = Path(target).suffix.lstrip(".")
        rendered.extend((f"```{suffix}", documents[target].rstrip(), "```"))
        included_paths.append(target)
        index += 1
        while index <= end and not lines[index].startswith("```"):
            index += 1
        if index <= end:
            index += 1
    return "\n".join(rendered).strip(), tuple(included_paths)


def _chunks_for_file(
    content: str,
    *,
    source_id: str,
    revision: str,
    path: str,
    documents: dict[str, str],
) -> Iterator[DocumentChunk]:
    lines = content.splitlines()
    for headings, section_start, section_end in _sections(lines):
        for start, end in _bounded_ranges(lines, section_start, section_end):
            text, included_paths = _render_range(
                lines,
                start,
                end,
                page_path=path,
                documents=documents,
            )
            if not text:
                continue
            content_hash = hashlib.sha256(text.encode()).hexdigest()
            identity = f"{source_id}\0{revision}\0{path}\0{start + 1}\0{end + 1}\0{content_hash}"
            yield DocumentChunk(
                id=hashlib.sha256(identity.encode()).hexdigest()[:32],
                source_id=source_id,
                revision=revision,
                path=path,
                headings=headings,
                included_paths=included_paths,
                line_start=start + 1,
                line_end=end + 1,
                text=text,
                sha256=content_hash,
            )


def build_documents(source_id: str, data_dir: Path | None = None) -> tuple[DocumentChunk, ...]:
    """Verify raw files and build deterministic chunks for one source."""
    data_dir = data_dir or data_directory()
    record_path = data_dir / "records" / f"{source_id}.json"
    if not record_path.is_file():
        raise DocumentBuildError(f"ingestion record not found: {source_id}")
    try:
        record = IngestionRecord.model_validate_json(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise DocumentBuildError(f"invalid ingestion record: {source_id}") from error
    if record.source_id != source_id:
        raise DocumentBuildError("ingestion record source ID does not match its filename")
    registry = {source.id: source for source in load_registry().sources}
    source = registry.get(source_id)
    if source is None or source.revision != record.revision:
        raise DocumentBuildError(f"source registry does not match ingestion record: {source_id}")

    documents: dict[str, str] = {}
    raw_dir = data_dir / "raw" / source_id
    for file_record in record.files:
        path = raw_dir.joinpath(*Path(file_record.path).parts)
        if not path.is_file():
            raise DocumentBuildError(f"ingested file is missing: {file_record.path}")
        content_bytes = path.read_bytes()
        if hashlib.sha256(content_bytes).hexdigest() != file_record.sha256:
            raise DocumentBuildError(f"checksum mismatch: {file_record.path}")
        try:
            content = content_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise DocumentBuildError(f"document is not UTF-8: {file_record.path}") from error
        documents[file_record.path] = content

    chunks: list[DocumentChunk] = []
    for file_record in record.files:
        if not _matches(file_record.path, record.document_paths) or _matches(
            file_record.path, source.excluded_document_paths
        ):
            continue
        chunks.extend(
            _chunks_for_file(
                documents[file_record.path],
                source_id=source_id,
                revision=record.revision,
                path=file_record.path,
                documents=documents,
            )
        )

    output_dir = data_dir / "chunks"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{source_id}.jsonl"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=output_dir,
        prefix=f".{source_id}-",
        suffix=".jsonl",
        delete=False,
    ) as stream:
        temporary_path = Path(stream.name)
        for chunk in chunks:
            stream.write(json.dumps(chunk.model_dump(mode="json"), ensure_ascii=False) + "\n")
    temporary_path.replace(output_path)
    return tuple(chunks)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build citation-ready documentation chunks")
    parser.add_argument("source_id", help="ID of an ingested documentation source")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=data_directory(),
        help="storage directory (default: data)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run the document build command."""
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        chunks = build_documents(args.source_id, args.data_dir)
    except (DocumentBuildError, IngestionError) as error:
        parser.error(str(error))
    print(f"Built {len(chunks)} chunks from {args.source_id}")


if __name__ == "__main__":
    main()
