"""Safely ingest approved documentation archives."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Literal, cast
from urllib.request import Request, urlopen

from pydantic import HttpUrl

from fortran_mcp.config import data_directory
from fortran_mcp.sources import (
    FileRecord,
    IngestionRecord,
    RedistributionPolicy,
    Source,
    SourceStatus,
    load_registry,
)

DOWNLOAD_LIMIT = 128 * 1024 * 1024
FILE_LIMIT = 5 * 1024 * 1024
TOTAL_CONTENT_LIMIT = 100 * 1024 * 1024
ALLOWED_SUFFIXES = frozenset({".f90", ".md", ".markdown", ".rst", ".texi", ".toml", ".txt"})
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


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    candidate = PurePosixPath(path)
    return any(
        candidate.is_relative_to(PurePosixPath(pattern.removesuffix("/**")))
        if pattern.endswith("/**")
        else candidate == PurePosixPath(pattern)
        for pattern in patterns
    )


def _extract_documents(archive: bytes, source: Source, destination: Path) -> tuple[FileRecord, ...]:
    records: list[FileRecord] = []
    total_size = 0
    try:
        with tarfile.open(fileobj=BytesIO(archive), mode="r:*") as opened_archive:
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
        raise IngestionError("source is not a supported tar archive") from error

    if not records:
        raise IngestionError("archive contained no supported documentation files")
    return tuple(sorted(records, key=lambda record: record.path))


def _record_file(path: Path, root: Path) -> FileRecord:
    content = path.read_bytes()
    return FileRecord(
        path=path.relative_to(root).as_posix(),
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def _convert_texinfo(source: Source, root: Path) -> tuple[tuple[FileRecord, ...], str]:
    executable = shutil.which("makeinfo") or shutil.which("texi2any")
    if executable is None:
        raise IngestionError(
            "Texinfo conversion requires makeinfo 7.3; install GNU Texinfo and add it to PATH"
        )
    try:
        version_output = subprocess.run(
            [executable, "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError) as error:
        raise IngestionError(f"could not run Texinfo converter: {error}") from error
    first_line = version_output.splitlines()[0] if version_output else ""
    version = first_line.rsplit(" ", 1)[-1]
    if version != "7.3":
        found = version or "unknown"
        raise IngestionError(f"Texinfo conversion requires makeinfo 7.3; found {found}")

    entrypoint = root / str(source.converter_entrypoint)
    if not entrypoint.is_file():
        raise IngestionError(f"Texinfo entrypoint is unavailable: {source.converter_entrypoint}")
    include_dir = root / "gcc/doc/include"
    version_file = include_dir / "gcc-vers.texi"
    version_file.write_text(
        f"@set version-GCC {source.version}\n@clear DEVELOPMENT\n@set srcdir .\n",
        encoding="utf-8",
    )
    html_dir = root / ".generated-html"
    output_dir = root / "manual"
    environment = {**os.environ, "LC_ALL": "C.UTF-8"}
    try:
        subprocess.run(
            [
                executable,
                "--html",
                "-I",
                str(include_dir),
                f"--output={html_dir}",
                str(entrypoint),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as error:
        detail = getattr(error, "stderr", None) or str(error)
        raise IngestionError(f"Texinfo conversion failed: {detail.strip()}") from error
    finally:
        version_file.unlink(missing_ok=True)

    try:
        from html_to_markdown import ConversionOptions, convert
    except ImportError as error:
        raise IngestionError(
            "Texinfo conversion requires the 'ingest' extra: install fortran-mcp[ingest]"
        ) from error

    output_dir.mkdir()
    records: list[FileRecord] = []
    options = ConversionOptions(
        extract_metadata=False,
        exclude_selectors=[".nav-panel", ".copiable-link", "hr"],
    )
    for html_path in sorted(html_dir.glob("*.html")):
        result = convert(html_path.read_text(encoding="utf-8"), options)
        markdown = (result.content or "").strip()
        if not markdown:
            continue
        output_path = output_dir / f"{html_path.stem}.md"
        output_path.write_text(markdown + "\n", encoding="utf-8")
        records.append(_record_file(output_path, root))
    shutil.rmtree(html_dir)
    if not records:
        raise IngestionError("Texinfo conversion produced no documentation pages")
    return tuple(records), first_line


def ingest_source(
    source: Source,
    data_dir: Path | None = None,
    *,
    downloader: Downloader = download,
    retrieved_at: datetime | None = None,
) -> IngestionRecord:
    """Download and persist one approved, redistributable source."""
    if source.status is not SourceStatus.APPROVED:
        raise IngestionError(f"source is not approved: {source.id}")
    if source.redistribution is not RedistributionPolicy.REDISTRIBUTABLE:
        raise IngestionError(f"source is not redistributable: {source.id}")

    data_dir = data_dir or data_directory()
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
        converter_version: str | None = None
        schema_version: Literal[1, 2] = 1
        if source.converter == "texinfo":
            generated, converter_version = _convert_texinfo(source, temporary_path)
            stored_files = tuple(sorted((*stored_files, *generated), key=lambda item: item.path))
            schema_version = 2
        document_count = sum(_matches(file.path, source.document_paths) for file in stored_files)
        if (
            source.expected_document_count is not None
            and document_count != source.expected_document_count
        ):
            raise IngestionError(
                f"expected {source.expected_document_count} document files; found {document_count}"
            )
        record = IngestionRecord(
            schema_version=schema_version,
            source_id=source.id,
            revision=source.revision,
            archive_url=HttpUrl(str(source.archive_url)),
            archive_sha256=hashlib.sha256(archive).hexdigest(),
            retrieved_at=timestamp,
            document_paths=source.document_paths,
            files=stored_files,
            converter=None if source.converter == "none" else source.converter,
            converter_version=converter_version,
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
        default=data_directory(),
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
