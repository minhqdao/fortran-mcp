"""Validated provenance models and registry loading for documentation sources."""

import tomllib
from datetime import UTC, datetime
from enum import StrEnum
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class DocumentType(StrEnum):
    """Kinds of material accepted by the documentation library."""

    STANDARD = "standard"
    CORRIGENDUM = "corrigendum"
    COMPILER_MANUAL = "compiler-manual"
    ECOSYSTEM_GUIDE = "ecosystem-guide"
    INTEROPERABILITY_GUIDE = "interoperability-guide"
    MIGRATION_GUIDE = "migration-guide"
    DIALECT_REFERENCE = "dialect-reference"


class RedistributionPolicy(StrEnum):
    """What the project may do with source content."""

    REDISTRIBUTABLE = "redistributable"
    LINK_ONLY = "link-only"
    REVIEW_REQUIRED = "review-required"


class SourceStatus(StrEnum):
    """Review state of a registry entry."""

    CANDIDATE = "candidate"
    APPROVED = "approved"
    RETIRED = "retired"


class SourceAuthority(StrEnum):
    """Authority level of a documentation source."""

    NORMATIVE = "normative"
    OFFICIAL = "official"
    COMMUNITY = "community"


class StrictModel(BaseModel):
    """Base model that rejects unknown or mutated metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Source(StrictModel):
    """A reviewed upstream documentation source."""

    id: str = Field(pattern=r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
    title: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
    document_type: DocumentType
    authority: SourceAuthority
    topics: tuple[str, ...] = Field(min_length=1)
    fortran_versions: tuple[str, ...] = ()
    compilers: tuple[str, ...] = ()
    dialects: tuple[str, ...] = ()
    version: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    source_url: HttpUrl
    archive_url: HttpUrl
    archive_root: str = Field(min_length=1)
    include_paths: tuple[str, ...] = Field(min_length=1)
    document_paths: tuple[str, ...] = Field(min_length=1)
    expected_document_count: int | None = Field(default=None, ge=1)
    homepage_url: HttpUrl
    published_path_prefix: str
    citation_base_url: HttpUrl
    citation_format: Literal["published-html", "source"]
    converter: Literal["none", "texinfo"] = "none"
    converter_entrypoint: str | None = None
    license: str = Field(min_length=1)
    license_url: HttpUrl
    redistribution: RedistributionPolicy
    status: SourceStatus
    notes: str = ""

    @model_validator(mode="after")
    def approved_sources_require_a_decided_policy(self) -> "Source":
        if (
            self.status is SourceStatus.APPROVED
            and self.redistribution is RedistributionPolicy.REVIEW_REQUIRED
        ):
            msg = "approved sources must have a decided redistribution policy"
            raise ValueError(msg)
        if self.converter == "texinfo" and not self.converter_entrypoint:
            raise ValueError("Texinfo sources require a converter entrypoint")
        if self.converter == "none" and self.converter_entrypoint is not None:
            raise ValueError("native sources must not define a converter entrypoint")
        if self.converter_entrypoint is not None:
            entrypoint = PurePosixPath(self.converter_entrypoint)
            if entrypoint.is_absolute() or ".." in entrypoint.parts:
                raise ValueError("converter entrypoint must be a safe relative path")
        return self


class SourceRegistry(StrictModel):
    """Versioned collection of source definitions."""

    schema_version: int = Field(ge=1)
    sources: tuple[Source, ...]

    @model_validator(mode="after")
    def source_ids_are_unique(self) -> "SourceRegistry":
        ids = [source.id for source in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError("source IDs must be unique")
        return self


class CitationLocation(StrictModel):
    """Stable location within an ingested document."""

    page: int | None = Field(default=None, ge=1)
    section: str | None = None
    anchor: str | None = None

    @model_validator(mode="after")
    def has_at_least_one_locator(self) -> "CitationLocation":
        if self.page is None and self.section is None and self.anchor is None:
            raise ValueError("a citation requires a page, section, or anchor")
        return self


class DocumentRecord(StrictModel):
    """Provenance captured when a document is downloaded."""

    source_id: str
    retrieved_at: datetime
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_url: HttpUrl
    citation: CitationLocation

    @model_validator(mode="after")
    def retrieval_time_has_timezone(self) -> "DocumentRecord":
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone")
        return self

    @property
    def retrieved_at_utc(self) -> datetime:
        """Return the retrieval time normalized to UTC."""
        return self.retrieved_at.astimezone(UTC)


class FileRecord(StrictModel):
    """Integrity metadata for one stored documentation file."""

    path: str = Field(min_length=1)
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class IngestionRecord(StrictModel):
    """Provenance for one completed source ingestion."""

    schema_version: Literal[1, 2] = 1
    source_id: str
    revision: str
    archive_url: HttpUrl
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieved_at: datetime
    document_paths: tuple[str, ...] = Field(min_length=1)
    files: tuple[FileRecord, ...]
    converter: str | None = None
    converter_version: str | None = None

    @model_validator(mode="after")
    def retrieval_time_has_timezone(self) -> "IngestionRecord":
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone")
        return self


def load_registry(path: Path | None = None) -> SourceRegistry:
    """Load and validate a registry, defaulting to the packaged registry."""
    if path is None:
        registry_file = files("fortran_mcp").joinpath("data/sources.toml")
        if registry_file.is_file():
            with registry_file.open("rb") as stream:
                return SourceRegistry.model_validate(tomllib.load(stream))
        path = Path(__file__).parents[2] / "docs" / "sources.toml"

    with path.open("rb") as stream:
        return SourceRegistry.model_validate(tomllib.load(stream))
