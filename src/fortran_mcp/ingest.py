"""Safely ingest approved documentation archives."""

import argparse
import hashlib
import json
import os
import posixpath
import re
import shutil
import subprocess
import tarfile
import tempfile
import textwrap
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
ALLOWED_SUFFIXES = frozenset(
    {
        ".cmake",
        ".f",
        ".f90",
        ".build",
        ".bib",
        ".dat",
        ".fypp",
        ".ini",
        ".md",
        ".markdown",
        ".py",
        ".pyf",
        ".rst",
        ".tex",
        ".texi",
        ".toml",
        ".txt",
        ".yml",
    }
)
Downloader = Callable[[str, int, int], bytes]


class IngestionError(RuntimeError):
    """Raised when a source cannot be ingested safely."""


def download(url: str, timeout: int, limit: int) -> bytes:
    """Download a URL while enforcing a maximum response size."""
    request = Request(url, headers={"User-Agent": "fortran-mcp/0.1"})
    try:
        with urlopen(request, timeout=timeout) as response:
            declared_size = response.headers.get("Content-Length")
            if declared_size is not None and int(declared_size) > limit:
                raise IngestionError(f"download exceeds {limit} bytes")
            content = cast("bytes", response.read(limit + 1))
    except (OSError, ValueError) as error:
        raise IngestionError(f"could not download source from {url}: {error}") from error
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
        pattern == "**"
        or (
            relative.is_relative_to(PurePosixPath(pattern.removesuffix("/**")))
            if pattern.endswith("/**")
            else relative == PurePosixPath(pattern)
        )
        for pattern in source.include_paths
    )
    if not included or not relative.parts or relative.suffix.lower() not in ALLOWED_SUFFIXES:
        return None
    return relative


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    candidate = PurePosixPath(path)
    return any(
        pattern == "**"
        or (
            candidate.is_relative_to(PurePosixPath(pattern.removesuffix("/**")))
            if pattern.endswith("/**")
            else candidate == PurePosixPath(pattern)
        )
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


def _cmake_module_document(content: str, path: Path) -> str:
    marker = "[.rst:\n"
    start = content.find(marker)
    end = content.rfind("#]")
    if start < 0 or end < start:
        raise IngestionError(f"CMake module has no embedded RST documentation: {path}")
    return content[start + len(marker) : end].rstrip() + "\n"


def _expand_rst_includes(
    content: str,
    path: PurePosixPath,
    documents: dict[PurePosixPath, str],
    stack: tuple[PurePosixPath, ...] = (),
) -> str:
    if path in stack:
        chain = " -> ".join(item.as_posix() for item in (*stack, path))
        raise IngestionError(f"recursive CMake documentation include: {chain}")

    output: list[str] = []
    include_pattern = re.compile(r"^(?P<indent>\s*)\.\. include::\s+(?P<target>\S+)\s*$")
    for line in content.splitlines():
        match = include_pattern.match(line)
        if match is None:
            output.append(line)
            continue
        target_text = match.group("target")
        if target_text.startswith("/"):
            target = PurePosixPath("Help") / target_text.removeprefix("/")
        else:
            target = path.parent / target_text
        included = documents.get(target)
        if included is None:
            raise IngestionError(f"unavailable CMake documentation include: {target}")
        expanded = _expand_rst_includes(included, target, documents, (*stack, path))
        indent = match.group("indent")
        output.extend(f"{indent}{item}" if item else "" for item in expanded.splitlines())
    return "\n".join(output) + "\n"


def _rst_to_markdown(content: str) -> str:
    links = dict(re.findall(r"^\.\. _([^:]+):\s+(https?://\S+)\s*$", content, re.MULTILINE))

    def rst_link(match: re.Match[str]) -> str:
        label = match.group(1)
        explicit = re.fullmatch(r"(.+?)\s+<(https?://[^>]+)>", label)
        if explicit:
            return f"[{explicit.group(1)}]({explicit.group(2)})"
        return f"[{label}]({links[label]})" if label in links else label

    substitutions = dict(
        re.findall(r"^\s*\.\. \|([^|]+)\| replace::\s*(.+)$", content, re.MULTILINE)
    )
    content = re.sub(r"^\s*\.\. \|[^|]+\| replace::.*(?:\n|$)", "", content, flags=re.MULTILINE)
    for name, replacement in substitutions.items():
        content = content.replace(f"|{name}|", replacement)
    content = re.sub(
        r"`([^`]+)`_{1,2}",
        rst_link,
        content,
    )
    content = re.sub(
        r":([a-z_]+):`([^`]+)`",
        lambda match: f":{match.group(1)}:`{' '.join(match.group(2).split())}`",
        content,
        flags=re.DOTALL,
    )
    lines = content.splitlines()
    output: list[str] = []
    heading_levels: dict[str, int] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if (
            index + 2 < len(lines)
            and re.fullmatch(r"([=\-^\"*~])\1{2,}", line.strip())
            and lines[index + 1].strip()
            and lines[index + 2].strip() == line.strip()
        ):
            adornment = line.strip()[0]
            level = heading_levels.setdefault(adornment, len(heading_levels) + 1)
            output.append(f"{'#' * min(level, 6)} {lines[index + 1].strip()}")
            index += 3
            continue
        if line.rstrip().endswith("::") and not line.lstrip().startswith(".. "):
            probe = index + 1
            while probe < len(lines) and not lines[probe].strip():
                probe += 1
            base_indent = len(line) - len(line.lstrip())
            if probe < len(lines) and len(lines[probe]) - len(lines[probe].lstrip()) > base_indent:
                literal_block: list[str] = []
                block_indent = len(lines[probe]) - len(lines[probe].lstrip())
                while probe < len(lines):
                    candidate = lines[probe]
                    if (
                        candidate.strip()
                        and len(candidate) - len(candidate.lstrip()) < block_indent
                    ):
                        break
                    literal_block.append(candidate)
                    probe += 1
                introduction = line.rstrip()[:-1]
                if introduction.strip() != ":":
                    output.append(introduction)
                output.extend(
                    ("```text", *textwrap.dedent("\n".join(literal_block)).splitlines(), "```")
                )
                index = probe
                continue
        if (
            index + 1 < len(lines)
            and line.strip()
            and re.fullmatch(r"([=\-\^\"*~])\1{2,}", lines[index + 1].strip())
        ):
            adornment = lines[index + 1].strip()[0]
            level = heading_levels.setdefault(adornment, len(heading_levels) + 1)
            output.append(f"{'#' * min(level, 6)} {line.strip()}")
            index += 2
            continue

        directive = re.match(r"^(?P<indent>\s*)\.\. (?P<kind>[\w-]+)::\s*(?P<value>.*)$", line)
        if directive:
            indent = directive.group("indent")
            kind = directive.group("kind")
            value = directive.group("value").strip()
            if kind == "code-block":
                index += 1
                while index < len(lines) and not lines[index].strip():
                    index += 1
                block: list[str] = []
                while index < len(lines):
                    candidate = lines[index]
                    if candidate.strip() and len(candidate) - len(candidate.lstrip()) <= len(
                        indent
                    ):
                        break
                    block.append(candidate)
                    index += 1
                dedented = textwrap.dedent("\n".join(block)).splitlines()
                output.extend(
                    (
                        f"{indent}```{value}",
                        *(f"{indent}{item}" for item in dedented),
                        f"{indent}```",
                    )
                )
                continue
            if kind == "toctree":
                index += 1
                while index < len(lines) and (
                    not lines[index].strip()
                    or len(lines[index]) - len(lines[index].lstrip()) > len(indent)
                ):
                    index += 1
                continue
            if kind in {"command", "variable"}:
                output.append(f"{indent}### `{value}`")
            elif kind == "rubric":
                output.append(f"{indent}### {value}")
            elif kind in {"versionadded", "versionchanged", "deprecated"}:
                labels = {
                    "versionadded": "Added",
                    "versionchanged": "Changed",
                    "deprecated": "Deprecated",
                }
                output.append(f"{indent}*{labels[kind]} in {value}.*")
            elif kind in {"note", "warning"}:
                output.append(f"{indent}**{kind.title()}:** {value}".rstrip())
            index += 1
            continue
        if re.match(r"^\s*\.\. _[^:]+:\s*$", line):
            index += 1
            continue
        if re.match(r"^\s*\.\. _.+:\s+\S+\s*$", line):
            index += 1
            continue
        if re.match(r"^\s*\.\. [A-Za-z][^:]*:\s*", line):
            index += 1
            continue

        line = re.sub(
            r":\w+:`([^`]+)`",
            lambda match: f"`{match.group(1).split(' <', 1)[0]}`",
            line,
        )
        line = re.sub(r"`([^`<]+) <(https?://[^>]+)>`_", r"[\1](\2)", line)
        line = re.sub(r"`([^`<]+) <[^>]+>`_", r"`\1`", line)
        line = re.sub(r"``([^`]+)``", r"`\1`", line)
        output.append(line)
        index += 1
    return "\n".join(output).strip() + "\n"


def _convert_cmake_rst(source: Source, root: Path) -> tuple[tuple[FileRecord, ...], str]:
    documents: dict[PurePosixPath, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".cmake", ".rst"}:
            continue
        relative = PurePosixPath(path.relative_to(root).as_posix())
        content = path.read_text(encoding="utf-8")
        documents[relative] = (
            _cmake_module_document(content, path) if path.suffix.lower() == ".cmake" else content
        )

    output_dir = root / "manual"
    output_dir.mkdir()
    records: list[FileRecord] = []
    for document_path, content in documents.items():
        if "include" in document_path.parts:
            continue
        if document_path.parts[0] == "Help":
            published = PurePosixPath(*document_path.parts[1:]).with_suffix(".md")
        elif document_path.parts[0] == "Modules":
            published = PurePosixPath("module", document_path.stem).with_suffix(".md")
        else:
            continue
        expanded = _expand_rst_includes(content, document_path, documents)
        output_path = output_dir.joinpath(*published.parts)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(_rst_to_markdown(expanded), encoding="utf-8")
        records.append(_record_file(output_path, root))
    if not records:
        raise IngestionError("CMake RST conversion produced no documentation pages")
    return tuple(sorted(records, key=lambda item: item.path)), "builtin cmake-rst 1"


def _included_code_language(path: Path) -> str:
    if path.suffix.lower() in {".f", ".f90", ".fypp", ".pyf"}:
        return "fortran"
    if path.suffix.lower() == ".py":
        return "python"
    if path.name.startswith("CMakeLists"):
        return "cmake"
    if path.suffix.lower() == ".build":
        return "meson"
    return path.suffix.lower().removeprefix(".") or "text"


def _expand_f2py_includes(content: str, path: Path, root: Path) -> str:
    lines = content.splitlines()
    output: list[str] = []
    index = 0
    pattern = re.compile(
        r"^(?P<indent>\s*)\.\. (?P<kind>literalinclude|include)::\s+(?P<target>\S+)"
    )
    while index < len(lines):
        match = pattern.match(lines[index])
        if match is None:
            output.append(lines[index])
            index += 1
            continue
        options: dict[str, str] = {}
        index += 1
        while index < len(lines):
            option = re.match(r"^\s+:([\w-]+):\s*(.*)$", lines[index])
            if option is None:
                break
            options[option.group(1)] = option.group(2)
            index += 1
        target = (path.parent / match.group("target")).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError as error:
            raise IngestionError(
                f"F2PY include escapes the archive: {match.group('target')}"
            ) from error
        if not target.is_file():
            raise IngestionError(f"F2PY include is unavailable: {target.relative_to(root)}")
        included = target.read_text(encoding="utf-8")
        if "lines" in options:
            bounds = options["lines"].split("-", 1)
            start = int(bounds[0]) if bounds[0] else 1
            end = int(bounds[1]) if len(bounds) == 2 and bounds[1] else None
            included = "\n".join(included.splitlines()[start - 1 : end])
        language = options.get("language") or _included_code_language(target)
        indent = match.group("indent")
        output.extend(
            (
                f"{indent}```{language}",
                *(f"{indent}{line}" for line in included.rstrip().splitlines()),
                f"{indent}```",
            )
        )
    return "\n".join(output) + "\n"


def _convert_numpy_f2py_rst(source: Source, root: Path) -> tuple[tuple[FileRecord, ...], str]:
    source_dir = root / "doc/source/f2py"
    output_dir = root / "manual"
    output_dir.mkdir()
    records: list[FileRecord] = []
    for path in sorted(source_dir.rglob("*.rst")):
        if path.name in {"f2py-reference.rst", "f2py-user.rst"}:
            continue
        expanded = _expand_f2py_includes(path.read_text(encoding="utf-8"), path, root)
        markdown = _rst_to_markdown(expanded)
        output_path = (output_dir / path.relative_to(source_dir)).with_suffix(".md")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding="utf-8")
        records.append(_record_file(output_path, root))
    if not records:
        raise IngestionError("NumPy F2PY conversion produced no documentation pages")
    return tuple(records), "builtin numpy-f2py-rst 1"


