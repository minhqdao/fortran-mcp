"""Safely ingest approved documentation archives."""

import argparse
import hashlib
import json
import tarfile
import tempfile
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import cast
from urllib.request import Request, urlopen

from pydantic import HttpUrl

from fortran_mcp.sources import (
    FileRecord,
    IngestionRecord,
    RedistributionPolicy,
    Source,
    SourceStatus,
    load_registry,
)

DEFAULT_DATA_DIR = Path("data")
DOWNLOAD_LIMIT = 50 * 1024 * 1024
FILE_LIMIT = 5 * 1024 * 1024
TOTAL_CONTENT_LIMIT = 100 * 1024 * 1024
ALLOWED_SUFFIXES = frozenset({".f90", ".md", ".markdown", ".rst", ".toml", ".txt"})
Downloader = Callable[[str, int, int], bytes]


class IngestionError(RuntimeError):
    """Raised when a source cannot be ingested safely."""


def download(url: str, timeout: int, limit: int) -> bytes:
    """Download a URL while enforcing a maximum response size."""
    request = Request(url, headers={"User-Agent": "fortran-mcp/0.1"})
    with urlopen(request, timeout=timeout) as response:
        declared_size = response.headers.get("Content-Length")
        if declared_size is not None and int(declared_size) > limit:
            raise IngestionError(f"download exceeds {limit} bytes")
        content = cast("bytes", response.read(limit + 1))
    if len(content) > limit:
        raise IngestionError(f"download exceeds {limit} bytes")
    return content


def _relative_document_path(member_name: str, source: Source) -> PurePosixPath | None:
    member_path = PurePosixPath(member_name)
    if member_path.is_absolute() or ".." in member_path.parts:
        raise IngestionError(f"unsafe archive path: {member_name}")
    try:
        relative = member_path.relative_to(PurePosixPath(source.archive_root))
    except ValueError:
        return None
    included = any(
        relative.is_relative_to(PurePosixPath(pattern.removesuffix("/**")))
        if pattern.endswith("/**")
        else relative == PurePosixPath(pattern)
        for pattern in source.include_paths
    )
    if not included or not relative.parts or relative.suffix.lower() not in ALLOWED_SUFFIXES:
        return None
    return relative


def _extract_documents(archive: bytes, source: Source, destination: Path) -> tuple[FileRecord, ...]:
    records: list[FileRecord] = []
    total_size = 0
    try:
        with tarfile.open(fileobj=BytesIO(archive), mode="r:gz") as opened_archive:
            for member in opened_archive:
                relative = _relative_document_path(member.name, source)
                if relative is None or not member.isfile():
                    continue
                if member.size > FILE_LIMIT:
                    raise IngestionError(f"file exceeds {FILE_LIMIT} bytes: {relative}")
                total_size += member.size
                if total_size > TOTAL_CONTENT_LIMIT:
                    raise IngestionError(f"extracted content exceeds {TOTAL_CONTENT_LIMIT} bytes")
                stream = opened_archive.extractfile(member)
                if stream is None:
                    raise IngestionError(f"could not read archive member: {relative}")
                content = stream.read(FILE_LIMIT + 1)
                if len(content) != member.size:
                    raise IngestionError(f"archive member size mismatch: {relative}")
                try:
                    content.decode("utf-8")
                except UnicodeDecodeError as error:
                    raise IngestionError(f"documentation is not UTF-8: {relative}") from error

                output_path = destination.joinpath(*relative.parts)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(content)
                records.append(
                    FileRecord(
                        path=relative.as_posix(),
                        size=len(content),
                        sha256=hashlib.sha256(content).hexdigest(),
                    )
                )
    except tarfile.TarError as error:
        raise IngestionError("source is not a valid tar.gz archive") from error

    if not records:
        raise IngestionError("archive contained no supported documentation files")
    return tuple(sorted(records, key=lambda record: record.path))


def ingest_source(
    source: Source,
    data_dir: Path = DEFAULT_DATA_DIR,
    *,
    downloader: Downloader = download,
    retrieved_at: datetime | None = None,
) -> IngestionRecord:
    """Download and persist one approved, redistributable source."""
    if source.status is not SourceStatus.APPROVED:
        raise IngestionError(f"source is not approved: {source.id}")
    if source.redistribution is not RedistributionPolicy.REDISTRIBUTABLE:
        raise IngestionError(f"source is not redistributable: {source.id}")

    source_dir = data_dir / "raw" / source.id
    record_path = data_dir / "records" / f"{source.id}.json"
    if source_dir.exists() or record_path.exists():
        raise IngestionError(f"source has already been ingested: {source.id}")

    archive = downloader(str(source.archive_url), 30, DOWNLOAD_LIMIT)
    timestamp = retrieved_at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise IngestionError("retrieval time must include a timezone")

    data_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{source.id}-", dir=data_dir) as temporary:
        temporary_path = Path(temporary)
        stored_files = _extract_documents(archive, source, temporary_path)
        record = IngestionRecord(
            source_id=source.id,
            revision=source.revision,
            archive_url=HttpUrl(str(source.archive_url)),
            archive_sha256=hashlib.sha256(archive).hexdigest(),
            retrieved_at=timestamp,
            document_paths=source.document_paths,
            files=stored_files,
        )
        source_dir.parent.mkdir(parents=True, exist_ok=True)
        temporary_path.replace(source_dir)
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(
            json.dumps(record.model_dump(mode="json"), indent=2) + "\n",
            encoding="utf-8",
        )
    return record


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest an approved Fortran documentation source")
    parser.add_argument("source_id", help="ID from docs/sources.toml")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="storage directory (default: data)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run the ingestion command."""
    parser = _parser()
    args = parser.parse_args(argv)
    registry = load_registry()
    source = next((item for item in registry.sources if item.id == args.source_id), None)
    if source is None:
        parser.error(f"unknown source ID: {args.source_id}")
    try:
        record = ingest_source(source, args.data_dir)
    except IngestionError as error:
        parser.error(str(error))
    print(f"Ingested {len(record.files)} files from {record.source_id}")


if __name__ == "__main__":
    main()
