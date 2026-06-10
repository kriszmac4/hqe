"""HQE Layer: Graph — entity-relationship search."""


class GraphAdapter:
    """Search entity-relationship stores."""

    def __init__(self, paths: list[str] | None = None):
        self.paths = paths or []

    def search(self, query: str, **kwargs) -> list[dict]:
        """Search entity graph for matches."""
        # TODO: implement entity probe/reason search
        return []
