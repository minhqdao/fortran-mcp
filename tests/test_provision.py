"""Tests for interactive first-run data provisioning."""

import hashlib
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from fortran_mcp.bundle import build_bundle
from fortran_mcp.catalog import build_catalog
from fortran_mcp.documents import DocumentChunk
from fortran_mcp.provision import any_data_present, offer_data_install
from fortran_mcp.search import INDEX_FILENAME, build_index
from fortran_mcp.semantic import SEMANTIC_INDEX_FILENAME

ChunkFactory = Callable[[str, str], DocumentChunk]


def _chunk(chunk_id: str, text: str) -> DocumentChunk:
    return DocumentChunk(
        id=chunk_id,
        source_id="fpm-0.13.0-docs",
        revision="5097350c24ea7b5ceec233714f5a2604f79d0c02",
        path="pages/spec/manifest.md",
        headings=("Manifest reference", "OpenMP"),
        line_start=1,
        line_end=2,
        text=text,
        sha256="b" * 64,
    )


def _release(tmp_path: Path) -> Path:
    release_data = tmp_path / "release-data"
    chunks = release_data / "chunks"
    chunks.mkdir(parents=True)
    (chunks / "fpm.jsonl").write_text(
        _chunk(
            "a" * 32, "Add OpenMP as a built-in metapackage dependency in fpm.toml."
        ).model_dump_json()
        + "\n"
    )
    build_index(release_data)
    lexical_sha = hashlib.sha256((release_data / INDEX_FILENAME).read_bytes()).hexdigest()
    with sqlite3.connect(release_data / SEMANTIC_INDEX_FILENAME) as database:
        database.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        database.execute(
            "CREATE TABLE vectors("
            "chunk_id TEXT PRIMARY KEY, source_id TEXT, content_sha256 TEXT, embedding BLOB)"
        )
        database.executemany(
            "INSERT INTO metadata VALUES (?, ?)",
            (
                ("schema_version", "2"),
                ("model", "fake-model"),
                ("dimensions", "2"),
                ("lexical_index_sha256", lexical_sha),
            ),
        )
    licenses = tmp_path / "licenses"
    licenses.mkdir()
    (licenses / "fpm-0.13.0-docs.txt").write_text("MIT\n")
    release = tmp_path / "release"
    release.mkdir()
    core = release / "fortran-mcp-core.zip"
    semantic = release / "fortran-mcp-semantic.zip"
    build_bundle("core", core, data_dir=release_data, license_dir=licenses)
    build_bundle("semantic", semantic, data_dir=release_data, license_dir=licenses)
    catalog = release / "catalog.json"
    build_catalog("2026.08.1", catalog, [core, semantic])
    return catalog


def _offer(tmp_path: Path, catalog: Path, answer: str) -> tuple[bool, list[str], list[str]]:
    prompts: list[str] = []
    messages: list[str] = []

    def prompt(text: str) -> str:
        prompts.append(text)
        return answer

    installed = offer_data_install(
        data_dir=tmp_path / "installed",
        catalog_location=catalog,
        interactive=True,
        prompt=prompt,
        message=messages.append,
    )
    return installed, prompts, messages


def test_choice_one_installs_only_core(tmp_path: Path) -> None:
    catalog = _release(tmp_path)

    installed, prompts, messages = _offer(tmp_path, catalog, "1")

    data_dir = tmp_path / "installed"
    assert installed is True
    assert len(prompts) == 1
    assert (data_dir / "manifests" / "core.json").is_file()
    assert (data_dir / INDEX_FILENAME).is_file()
    assert not (data_dir / "manifests" / "semantic.json").exists()
    assert any("MB (lexical search)" in text for text in messages)


def test_choice_two_installs_core_and_semantic(tmp_path: Path) -> None:
    catalog = _release(tmp_path)

    installed, prompts, messages = _offer(tmp_path, catalog, "2")

    data_dir = tmp_path / "installed"
    assert installed is True
    assert len(prompts) == 1
    assert (data_dir / "manifests" / "core.json").is_file()
    assert (data_dir / "manifests" / "semantic.json").is_file()
    assert (data_dir / SEMANTIC_INDEX_FILENAME).is_file()
    assert any("adds semantic and hybrid search" in text for text in messages)


@pytest.mark.parametrize("answer", ["3", "", "x", "yes"])
def test_other_answers_install_nothing(tmp_path: Path, answer: str) -> None:
    catalog = _release(tmp_path)

    installed, _, messages = _offer(tmp_path, catalog, answer)

    data_dir = tmp_path / "installed"
    assert installed is False
    assert not (data_dir / "manifests").exists()
    assert any("fortran-mcp data install" in text for text in messages)


def test_non_interactive_session_prints_hint_without_prompting(tmp_path: Path) -> None:
    prompts: list[str] = []
    messages: list[str] = []

    def prompt(text: str) -> str:
        prompts.append(text)
        return ""

    installed = offer_data_install(
        data_dir=tmp_path / "installed",
        interactive=False,
        prompt=prompt,
        message=messages.append,
    )

    assert installed is False
    assert prompts == []
    assert any("fortran-mcp data install core" in text for text in messages)


@pytest.mark.parametrize(
    "relative",
    [
        Path("manifests") / "core.json",
        Path("manifests") / "semantic.json",
        INDEX_FILENAME,
        SEMANTIC_INDEX_FILENAME,
    ],
)
def test_existing_data_suppresses_the_prompt(tmp_path: Path, relative: Path) -> None:
    data_dir = tmp_path / "installed"
    (data_dir / relative).parent.mkdir(parents=True, exist_ok=True)
    (data_dir / relative).write_text("{}\n")

    prompts: list[str] = []
    messages: list[str] = []

    def prompt(text: str) -> str:
        prompts.append(text)
        return "1"

    installed = offer_data_install(
        data_dir=data_dir,
        catalog_location=tmp_path / "missing-catalog.json",
        interactive=True,
        prompt=prompt,
        message=messages.append,
    )

    assert any_data_present(data_dir) is True
    assert installed is False
    assert prompts == []
    assert messages == []


def test_unreachable_catalog_is_reported_without_crashing(tmp_path: Path) -> None:
    prompts: list[str] = []
    messages: list[str] = []

    def prompt(text: str) -> str:
        prompts.append(text)
        return "1"

    installed = offer_data_install(
        data_dir=tmp_path / "installed",
        catalog_location=tmp_path / "missing-catalog.json",
        interactive=True,
        prompt=prompt,
        message=messages.append,
    )

    assert installed is False
    assert prompts == []
    assert any("could not read catalog" in text for text in messages)