def _convert_fypp_rst(source: Source, root: Path) -> tuple[tuple[FileRecord, ...], str]:
    source_path = root / "docs/fypp.rst"
    if not source_path.is_file():
        raise IngestionError("Fypp manual is unavailable: docs/fypp.rst")
    output_path = root / "manual/fypp.md"
    output_path.parent.mkdir()
    output_path.write_text(
        _rst_to_markdown(source_path.read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    return (_record_file(output_path, root),), "builtin fypp-rst 1"


OPEN_MPI_FORTRAN_ROUTINES = (
    "MPI_Abort",
    "MPI_Accumulate",
    "MPI_Allgather",
    "MPI_Allgatherv",
    "MPI_Allreduce",
    "MPI_Alltoall",
    "MPI_Alltoallv",
    "MPI_Barrier",
    "MPI_Bcast",
    "MPI_Cart_coords",
    "MPI_Cart_create",
    "MPI_Cart_shift",
    "MPI_Comm_dup",
    "MPI_Comm_free",
    "MPI_Comm_rank",
    "MPI_Comm_size",
    "MPI_Comm_split",
    "MPI_Exscan",
    "MPI_File_close",
    "MPI_File_open",
    "MPI_File_read",
    "MPI_File_read_all",
    "MPI_File_read_at",
    "MPI_File_set_view",
    "MPI_File_write",
    "MPI_File_write_all",
    "MPI_File_write_at",
    "MPI_Finalize",
    "MPI_Gather",
    "MPI_Gatherv",
    "MPI_Get",
    "MPI_Get_count",
    "MPI_Iallreduce",
    "MPI_Ibcast",
    "MPI_Init",
    "MPI_Init_thread",
    "MPI_Iprobe",
    "MPI_Irecv",
    "MPI_Isend",
    "MPI_Neighbor_alltoallv",
    "MPI_Probe",
    "MPI_Put",
    "MPI_Recv",
    "MPI_Reduce",
    "MPI_Scan",
    "MPI_Scatter",
    "MPI_Scatterv",
    "MPI_Send",
    "MPI_Sendrecv",
    "MPI_Test",
    "MPI_Testall",
    "MPI_Type_commit",
    "MPI_Type_contiguous",
    "MPI_Type_create_struct",
    "MPI_Type_create_subarray",
    "MPI_Type_free",
    "MPI_Type_get_extent",
    "MPI_Type_size",
    "MPI_Type_vector",
    "MPI_Wait",
    "MPI_Waitall",
    "MPI_Waitany",
    "MPI_Win_allocate",
    "MPI_Win_create",
    "MPI_Win_fence",
    "MPI_Win_flush",
    "MPI_Win_free",
    "MPI_Win_lock",
    "MPI_Win_unlock",
    "MPI_Wtime",
)


def _remove_rst_section(content: str, title: str) -> str:
    pattern = re.compile(
        rf"(?m)^{re.escape(title)}\s*\n(?P<adornment>[-=^\"*~])(?P=adornment){{2,}}\s*$"
    )
    match = pattern.search(content)
    if match is None:
        return content
    adornment = re.escape(match.group("adornment"))
    next_section = re.compile(rf"(?m)^\S.*\n{adornment}{{3,}}\s*$").search(content, match.end())
    end = next_section.start() if next_section else len(content)
    return content[: match.start()] + content[end:]


def _convert_openmpi_fortran_rst(source: Source, root: Path) -> tuple[tuple[FileRecord, ...], str]:
    source_dir = root / "docs/man-openmpi/man3"
    output_dir = root / "manual"
    output_dir.mkdir()
    records: list[FileRecord] = []
    for routine in OPEN_MPI_FORTRAN_ROUTINES:
        path = source_dir / f"{routine}.3.rst"
        if not path.is_file():
            raise IngestionError(f"Open MPI routine page is unavailable: {routine}")
        content = path.read_text(encoding="utf-8")
        included_page = re.search(r"(?m)^\.\. include:: \.\./man3/(MPI_\w+\.3\.rst)\s*$", content)
        if included_page:
            included_path = source_dir / included_page.group(1)
            if not included_path.is_file():
                raise IngestionError(
                    f"Open MPI included routine page is unavailable: {included_path.name}"
                )
            included_content = included_path.read_text(encoding="utf-8")
            marker = ".. include_body"
            if marker not in included_content:
                raise IngestionError(
                    f"Open MPI included routine page has no body: {included_path.name}"
                )
            content = f"{routine}\n{'=' * len(routine)}\n" + included_content.split(marker, 1)[1]
        for title in ("C Syntax", "ERRORS", "SEE ALSO"):
            content = _remove_rst_section(content, title)
        content = re.sub(
            r"(?m)^Fortran Syntax\n\^+$",
            "Legacy Fortran Syntax (use mpi or mpif.h)\n"
            "^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^",
            content,
        )
        content = re.sub(
            r"(?m)^Fortran 2008 Syntax\n\^+$",
            "Recommended Fortran Syntax (mpi_f08)\n^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^",
            content,
        )
        content = re.sub(r"(?m)^\.\. include_body\s*$", "", content)
        content = content.replace("|mdash|", "-").replace("|mpi_standard_version|", "3.1")
        content = re.sub(r"(?ms)^\.\. code-block:: [cC]\s*\n(?:\n|[ \t]+.*\n?)*", "", content)
        output_path = output_dir / f"{routine}.3.md"
        output_path.write_text(_rst_to_markdown(content), encoding="utf-8")
        records.append(_record_file(output_path, root))

    examples = [root / "examples/hello_usempif08.f90", root / "examples/ring_usempif08.f90"]
    if not all(path.is_file() for path in examples):
        raise IngestionError("Open MPI Fortran 2008 examples are unavailable")
    example_text = ["# Open MPI Fortran 2008 examples"]
    for path in examples:
        example_text.extend(
            (f"## `{path.name}`", f"```fortran\n{path.read_text(encoding='utf-8').rstrip()}\n```")
        )
    output_path = output_dir / "Fortran-2008-examples.md"
    output_path.write_text("\n\n".join(example_text) + "\n", encoding="utf-8")
    records.append(_record_file(output_path, root))
    return tuple(records), "builtin openmpi-fortran-rst 2"


CODEE_FORTRAN_GUIDELINES = ("PWR022", "PWR079", "PWR080", "PWR081", "PWD004")
CODEE_MODIFICATION_NOTICE = (
    "> **Fortran MCP modification notice:** This page was modified from the pinned Open Catalog "
    "source: C and C++ example sections were removed. The shared guidance and Fortran examples "
    "are otherwise retained."
)


def _remove_codee_non_fortran_sections(content: str) -> str:
    """Remove Markdown sections explicitly headed C or C++ while retaining shared guidance."""
    lines = content.splitlines()
    output: list[str] = []
    skipped_level: int | None = None
    in_fence = False
    for line in lines:
        if re.match(r"^\s*(```|~~~)", line):
            in_fence = not in_fence
        heading = None if in_fence else re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip().casefold()
            if skipped_level is not None and level <= skipped_level:
                skipped_level = None
            if title in {"c", "c++", "c/c++", "c and c++", "c++ and c"}:
                skipped_level = level
                continue
        if skipped_level is None:
            output.append(line)
    return "\n".join(output).strip() + "\n"


def _rewrite_codee_links(content: str, source: Source, document: PurePosixPath) -> str:
    base = str(source.citation_base_url).rstrip("/")

    def replace(match: re.Match[str]) -> str:
        target = match.group(1)
        if target.startswith(("#", "mailto:")):
            return target
        target = target.replace("/tree/main/", f"/tree/{source.revision}/")
        target = target.replace("/blob/main/", f"/blob/{source.revision}/")
        if target.startswith(("http://", "https://")):
            return target
        path, separator, fragment = target.partition("#")
        if path.startswith("/"):
            resolved = path.lstrip("/")
        else:
            resolved = posixpath.normpath(f"{document.parent.as_posix()}/{path}")
        suffix = f"#{fragment}" if separator else ""
        return f"{base}/{resolved}{suffix}"

    return re.sub(r"(?<=\]\()([^)]+)", replace, content)


def _convert_codee_fortran_subset(source: Source, root: Path) -> tuple[tuple[FileRecord, ...], str]:
    records: list[FileRecord] = []
    for guideline in CODEE_FORTRAN_GUIDELINES:
        relative = PurePosixPath("Checks", guideline, "README.md")
        input_path = root.joinpath(*relative.parts)
        if not input_path.is_file():
            raise IngestionError(f"selected Codee guideline is unavailable: {guideline}")
        content = _remove_codee_non_fortran_sections(input_path.read_text(encoding="utf-8"))
        content = _rewrite_codee_links(content, source, relative)
        lines = content.splitlines()
        if not lines or not lines[0].startswith("# "):
            raise IngestionError(f"selected Codee guideline has no title: {guideline}")
        lines[1:1] = ["", CODEE_MODIFICATION_NOTICE]
        output_path = root / "manual" / "Checks" / guideline / "README.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        records.append(_record_file(output_path, root))
    return tuple(records), "builtin codee-fortran-subset 1"


BELIAVSKY_PACKAGE_URLS_IN_FORTRAN_LANG = frozenset(
    {
        "https://github.com/dftd4/dftd4",
        "https://github.com/exequantcode/raffle",
        "https://github.com/flexi-framework/flexi",
        "https://github.com/fluidnumerics/feq-parse",
        "https://github.com/fortran-gaming/blocktran",
        "https://github.com/fortran-lang/stdlib",
        "https://github.com/fortran-lang/test-drive",
        "https://github.com/geospace-code/h5fortran",
        "https://github.com/geospace-code/maptran3d",
        "https://github.com/geospace-code/nc4fortran",
        "https://github.com/interkosmos/fortran-curl",
        "https://github.com/interkosmos/fortran-grace",
        "https://github.com/interkosmos/fortran-lmdb",
        "https://github.com/interkosmos/fortran-lua54",
        "https://github.com/interkosmos/fortran-modbus",
        "https://github.com/interkosmos/fortran-motif",
        "https://github.com/interkosmos/fortran-pcre2",
        "https://github.com/interkosmos/fortran-raylib",
        "https://github.com/interkosmos/fortran-sdl2",
        "https://github.com/interkosmos/fortran-sqlite3",
        "https://github.com/interkosmos/fortran-tcl86",
        "https://github.com/interkosmos/fortran-unix",
        "https://github.com/interkosmos/fortran-xlib",
        "https://github.com/interkosmos/fortran-xmpp",
        "https://github.com/interkosmos/fortran-zlib",
        "https://github.com/interkosmos/fortran-zstd",
        "https://github.com/jacobwilliams/astro-fortran",
        "https://github.com/jacobwilliams/bspline-fortran",
        "https://github.com/jacobwilliams/ddeabm",
        "https://github.com/jacobwilliams/dop853",
        "https://github.com/jacobwilliams/fortran-astrodynamics-toolkit",
        "https://github.com/jacobwilliams/json-fortran",
        "https://github.com/jacobwilliams/nlesolver-fortran",
        "https://github.com/jacobwilliams/numdiff",
        "https://github.com/jacobwilliams/pchip",
        "https://github.com/jacobwilliams/pyplot-fortran",
        "https://github.com/jacobwilliams/quadpack",
        "https://github.com/jacobwilliams/regridpack",
        "https://github.com/jacobwilliams/roots-fortran",
        "https://github.com/jacobwilliams/slsqp",
        "https://github.com/kookma/ogpf",
        "https://github.com/modern-fortran/neural-fortran",
        "https://github.com/nedtaylor/athena",
        "https://github.com/perazz/fitpack",
        "https://github.com/perazz/fortran-bessels",
        "https://github.com/perazz/fortran-lapack",
        "https://github.com/perazz/fortran-regex",
        "https://github.com/perazz/fortran-shlex",
        "https://github.com/princemahajan/flint",
        "https://github.com/samharrison7/fortran-error-handler",
        "https://github.com/scivision/fortran2018-examples",
        "https://github.com/scivision/rpn-calc-fortran",
        "https://github.com/szaghi/flap",
        "https://github.com/szaghi/penf",
        "https://github.com/szaghi/stringifor",
        "https://github.com/szaghi/vtkfortran",
        "https://github.com/toml-f/toml-f",
        "https://github.com/urbanjost/general-purpose-fortran",
        "https://github.com/urbanjost/m_draw",
        "https://github.com/urbanjost/m_history",
        "https://github.com/urbanjost/m_io",
        "https://github.com/urbanjost/m_ncurses",
        "https://github.com/urbanjost/m_process",
        "https://github.com/urbanjost/m_strings",
        "https://github.com/urbanjost/m_system",
        "https://github.com/urbanjost/m_time",
        "https://github.com/vmagnin/gtk-fortran",
        "https://github.com/wavebitscientific/functional-fortran",
    }
)
PACKAGE_DIRECTORY_NOTICE = (
    "> Discovery directory, not an endorsement: package entries are brief upstream descriptions. "
    "Check the linked repository for current maintenance, license, compatibility, and installation "
    "instructions before adopting a package."
)


def _convert_beliavsky_packages(source: Source, root: Path) -> tuple[tuple[FileRecord, ...], str]:
    input_path = root / "README.md"
    if not input_path.is_file():
        raise IngestionError("Beliavsky package list README is unavailable")
    content = input_path.read_text(encoding="utf-8")
    first_category = re.search(r"(?m)^## ", content)
    if first_category is None:
        raise IngestionError("Beliavsky package list contains no categories")
    entries = re.findall(r"(?m)^\[[^]]+\]\(https?://[^)]+\)", content)
    if len(entries) != 396:
        raise IngestionError(f"expected 396 Beliavsky package entries; found {len(entries)}")
    body = content[first_category.start() :].strip()
    markdown = (
        "# Beliavsky list of fpm-compatible Fortran projects\n\n"
        f"{PACKAGE_DIRECTORY_NOTICE}\n\n"
        "This pinned community-maintained snapshot is the primary broad package directory in "
        "Fortran MCP. Its table of contents was removed as redundant; all categorized entries "
        "are retained.\n\n"
        f"{body}\n"
    )
    output_path = root / "manual" / "README.md"
    output_path.parent.mkdir(parents=True)
    output_path.write_text(markdown, encoding="utf-8")
    return (_record_file(output_path, root),), "builtin beliavsky-packages 1"


def _yaml_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _parse_fortran_lang_packages(content: str) -> list[dict[str, str]]:
    """Parse the deliberately flat, documented package-index YAML schema without a dependency."""
    packages: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in content.splitlines():
        if line.startswith("- name: "):
            if current is not None:
                packages.append(current)
            current = {"name": _yaml_scalar(line.partition(":")[2])}
        elif current is not None and re.match(r"^  [a-z]+: ", line):
            key, _, value = line.strip().partition(":")
            current[key] = _yaml_scalar(value)
    if current is not None:
        packages.append(current)
    return packages


def _package_url(package: dict[str, str]) -> str:
    if "github" in package:
        return f"https://github.com/{package['github']}"
    if "gitlab" in package:
        return f"https://gitlab.com/{package['gitlab']}"
    return package.get("url", "")


def _normalized_repository_url(url: str) -> str:
    return url.casefold().rstrip("/").removesuffix(".git")


def _convert_fortran_lang_package_index(
    source: Source, root: Path
) -> tuple[tuple[FileRecord, ...], str]:
    input_path = root / "data" / "package_index.yml"
    if not input_path.is_file():
        raise IngestionError("Fortran-lang package index is unavailable")
    packages = _parse_fortran_lang_packages(input_path.read_text(encoding="utf-8"))
    if len(packages) != 272:
        raise IngestionError(f"expected 272 Fortran-lang package entries; found {len(packages)}")

    retained: list[dict[str, str]] = []
    excluded: list[dict[str, str]] = []
    for package in packages:
        required = {"name", "description", "categories"}
        if not required.issubset(package) or not _package_url(package):
            raise IngestionError(f"incomplete Fortran-lang package entry: {package.get('name')}")
        target = _normalized_repository_url(_package_url(package))
        if target in BELIAVSKY_PACKAGE_URLS_IN_FORTRAN_LANG:
            excluded.append(package)
        else:
            retained.append(package)
    if len(excluded) != 68 or len(retained) != 204:
        raise IngestionError(
            "package-index deduplication drifted: "
            f"excluded {len(excluded)} and retained {len(retained)} entries"
        )

    by_category: dict[str, list[dict[str, str]]] = {}
    for package in retained:
        category = package["categories"].split()[0].replace("-", " ").title()
        by_category.setdefault(category, []).append(package)
    lines = [
        "# Additional Fortran-lang package index entries",
        "",
        PACKAGE_DIRECTORY_NOTICE,
        "",
        "This pinned official community index contributes 204 entries absent by normalized "
        "repository URL from the pinned Beliavsky list. The 68 overlaps are omitted so each "
        "repository is indexed only once. Categories and tags are retained for discovery.",
    ]
    for category, category_packages in by_category.items():
        lines.extend(("", f"## {category}", ""))
        for package in category_packages:
            metadata = [f"Categories: {package['categories']}"]
            if tags := package.get("tags"):
                metadata.append(f"Tags: {tags}")
            lines.append(
                f"- [{package['name']}]({_package_url(package)}): "
                f"{package['description']}. {'; '.join(metadata)}."
            )
    output_path = root / "manual" / "data" / "package_index.yml"
    output_path.parent.mkdir(parents=True)
    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return (_record_file(output_path, root),), "builtin fortran-lang-package-index 1"


OLD_FORTRAN_IDIOM_CHAPTERS = (
    "old_source_form.tex",
    "old_subroutine_function.tex",
    "old_floating_point.tex",
    "old_character_handling.tex",
    "old_control_structures.tex",
    "old_memory_management.tex",
    "old_input_output.tex",
    "old_miscellaneous.tex",
    "old_caveats_for_c_programmers.tex",
)
OLD_FORTRAN_IDIOMS_NOTICE = (
    "> Modified copy: converted from the upstream LaTeX chapters to Markdown-compatible text. "
    "The community-authored guidance is practical rather than normative."
)


def _bibtex_urls(content: str) -> dict[str, str]:
    urls: dict[str, str] = {}
    for entry in re.finditer(r"@\w+\{(?P<key>[^,{}]+),(?P<body>.*?)\n\}", content, re.DOTALL):
        url = re.search(r"\burl\s*=\s*\{(?P<url>https?://[^}]+)\}", entry.group("body"))
        if url:
            urls[entry.group("key").casefold()] = url.group("url").replace(r"\#", "#")
    if "ieee754" in urls:
        urls["ieee"] = urls["ieee754"]
    urls["modernizeoldfortran"] = "https://fortranwiki.org/fortran/show/Modernizing%2BOld%2BFortran"
    return urls


def _convert_old_idioms_tex(content: str, citation_urls: dict[str, str]) -> str:
    """Convert the deliberately small LaTeX vocabulary used by the idioms guide."""
    content = re.sub(r"(?m)^\s*%.*$", "", content)
    content = re.sub(r"\\verb(?P<delimiter>[^\w\s])(?P<value>.*?)\1", r"`\g<value>`", content)
    for command, prefix in (
        ("section", "#"),
        ("subsection", "##"),
        ("subsubsection", "###"),
    ):
        content = re.sub(rf"\\{command}\*?\{{([^{{}}]+)\}}", rf"{prefix} \1", content)
    for command in ("emph", "textit"):
        content = _replace_tex_command(content, command, lambda value: f"*{value}*")
    content = _replace_tex_command(content, "textbf", lambda value: f"**{value}**")
    content = _replace_tex_command(content, "footnote", lambda value: f" (Note: {value})")
    content = re.sub(r"\\begin\{verbatim\}", "```fortran", content)
    content = re.sub(r"\\end\{verbatim\}", "```", content)
    content = re.sub(r"(?m)^\s*\\item\s*", "- ", content)
    content = re.sub(r"\\(?:begin|end)\{(?:itemize|enumerate|quote|quotation)\}", "", content)
    content = re.sub(r"\\begin\{(?:table|tabular)\}(?:\[[^]]*\])?(?:\{[^}]*\})?", "", content)
    content = re.sub(r"\\end\{(?:table|tabular)\}", "", content)
    content = re.sub(r"(?m)\s*\\\\\s*$", "", content)
    content = re.sub(r"\\(?:label|bibliography|bibliographystyle)\{[^{}]*\}", "", content)

    def citation(match: re.Match[str]) -> str:
        rendered = [
            f"[{key}]({citation_urls[key.casefold()]})"
            if key.casefold() in citation_urls
            else f"[citation: {key}]"
            for key in (item.strip() for item in match.group(1).split(","))
        ]
        return "(" + ", ".join(rendered) + ")"

    content = re.sub(r"\\cite\{([^{}]+)\}", citation, content)
    content = re.sub(r"\\ref\{[^{}]*\}", "the referenced section", content)
    content = re.sub(r"\\vspace\{[^{}]*\}", "", content)
    content = re.sub(r"\\(?:noindent|newpage|clearpage)\b", "", content)
    content = content.replace(r"\%", "%").replace(r"\_", "_")
    content = content.replace(r"\&", "&").replace(r"\,", "")
    content = content.replace("~", " ")
    content = re.sub(r"\$([^$]+)\$", r"\1", content)
    content = re.sub(r"\\([A-Za-z]+)\{([^{}]*)\}", r"\2", content)
    content = re.sub(r"\\([A-Za-z]+)\b", "", content)
    content = re.sub(r"\n{3,}", "\n\n", content).strip()
    lines: list[str] = []
    in_fence = False
    for line in content.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
        elif not in_fence:
            line = line.replace(" & ", " — ")
        lines.append(line)
    if not lines or not lines[0].startswith("# "):
        raise IngestionError("old Fortran idioms chapter has no section title")
    lines[1:1] = ["", OLD_FORTRAN_IDIOMS_NOTICE]
    return "\n".join(lines).rstrip() + "\n"


def _convert_old_fortran_idioms(source: Source, root: Path) -> tuple[tuple[FileRecord, ...], str]:
    bibliography_path = root / "src" / "old_idioms.bib"
    if not bibliography_path.is_file():
        raise IngestionError("old Fortran idioms bibliography is unavailable")
    citation_urls = _bibtex_urls(bibliography_path.read_text(encoding="utf-8"))
    records: list[FileRecord] = []
    for filename in OLD_FORTRAN_IDIOM_CHAPTERS:
        input_path = root / "src" / filename
        if not input_path.is_file():
            raise IngestionError(f"old Fortran idioms chapter is unavailable: {filename}")
        content = input_path.read_text(encoding="utf-8")
        if filename == "old_memory_management.tex":
            content = re.sub(
                r"\\subsection\{Initialising variables in COMMON blocks: BLOCK DATA\}.*?"
                r"(?=\\subsection\{Work arrays\})",
                "",
                content,
                flags=re.DOTALL,
            )
        output_path = root / "manual" / "src" / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(_convert_old_idioms_tex(content, citation_urls), encoding="utf-8")
        records.append(_record_file(output_path, root))
    return tuple(records), "builtin old-fortran-idioms-latex 1"


PRIMA_MODIFICATION_NOTICE = (
    "> Modified copy: only the compact goal and testing method for modernizing the original "
    "Fortran 77 implementation are retained; project-specific material is excluded."
)


def _convert_prima_modernization(source: Source, root: Path) -> tuple[tuple[FileRecord, ...], str]:
    readme_path = root / "README.md"
    if not readme_path.is_file():
        raise IngestionError("PRIMA README is unavailable")
    content = readme_path.read_text(encoding="utf-8")
    try:
        goal_start = content.index("PRIMA aims to provide")
        goal_end = content.index("There do exist", goal_start)
        method_start = content.index("The mission of PRIMA is nontrivial", goal_end)
        method_end = content.index("[The tests](./tests.md) are **automated**", method_start)
    except ValueError as error:
        raise IngestionError("PRIMA modernization sections changed upstream") from error
    output = "\n\n".join(
        (
            "# Behavior-preserving modernization in PRIMA",
            PRIMA_MODIFICATION_NOTICE,
            "## Goal and constraints\n\n" + content[goal_start:goal_end].strip(),
            "## Incremental testing method\n\n" + content[method_start:method_end].strip(),
        )
    )
    output_path = root / "manual" / "README.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output.rstrip() + "\n", encoding="utf-8")
    return (_record_file(output_path, root),), "builtin prima-modernization-subset 1"


def _normalize_myst_markdown(content: str) -> str:
    content = re.sub(r"^\([^)]+\)=\s*\n", "", content, flags=re.MULTILINE)
    content = re.sub(r"^```\{(?:play-)?code-block\}\s*", "```", content, flags=re.MULTILINE)
    return content


def _compact_intrinsic(content: str) -> str:
    content = _normalize_myst_markdown(content)
    content = re.sub(r"^##\s+", "## ", content, count=1, flags=re.MULTILINE)
    content = re.sub(
        r"^#{3,6}\s+\*\*(.+?)\*\*\s*$",
        lambda match: f"**{match.group(1)}**",
        content,
        flags=re.MULTILINE,
    )
    return content.strip()


def _intrinsic_groups(content: str) -> dict[str, tuple[str, ...]]:
    groups: dict[str, list[str]] = {}
    current: str | None = None
    for line in content.splitlines():
        group = re.fullmatch(r"([a-z_]+):", line)
        if group:
            current = group.group(1)
            groups[current] = []
            continue
        name = re.fullmatch(r'\s+-\s+"([A-Z0-9_]+)"', line)
        if name and current is not None:
            groups[current].append(name.group(1))
    return {key: tuple(value) for key, value in groups.items()}


def _published_fortran_lang_path(path: PurePosixPath) -> PurePosixPath:
    relative = path.relative_to(PurePosixPath("source"))
    if relative.suffix == ".md":
        relative = (
            relative.parent if relative.name == "index.md" else relative.parent / relative.stem
        )
    return PurePosixPath("manual", *relative.parts, "index.md")


def _convert_fortran_lang_markdown(
    source: Source, root: Path
) -> tuple[tuple[FileRecord, ...], str]:
    output_dir = root / "manual"
    output_dir.mkdir()
    records: list[FileRecord] = []

    if source.id == "fortran-lang-intrinsics-reference":
        groups_path = root / "data/intrinsics.yml"
        index_path = root / "source/learn/intrinsics/index.md"
        if not groups_path.is_file() or not index_path.is_file():
            raise IngestionError("Fortran-lang intrinsic source metadata is incomplete")
        groups = _intrinsic_groups(groups_path.read_text(encoding="utf-8"))
        for group, names in groups.items():
            parts = [f"# {group.replace('_', ' ').title()} Fortran intrinsics"]
            for name in names:
                path = root / f"source/learn/intrinsics/_pages/{name}.md"
                if not path.is_file():
                    raise IngestionError(f"Fortran-lang intrinsic page is unavailable: {name}")
                parts.append(_compact_intrinsic(path.read_text(encoding="utf-8")))
            output_path = output_dir / f"learn/intrinsics/{group}/index.md"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
            records.append(_record_file(output_path, root))
        overview = _normalize_myst_markdown(index_path.read_text(encoding="utf-8"))
        overview = re.sub(r"::::\{dropdown\}.*?::::\s*", "", overview, flags=re.DOTALL)
        output_path = output_dir / "learn/intrinsics/index.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(overview.strip() + "\n", encoding="utf-8")
        records.append(_record_file(output_path, root))
    else:
        for path in sorted(root.glob("source/learn/**/*.md")):
            relative = path.relative_to(root).as_posix()
            if not _matches(relative, source.include_paths):
                continue
            output_path = root.joinpath(
                *_published_fortran_lang_path(PurePosixPath(relative)).parts
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                _normalize_myst_markdown(path.read_text(encoding="utf-8")), encoding="utf-8"
            )
            records.append(_record_file(output_path, root))
    if not records:
        raise IngestionError("Fortran-lang Markdown conversion produced no documentation pages")
    return tuple(sorted(records, key=lambda item: item.path)), "builtin fortran-lang-markdown 1"


OPENMP_FORTRAN_EXAMPLE = re.compile(
    r"\\(?P<kind>f(?:free)?n?example)(?:\[[^]]+\])?"
    r"\{(?P<name>[^}]+)\}\{(?P<number>[^}]+)\}"
)


def _openmp_example(content: str, path: Path) -> str:
    """Render one official OpenMP Fortran example as a fenced block."""
    metadata = "\n".join(
        line.removeprefix("! @@").strip()
        for line in content.splitlines()
        if line.lstrip().startswith("! @@")
    )
    header = f"Example source: `{path.name}`"
    if metadata:
        header += f"\n\n```text\n{metadata}\n```"
    return f"{header}\n\n```fortran\n{content.rstrip()}\n```"


def _replace_tex_command(content: str, command: str, render: Callable[[str], str]) -> str:
    """Replace a braced LaTeX command while respecting nested, unescaped braces."""
    marker = f"\\{command}{{"
    start = content.find(marker)
    while start >= 0:
        value_start = start + len(marker)
        depth = 1
        index = value_start
        while index < len(content) and depth:
            if content[index] in "{}" and (index == 0 or content[index - 1] != "\\"):
                depth += 1 if content[index] == "{" else -1
            index += 1
        if depth:
            break
        content = content[:start] + render(content[value_start : index - 1]) + content[index:]
        start = content.find(marker, start)
    return content


def _convert_openmp_tex(content: str, path: Path, root: Path) -> str | None:
    if OPENMP_FORTRAN_EXAMPLE.search(content) is None:
        return None

    def example(match: re.Match[str]) -> str:
        suffix = ".f90" if "free" in match.group("kind") else ".f"
        source_path = (
            path.parent / "sources" / (f"{match.group('name')}.{match.group('number')}{suffix}")
        )
        if not source_path.is_file():
            raise IngestionError(
                f"OpenMP Fortran example source is unavailable: {source_path.relative_to(root)}"
            )
        return _openmp_example(source_path.read_text(encoding="utf-8"), source_path)

    content = re.sub(r"(?m)^\s*%.*$", "", content)
    content = re.sub(r"``([^`\n]+)''", r'"\1"', content)
    content = re.sub(
        r"\\begin\{(?P<environment>figure|tikzpicture)\}.*?"
        r"\\end\{(?P=environment)\}",
        "\n[Diagram omitted; see the cited official source.]\n",
        content,
        flags=re.DOTALL,
    )
    content = re.sub(
        r"\\begin\{(?P<language>c|cpp|ccpp)specific\}.*?"
        r"\\end\{(?P=language)specific\}",
        "",
        content,
        flags=re.DOTALL,
    )
    content = re.sub(r"\\(?:begin|end)\{fortranspecific\}", "", content)
    content = OPENMP_FORTRAN_EXAMPLE.sub(example, content)
    content = re.sub(
        r"\\(?:c|cpp|src)n?example(?:\[[^]]+\])?"
        r"\{[^}]+\}\{[^}]+\}(?:\{[^}]+\})?",
        "",
        content,
    )
    for command in ("kcode", "ucode", "bcode", "vcode", "code", "scode", "pout"):
        content = _replace_tex_command(content, command, lambda value: f"`{value}`")
    for command in ("docref", "specref"):
        content = _replace_tex_command(content, command, lambda value: value)
    for command in ("emph", "textit"):
        content = _replace_tex_command(content, command, lambda value: f"*{value}*")
    content = _replace_tex_command(content, "textbf", lambda value: f"**{value}**")
    for command, prefix in (("section", "#"), ("subsection", "##"), ("subsubsection", "###")):
        content = re.sub(rf"\\{command}\{{([^{{}}]+)\}}", rf"{prefix} \1", content)
    content = re.sub(r"(?m)^\s*\\item\s*", "- ", content)
    content = re.sub(
        r"\\(?:begin|end)\{(?:itemize|enumerate|description|compactitem)\}", "", content
    )
    content = re.sub(r"\\begin\{(?:small)?verbatim\}", "```text", content)
    content = re.sub(r"\\end\{(?:small)?verbatim\}", "```", content)
    content = re.sub(r"\\(?:index|label|newlabel|verlabel)\{(?:[^{}]|\{[^{}]*\})*\}", "", content)
    content = re.sub(
        r"\\(?:pagebreak|clearpage|newpage|bigskip|smallskip|noindent|linenumbers|nolinenumbers)\b",
        "",
        content,
    )
    content = content.replace(r"\OpenMP", "OpenMP").replace(r"\LaTeX", "LaTeX")
    content = content.replace(r"\\", "\n")
    content = content.replace("~", " ").replace(r"\_", "_").replace(r"\%", "%")
    content = re.sub(r"\$([^$]+)\$", r"\1", content)
    content = content.replace(r"\times", " x ").replace(r"\rightarrow", " -> ")
    content = content.replace(r"\le", " <= ").replace(r"\ge", " >= ")
    content = re.sub(r"\\([A-Za-z]+)\{([^{}]*)\}", r"\2", content)
    content = re.sub(r"\\([A-Za-z]+)\b", r"\1", content)
    content = re.sub(r"\n{3,}", "\n\n", content).strip()
    return content + "\n"


def _convert_openmp_examples(source: Source, root: Path) -> tuple[tuple[FileRecord, ...], str]:
    output_dir = root / "manual"
    output_dir.mkdir()
    records: list[FileRecord] = []
    for path in sorted(root.rglob("*.tex")):
        markdown = _convert_openmp_tex(path.read_text(encoding="utf-8"), path, root)
        if markdown is None:
            continue
        relative = path.relative_to(root)
        output_path = output_dir / relative
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding="utf-8")
        records.append(_record_file(output_path, root))
    if not records:
        raise IngestionError("OpenMP conversion found no Fortran examples")
    return tuple(records), "builtin openmp-examples 1"


GNU_MAKE_MANUAL_PAGES = (
    "Rule-Syntax",
    "Prerequisite-Types",
    "Phony-Targets",
    "Static-Pattern",
    "Automatic-Prerequisites",
    "Parallel",
    "Parallel-Disable",
    "Parallel-Output",
    "Recursion",
    "Pattern-Intro",
    "Pattern-Examples",
    "Automatic-Variables",
    "Catalogue-of-Rules",
    "Implicit-Variables",
    "Errors",
    "GNU-Free-Documentation-License",
)


def _convert_gnu_make_texinfo(source: Source, root: Path) -> tuple[tuple[FileRecord, ...], str]:
    executable = shutil.which("makeinfo") or shutil.which("texi2any")
    if executable is None:
        raise IngestionError(
            "GNU Make conversion requires makeinfo 7.3; install GNU Texinfo and add it to PATH"
        )
    try:
        version_output = subprocess.run(
            [executable, "--version"], check=True, capture_output=True, text=True, timeout=10
        ).stdout
    except (OSError, subprocess.SubprocessError) as error:
        raise IngestionError(f"could not run Texinfo converter: {error}") from error
    first_line = version_output.splitlines()[0] if version_output else ""
    if first_line.rsplit(" ", 1)[-1] != "7.3":
        raise IngestionError(f"GNU Make conversion requires makeinfo 7.3; found {first_line}")

    entrypoint = root / "doc/make.texi"
    html_dir = root / ".generated-html"
    environment = {**os.environ, "LC_ALL": "C.UTF-8"}
    try:
        subprocess.run(
            [executable, "--html", f"--output={html_dir}", str(entrypoint)],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as error:
        detail = getattr(error, "stderr", None) or str(error)
        raise IngestionError(f"GNU Make Texinfo conversion failed: {detail.strip()}") from error

    try:
        from html_to_markdown import ConversionOptions, convert
    except ImportError as error:
        raise IngestionError(
            "GNU Make conversion requires the 'ingest' extra: install fortran-mcp[ingest]"
        ) from error

    output_dir = root / "manual"
    output_dir.mkdir()
    records: list[FileRecord] = []
    options = ConversionOptions(
        extract_metadata=False,
        exclude_selectors=[".header", ".nav-panel", ".copiable-link", "hr"],
    )
    for stem in GNU_MAKE_MANUAL_PAGES:
        html_path = html_dir / f"{stem}.html"
        if not html_path.is_file():
            raise IngestionError(f"GNU Make manual page is unavailable: {stem}")
        result = convert(html_path.read_text(encoding="utf-8"), options)
        markdown = (result.content or "").strip()
        if not markdown:
            raise IngestionError(f"GNU Make manual page is empty: {stem}")
        output_path = output_dir / f"{stem}.md"
        output_path.write_text(markdown + "\n", encoding="utf-8")
        records.append(_record_file(output_path, root))
    shutil.rmtree(html_dir)

    notice = root / "FORTRAN-MCP-MODIFICATION-NOTICE.txt"
    notice.write_text(
        "Fortran-focused GNU Make 4.4.1 Manual Extracts\n\n"
        "Modified and selected by Fortran MCP contributors from The GNU Make Manual.\n"
        "Principal authors: Richard M. Stallman, Roland McGrath, and Paul D. Smith.\n"
        "Modifications: conversion to Markdown and selection of build-rule, dependency, "
        "parallel-execution, diagnostic, and Fortran-relevant reference sections.\n",
        encoding="utf-8",
    )
    records.append(_record_file(notice, root))
    return tuple(records), f"{first_line}; curated pages 1"


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
        elif source.converter == "cmake-rst":
            generated, converter_version = _convert_cmake_rst(source, temporary_path)
            stored_files = tuple(sorted((*stored_files, *generated), key=lambda item: item.path))
            schema_version = 2
        elif source.converter == "fortran-lang-markdown":
            generated, converter_version = _convert_fortran_lang_markdown(source, temporary_path)
            stored_files = tuple(sorted((*stored_files, *generated), key=lambda item: item.path))
            schema_version = 2
        elif source.converter == "openmp-examples":
            generated, converter_version = _convert_openmp_examples(source, temporary_path)
            stored_files = tuple(sorted((*stored_files, *generated), key=lambda item: item.path))
            schema_version = 2
        elif source.converter == "gnu-make-texinfo":
            generated, converter_version = _convert_gnu_make_texinfo(source, temporary_path)
            stored_files = tuple(sorted((*stored_files, *generated), key=lambda item: item.path))
            schema_version = 2
        elif source.converter == "numpy-f2py-rst":
            generated, converter_version = _convert_numpy_f2py_rst(source, temporary_path)
            stored_files = tuple(sorted((*stored_files, *generated), key=lambda item: item.path))
            schema_version = 2
        elif source.converter == "fypp-rst":
            generated, converter_version = _convert_fypp_rst(source, temporary_path)
            stored_files = tuple(sorted((*stored_files, *generated), key=lambda item: item.path))
            schema_version = 2
        elif source.converter == "openmpi-fortran-rst":
            generated, converter_version = _convert_openmpi_fortran_rst(source, temporary_path)
            stored_files = tuple(sorted((*stored_files, *generated), key=lambda item: item.path))
            schema_version = 2
        elif source.converter == "codee-fortran-subset":
            generated, converter_version = _convert_codee_fortran_subset(source, temporary_path)
            stored_files = tuple(sorted((*stored_files, *generated), key=lambda item: item.path))
            schema_version = 2
        elif source.converter == "old-fortran-idioms-latex":
            generated, converter_version = _convert_old_fortran_idioms(source, temporary_path)
            stored_files = tuple(sorted((*stored_files, *generated), key=lambda item: item.path))
            schema_version = 2
        elif source.converter == "prima-modernization-subset":
            generated, converter_version = _convert_prima_modernization(source, temporary_path)
            stored_files = tuple(sorted((*stored_files, *generated), key=lambda item: item.path))
            schema_version = 2
        elif source.converter == "beliavsky-packages":
            generated, converter_version = _convert_beliavsky_packages(source, temporary_path)
            stored_files = tuple(sorted((*stored_files, *generated), key=lambda item: item.path))
            schema_version = 2
        elif source.converter == "fortran-lang-package-index":
            generated, converter_version = _convert_fortran_lang_package_index(
                source, temporary_path
            )
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
