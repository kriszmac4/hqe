#!/usr/bin/env python3
"""
HQE MCP Server — Hermes Query Engine

Unified semantic search across agent memory layers:
- Cortex: session databases (FTS5 on state.db)
- Codex: knowledge base files (FTS5 on hqe_codex.db)
- Graph: entity relationship store (FTS5 on session content)

Usage:
    python3 hqe_mcp_server.py

Register in config.yaml:
    mcp_servers:
      hqe:
        command: python3
        args:
        - /home/artofphotogrphyy/.hermes/profiles/dev/scripts/hqe_mcp_server.py
        env:
          HERMES_HOME: /home/artofphotogrphyy/.hermes
          HERMES_PROFILE: dev
        connect_timeout: 5
        timeout: 30
"""

import json
import logging
import os
import sqlite3
import sys
import re
from pathlib import Path
from datetime import datetime
from typing import Any

import asyncio
from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions, Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("hqe-mcp")

server = Server("hqe")

# ─── Configuration ──────────────────────────────────────────────────────────

# Resolve Herrmes home
HERMES_HOME = os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))

# Database paths — absolute to avoid profile home remapping issues
STATE_DB = "/home/artofphotogrphyy/.hermes/state.db" if os.path.exists("/home/artofphotogrphyy/.hermes/state.db") else os.path.join(HERMES_HOME, "state.db")
CODEX_DB = "/home/artofphotogrphyy/.hermes/profiles/dev/data/hqe_codex.db" if os.path.exists("/home/artofphotogrphyy/.hermes/profiles/dev/data/hqe_codex.db") else os.path.join(HERMES_HOME, "profiles", "dev", "data", "hqe_codex.db")

# Also scan for additional profile state DBs
PROFILES_DIR = "/home/artofphotogrphyy/.hermes/profiles" if os.path.exists("/home/artofphotogrphyy/.hermes/profiles") else os.path.join(HERMES_HOME, "profiles")

MAX_RESULTS_PER_LAYER = 15
MAX_TOTAL_RESULTS = 30

# ─── Layer implementations ──────────────────────────────────────────────────

def _search_cortex(query: str, limit: int = MAX_RESULTS_PER_LAYER) -> list[dict]:
    """Search session messages using FTS5."""
    results = []
    db_paths = _find_state_dbs()

    for db_path in db_paths:
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # FTS5 search on messages
            sql = """
                SELECT m.id, m.session_id, m.role, 
                       snippet(messages_fts, 0, '<<<', '>>>', '...', 40) AS snippet,
                       m.timestamp, s.title AS session_title
                FROM messages m
                JOIN messages_fts ON m.id = messages_fts.rowid
                LEFT JOIN sessions s ON m.session_id = s.id
                WHERE messages_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """
            try:
                cursor.execute(sql, (query, limit))
                for row in cursor.fetchall():
                    results.append({
                        "id": row["id"],
                        "session_id": row["session_id"],
                        "session_title": row["session_title"] or "Untitled",
                        "role": row["role"],
                        "snippet": row["snippet"],
                        "timestamp": row["timestamp"],
                        "layer": "cortex",
                        "source": db_path,
                    })
            except sqlite3.OperationalError as e:
                logger.warning(f"FTS5 search failed on {db_path}: {e}")

            conn.close()
        except Exception as e:
            logger.error(f"Error searching {db_path}: {e}")

    return results


