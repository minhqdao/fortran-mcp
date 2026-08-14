"""Fuse lexical and semantic documentation rankings."""

from collections import Counter

from fortran_mcp.search import SearchProvider, SearchResult

RRF_CONSTANT = 60
DEFAULT_SEMANTIC_THRESHOLD = 0.785
CONCENTRATED_SEMANTIC_THRESHOLD = 0.74
CONCENTRATED_DOCUMENT_RESULTS = 8
CONCENTRATED_DOCUMENT_RATIO = 0.70
MAX_RESULTS_PER_DOCUMENT = 4


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
        semantic_results = self.semantic.search(query, limit=candidate_limit, **filters)
        document_counts = Counter((result.source_id, result.path) for result in semantic_results)
        dominant_document_results = max(document_counts.values(), default=0)
        concentrated = (
            bool(semantic_results)
            and semantic_results[0].score >= CONCENTRATED_SEMANTIC_THRESHOLD
            and dominant_document_results >= CONCENTRATED_DOCUMENT_RESULTS
            and dominant_document_results / len(semantic_results)
            >= CONCENTRATED_DOCUMENT_RATIO
        )
        if not any(filters.values()) and (
            not semantic_results
            or (semantic_results[0].score < self.semantic_threshold and not concentrated)
        ):
            return ()
        rankings = (
            (
                self.lexical.search(query, limit=candidate_limit, **filters),
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
