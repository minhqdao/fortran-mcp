"""Fuse lexical and semantic documentation rankings."""

from fortran_mcp.search import SearchProvider, SearchResult

RRF_CONSTANT = 60
DEFAULT_SEMANTIC_THRESHOLD = 0.785


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
        if not any(filters.values()) and (
            not semantic_results or semantic_results[0].score < self.semantic_threshold
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
        ordered = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))[:limit]
        return tuple(
            results[chunk_id].model_copy(update={"score": scores[chunk_id]}) for chunk_id in ordered
        )

    def get_chunk(self, chunk_id: str) -> SearchResult:
        return self.lexical.get_chunk(chunk_id)