def _search_codex(query: str, limit: int = MAX_RESULTS_PER_LAYER) -> list[dict]:
    """Search knowledge base index using FTS5."""
    results = []
    if not os.path.exists(CODEX_DB):
        logger.warning(f"Codex DB not found: {CODEX_DB}")
        return results

    try:
        conn = sqlite3.connect(CODEX_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        sql = """
            SELECT file_path, file_name, category,
                   snippet(codex_fts, 2, '<<<', '>>>', '...', 40) AS snippet
            FROM codex_fts
            WHERE codex_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """
        try:
            cursor.execute(sql, (query, limit))
            for row in cursor.fetchall():
                results.append({
                    "file_path": row["file_path"],
                    "file_name": row["file_name"],
                    "category": row["category"],
                    "snippet": row["snippet"],
                    "layer": "codex",
                    "source": CODEX_DB,
                })
        except sqlite3.OperationalError as e:
            logger.warning(f"Codex FTS5 search failed: {e}")

        conn.close()
    except Exception as e:
        logger.error(f"Error searching codex: {e}")

    return results


def _search_graph(query: str, limit: int = MAX_RESULTS_PER_LAYER) -> list[dict]:
    """Search entity relationships from session content.
    
    Extracts entity mentions and relationships from message content.
    Uses pattern matching for known entity types and FTS5 fallback.
    """
    results = []
    db_paths = _find_state_dbs()

    # Entity extraction patterns
    entity_patterns = [
        (r'(?i)\b(project|repo|repository)\s*[:\s]+([\w\-\./]+)', "project"),
        (r'(?i)\b(tool|script|function)\s*[:\s]+([\w\-\._]+)', "tool"),
        (r'(?i)\b(book|paper|source|author)\s*[:\s]+([\w\-\.\s]+)', "reference"),
        (r'(?i)\b(stock|ticker|symbol)\s*[:\s]+([A-Z]{1,5})\b', "financial"),
        (r'(?i)\b(file|path|location)\s*[:\s]+([\w\-\._/\\~]+)', "filepath"),
    ]

    # Search for entity relationships in messages
    for db_path in db_paths:
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Use FTS5 to find relevant messages
            sql = """
                SELECT m.id, m.session_id, m.role, m.content,
                       m.timestamp, s.title AS session_title
                FROM messages m
                JOIN messages_fts ON m.id = messages_fts.rowid
                LEFT JOIN sessions s ON m.session_id = s.id
                WHERE messages_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """
            try:
                cursor.execute(sql, (query, limit * 2))  # Fetch more for entity extraction
                for row in cursor.fetchall():
                    content = row["content"] or ""
                    # Try to extract entity relationships
                    entities_found = []
                    for pattern, etype in entity_patterns:
                        for match in re.finditer(pattern, content):
                            entities_found.append({
                                "type": etype,
                                "value": match.group(2).strip(),
                                "match": match.group(0).strip(),
                            })

                    if entities_found:
                        results.append({
                            "id": row["id"],
                            "session_id": row["session_id"],
                            "session_title": row["session_title"] or "Untitled",
                            "role": row["role"],
                            "entities": entities_found,
                            "content_preview": content[:200],
                            "timestamp": row["timestamp"],
                            "layer": "graph",
                            "source": db_path,
                        })
            except sqlite3.OperationalError:
                pass

            conn.close()
        except Exception as e:
            logger.error(f"Error in graph search for {db_path}: {e}")

    return results[:limit]


def _find_state_dbs() -> list[str]:
    """Find all accessible state.db files across profiles."""
    dbs = []
    
    # Primary state.db
    if os.path.exists(STATE_DB):
        dbs.append(STATE_DB)
    
    # Profile-specific state DBs
    if os.path.isdir(PROFILES_DIR):
        for profile_name in sorted(os.listdir(PROFILES_DIR)):
            profile_db = os.path.join(PROFILES_DIR, profile_name, "state.db")
            if os.path.exists(profile_db) and os.path.getsize(profile_db) > 100:
                if profile_db not in dbs:
                    dbs.append(profile_db)
    
    return dbs


def _rank_and_merge(all_results: list[dict], query: str) -> list[dict]:
    """Rank and merge results from all layers with relevance scoring."""
    query_lower = query.lower()
    query_terms = set(query_lower.split())

    for r in all_results:
        score = 0.0

        # Base score from layer weight
        layer_weights = {"cortex": 1.0, "codex": 1.2, "graph": 1.1}
        score += layer_weights.get(r.get("layer", ""), 1.0)

        # Content match bonus
        text = json.dumps(r).lower()
        term_matches = sum(1 for t in query_terms if t in text)
        score += term_matches * 0.5

        # Freshness bonus (cortex only)
        ts = r.get("timestamp")
        if ts:
            try:
                age_hours = (datetime.now().timestamp() - float(ts)) / 3600
                if age_hours < 24:
                    score += 2.0
                elif age_hours < 168:  # 1 week
                    score += 1.0
                elif age_hours < 720:  # 1 month
                    score += 0.5
            except (ValueError, TypeError):
                pass

        # Snippet match precision bonus
        snippet = r.get("snippet", r.get("content_preview", ""))
        if "<<" in snippet:  # FTS5 highlighted
            score += 0.5

        r["score"] = round(score, 2)

    # Sort by score descending
    all_results.sort(key=lambda r: r["score"], reverse=True)
    return all_results[:MAX_TOTAL_RESULTS]


# ─── Tool definitions ───────────────────────────────────────────────────────

def _tool(name: str, description: str, inputSchema: dict) -> Tool:
    return Tool(name=name, description=description, inputSchema=inputSchema)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        _tool(
            "hqe_query",
            "Unified semantic search across ALL agent memory layers (Cortex + Codex + Graph). "
            "Use this when you need information from past conversations, knowledge base files, "
            "or entity relationships. One query searches everything at once.",
            {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language search query (e.g. 'Wheel strategy deployment', 'Natenberg delta hedging')"
                    },
                    "layers": {
                        "type": "string",
                        "enum": ["all", "cortex", "codex", "graph"],
                        "description": "Which layers to search (default: all)",
                        "default": "all"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results (default: 20)",
                        "default": 20
                    }
                },
                "required": ["query"]
            }
        ),
        _tool(
            "hqe_search_cortex",
            "Search only the Cortex layer — past agent conversations and sessions. "
            "Use this when you specifically need to find something discussed in a previous session.",
            {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query for session messages"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default: 10)",
                        "default": 10
                    }
                },
                "required": ["query"]
            }
        ),
        _tool(
            "hqe_search_codex",
            "Search only the Codex layer — indexed knowledge base files. "
            "Use this when you need information from stored documents, guides, and references.",
            {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query for knowledge base"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default: 10)",
                        "default": 10
                    }
                },
                "required": ["query"]
            }
        ),
        _tool(
            "hqe_search_graph",
            "Search only the Graph layer — entity relationships extracted from conversations. "
            "Use this to find connections between projects, tools, people, and concepts.",
            {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query for entity relationships"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default: 10)",
                        "default": 10
                    }
                },
                "required": ["query"]
            }
        ),
        _tool(
            "hqe_status",
            "Show HQE configuration status — which databases are available, their sizes, "
            "and the total number of indexed messages/documents.",
            {
                "type": "object",
                "properties": {}
            }
        ),
    ]


