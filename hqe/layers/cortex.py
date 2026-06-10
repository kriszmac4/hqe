"""HQE Layer: Cortex — session database search."""


class CortexAdapter:
    """Search agent conversation sessions via FTS5."""

    def __init__(self, paths: list[str] | None = None):
        self.paths = paths or []

    def search(self, query: str, **kwargs) -> list[dict]:
        """Search session databases for matching conversations."""
        # TODO: implement FTS5 search across state.db files
        return []
