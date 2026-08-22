"""Inspect and materialize reviewed documentation sources."""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from fortran_mcp.config import data_directory
from fortran_mcp.documents import DocumentBuildError, build_documents
from fortran_mcp.ingest import IngestionError, ingest_source
from fortran_mcp.search import SearchError, build_index
from fortran_mcp.sources import (
    RedistributionPolicy,
    SourceStatus,
    StrictModel,
    load_registry,
)


class SyncedSource(StrictModel):
    """Result of materializing one registered source."""

    source_id: str
    downloaded: bool
    chunks: int


class SourceSyncReport(StrictModel):
    """Result of one source-to-index pipeline run."""

    sources: tuple[SyncedSource, ...]
    indexed_chunks: int


class SourceSyncError(RuntimeError):
    """Raised when a requested source cannot enter the local index."""


def sync_sources(source_ids: Sequence[str], data_dir: Path) -> SourceSyncReport:
    """Ingest missing approved sources, rebuild their chunks, then rebuild the index once."""
    source_ids = tuple(dict.fromkeys(source_ids))
    registry = {source.id: source for source in load_registry().sources}
    unknown = sorted(set(source_ids) - registry.keys())
    if unknown:
        raise SourceSyncError(f"unknown source IDs: {', '.join(unknown)}")
    unavailable = sorted(
        source_id
        for source_id in source_ids
        if registry[source_id].status is not SourceStatus.APPROVED
        or registry[source_id].redistribution is not RedistributionPolicy.REDISTRIBUTABLE
    )
    if unavailable:
        raise SourceSyncError(
            f"sources are not approved for local ingestion: {', '.join(unavailable)}"
        )

    results: list[SyncedSource] = []
    try:
        for source_id in source_ids:
            source = registry[source_id]
            record_path = data_dir / "records" / f"{source_id}.json"
            downloaded = not record_path.is_file()
            if downloaded:
                ingest_source(source, data_dir)
            chunks = build_documents(source_id, data_dir)
            results.append(
                SyncedSource(source_id=source_id, downloaded=downloaded, chunks=len(chunks))
            )
        indexed = build_index(data_dir)
    except (DocumentBuildError, IngestionError, SearchError) as error:
        raise SourceSyncError(str(error)) from error
    return SourceSyncReport(sources=tuple(results), indexed_chunks=indexed)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fortran-mcp source", description="Inspect or materialize reviewed sources"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    listing = subparsers.add_parser("list", help="list registered sources")
    listing.add_argument("--json", action="store_true")
    sync = subparsers.add_parser(
        "sync", help="ingest, chunk, and index one or more registered sources"
    )
    sync.add_argument("source_ids", nargs="*")
    sync.add_argument("--all", action="store_true", help="sync every approved source")
    sync.add_argument("--data-dir", type=Path, default=data_directory())
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run reviewed-source management commands."""
    parser = _parser()
    args = parser.parse_args(argv)
    registry = load_registry()
    if args.command == "list":
        if args.json:
            print(json.dumps(registry.model_dump(mode="json"), indent=2))
        else:
            blocks = []
            for source in registry.sources:
                details = f"  {source.license} · {source.document_type}"
                if source.status is not SourceStatus.APPROVED:
                    details += f" · status: {source.status.value}"
                blocks.append(f"{source.id}\n  {source.title}\n{details}\n  {source.source_url}")
            print("\n\n".join(blocks))
        return

    if args.all == bool(args.source_ids):
        parser.error("provide source IDs or --all, but not both")
    source_ids = (
        [
            source.id
            for source in registry.sources
            if source.status is SourceStatus.APPROVED
            and source.redistribution is RedistributionPolicy.REDISTRIBUTABLE
        ]
        if args.all
        else args.source_ids
    )
    try:
        report = sync_sources(source_ids, args.data_dir)
    except SourceSyncError as error:
        parser.error(str(error))
    for synced in report.sources:
        action = "downloaded" if synced.downloaded else "reused"
        print(f"{synced.source_id}: {action}, {synced.chunks} chunks")
    print(f"Indexed {report.indexed_chunks} total chunks in {args.data_dir}")
