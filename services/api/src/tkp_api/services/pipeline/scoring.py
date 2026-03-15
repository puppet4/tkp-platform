"""Score normalisation utilities.

All internal scores are normalised to 0.0–1.0.
API output converts to int(score * 100) to stay compatible with the existing
RetrievalHit.score: int schema.
"""

from __future__ import annotations


def normalize_vector_score(cosine_distance: float) -> float:
    """pgvector returns cosine *distance* (0-2).  similarity = 1 - distance."""
    return max(0.0, min(1.0, 1.0 - cosine_distance))


def normalize_vector_similarity(similarity: float) -> float:
    """If we already have similarity (1 - distance), just clamp."""
    return max(0.0, min(1.0, similarity))


def normalize_keyword_tsvector(ts_rank: float) -> float:
    """ts_rank() can exceed 1.0, so we scale and clamp."""
    return max(0.0, min(1.0, ts_rank * 2.0))


def normalize_keyword_trigram(similarity: float) -> float:
    """pg_trgm similarity() already in 0-1."""
    return max(0.0, min(1.0, similarity))


def normalize_rrf_scores(hits: list[dict], score_key: str = "score") -> list[dict]:
    """Divide all RRF scores by the maximum so the top hit = 1.0."""
    if not hits:
        return hits
    max_score = max(h[score_key] for h in hits)
    if max_score <= 0:
        return hits
    for h in hits:
        h[score_key] = h[score_key] / max_score
    return hits


def score_to_api(normalised: float) -> int:
    """0.0-1.0 → 0-100 for API output."""
    return int(max(0.0, min(1.0, normalised)) * 100)


def api_min_score_to_internal(api_min_score: int) -> float:
    """Convert legacy 0-1000 min_score to internal 0-1.

    Existing callers send 0-1000; new callers can send 0-100.
    We handle both by dividing by 1000 if > 1, by 100 if <= 100.
    """
    if api_min_score <= 0:
        return 0.0
    if api_min_score > 100:
        return min(1.0, api_min_score / 1000.0)
    return min(1.0, api_min_score / 100.0)
