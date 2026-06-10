"""HQE Layer: Codex — knowledge base file search."""


class CodexAdapter:
    """Search knowledge base markdown files."""

    def __init__(self, paths: list[str] | None = None):
        self.paths = paths or []

    def search(self, query: str, **kwargs) -> list[dict]:
        """Search knowledge base files for relevant content."""
        # TODO: implement FTS + optional embedding search
        return []
