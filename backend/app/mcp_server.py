"""Model Context Protocol (MCP) JSON-RPC 2.0 Server for external AI Agents (Antigravity, Claude Code, Codex)."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from app.agents.critic import CriticVerifierAgent
from app.agents.reader import ReaderAgent
from app.agents.resolver import EntityResolutionAgent
from app.connectors.web_fetcher import ingest_manual_snippet
from app.connectors.web_search import DorkRequest, generate_smart_dorks
from app.core.graph_store import GraphStore
from app.core.schemas import EdgeCreate, NodeCreate

MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "stalker_generate_dorks",
        "description": "Generate targeted Boolean OSINT search dorks with Vietnamese variants and negative filters.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "full_name": {"type": "string"},
                "aliases": {"type": "array", "items": {"type": "string"}},
                "organizations": {"type": "array", "items": {"type": "string"}},
                "locations": {"type": "array", "items": {"type": "string"}},
                "keywords": {"type": "array", "items": {"type": "string"}},
                "negative_keywords": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["full_name"],
        },
    },
    {
        "name": "stalker_ingest_snippet",
        "description": "Ingest a public text snippet into a workspace, auto-extracting claims onto a target node.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string"},
                "target_label": {"type": "string"},
                "text": {"type": "string"},
                "source_url": {"type": "string"},
            },
            "required": ["workspace_id", "target_label", "text"],
        },
    },
    {
        "name": "stalker_analyze_and_verify",
        "description": "Run ReaderAgent + CriticVerifierAgent on unstructured text to extract and commit verified nodes & edges.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string"},
                "subject_label": {"type": "string"},
                "text": {"type": "string"},
                "source_url": {"type": "string"},
            },
            "required": ["workspace_id", "subject_label", "text"],
        },
    },
    {
        "name": "stalker_resolve_entities",
        "description": "Compare two nodes in the Knowledge Graph across all 8 dimensions using EntityResolutionAgent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_a_id": {"type": "string"},
                "node_b_id": {"type": "string"},
            },
            "required": ["node_a_id", "node_b_id"],
        },
    },
    {
        "name": "stalker_search_graph",
        "description": "Search workspace nodes across 8D claims using hybrid SQLite FTS5 BM25 + Jaro-Winkler.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string"},
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["workspace_id", "query"],
        },
    },
    {
        "name": "stalker_suggest_pivots",
        "description": "Rank nodes in a workspace by Information Gain potential to decide the next OSINT pivot.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string"},
                "top_k": {"type": "integer", "default": 5},
            },
            "required": ["workspace_id"],
        },
    },
    {
        "name": "stalker_deep_investigate",
        "description": "Run the full Deep ReAct OSINT pipeline (Anchor Decoding + Intersection Search + Studocu/Scribd Mirror Pivoting + 8D Graph).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string"},
                "prompt": {"type": "string"},
                "live_search": {"type": "boolean", "default": True},
                "deep_mode": {"type": "boolean", "default": True},
            },
            "required": ["workspace_id", "prompt"],
        },
    },
    {
        "name": "stalker_decode_anchors",
        "description": "Decode high-entropy OSINT anchors (Vietnamese student IDs, academic emails, document numbers, class/LHP codes).",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "stalker_scan_username",
        "description": "Sherlock/Maigret/Social-Analyzer-inspired public username sweep across 14 developer & social platforms with 0-100 confidence scores and recursive bio pivot extraction.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "username": {"type": "string"},
                "target_hints": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["username"],
        },
    },
    {
        "name": "stalker_analyze_phone",
        "description": "PhoneInfoga-inspired E.164 & Vietnamese carrier analyzer generating normalized multi-format public search dorks.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "phone": {"type": "string"},
                "name_hint": {"type": "string"},
            },
            "required": ["phone"],
        },
    },
    {
        "name": "stalker_recon_domain_email",
        "description": "theHarvester/Amass-inspired passive DNS (Cloudflare DoH MX/TXT), RDAP/crt.sh subdomains, plus public Gravatar & OpenPGP email identity lookup.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
                "email": {"type": "string"},
                "full_name": {"type": "string"},
            },
        },
    },
]


async def run_reader_and_critic_pipeline(
    store: GraphStore,
    workspace_id: str,
    subject_label: str,
    text: str,
    source_url: str,
) -> dict[str, Any]:
    """Execute ReaderAgent -> CriticVerifierAgent and commit verified nodes/edges to GraphStore."""
    reader = ReaderAgent()
    critic = CriticVerifierAgent()

    extraction = await reader.extract(text=text, subject_label=subject_label, source_url=source_url)
    verified_claims, audited_triples = critic.audit_extraction(extraction, text)

    subject_node = store.upsert_node(
        workspace_id,
        NodeCreate(type="Person", label=subject_label, claims=verified_claims, confidence=0.65),
    )

    committed_edges = []
    for triple, status in audited_triples:
        obj_node = store.upsert_node(
            workspace_id,
            NodeCreate(type=triple.object_type, label=triple.object_label, confidence=triple.confidence),
        )
        edge = store.add_edge(
            workspace_id,
            EdgeCreate(
                source_id=subject_node.id,
                target_id=obj_node.id,
                relation=triple.relation,
                confidence=triple.confidence,
                status=status,  # type: ignore[arg-type]
                evidence_quote=triple.evidence_quote,
                source_url=triple.source_url,
                time_range=triple.time_range,
            ),
        )
        committed_edges.append(edge.model_dump(mode="json"))

    timeline = critic.reconstruct_and_audit_timeline(subject_node)
    return {
        "subject_node": subject_node.model_dump(mode="json"),
        "committed_edges": committed_edges,
        "timeline_audit": timeline.model_dump(mode="json"),
    }


async def handle_mcp_request(request: dict[str, Any], store: GraphStore) -> dict[str, Any]:
    """Process a JSON-RPC 2.0 MCP request (`initialize`, `tools/list`, `tools/call`)."""
    req_id = request.get("id")
    method = request.get("method", "")
    params = request.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "stalker-pp-mcp", "version": "0.3.0"},
                "capabilities": {"tools": {}},
            },
        }

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": MCP_TOOLS}}

    if method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments") or {}

        if tool_name == "stalker_generate_dorks":
            dorks = generate_smart_dorks(DorkRequest(**args))
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(dorks, ensure_ascii=False)}]},
            }

        if tool_name == "stalker_ingest_snippet":
            doc = ingest_manual_snippet(
                text=args["text"],
                source_url=args.get("source_url", "manual://mcp-agent"),
            )
            node = store.upsert_node(
                args["workspace_id"],
                NodeCreate(type="Person", label=args["target_label"], claims=doc.claims, confidence=0.6),
            )
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(node.model_dump(mode="json"), ensure_ascii=False),
                        }
                    ]
                },
            }

        if tool_name == "stalker_analyze_and_verify":
            res = await run_reader_and_critic_pipeline(
                store=store,
                workspace_id=args["workspace_id"],
                subject_label=args["subject_label"],
                text=args["text"],
                source_url=args.get("source_url", "manual://mcp-agent"),
            )
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}]},
            }

        if tool_name == "stalker_resolve_entities":
            na = store.get_node(args["node_a_id"])
            nb = store.get_node(args["node_b_id"])
            if not na or not nb:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": "One or both nodes not found"},
                }
            report = EntityResolutionAgent().compare_nodes(na, nb)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(report.model_dump(mode="json"), ensure_ascii=False),
                        }
                    ]
                },
            }

        if tool_name == "stalker_search_graph":
            hits = store.search_candidates(
                args["workspace_id"], args["query"], limit=int(args.get("limit", 10))
            )
            serializable = [
                {"node": h["node"].model_dump(mode="json"), "match_score": h["match_score"]}
                for h in hits
            ]
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(serializable, ensure_ascii=False)}]
                },
            }

        if tool_name == "stalker_suggest_pivots":
            pivots = store.suggest_pivots(args["workspace_id"], top_k=int(args.get("top_k", 5)))
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(pivots, ensure_ascii=False)}]},
            }

        if tool_name == "stalker_deep_investigate":
            from app.agents.chat_orchestrator import handle_chat_turn

            res = await handle_chat_turn(
                store=store,
                workspace_id=args["workspace_id"],
                prompt=args["prompt"],
                live_search=bool(args.get("live_search", True)),
                deep_mode=bool(args.get("deep_mode", True)),
            )
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}]},
            }

        if tool_name == "stalker_decode_anchors":
            from app.core.anchor_decoder import decode_high_entropy_anchors

            decoded = decode_high_entropy_anchors(args["text"])
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(decoded, ensure_ascii=False)}]},
            }

        if tool_name == "stalker_scan_username":
            from app.connectors.username_recon import scan_username_profiles

            res = await scan_username_profiles(
                args["username"], target_hints=args.get("target_hints") or []
            )
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}]},
            }

        if tool_name == "stalker_analyze_phone":
            from app.connectors.phone_recon import analyze_phone_number

            res = analyze_phone_number(args["phone"], name_hint=args.get("name_hint", ""))
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}]},
            }

        if tool_name == "stalker_recon_domain_email":
            from app.connectors.domain_email_recon import (
                infer_corporate_email_patterns,
                inspect_public_email_crypto_identity,
                run_full_passive_domain_recon,
            )

            out: dict[str, Any] = {}
            dom = str(args.get("domain") or "").strip()
            em = str(args.get("email") or "").strip()
            fname = str(args.get("full_name") or "").strip()
            if em:
                out["email_identity"] = await inspect_public_email_crypto_identity(em)
                if not dom and "@" in em:
                    dom = em.split("@")[-1]
            if dom:
                out["domain_recon"] = await run_full_passive_domain_recon(dom)
                if fname:
                    out["inferred_email_patterns"] = infer_corporate_email_patterns(fname, dom)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]},
            }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
        }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


async def _stdio_loop() -> None:
    """Run MCP server over stdin/stdout for local CLI coding agents."""
    from app.config import settings

    local_store = GraphStore(settings.db_path)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = json.loads(line)
        resp = await handle_mcp_request(req, local_store)
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    asyncio.run(_stdio_loop())
