"""HQE Ranking — cross-source result ranking."""


class Ranker:
    """Rank and merge results from multiple layers."""

    def rank(self, results: list[dict], **kwargs) -> list[dict]:
        """Sort results by combined relevance score."""
        return sorted(results, key=lambda r: r.get("score", 0), reverse=True)
