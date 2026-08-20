"""Tests for safe documentation ingestion."""

import hashlib
import subprocess
import tarfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

from fortran_mcp.ingest import (
    CODEE_FORTRAN_GUIDELINES,
    GNU_MAKE_MANUAL_PAGES,
    OLD_FORTRAN_IDIOM_CHAPTERS,
    IngestionError,
    ingest_source,
)
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


def _source_by_id(source_id: str) -> Source:
    return next(source for source in load_registry(REGISTRY_PATH).sources if source.id == source_id)


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


def test_fortitude_ingestion_keeps_only_reviewed_native_markdown(tmp_path: Path) -> None:
    source = _source_by_id("fortitude-0.9.2-reference").model_copy(
        update={"expected_document_count": 2}
    )
    archive = _archive(
        {
            f"{source.archive_root}/LICENSE": b"MIT\n",
            f"{source.archive_root}/docs/linter.md": b"# Linter\n",
            f"{source.archive_root}/docs/rules/implicit-typing.md": b"# implicit-typing (C001)\n",
            f"{source.archive_root}/docs/tutorial.md": b"# Excluded tutorial\n",
            f"{source.archive_root}/crates/fortitude_linter/src/rules/mod.rs": b"// excluded\n",
        }
    )

    record = ingest_source(source, tmp_path, downloader=lambda *_args: archive)

    assert {file.path for file in record.files} == {
        "docs/linter.md",
        "docs/rules/implicit-typing.md",
    }
    assert record.converter is None


def test_codee_ingestion_keeps_only_selected_fortran_material(tmp_path: Path) -> None:
    source = _source_by_id("codee-open-catalog-fortran-subset")
    page = b"""# Guideline

Shared [glossary](../../Glossary/Vectorization.md).

#### C

```c
int main(void) {}
```

#### Fortran

```fortran
program demo
end program demo
```

[Examples](https://github.com/codee-com/open-catalog/tree/main/Checks/PWR022/)
"""
    archive = _archive(
        {
            f"{source.archive_root}/Checks/{guideline}/README.md": page
            for guideline in CODEE_FORTRAN_GUIDELINES
        }
    )

    record = ingest_source(source, tmp_path, downloader=lambda *_args: archive)

    generated = tmp_path / "raw" / source.id / "manual/Checks/PWR022/README.md"
    content = generated.read_text(encoding="utf-8")
    assert record.converter == "codee-fortran-subset"
    assert record.converter_version == "builtin codee-fortran-subset 1"
    assert sum(file.path.startswith("manual/") for file in record.files) == 5
    assert "Fortran MCP modification notice" in content
    assert "int main" not in content
    assert "program demo" in content
    assert (
        "https://github.com/codee-com/open-catalog/blob/"
        f"{source.revision}/Glossary/Vectorization.md"
    ) in content
    assert f"/tree/{source.revision}/Checks/PWR022/" in content


def test_old_fortran_idioms_ingestion_converts_reviewed_chapters(tmp_path: Path) -> None:
    source = _source_by_id("old-fortran-programming-idioms")
    chapter = b"""\\section{Legacy feature}

Use \\verb+COMMON+ and its \\emph{modern alternative} \\cite{Example}.

\\begin{verbatim}
      COMMON /STATE/ VALUE
     & CONTINUATION
\\end{verbatim}
"""
    memory_chapter = (
        chapter
        + b"""
\\subsection{Initialising variables in COMMON blocks: BLOCK DATA}
Redundant guidance.
\\subsection{Work arrays}
Retained guidance.
"""
    )
    archive = _archive(
        {
            f"{source.archive_root}/src/{filename}": (
                memory_chapter if filename == "old_memory_management.tex" else chapter
            )
            for filename in OLD_FORTRAN_IDIOM_CHAPTERS
        }
        | {
            f"{source.archive_root}/LICENSE": b"MIT\n",
            f"{source.archive_root}/src/old_idioms.bib": b"""@Electronic{Example,
  url = {https://example.com/reference},
}
""",
        }
    )

    record = ingest_source(source, tmp_path, downloader=lambda *_args: archive)

    generated = tmp_path / "raw" / source.id / "manual/src/old_source_form.tex"
    content = generated.read_text(encoding="utf-8")
    assert record.converter == "old-fortran-idioms-latex"
    assert record.converter_version == "builtin old-fortran-idioms-latex 1"
    assert sum(file.path.startswith("manual/") for file in record.files) == 9
    assert content.startswith("# Legacy feature\n")
    assert "community-authored guidance" in content
    assert "`COMMON`" in content
    assert "*modern alternative*" in content
    assert "[Example](https://example.com/reference)" in content
    assert "```fortran" in content
    assert "     & CONTINUATION" in content
    memory = (tmp_path / "raw" / source.id / "manual/src/old_memory_management.tex").read_text(
        encoding="utf-8"
    )
    assert "Redundant guidance" not in memory
    assert "Retained guidance" in memory


