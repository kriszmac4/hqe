"""HQE CLI — Command-line interface."""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="hqe",
        description="Hermes Query Engine — unified search across agent memory",
    )
    parser.add_argument(
        "query",
        nargs="?",
        help="Natural language query",
    )
    parser.add_argument(
        "--layer",
        "-l",
        choices=["all", "cortex", "codex", "graph"],
        default="all",
        help="Which memory layer to search (default: all)",
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=["pretty", "json", "csv"],
        default="pretty",
        help="Output format (default: pretty)",
    )
    parser.add_argument(
        "--max-results",
        "-n",
        type=int,
        default=20,
        help="Maximum results (default: 20)",
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Start interactive mode",
    )
    parser.add_argument(
        "--version",
        "-v",
        action="version",
        version="HQE 1.0.0",
    )

    args = parser.parse_args()

    if args.interactive or not args.query:
        _run_interactive()
        return

    result = _execute_query(args.query, layer=args.layer, max_results=args.max_results)
    _render(result, fmt=args.format)


def _execute_query(query: str, layer: str = "all", max_results: int = 20) -> dict:
    """Execute a query across the selected layers."""
    # TODO: implement actual query engine
    return {
        "query": query,
        "layer": layer,
        "results": [],
        "total": 0,
    }


def _render(result: dict, fmt: str = "pretty"):
    """Render query results."""
    if fmt == "json":
        import json
        print(json.dumps(result, indent=2))
    elif fmt == "csv":
        print("layer,source,title,score")
    else:
        print(f"\n  Query: {result['query']}")
        print(f"  Layer: {result['layer']}")
        print(f"  Results: {result['total']}")
        print()


def _run_interactive():
    """Start interactive query mode."""
    print("HQE Interactive — type 'exit' to quit")
    print()
    try:
        import readline
    except ImportError:
        pass
    while True:
        try:
            q = input("hqe> ").strip()
            if not q:
                continue
            if q.lower() in ("exit", "quit", ":q"):
                break
            result = _execute_query(q)
            _render(result)
        except (KeyboardInterrupt, EOFError):
            print()
            break


if __name__ == "__main__":
    main()
