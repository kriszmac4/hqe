"""HQE Router — classify query intent and dispatch to appropriate layers."""


class SemanticRouter:
    """Classify query intent and route to best layer(s)."""

    def route(self, query: str) -> list[str]:
        """Determine which layers should process this query."""
        q = query.lower()
        layers = []

        # Session-related keywords → Cortex
        if any(w in q for w in ["session", "beszél", "mondt", "beszélt", "discuss", "talk", "chat"]):
            layers.append("cortex")

        # Document-related keywords → Codex
        if any(w in q for w in ["könyv", "doksi", "document", "pdf", "file", "knowledge", "guide",
                                 "Natenberg", "Chan", "Taleb", "Wheel", "strategy"]):
            layers.append("codex")

        # Entity-related keywords → Graph
        if any(w in q for w in ["entity", "related", "kapcsol", "minden", "all", "project",
                                 "who", "what is", "mi az", "ki az"]):
            layers.append("graph")

        # Default: all layers
        if not layers:
            layers = ["cortex", "codex", "graph"]

        return layers
