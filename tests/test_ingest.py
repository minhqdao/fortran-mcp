"""Tests for safe documentation ingestion."""

import hashlib
import tarfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

import pytest

from fortran_mcp.ingest import IngestionError, ingest_source
from fortran_mcp.sources import Source, load_registry

REGISTRY_PATH = Path(__file__).parents[1] / "docs" / "sources.toml"


def _archive(files: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, BytesIO(content))
    return buffer.getvalue()


def _source() -> Source:
    return load_registry(REGISTRY_PATH).sources[0]


def test_ingestion_stores_text_documents_and_provenance(tmp_path: Path) -> None:
    readme = b"# fpm\n"
    archive = _archive(
        {
            "fpm-0.13.0/README.md": readme,
            "fpm-0.13.0/doc/image.png": b"not documentation",
            "fpm-0.13.0/src/main.f90": b"program main\nend program\n",
        }
    )
    retrieved_at = datetime(2026, 8, 13, 12, tzinfo=UTC)

    record = ingest_source(
        _source(),
        tmp_path,
        downloader=lambda _url, _timeout, _limit: archive,
        retrieved_at=retrieved_at,
    )

    assert (tmp_path / "raw/fpm-0.13.0-docs/README.md").read_bytes() == readme
    assert record.archive_sha256 == hashlib.sha256(archive).hexdigest()
    assert record.files[0].sha256 == hashlib.sha256(readme).hexdigest()
    assert (tmp_path / "records/fpm-0.13.0-docs.json").is_file()


def test_ingestion_rejects_an_unapproved_source(tmp_path: Path) -> None:
    source = _source().model_copy(update={"status": "candidate"})

    with pytest.raises(IngestionError, match="not approved"):
        ingest_source(source, tmp_path, downloader=lambda _url, _timeout, _limit: b"")


def test_ingestion_rejects_unsafe_archive_paths(tmp_path: Path) -> None:
    archive = _archive({"../fpm-0.13.0/doc/escape.md": b"escape"})

    with pytest.raises(IngestionError, match="unsafe archive path"):
        ingest_source(
            _source(),
            tmp_path,
            downloader=lambda _url, _timeout, _limit: archive,
        )


def test_ingestion_does_not_overwrite_existing_data(tmp_path: Path) -> None:
    archive = _archive({"fpm-0.13.0/README.md": b"# fpm\n"})

    def downloader(_url: str, _timeout: int, _limit: int) -> bytes:
        return archive

    ingest_source(_source(), tmp_path, downloader=downloader)

    with pytest.raises(IngestionError, match="already been ingested"):
        ingest_source(_source(), tmp_path, downloader=downloader)
