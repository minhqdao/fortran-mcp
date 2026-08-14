"""Tests for safe documentation ingestion."""

import hashlib
import subprocess
import tarfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

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
    source = _source()
    readme = b"# fpm\n"
    archive = _archive(
        {
            f"{source.archive_root}/pages/index.md": readme,
            f"{source.archive_root}/pages/image.png": b"not documentation",
            f"{source.archive_root}/src/main.py": b"print('not documentation')\n",
        }
    )
    retrieved_at = datetime(2026, 8, 13, 12, tzinfo=UTC)

    record = ingest_source(
        source,
        tmp_path,
        downloader=lambda _url, _timeout, _limit: archive,
        retrieved_at=retrieved_at,
    )

    assert (tmp_path / "raw/fpm-0.13.0-docs/pages/index.md").read_bytes() == readme
    assert record.archive_sha256 == hashlib.sha256(archive).hexdigest()
    assert record.files[0].sha256 == hashlib.sha256(readme).hexdigest()
    assert (tmp_path / "records/fpm-0.13.0-docs.json").is_file()


def test_ingestion_rejects_an_unapproved_source(tmp_path: Path) -> None:
    source = _source().model_copy(update={"status": "candidate"})

    with pytest.raises(IngestionError, match="not approved"):
        ingest_source(source, tmp_path, downloader=lambda _url, _timeout, _limit: b"")


def test_ingestion_rejects_unsafe_archive_paths(tmp_path: Path) -> None:
    archive = _archive({"../fpm-docs/pages/escape.md": b"escape"})

    with pytest.raises(IngestionError, match="unsafe archive path"):
        ingest_source(
            _source(),
            tmp_path,
            downloader=lambda _url, _timeout, _limit: archive,
        )


def test_ingestion_does_not_overwrite_existing_data(tmp_path: Path) -> None:
    source = _source()
    archive = _archive({f"{source.archive_root}/pages/index.md": b"# fpm\n"})

    def downloader(_url: str, _timeout: int, _limit: int) -> bytes:
        return archive

    ingest_source(source, tmp_path, downloader=downloader)

    with pytest.raises(IngestionError, match="already been ingested"):
        ingest_source(source, tmp_path, downloader=downloader)


def test_texinfo_ingestion_records_generated_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = (
        load_registry(REGISTRY_PATH).sources[2].model_copy(update={"expected_document_count": 1})
    )
    archive = _archive(
        {f"{source.archive_root}/{path}": b"@c fixture\n" for path in source.include_paths}
    )
    monkeypatch.setattr("fortran_mcp.ingest.shutil.which", lambda _name: "/usr/bin/makeinfo")

    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if "--version" in command:
            return subprocess.CompletedProcess(command, 0, "texi2any (GNU texinfo) 7.3\n", "")
        output_argument = next(item for item in command if item.startswith("--output="))
        html_dir = Path(output_argument.removeprefix("--output="))
        html_dir.mkdir()
        (html_dir / "index.html").write_text(
            "<html><body><h1>GNU Fortran</h1><p>Compiler manual.</p></body></html>"
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("fortran_mcp.ingest.subprocess.run", fake_run)

    record = ingest_source(source, tmp_path, downloader=lambda *_args: archive)

    generated = tmp_path / f"raw/{source.id}/manual/index.md"
    assert record.schema_version == 2
    assert record.converter == "texinfo"
    assert record.converter_version == "texi2any (GNU texinfo) 7.3"
    assert generated.read_text().startswith("# GNU Fortran")


def test_cmake_rst_ingestion_expands_includes_and_generates_markdown(tmp_path: Path) -> None:
    source = (
        load_registry(REGISTRY_PATH)
        .sources[3]
        .model_copy(
            update={
                "include_paths": (
                    "Modules/CheckFortranSourceCompiles.cmake",
                    "Help/module/include/CMAKE_REQUIRED_FLAGS.rst",
                ),
                "expected_document_count": 1,
            }
        )
    )
    archive = _archive(
        {
            f"{source.archive_root}/Modules/CheckFortranSourceCompiles.cmake": b"""
#[==[.rst:
CheckFortranSourceCompiles
--------------------------

.. command:: check_fortran_source_compiles

  Use :variable:`CMAKE_REQUIRED_FLAGS`:

  .. include:: /module/include/CMAKE_REQUIRED_FLAGS.rst

  .. code-block:: cmake

    check_fortran_source_compiles(\"program main\\nend\" WORKS)
#]==]
""",
            f"{source.archive_root}/Help/module/include/CMAKE_REQUIRED_FLAGS.rst": b"""
``CMAKE_REQUIRED_FLAGS``
  Compiler flags used by the check.
""",
        }
    )

    record = ingest_source(source, tmp_path, downloader=lambda *_args: archive)

    generated = tmp_path / f"raw/{source.id}/manual/module/CheckFortranSourceCompiles.md"
    markdown = generated.read_text()
    assert record.converter == "cmake-rst"
    assert record.converter_version == "builtin cmake-rst 1"
    assert markdown.startswith("# CheckFortranSourceCompiles")
    assert "### `check_fortran_source_compiles`" in markdown
    assert "`CMAKE_REQUIRED_FLAGS`" in markdown
    assert "```cmake" in markdown


def test_fortran_lang_intrinsics_are_grouped_without_tiny_heading_chunks(tmp_path: Path) -> None:
    source = (
        load_registry(REGISTRY_PATH).sources[4].model_copy(update={"expected_document_count": 2})
    )
    archive = _archive(
        {
            f"{source.archive_root}/data/intrinsics.yml": b'numeric:\n  - "ABS"\n',
            f"{source.archive_root}/source/learn/intrinsics/index.md": b"# Intrinsics\n",
            f"{source.archive_root}/source/learn/intrinsics/_pages/ABS.md": b"""
(abs)=
## abs

### **Name**

Absolute value.

### **Synopsis**

```fortran
result = abs(a)
```
""",
        }
    )

    record = ingest_source(source, tmp_path, downloader=lambda *_args: archive)

    generated = tmp_path / f"raw/{source.id}/manual/learn/intrinsics/numeric/index.md"
    markdown = generated.read_text()
    assert record.converter == "fortran-lang-markdown"
    assert markdown.startswith("# Numeric Fortran intrinsics\n\n## abs")
    assert "**Name**" in markdown
    assert "### **Name**" not in markdown


def test_ingestion_rejects_unexpected_document_count(tmp_path: Path) -> None:
    source = _source().model_copy(update={"expected_document_count": 2})
    archive = _archive({f"{source.archive_root}/pages/index.md": b"# fpm\n"})

    with pytest.raises(IngestionError, match="expected 2 document files; found 1"):
        ingest_source(source, tmp_path, downloader=lambda *_args: archive)
