"""Fuse lexical and semantic documentation rankings."""

import re
from collections import Counter

from fortran_mcp.search import SearchProvider, SearchResult
from fortran_mcp.sources import load_registry

RRF_CONSTANT = 60
# Calibrated against benchmarks/retrieval.toml; re-sweep when corpus chunk shape changes.
DEFAULT_SEMANTIC_THRESHOLD = 0.79
CONCENTRATED_SEMANTIC_THRESHOLD = 0.74
CONCENTRATED_DOCUMENT_RESULTS = 8
CONCENTRATED_DOCUMENT_RATIO = 0.70
MAX_RESULTS_PER_DOCUMENT = 4


def _mentions_applicable_dialect(query: str, results: tuple[SearchResult, ...]) -> bool:
    """Recognize an explicit registered dialect name backed by lexical evidence."""
    result_sources = {result.source_id for result in results}
    normalized_query = query.casefold()
    return any(
        source.id in result_sources
        and any(
            re.search(rf"(?<!\w){re.escape(dialect.casefold())}(?!\w)", normalized_query)
            for dialect in source.dialects
        )
        for source in load_registry().sources
    )


class HybridSearchProvider:
    """Combine two providers using reciprocal rank fusion."""

    def __init__(
        self,
        lexical: SearchProvider,
        semantic: SearchProvider,
        *,
        lexical_weight: float = 1.0,
        semantic_weight: float = 1.0,
        semantic_threshold: float = DEFAULT_SEMANTIC_THRESHOLD,
    ) -> None:
        if lexical_weight <= 0 or semantic_weight <= 0:
            raise ValueError("hybrid provider weights must be positive")
        if not 0 <= semantic_threshold <= 1:
            raise ValueError("semantic threshold must be between zero and one")
        self.lexical = lexical
        self.semantic = semantic
        self.lexical_weight = lexical_weight
        self.semantic_weight = semantic_weight
        self.semantic_threshold = semantic_threshold

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        source_id: str | None = None,
        compiler: str | None = None,
        version: str | None = None,
        fortran_version: str | None = None,
    ) -> tuple[SearchResult, ...]:
        candidate_limit = min(20, max(10, limit * 2))
        filters = {
            "source_id": source_id,
            "compiler": compiler,
            "version": version,
            "fortran_version": fortran_version,
        }
        lexical_results = self.lexical.search(query, limit=candidate_limit, **filters)
        semantic_results = self.semantic.search(query, limit=candidate_limit, **filters)
        document_counts = Counter((result.source_id, result.path) for result in semantic_results)
        dominant_document_results = max(document_counts.values(), default=0)
        concentrated = (
            bool(semantic_results)
            and semantic_results[0].score >= CONCENTRATED_SEMANTIC_THRESHOLD
            and dominant_document_results >= CONCENTRATED_DOCUMENT_RESULTS
            and dominant_document_results / len(semantic_results) >= CONCENTRATED_DOCUMENT_RATIO
        )
        dialect_evidence = _mentions_applicable_dialect(query, lexical_results)
        if (
            not any(filters.values())
            and not dialect_evidence
            and (
                not semantic_results
                or (semantic_results[0].score < self.semantic_threshold and not concentrated)
            )
        ):
            return ()
        rankings = (
            (
                lexical_results,
                self.lexical_weight,
            ),
            (
                semantic_results,
                self.semantic_weight,
            ),
        )
        scores: dict[str, float] = {}
        results: dict[str, SearchResult] = {}
        for ranking, weight in rankings:
            for rank, result in enumerate(ranking, start=1):
                scores[result.chunk_id] = scores.get(result.chunk_id, 0.0) + weight / (
                    RRF_CONSTANT + rank
                )
                results.setdefault(result.chunk_id, result)
        ranked = sorted(scores, key=lambda item: (-scores[item], item))
        ordered: list[str] = []
        deferred: list[str] = []
        selected_documents: Counter[tuple[str, str]] = Counter()
        for chunk_id in ranked:
            result = results[chunk_id]
            document = (result.source_id, result.path)
            if selected_documents[document] >= MAX_RESULTS_PER_DOCUMENT:
                deferred.append(chunk_id)
                continue
            ordered.append(chunk_id)
            selected_documents[document] += 1
            if len(ordered) == limit:
                break
        if len(ordered) < limit:
            ordered.extend(deferred[: limit - len(ordered)])
        return tuple(
            results[chunk_id].model_copy(update={"score": scores[chunk_id]}) for chunk_id in ordered
        )

    def get_chunk(self, chunk_id: str) -> SearchResult:
        return self.lexical.get_chunk(chunk_id)