# ─── Tool handlers ──────────────────────────────────────────────────────────

def _text_result(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=text)]


def _format_results_json(results: list[dict], title: str) -> str:
    """Format search results as a structured JSON text block."""
    if not results:
        return f"**{title}**\n\nNo results found.\n"

    lines = [f"**{title}**\n", f"Found {len(results)} result(s):\n"]

    for i, r in enumerate(results, 1):
        layer = r.get("layer", "?").upper()
        score = r.get("score", "?")
        
        if r.get("layer") == "cortex":
            snippet = r.get("snippet", "")
            session = r.get("session_title", "Unknown Session")
            role = r.get("role", "?")
            lines.append(f"  `#{i}` **[Cortex]** [{score}] *{session}* ({role})\n  {snippet}\n")

        elif r.get("layer") == "codex":
            fname = r.get("file_name", "?")
            cat = r.get("category", "?")
            snippet = r.get("snippet", "")
            lines.append(f"  `#{i}` **[Codex]** [{score}] `{fname}` [{cat}]\n  {snippet}\n")

        elif r.get("layer") == "graph":
            entities = r.get("entities", [])
            session = r.get("session_title", "Unknown Session")
            entity_str = "; ".join(f"{e['type']}: {e['value']}" for e in entities[:3])
            preview = r.get("content_preview", "")[:120]
            lines.append(f"  `#{i}` **[Graph]** [{score}] *{session}*\n  Entities: {entity_str}\n  ...{preview}...\n")

    return "\n".join(lines)


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        # ── hqe_query ──────────────────────────────────────────────────────
        if name == "hqe_query":
            query = arguments.get("query", "").strip()
            layers = arguments.get("layers", "all")
            max_results = arguments.get("max_results", 20)

            if not query:
                return _text_result("Please provide a query.")

            all_results = []

            if layers in ("all", "cortex"):
                cortex_results = _search_cortex(query)
                all_results.extend(cortex_results)
                logger.info(f"Cortex: {len(cortex_results)} results")

            if layers in ("all", "codex"):
                codex_results = _search_codex(query)
                all_results.extend(codex_results)
                logger.info(f"Codex: {len(codex_results)} results")

            if layers in ("all", "graph"):
                graph_results = _search_graph(query)
                all_results.extend(graph_results)
                logger.info(f"Graph: {len(graph_results)} results")

            ranked = _rank_and_merge(all_results, query)

            if not ranked:
                return _text_result(f"**🔍 HQE Query**: `{query}` (layer: {layers})\n\nNo results found across any layer.")

            # Build summary
            cortex_count = sum(1 for r in ranked if r["layer"] == "cortex")
            codex_count = sum(1 for r in ranked if r["layer"] == "codex")
            graph_count = sum(1 for r in ranked if r["layer"] == "graph")

            summary = (
                f"**🔍 HQE Query**: `{query}`\n"
                f"*Layers searched: {layers}*  "
                f"| 🧠 Cortex: {cortex_count}  "
                f"| 📚 Codex: {codex_count}  "
                f"| 🔗 Graph: {graph_count}\n\n"
            )

            body = _format_results_json(ranked[:max_results], "Results")
            return _text_result(summary + body)

        # ── hqe_search_cortex ─────────────────────────────────────────────
        elif name == "hqe_search_cortex":
            query = arguments.get("query", "").strip()
            limit = arguments.get("limit", 10)
            if not query:
                return _text_result("Please provide a query.")
            results = _search_cortex(query, limit)
            body = _format_results_json(results, f"**🧠 Cortex Search**: `{query}`")
            return _text_result(body)

        # ── hqe_search_codex ──────────────────────────────────────────────
        elif name == "hqe_search_codex":
            query = arguments.get("query", "").strip()
            limit = arguments.get("limit", 10)
            if not query:
                return _text_result("Please provide a query.")
            results = _search_codex(query, limit)
            body = _format_results_json(results, f"**📚 Codex Search**: `{query}`")
            return _text_result(body)

        # ── hqe_search_graph ──────────────────────────────────────────────
        elif name == "hqe_search_graph":
            query = arguments.get("query", "").strip()
            limit = arguments.get("limit", 10)
            if not query:
                return _text_result("Please provide a query.")
            results = _search_graph(query, limit)
            body = _format_results_json(results, f"**🔗 Graph Search**: `{query}`")
            return _text_result(body)

        # ── hqe_status ────────────────────────────────────────────────────
        elif name == "hqe_status":
            status_lines = ["**📊 HQE Status**\n"]

            # Cortex status
            state_dbs = _find_state_dbs()
            status_lines.append(f"**🧠 Cortex (Session DBs)**:")
            if state_dbs:
                for db_path in state_dbs:
                    try:
                        conn = sqlite3.connect(db_path)
                        msg_count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
                        ses_count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
                        conn.close()
                        status_lines.append(f"  • `{db_path}` — {msg_count} messages, {ses_count} sessions")
                    except Exception as e:
                        status_lines.append(f"  • `{db_path}` — Error: {e}")
            else:
                status_lines.append("  ❌ No state databases found")

            # Codex status
            status_lines.append(f"\n**📚 Codex (Knowledge Base)**")
            if os.path.exists(CODEX_DB):
                try:
                    conn = sqlite3.connect(CODEX_DB)
                    doc_count = conn.execute("SELECT COUNT(*) FROM codex_fts").fetchone()[0]
                    cats = conn.execute("SELECT DISTINCT category FROM codex_fts").fetchall()
                    category_list = [c[0] for c in cats if c[0]]
                    conn.close()
                    status_lines.append(f"  • `{CODEX_DB}` — {doc_count} documents, categories: {category_list}")
                except Exception as e:
                    status_lines.append(f"  • Error: {e}")
            else:
                status_lines.append("  ❌ Codex DB not found")

            # HQE version
            status_lines.append(f"\n**⚙️ Config**")
            status_lines.append(f"  • HERMES_HOME: {HERMES_HOME}")
            status_lines.append(f"  • Profiles dir: {PROFILES_DIR}")
            status_lines.append(f"  • Max results/layer: {MAX_RESULTS_PER_LAYER}")

            return _text_result("\n".join(status_lines))

        else:
            return _text_result(f"Unknown tool: {name}")

    except Exception as e:
        logger.exception(f"Error in {name}")
        return _text_result(f"Error: {str(e)}")


# ─── Main ───────────────────────────────────────────────────────────────────

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="hqe",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

if __name__ == "__main__":
    asyncio.run(main())