def test_prima_ingestion_keeps_only_modernization_method(tmp_path: Path) -> None:
    source = _source_by_id("prima-modernization-case-study")
    readme = b"""# PRIMA

PRIMA aims to provide a faithful modern implementation.

There do exist translations.

### How

The mission of PRIMA is nontrivial. Test after every tiny modification.

[The tests](./tests.md) are **automated** by CI.

### Current status

Project-specific status.
"""
    archive = _archive(
        {
            f"{source.archive_root}/README.md": readme,
            f"{source.archive_root}/LICENCE.txt": b"BSD-3-Clause\n",
        }
    )

    record = ingest_source(source, tmp_path, downloader=lambda *_args: archive)

    generated = tmp_path / "raw" / source.id / "manual/README.md"
    content = generated.read_text(encoding="utf-8")
    assert record.converter == "prima-modernization-subset"
    assert record.converter_version == "builtin prima-modernization-subset 1"
    assert "faithful modern implementation" in content
    assert "every tiny modification" in content
    assert "Project-specific status" not in content


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


def test_numpy_f2py_ingestion_embeds_literal_examples(tmp_path: Path) -> None:
    source = _source_by_id("numpy-2.5.2-f2py-docs").model_copy(
        update={"expected_document_count": 1}
    )
    archive = _archive(
        {
            f"{source.archive_root}/doc/source/f2py/f2py-examples.rst": b"""F2PY examples
=============

.. literalinclude:: ./code/add.f
   :language: fortran
""",
            f"{source.archive_root}/doc/source/f2py/code/add.f": b"""      subroutine add(a, b, c)
      c = a + b
      end
""",
            f"{source.archive_root}/numpy/f2py/tests/util.py": b"# fixture\n",
        }
    )

    record = ingest_source(source, tmp_path, downloader=lambda *_args: archive)

    generated = tmp_path / f"raw/{source.id}/manual/f2py-examples.md"
    markdown = generated.read_text()
    assert record.converter == "numpy-f2py-rst"
    assert record.converter_version == "builtin numpy-f2py-rst 1"
    assert markdown.startswith("# F2PY examples")
    assert "```fortran" in markdown
    assert "subroutine add(a, b, c)" in markdown
    assert "literalinclude" not in markdown


