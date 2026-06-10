"""HQE Engine — core query engine."""

from typing import Any


class QueryEngine:
    """Unified query engine spanning memory layers."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self._layers = {}

    def register_layer(self, name: str, instance: Any):
        """Register a queryable layer (cortex, codex, graph, etc.)."""
        self._layers[name] = instance

    def query(self, text: str, layer: str | None = None, **kwargs) -> dict:
        """Execute a query across registered layers."""
        targets = [layer] if layer else list(self._layers.keys())
        results = []
        for name in targets:
            if name in self._layers:
                layer_results = self._layers[name].search(text, **kwargs)
                results.extend(layer_results)
        return {
            "query": text,
            "results": sorted(results, key=lambda r: r.get("score", 0), reverse=True),
            "total": len(results),
        }
