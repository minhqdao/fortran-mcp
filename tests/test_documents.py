"""Tests for deterministic document normalization and chunking."""

import tarfile
from io import BytesIO
from pathlib import Path

import pytest

from fortran_mcp.documents import DocumentBuildError, build_documents
from fortran_mcp.ingest import ingest_source
from fortran_mcp.sources import Source, load_registry

REGISTRY_PATH = Path(__file__).parents[1] / "docs" / "sources.toml"


def _source() -> Source:
    return load_registry(REGISTRY_PATH).sources[0]


def _archive(source: Source, content: bytes) -> bytes:
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        files = {
            f"{source.archive_root}/pages/guide.md": content,
            f"{source.archive_root}/src/example.toml": b'name = "demo"\n',
        }
        for name, file_content in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(file_content)
            archive.addfile(member, BytesIO(file_content))
    return buffer.getvalue()


def _ingest_fixture(tmp_path: Path) -> None:
    source = _source()
    content = (
        b"---\ntitle: Guide\n---\n# Guide\nIntro.\n\n## Build\n"
        b"```{literalinclude} ../src/example.toml\n```\n"
    )
    archive = _archive(source, content)
    ingest_source(source, tmp_path, downloader=lambda _url, _timeout, _limit: archive)


def test_build_preserves_headings_and_source_lines(tmp_path: Path) -> None:
    _ingest_fixture(tmp_path)

    chunks = build_documents("fpm-0.13.0-docs", tmp_path)

    assert [chunk.headings for chunk in chunks] == [("Guide",), ("Guide", "Build")]
    assert chunks[0].line_start == 4
    assert chunks[1].line_start == 7
    assert "title: Guide" not in chunks[0].text
    assert 'name = "demo"' in chunks[1].text
    assert chunks[1].included_paths == ("src/example.toml",)


def test_build_is_deterministic(tmp_path: Path) -> None:
    _ingest_fixture(tmp_path)

    first = build_documents("fpm-0.13.0-docs", tmp_path)
    first_output = (tmp_path / "chunks/fpm-0.13.0-docs.jsonl").read_bytes()
    second = build_documents("fpm-0.13.0-docs", tmp_path)

    assert first == second
    assert first_output == (tmp_path / "chunks/fpm-0.13.0-docs.jsonl").read_bytes()


def test_build_rejects_modified_raw_content(tmp_path: Path) -> None:
    _ingest_fixture(tmp_path)
    document = tmp_path / "raw/fpm-0.13.0-docs/pages/guide.md"
    document.write_text("modified", encoding="utf-8")

    with pytest.raises(DocumentBuildError, match="checksum mismatch"):
        build_documents("fpm-0.13.0-docs", tmp_path)


def test_long_section_does_not_orphan_its_heading(tmp_path: Path) -> None:
    source = _source()
    content = (
        "# Options\n\n" + "\n".join(f"- option {index}: " + "x" * 120 for index in range(50))
    ).encode()
    archive = _archive(source, content)
    ingest_source(source, tmp_path, downloader=lambda _url, _timeout, _limit: archive)

    chunks = build_documents(source.id, tmp_path)

    assert chunks[0].text.startswith("# Options\n\n- option 0:")
    assert all(chunk.text != "# Options" for chunk in chunks)