def test_openmpi_ingestion_labels_modern_and_legacy_fortran_syntax(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source_by_id("openmpi-5.0.10-fortran-reference").model_copy(
        update={"expected_document_count": 2}
    )
    monkeypatch.setattr("fortran_mcp.ingest.OPEN_MPI_FORTRAN_ROUTINES", ("MPI_Send",))
    archive = _archive(
        {
            f"{source.archive_root}/LICENSE": b"BSD fixture\n",
            f"{source.archive_root}/docs/man-openmpi/man3/MPI_Send.3.rst": b"""MPI_Send
========

C Syntax
^^^^^^^^

.. code-block:: c

   int MPI_Send(void);

Fortran Syntax
^^^^^^^^^^^^^^

.. code-block:: fortran

   USE MPI

Fortran 2008 Syntax
^^^^^^^^^^^^^^^^^^^

.. code-block:: fortran

   USE mpi_f08
   CALL MPI_Send(buffer, 1, MPI_INTEGER, 1, 0, MPI_COMM_WORLD)

DESCRIPTION
-----------

Performs a blocking send.

.. code-block:: c

   MPI_Send(buffer, 1, MPI_INT, 1, 0, MPI_COMM_WORLD);
""",
            f"{source.archive_root}/examples/hello_usempif08.f90": b"use mpi_f08\n",
            f"{source.archive_root}/examples/ring_usempif08.f90": b"use mpi_f08\n",
        }
    )

    record = ingest_source(source, tmp_path, downloader=lambda *_args: archive)

    generated = tmp_path / f"raw/{source.id}/manual/MPI_Send.3.md"
    markdown = generated.read_text()
    assert record.converter == "openmpi-fortran-rst"
    assert record.converter_version == "builtin openmpi-fortran-rst 2"
    assert "USE mpi_f08" in markdown
    assert "Recommended Fortran Syntax (mpi_f08)" in markdown
    assert "Legacy Fortran Syntax (use mpi or mpif.h)" in markdown
    assert "USE MPI" in markdown
    assert "Performs a blocking send" in markdown
    assert "int MPI_Send" not in markdown
    assert "MPI_Send(buffer, 1, MPI_INT," not in markdown


def test_openmpi_ingestion_expands_shared_routine_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source_by_id("openmpi-5.0.10-fortran-reference").model_copy(
        update={"expected_document_count": 2}
    )
    monkeypatch.setattr("fortran_mcp.ingest.OPEN_MPI_FORTRAN_ROUTINES", ("MPI_Ibcast",))
    archive = _archive(
        {
            f"{source.archive_root}/LICENSE": b"BSD fixture\n",
            f"{source.archive_root}/docs/man-openmpi/man3/MPI_Ibcast.3.rst": b"""MPI_Ibcast
===========
    .. include_body

.. include:: ../man3/MPI_Bcast.3.rst
    :start-after: .. include_body
""",
            f"{source.archive_root}/docs/man-openmpi/man3/MPI_Bcast.3.rst": b"""MPI_Bcast
=========

.. include_body

MPI_Bcast and MPI_Ibcast broadcast a message.

Fortran Syntax
^^^^^^^^^^^^^^

.. code-block:: fortran

   USE MPI
   CALL MPI_IBCAST(BUFFER, COUNT, DATATYPE, ROOT, COMM, REQUEST, IERROR)

Fortran 2008 Syntax
^^^^^^^^^^^^^^^^^^^

.. code-block:: fortran

   USE mpi_f08
   CALL MPI_Ibcast(buffer, count, datatype, root, comm, request, ierror)
""",
            f"{source.archive_root}/examples/hello_usempif08.f90": b"use mpi_f08\n",
            f"{source.archive_root}/examples/ring_usempif08.f90": b"use mpi_f08\n",
        }
    )

    ingest_source(source, tmp_path, downloader=lambda *_args: archive)

    markdown = (tmp_path / f"raw/{source.id}/manual/MPI_Ibcast.3.md").read_text()
    assert markdown.startswith("# MPI_Ibcast")
    assert "broadcast a message" in markdown
    assert "USE MPI" in markdown
    assert "USE mpi_f08" in markdown
    assert "include::" not in markdown


def test_openmp_ingestion_keeps_explanations_and_fortran_examples(tmp_path: Path) -> None:
    source = _source_by_id("openmp-6.0.1-fortran-examples").model_copy(
        update={"expected_document_count": 1}
    )
    archive = _archive(
        {
            f"{source.archive_root}/parallel/collapse.tex": b"""
\\section{\\kcode{collapse} Clause}

The loops are combined into one iteration space.

\\cexample[3.0]{collapse}{1}
\\ffreeexample[3.0]{collapse}{1}
""",
            f"{source.archive_root}/parallel/sources/collapse.1.f90": b"""! @@name: collapse.1
! @@type: F-free
program collapse
  !$omp parallel do collapse(2)
end program collapse
""",
            f"{source.archive_root}/omp_copyright.txt": b"OpenMP notice\n",
        }
    )

    record = ingest_source(source, tmp_path, downloader=lambda *_args: archive)

    generated = tmp_path / f"raw/{source.id}/manual/parallel/collapse.tex"
    markdown = generated.read_text()
    assert record.converter == "openmp-examples"
    assert record.converter_version == "builtin openmp-examples 1"
    assert markdown.startswith("# `collapse` Clause")
    assert "The loops are combined" in markdown
    assert "```fortran" in markdown
    assert "!$omp parallel do collapse(2)" in markdown
    assert "cexample" not in markdown


def test_gnu_make_ingestion_selects_reviewed_manual_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source_by_id("gnu-make-4.4.1-build-reference")
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
        for page in GNU_MAKE_MANUAL_PAGES:
            (html_dir / f"{page}.html").write_text(
                f"<html><body><h1>{page}</h1><p>GNU Make reference.</p></body></html>"
            )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("fortran_mcp.ingest.subprocess.run", fake_run)

    record = ingest_source(source, tmp_path, downloader=lambda *_args: archive)

    generated = tmp_path / f"raw/{source.id}/manual/Automatic-Variables.md"
    assert generated.read_text().startswith("# Automatic-Variables")
    assert record.converter == "gnu-make-texinfo"
    assert record.converter_version == "texi2any (GNU texinfo) 7.3; curated pages 1"
    assert (tmp_path / f"raw/{source.id}/FORTRAN-MCP-MODIFICATION-NOTICE.txt").is_file()
