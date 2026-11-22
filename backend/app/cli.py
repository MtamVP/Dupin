"""Dupin Command-Line Interface — Terminal & Headless OSINT Execution.

Usage:
    python -m app.cli serve [--host 127.0.0.1] [--port 8000]
    python -m app.cli investigate "Full Name, Organization, Year" [--no-live] [--json]
    python -m app.cli scan-username <handle> [--depth 1] [--json]
    python -m app.cli dorks "Full Name" [--org ORG] [--exclude TERM]
    python -m app.cli mcp
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from app.config import settings
from app.connectors.username_recon import scan_username_profiles
from app.connectors.web_search import DorkRequest, generate_smart_dorks
from app.core.graph_store import GraphStore
from app.core.schemas import WorkspaceCreate
from app.agents.chat_orchestrator import handle_chat_turn


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def _cmd_investigate(args: argparse.Namespace) -> int:
    store = GraphStore(settings.db_path)
    ws = store.create_workspace(WorkspaceCreate(name=args.workspace or "CLI Investigation"))

    async def _run() -> dict[str, Any]:
        return await handle_chat_turn(
            store=store,
            workspace_id=ws.id,
            prompt=args.prompt,
            live_search=not args.no_live,
            deep_mode=not args.fast,
        )

    result = asyncio.run(_run())
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0

    print("=== DUPIN 5-LAYER INVESTIGATION SUMMARY ===")
    print(result.get("assistant_reply", ""))
    sources = result.get("discovered_sources", [])
    if sources:
        print(f"\n--- Public Sources ({len(sources)}) ---")
        for idx, s in enumerate(sources, 1):
            print(f"{idx}. {s.get('title', '')} | {s.get('url', '')} (score={s.get('match_score', 0)})")
    dorks = result.get("suggested_dorks", [])
    if dorks:
        print(f"\n--- Suggested Boolean Queries ({len(dorks)}) ---")
        for d in dorks[:8]:
            print(f"  {d.get('query', '')}")
    return 0


def _cmd_scan_username(args: argparse.Namespace) -> int:
    async def _run() -> dict[str, Any]:
        return await scan_username_profiles(
            args.username,
            target_hints=args.hint or [],
            recursive_depth=args.depth,
        )

    res = asyncio.run(_run())
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
        return 0

    hits = res.get("hits", [])
    print(f"Username: {args.username} | Checked: {res.get('checked_sites', 0)} | Hits: {len(hits)}")
    for h in hits:
        print(f"  [{h.get('confidence_score', 0):>3}] {h.get('site', '')}: {h.get('url', '')}")
    return 0


def _cmd_dorks(args: argparse.Namespace) -> int:
    req = DorkRequest(
        full_name=args.name,
        organizations=args.org or [],
        locations=args.location or [],
        negative_keywords=args.exclude or [],
    )
    dorks = generate_smart_dorks(req)
    for d in dorks:
        tag = d.get("strategy") or d.get("category") or "dork"
        print(f"[{tag}] {d.get('query', '')}")
    return 0


def _cmd_mcp(_args: argparse.Namespace) -> int:
    from app.mcp_server import run_stdio_server

    asyncio.run(run_stdio_server())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dupin",
        description="Dupin — Local-First 5-Layer Multi-Agent OSINT & 8D Entity Resolution CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="Start the local Dupin web/API server")
    p_serve.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p_serve.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    p_serve.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    p_serve.set_defaults(func=_cmd_serve)

    p_inv = sub.add_parser("investigate", help="Run a 5-layer OSINT investigation from the terminal")
    p_inv.add_argument("prompt", help='Seed clues, e.g. "Full Name, Organization, 2002"')
    p_inv.add_argument("--workspace", default="", help="Optional workspace title")
    p_inv.add_argument("--no-live", action="store_true", help="Disable live web search (local graph only)")
    p_inv.add_argument("--fast", action="store_true", help="Skip deep ReAct round 2")
    p_inv.add_argument("--json", action="store_true", help="Output raw JSON payload")
    p_inv.set_defaults(func=_cmd_investigate)

    p_scan = sub.add_parser("scan-username", help="Scan a username across 55+ public platforms")
    p_scan.add_argument("username", help="Target handle or username")
    p_scan.add_argument("--hint", action="append", help="Optional context hint (org/city) for scoring")
    p_scan.add_argument("--depth", type=int, default=1, choices=[1, 2], help="Recursive bio pivot depth (1 or 2)")
    p_scan.add_argument("--json", action="store_true", help="Output raw JSON payload")
    p_scan.set_defaults(func=_cmd_scan_username)

    p_dorks = sub.add_parser("dorks", help="Generate multi-variant Boolean search dorks")
    p_dorks.add_argument("name", help="Target full name")
    p_dorks.add_argument("--org", action="append", help="Organization or school filter")
    p_dorks.add_argument("--location", action="append", help="Location filter")
    p_dorks.add_argument("--exclude", action="append", help="Negative exclusion keyword")
    p_dorks.set_defaults(func=_cmd_dorks)

    p_mcp = sub.add_parser("mcp", help="Run the MCP JSON-RPC 2.0 Stdio server for AI agents")
    p_mcp.set_defaults(func=_cmd_mcp)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
