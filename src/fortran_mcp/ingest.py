"""Safely ingest approved documentation archives."""

import argparse
import hashlib
import json
import os
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
        ".md",
        ".markdown",
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
    substitutions = dict(
        re.findall(r"^\s*\.\. \|([^|]+)\| replace::\s*(.+)$", content, re.MULTILINE)
    )
    content = re.sub(r"^\s*\.\. \|[^|]+\| replace::.*(?:\n|$)", "", content, flags=re.MULTILINE)
    for name, replacement in substitutions.items():
        content = content.replace(f"|{name}|", replacement)
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
                output.append(f"{indent}*{labels[kind]} in CMake {value}.*")
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
