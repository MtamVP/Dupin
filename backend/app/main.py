"""FastAPI entry point for Stalker++ local OSINT workbench (Phases 1, 2, 3 & 4)."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any, Optional

import networkx as nx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.agents.blackboard import InvestigationBlackboard
from app.agents.chat_orchestrator import handle_chat_turn
from app.agents.critic import CriticVerifierAgent, TimelineAuditReport
from app.agents.planner import PlannerAgent
from app.agents.playbooks import InvestigationPlaybook, PlaybookRegistry
from app.agents.resolver import EntityResolutionAgent, ResolutionReport
from app.config import settings
from app.connectors.base import CollectedDocument
from app.connectors.document_reader import fetch_and_inspect_document
from app.connectors.github_api import GitHubPublicConnector
from app.connectors.web_fetcher import PublicWebFetcher, ingest_manual_snippet
from app.connectors.web_search import DorkRequest, generate_smart_dorks, test_searxng_connection
from app.core.exporters import export_obsidian_markdown, export_stix_bundle
from app.core.fingerprints import (
    extract_handle_fingerprint,
    handle_pattern_similarity,
    stylometry_similarity,
)
from app.core.graph_analytics import analyze_communities_and_bridges, predict_hidden_links
from app.core.graph_store import GraphStore
from app.core.key_pool import APIKeyCreate, IntegrationStore, LocalHostConfig
from app.core.normalizer import (
    generate_name_variants,
    normalize_org_or_location,
    normalize_text,
    phonetic_vietnamese_key,
)
from app.core.schemas import (
    Edge,
    EdgeCreate,
    EdgeStatusUpdate,
    GraphSnapshot,
    Node,
    NodeCreate,
    Workspace,
    WorkspaceCreate,
)
from app.evaluation.benchmark_thesis import run_thesis_benchmark
from app.mcp_server import handle_mcp_request, run_reader_and_critic_pipeline
from app.plugins.registry import PluginRegistry
from app.ui_workbench import WORKBENCH_HTML

app = FastAPI(title=settings.app_name, version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    ],
    allow_origin_regex=r"^(chrome-extension|moz-extension|edge-extension)://.*$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST_DIR = REPO_ROOT / "frontend" / "dist"
store = GraphStore(settings.db_path)
playbook_registry = PlaybookRegistry()
plugin_registry = PluginRegistry(extra_plugin_dir=REPO_ROOT / "plugins")


class DocumentInspectRequest(BaseModel):
    url: str = Field(..., min_length=8)
    target_terms: list[str] = Field(default_factory=list)


class UsernameScanRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=60)
    target_hints: list[str] = Field(default_factory=list)
    sites: Optional[list[str]] = None
    tags: Optional[list[str]] = None
    recursive_depth: int = Field(default=1, ge=1, le=2)


class PhoneAnalyzeRequest(BaseModel):
    phone: str = Field(..., min_length=8, max_length=30)
    name_hint: str = ""


class DomainEmailReconRequest(BaseModel):
    domain: str = ""
    email: str = ""
    full_name: str = ""


class EventBusRunRequest(BaseModel):
    events: list[dict[str, Any]]
    target_name: str = ""
    target_hints: list[str] = Field(default_factory=list)
    max_hops: int = Field(default=2, ge=1, le=3)


class BrowserClipRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=240)
    url: str = Field(..., min_length=5)
    selected_text: str = Field(..., min_length=1)
    field_key: str = "Browser Clip"
    pin_to_dossier: bool = True
    analyze_with_agent: bool = False


class NormalizeRequest(BaseModel):
    text: str
    is_person_name: bool = True


class GitHubCollectRequest(BaseModel):
    username: str = Field(..., min_length=1)
    attach_to_person_label: str = ""


class WebPageCollectRequest(BaseModel):
    url: str = Field(..., min_length=5)
    attach_to_person_label: str = ""


class SnippetCollectRequest(BaseModel):
    target_label: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)
    source_url: str = "manual://human-analyst"
    title: str = "Human-Assisted Snippet"


class AgentAnalyzeRequest(BaseModel):
    subject_label: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)
    source_url: str = "manual://analyst-pipeline"


class EntityResolveRequest(BaseModel):
    node_a_id: str
    node_b_id: str


class StylometryCompareRequest(BaseModel):
    text_a: str = ""
    text_b: str = ""
    handle_a: str = ""
    handle_b: str = ""


class StartInvestigationRequest(BaseModel):
    target_name: str = Field(..., min_length=1)
    playbook_id: str = "vietnam_student_alumni"
    aliases: list[str] = Field(default_factory=list)
    organizations: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    negative_keywords: list[str] = Field(default_factory=list)


class MCTSStepRequest(BaseModel):
    hypothesis_id: Optional[str] = None
    collected_texts: list[dict[str, str]] = Field(default_factory=list)
    auto_fetch_live: bool = True
    use_llm: bool = False
    max_depth: int = Field(3, ge=1, le=6)


class ChatInvestigateRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    live_search: bool = True
    deep_mode: bool = True
    use_llm: bool = False
    model_override: Optional[str] = None
    image_b64: Optional[str] = None
    image_mime: str = "image/png"
    geo_point: Optional[dict[str, Any]] = None
    attached_file_text: Optional[str] = None


class DossierItemCreate(BaseModel):
    category: str = "general"
    field_key: str = Field(..., min_length=1, max_length=120)
    field_value: str = Field(..., min_length=1)
    source_url: str = ""
    note: str = ""


class DossierItemUpdate(BaseModel):
    category: Optional[str] = None
    field_key: Optional[str] = None
    field_value: Optional[str] = None
    source_url: Optional[str] = None
    note: Optional[str] = None


class WorkspaceRenameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class LLMSettingsUpdate(BaseModel):
    llm_provider: str = Field(..., pattern="^(ollama|gemini|openai|none)$")
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    ollama_model: Optional[str] = None


class KeyToggleRequest(BaseModel):
    enabled: bool


def _integration_store() -> IntegrationStore:
    return IntegrationStore(store.db_path)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name, "llm_provider": settings.llm_provider}


@app.get("/api/integrations/local", response_model=LocalHostConfig)
def get_local_host_config() -> LocalHostConfig:
    return _integration_store().get_local_config()


@app.post("/api/integrations/local", response_model=LocalHostConfig)
def save_local_host_config(payload: LocalHostConfig) -> LocalHostConfig:
    saved = _integration_store().save_local_config(payload)
    settings.ollama_base_url = saved.ollama_base_url
    settings.ollama_model = saved.ollama_model
    return saved


@app.get("/api/integrations/ollama/models")
async def list_local_ollama_models(base_url: Optional[str] = None) -> dict[str, Any]:
    import httpx

    target_url = (base_url or _integration_store().get_local_config().ollama_base_url).rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(f"{target_url}/api/tags")
            resp.raise_for_status()
            models = [m.get("name", "") for m in resp.json().get("models", []) if m.get("name")]
            return {"reachable": True, "base_url": target_url, "models": models}
    except Exception as exc:
        return {"reachable": False, "base_url": target_url, "models": [], "error": str(exc)}


@app.get("/api/integrations/searxng/test")
async def test_local_searxng(base_url: Optional[str] = None) -> dict[str, Any]:
    """Probe local/self-hosted SearXNG JSON API readiness (used in parallel with ddgs)."""
    cfg = _integration_store().get_local_config()
    target_url = (base_url if base_url is not None else cfg.searxng_url).strip() or "http://localhost:8888"
    return await test_searxng_connection(target_url)


@app.get("/api/integrations/keys")
def list_api_keys(provider: Optional[str] = None) -> dict[str, Any]:
    return {"keys": _integration_store().list_keys(provider=provider)}


@app.post("/api/integrations/keys", status_code=201)
def add_api_key(payload: APIKeyCreate) -> dict[str, Any]:
    return _integration_store().add_key(payload)


@app.patch("/api/integrations/keys/{key_id}")
def toggle_api_key(key_id: str, payload: KeyToggleRequest) -> dict[str, Any]:
    updated = _integration_store().toggle_key(key_id, payload.enabled)
    if not updated:
        raise HTTPException(status_code=404, detail="API key not found")
    return updated


@app.delete("/api/integrations/keys/{key_id}")
def delete_api_key(key_id: str) -> dict[str, Any]:
    if not _integration_store().delete_key(key_id):
        raise HTTPException(status_code=404, detail="API key not found")
    return {"deleted": True, "id": key_id}


@app.get("/api/integrations/mcp-config")
def get_mcp_agent_configs() -> dict[str, Any]:
    """Generate ready-to-copy MCP configuration snippets for Antigravity, Claude Code, and Codex/Cursor."""
    backend_dir = str((REPO_ROOT / "backend").resolve())
    python_exe = str((REPO_ROOT / "backend" / ".venv" / "Scripts" / "python.exe").resolve())
    http_url = "http://127.0.0.1:8000/api/mcp"

    antigravity_json = {
        "mcpServers": {
            "stalker-pp": {
                "command": python_exe,
                "args": ["-m", "app.mcp_server"],
                "cwd": backend_dir,
            }
        }
    }
    claude_code_cmd = (
        f'claude mcp add stalker-pp -- "{python_exe}" -m app.mcp_server'
    )
    codex_cursor_json = {
        "mcpServers": {
            "stalker-pp-http": {
                "url": http_url,
                "transport": "http",
            }
        }
    }
    return {
        "http_endpoint": http_url,
        "stdio_command": f'"{python_exe}" -m app.mcp_server',
        "cwd": backend_dir,
        "antigravity_config": json.dumps(antigravity_json, indent=2),
        "claude_code_cli": claude_code_cmd,
        "codex_cursor_config": json.dumps(codex_cursor_json, indent=2),
    }


@app.get("/api/settings/llm")
def get_llm_settings() -> dict[str, Any]:
    return {
        "llm_provider": settings.llm_provider,
        "gemini_model": settings.gemini_model,
        "has_gemini_key": bool(settings.gemini_api_key),
        "ollama_model": settings.ollama_model,
    }


@app.post("/api/settings/llm")
def update_llm_settings(payload: LLMSettingsUpdate) -> dict[str, Any]:
    settings.llm_provider = payload.llm_provider  # type: ignore[assignment]
    if payload.gemini_api_key is not None and payload.gemini_api_key.strip():
        settings.gemini_api_key = payload.gemini_api_key.strip()
    if payload.gemini_model and payload.gemini_model.strip():
        settings.gemini_model = payload.gemini_model.strip()
    if payload.ollama_model and payload.ollama_model.strip():
        settings.ollama_model = payload.ollama_model.strip()
    return get_llm_settings()


@app.post("/api/workspaces", response_model=Workspace, status_code=201)
def create_workspace(payload: WorkspaceCreate) -> Workspace:
    return store.create_workspace(payload)


@app.get("/api/workspaces", response_model=list[Workspace])
def list_workspaces() -> list[Workspace]:
    return store.list_workspaces()


@app.patch("/api/workspaces/{workspace_id}", response_model=Workspace)
def rename_workspace(workspace_id: str, payload: WorkspaceRenameRequest) -> Workspace:
    updated = store.rename_workspace(workspace_id, payload.name)
    if not updated:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return updated


@app.delete("/api/workspaces/{workspace_id}")
def delete_workspace(workspace_id: str) -> dict[str, Any]:
    deleted = store.delete_workspace(workspace_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"deleted": True, "id": workspace_id}


@app.post("/api/workspaces/{workspace_id}/nodes", response_model=Node, status_code=201)
def upsert_node(workspace_id: str, payload: NodeCreate) -> Node:
    if not store.get_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return store.upsert_node(workspace_id, payload)


@app.post("/api/workspaces/{workspace_id}/edges", response_model=Edge, status_code=201)
def create_edge(workspace_id: str, payload: EdgeCreate) -> Edge:
    if not store.get_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    if not store.get_node(payload.source_id) or not store.get_node(payload.target_id):
        raise HTTPException(status_code=404, detail="Source or target node not found")
    return store.add_edge(workspace_id, payload)


@app.patch("/api/edges/{edge_id}/status", response_model=Edge)
def update_edge_status(edge_id: str, payload: EdgeStatusUpdate) -> Edge:
    edge = store.update_edge_status(edge_id, payload)
    if not edge:
        raise HTTPException(status_code=404, detail="Edge not found")
    return edge


@app.get("/api/workspaces/{workspace_id}/graph", response_model=GraphSnapshot)
def get_graph(workspace_id: str) -> GraphSnapshot:
    snapshot = store.get_graph(workspace_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return snapshot


@app.get("/api/workspaces/{workspace_id}/paths")
def find_paths(
    workspace_id: str,
    source_id: str = Query(...),
    target_id: str = Query(...),
    max_hops: int = Query(5, ge=1, le=8),
) -> dict[str, list[list[str]]]:
    if not store.get_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"paths": store.find_paths(workspace_id, source_id, target_id, max_hops=max_hops)}


@app.get("/api/workspaces/{workspace_id}/search")
def search_candidates(
    workspace_id: str,
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
) -> dict[str, list[dict[str, Any]]]:
    if not store.get_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"results": store.search_candidates(workspace_id, q, limit=limit)}


@app.get("/api/workspaces/{workspace_id}/pivots")
def suggest_pivots(
    workspace_id: str,
    top_k: int = Query(5, ge=1, le=20),
) -> dict[str, list[dict[str, Any]]]:
    if not store.get_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"pivots": store.suggest_pivots(workspace_id, top_k=top_k)}


@app.post("/api/tools/normalize")
def normalize_tool(payload: NormalizeRequest) -> dict[str, object]:
    return {
        "normalized": normalize_text(payload.text),
        "phonetic_key": phonetic_vietnamese_key(payload.text),
        "org_location_expanded": normalize_org_or_location(payload.text),
        "name_variants": generate_name_variants(payload.text) if payload.is_person_name else [],
    }


@app.post("/api/tools/stylometry")
def stylometry_tool(payload: StylometryCompareRequest) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if payload.text_a and payload.text_b:
        result["stylometry"] = stylometry_similarity(payload.text_a, payload.text_b)
    if payload.handle_a and payload.handle_b:
        result["handle_similarity"] = handle_pattern_similarity(payload.handle_a, payload.handle_b)
        result["handle_a_fp"] = extract_handle_fingerprint(payload.handle_a)
        result["handle_b_fp"] = extract_handle_fingerprint(payload.handle_b)
    return result


# --- Phase 2: Public Connectors ---


@app.post("/api/dorks/generate")
def generate_dorks_endpoint(payload: DorkRequest) -> dict[str, list[dict[str, str]]]:
    return {"dorks": generate_smart_dorks(payload)}


@app.post("/api/workspaces/{workspace_id}/collect/github", response_model=CollectedDocument)
async def collect_github(workspace_id: str, payload: GitHubCollectRequest) -> CollectedDocument:
    if not store.get_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    connector = GitHubPublicConnector(store.db_path, timeout=settings.http_timeout_seconds)
    doc = await connector.collect(payload.username)
    if not doc.is_soft_404:
        alias_node = store.upsert_node(
            workspace_id,
            NodeCreate(type="Alias", label=payload.username, claims=doc.claims, confidence=0.8),
        )
        if payload.attach_to_person_label:
            person = store.upsert_node(
                workspace_id,
                NodeCreate(type="Person", label=payload.attach_to_person_label, confidence=0.7),
            )
            store.add_edge(
                workspace_id,
                EdgeCreate(
                    source_id=person.id,
                    target_id=alias_node.id,
                    relation="OWNS_ACCOUNT",
                    confidence=0.85,
                    status="HYPOTHESIS",
                    evidence_quote=doc.title,
                    source_url=doc.url,
                ),
            )
    return doc


@app.post("/api/workspaces/{workspace_id}/collect/webpage", response_model=CollectedDocument)
async def collect_webpage(workspace_id: str, payload: WebPageCollectRequest) -> CollectedDocument:
    if not store.get_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    fetcher = PublicWebFetcher(store.db_path, timeout=settings.http_timeout_seconds)
    doc = await fetcher.collect(payload.url)
    if not doc.is_soft_404 and payload.attach_to_person_label:
        store.upsert_node(
            workspace_id,
            NodeCreate(
                type="Person",
                label=payload.attach_to_person_label,
                claims=doc.claims,
                confidence=0.65,
            ),
        )
    return doc


@app.post("/api/workspaces/{workspace_id}/collect/snippet")
def collect_manual_snippet(workspace_id: str, payload: SnippetCollectRequest) -> dict[str, Any]:
    if not store.get_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    doc = ingest_manual_snippet(payload.text, payload.source_url, payload.title)
    node = store.upsert_node(
        workspace_id,
        NodeCreate(type="Person", label=payload.target_label, claims=doc.claims, confidence=0.65),
    )
    return {"document": doc, "updated_node": node}


# --- Phase 3: Multi-Agent Reader, Entity Resolver & Critic/Timeline Verifier ---


@app.post("/api/workspaces/{workspace_id}/agents/analyze-text")
async def analyze_text_pipeline(workspace_id: str, payload: AgentAnalyzeRequest) -> dict[str, Any]:
    if not store.get_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return await run_reader_and_critic_pipeline(
        store=store,
        workspace_id=workspace_id,
        subject_label=payload.subject_label,
        text=payload.text,
        source_url=payload.source_url,
    )


@app.post("/api/workspaces/{workspace_id}/agents/resolve", response_model=ResolutionReport)
def resolve_entities_endpoint(workspace_id: str, payload: EntityResolveRequest) -> ResolutionReport:
    if not store.get_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    na = store.get_node(payload.node_a_id)
    nb = store.get_node(payload.node_b_id)
    if not na or not nb:
        raise HTTPException(status_code=404, detail="One or both nodes not found")
    return EntityResolutionAgent().compare_nodes(na, nb)


@app.get("/api/workspaces/{workspace_id}/nodes/{node_id}/timeline", response_model=TimelineAuditReport)
def get_node_timeline(workspace_id: str, node_id: str) -> TimelineAuditReport:
    if not store.get_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    node = store.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return CriticVerifierAgent().reconstruct_and_audit_timeline(node)


# --- Phase 4: MCTS Planner, Playbooks, Blackboard, Link Prediction & GEXF Export ---


@app.get("/api/playbooks", response_model=list[InvestigationPlaybook])
def list_playbooks() -> list[InvestigationPlaybook]:
    return playbook_registry.list_playbooks()


@app.post("/api/playbooks", response_model=InvestigationPlaybook, status_code=201)
def register_custom_playbook(payload: InvestigationPlaybook) -> InvestigationPlaybook:
    return playbook_registry.register_playbook(payload)


@app.get("/api/workspaces/{workspace_id}/messages")
def get_workspace_messages(workspace_id: str) -> dict[str, Any]:
    if not store.get_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"messages": store.list_chat_messages(workspace_id)}


@app.get("/api/workspaces/{workspace_id}/dossier")
def list_dossier(workspace_id: str) -> dict[str, Any]:
    if not store.get_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"items": store.list_dossier_items(workspace_id)}


@app.post("/api/workspaces/{workspace_id}/dossier", status_code=201)
def add_dossier(workspace_id: str, payload: DossierItemCreate) -> dict[str, Any]:
    if not store.get_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return store.add_dossier_item(
        workspace_id=workspace_id,
        field_key=payload.field_key,
        field_value=payload.field_value,
        category=payload.category,
        source_url=payload.source_url,
        note=payload.note,
    )


@app.patch("/api/dossier/{item_id}")
def update_dossier(item_id: str, payload: DossierItemUpdate) -> dict[str, Any]:
    updated = store.update_dossier_item(
        item_id=item_id,
        field_key=payload.field_key,
        field_value=payload.field_value,
        category=payload.category,
        source_url=payload.source_url,
        note=payload.note,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Dossier item not found")
    return updated


@app.delete("/api/dossier/{item_id}")
def delete_dossier(item_id: str) -> dict[str, Any]:
    if not store.delete_dossier_item(item_id):
        raise HTTPException(status_code=404, detail="Dossier item not found")
    return {"deleted": True, "id": item_id}


@app.post("/api/workspaces/{workspace_id}/chat")
async def chat_investigate(workspace_id: str, payload: ChatInvestigateRequest) -> dict[str, Any]:
    if not store.get_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    if not payload.prompt.strip():
        raise HTTPException(status_code=422, detail="Prompt must not be blank")
    return await handle_chat_turn(
        store=store,
        workspace_id=workspace_id,
        prompt=payload.prompt,
        live_search=payload.live_search,
        deep_mode=payload.deep_mode,
        use_llm=payload.use_llm,
        model_override=payload.model_override,
        image_b64=payload.image_b64,
        image_mime=payload.image_mime,
        geo_point=payload.geo_point,
        attached_file_text=payload.attached_file_text,
        playbook_registry=playbook_registry,
    )


@app.post("/api/workspaces/{workspace_id}/chat/stream")
async def chat_investigate_stream(workspace_id: str, payload: ChatInvestigateRequest) -> StreamingResponse:
    """Server-Sent Events (SSE) streaming endpoint for real-time AI Agent progress & output."""
    if not store.get_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    if not payload.prompt.strip():
        raise HTTPException(status_code=422, detail="Prompt must not be blank")

    async def event_gen():
        def _sse(event_type: str, data: dict[str, Any]) -> str:
            return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        yield _sse("status", {"step": "Đang nạp Hồ sơ đã xác nhận & giải mã Khóa chính (MSSV/Email/Tọa độ)..."})
        yield _sse("status", {"step": f"Đang kích hoạt 5-Layer Concentric Pipeline ({payload.model_override or settings.gemini_model})..."})

        try:
            result = await handle_chat_turn(
                store=store,
                workspace_id=workspace_id,
                prompt=payload.prompt,
                live_search=payload.live_search,
                deep_mode=payload.deep_mode,
                use_llm=payload.use_llm,
                model_override=payload.model_override,
                image_b64=payload.image_b64,
                image_mime=payload.image_mime,
                geo_point=payload.geo_point,
                attached_file_text=payload.attached_file_text,
                playbook_registry=playbook_registry,
            )
            for st in result.get("reasoning_steps", [])[-4:]:
                yield _sse("step", {"agent": st.get("agent"), "action": st.get("action"), "detail": st.get("detail")})
            yield _sse("done", result)
        except Exception as exc:
            yield _sse("error", {"error": f"{type(exc).__name__}: {str(exc)[:240]}"})

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@app.post("/api/workspaces/{workspace_id}/investigations", status_code=201)
def start_investigation(
    workspace_id: str, payload: StartInvestigationRequest
) -> dict[str, Any]:
    if not store.get_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    planner = PlannerAgent(store=store, playbook_registry=playbook_registry)
    bb = planner.initialize_blackboard(
        workspace_id=workspace_id,
        target_name=payload.target_name,
        playbook_id=payload.playbook_id,
        aliases=payload.aliases,
        organizations=payload.organizations,
        locations=payload.locations,
        keywords=payload.keywords,
        negative_keywords=payload.negative_keywords,
    )
    store.save_blackboard(bb)
    return bb.model_dump(mode="json")


@app.get("/api/workspaces/{workspace_id}/investigations")
def list_workspace_investigations(workspace_id: str) -> list[dict[str, Any]]:
    if not store.get_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return store.list_blackboards(workspace_id)


@app.get("/api/investigations/{blackboard_id}")
def get_investigation_blackboard(blackboard_id: str) -> dict[str, Any]:
    raw = store.get_blackboard(blackboard_id)
    if not raw:
        raise HTTPException(status_code=404, detail="Investigation Blackboard not found")
    return raw


@app.post("/api/investigations/{blackboard_id}/step")
async def step_mcts_investigation(
    blackboard_id: str, payload: MCTSStepRequest
) -> dict[str, Any]:
    raw = store.get_blackboard(blackboard_id)
    if not raw:
        raise HTTPException(status_code=404, detail="Investigation Blackboard not found")
    bb = InvestigationBlackboard(**raw)
    planner = PlannerAgent(
        store=store, playbook_registry=playbook_registry, use_llm=payload.use_llm
    )

    h_id = payload.hypothesis_id
    if not h_id:
        selected = planner.select_next_hypothesis(bb)
        if not selected:
            store.save_blackboard(bb)
            return {"status": "COMPLETED", "message": "No more OPEN hypotheses in MCTS tree"}
        h_id = selected.id

    texts = payload.collected_texts
    if not texts and payload.auto_fetch_live:
        texts = await planner.collect_live_for_hypothesis(bb, bb.tree[h_id])

    step_result = await planner.evaluate_and_expand(
        bb=bb,
        hypothesis_id=h_id,
        collected_texts=texts,
        max_depth=payload.max_depth,
    )
    store.save_blackboard(bb)
    step_result["blackboard"] = bb.model_dump(mode="json")
    return step_result


@app.get("/api/workspaces/{workspace_id}/analytics")
def graph_network_analytics(
    workspace_id: str, top_k_links: int = Query(10, ge=1, le=50)
) -> dict[str, Any]:
    if not store.get_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    g = store.to_networkx(workspace_id)
    return {
        "predicted_hidden_links": predict_hidden_links(g, top_k=top_k_links),
        "communities_and_bridges": analyze_communities_and_bridges(g),
        "recommended_pivots": store.suggest_pivots(workspace_id, top_k=5),
    }


@app.get("/api/workspaces/{workspace_id}/export/gexf", response_class=PlainTextResponse)
def export_graph_gexf(workspace_id: str) -> str:
    if not store.get_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    g = store.to_networkx(workspace_id)
    xml_lines = "\n".join(nx.generate_gexf(g))
    return xml_lines


@app.get("/api/workspaces/{workspace_id}/export/jsonl", response_class=PlainTextResponse)
def export_graph_jsonl(workspace_id: str) -> str:
    """Export workspace nodes & edges in JSONL format (Hugging Face / LLM dataset ready)."""
    snapshot = store.get_graph(workspace_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Workspace not found")
    lines: list[str] = []
    for n in snapshot.nodes:
        lines.append(json.dumps({"record_type": "node", **n.model_dump(mode="json")}, ensure_ascii=False))
    for e in snapshot.edges:
        lines.append(json.dumps({"record_type": "edge", **e.model_dump(mode="json")}, ensure_ascii=False))
    return "\n".join(lines)


@app.get("/api/workspaces/{workspace_id}/export/csv", response_class=PlainTextResponse)
def export_graph_csv(workspace_id: str) -> str:
    """Export workspace claims & edges as a flat CSV table with provenance for Excel / Pandas."""
    snapshot = store.get_graph(workspace_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Workspace not found")
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["record_type", "entity_or_source", "relation_or_key", "value_or_target", "polarity_or_status", "confidence", "source_url", "evidence_quote"]
    )
    node_labels = {n.id: n.label for n in snapshot.nodes}
    for n in snapshot.nodes:
        for c in n.claims:
            writer.writerow(
                ["claim", n.label, f"{c.category.value}:{c.key}", str(c.value), c.polarity, c.confidence, c.source_url, c.evidence_quote]
            )
    for e in snapshot.edges:
        writer.writerow(
            [
                "edge",
                node_labels.get(e.source_id, e.source_id),
                e.relation,
                node_labels.get(e.target_id, e.target_id),
                e.status,
                e.confidence,
                e.source_url,
                e.evidence_quote,
            ]
        )
    return buf.getvalue()


@app.get("/api/plugins")
async def list_plugins() -> dict[str, Any]:
    """List built-in and community OSINT plugins with live readiness health."""
    items = await plugin_registry.list_with_health({"db_path": store.db_path})
    return {"plugins": items}


@app.get("/api/pipeline/architecture")
def get_pipeline_architecture() -> dict[str, Any]:
    """Inspect the 5-Layer Concentric OSINT Pipeline architecture & Sherlock/Maigret v2 manifest health."""
    from app.connectors.username_recon import SITE_HEALTH, validate_sites_manifest
    from app.pipeline import PIPELINE_ARCHITECTURE_SPEC

    return {
        "architecture": "5-layer-concentric-osint",
        "layers": PIPELINE_ARCHITECTURE_SPEC,
        "username_engine": {
            "manifest": validate_sites_manifest(),
            "circuit_breaker": SITE_HEALTH.status_snapshot(),
        },
    }


@app.post("/api/tools/inspect-document")
async def inspect_public_document(payload: DocumentInspectRequest) -> dict[str, Any]:
    """Download and extract target-matching rows from a public PDF or Excel (XLSX) file."""
    return await fetch_and_inspect_document(payload.url, payload.target_terms)


@app.post("/api/tools/scan-username")
async def scan_username_endpoint(payload: UsernameScanRequest) -> dict[str, Any]:
    """Sherlock/Maigret/Social-Analyzer v2 multi-platform public username scan with recursive depth-2 bio pivots."""
    from app.connectors.username_recon import scan_username_profiles

    return await scan_username_profiles(
        payload.username,
        target_hints=payload.target_hints,
        sites=payload.sites,
        tags=payload.tags,
        recursive_depth=payload.recursive_depth,
    )


@app.post("/api/tools/analyze-phone")
def analyze_phone_endpoint(payload: PhoneAnalyzeRequest) -> dict[str, Any]:
    """PhoneInfoga-inspired E.164 & Vietnamese carrier analyzer + multi-format dorks."""
    from app.connectors.phone_recon import analyze_phone_number

    return analyze_phone_number(payload.phone, name_hint=payload.name_hint)


@app.post("/api/tools/recon-domain-email")
async def recon_domain_email_endpoint(payload: DomainEmailReconRequest) -> dict[str, Any]:
    """theHarvester/Amass passive DNS (DoH), RDAP/crt.sh, Gravatar & OpenPGP public identity recon."""
    from app.connectors.domain_email_recon import (
        infer_corporate_email_patterns,
        inspect_public_email_crypto_identity,
        run_full_passive_domain_recon,
    )

    out: dict[str, Any] = {}
    dom = payload.domain.strip()
    em = payload.email.strip()
    if em:
        out["email_identity"] = await inspect_public_email_crypto_identity(em)
        if not dom and "@" in em:
            dom = em.split("@")[-1]
    if dom:
        out["domain_recon"] = await run_full_passive_domain_recon(dom)
        if payload.full_name.strip():
            out["inferred_email_patterns"] = infer_corporate_email_patterns(payload.full_name, dom)
    return out


@app.post("/api/tools/event-bus")
async def run_event_bus_endpoint(payload: EventBusRunRequest) -> dict[str, Any]:
    """SpiderFoot-style multi-hop Event-Driven Plugin Bus runner."""
    from app.plugins.base import OSINTEvent

    seeds = [OSINTEvent(**e) for e in payload.events]
    bus = plugin_registry.create_event_bus()
    return await bus.run(
        seed_events=seeds,
        context={"target_name": payload.target_name, "target_hints": payload.target_hints},
        max_hops=payload.max_hops,
    )


@app.post("/api/workspaces/{workspace_id}/clip", status_code=201)
async def ingest_browser_clip(workspace_id: str, payload: BrowserClipRequest) -> dict[str, Any]:
    """Human-in-the-loop Browser Companion Extension bridge (Chrome/Edge -> local Stalker++)."""
    if not store.get_workspace(workspace_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    dossier_item = None
    if payload.pin_to_dossier:
        dossier_item = store.add_dossier_item(
            workspace_id=workspace_id,
            field_key=payload.field_key.strip() or "Browser Clip",
            field_value=f"{payload.title.strip()} — {payload.selected_text.strip()[:260]}",
            category="browser_clip",
            source_url=payload.url.strip(),
            note="Captured via Stalker++ Browser Companion",
        )
    doc = ingest_manual_snippet(
        text=f"{payload.title}\n{payload.selected_text}",
        source_url=payload.url.strip(),
        title=payload.title.strip(),
    )
    chat_res = None
    if payload.analyze_with_agent:
        chat_res = await handle_chat_turn(
            store=store,
            workspace_id=workspace_id,
            prompt=f"Phân tích dữ liệu từ trình duyệt ({payload.url}): {payload.selected_text[:600]}",
            live_search=False,
            deep_mode=False,
            playbook_registry=playbook_registry,
        )
    return {
        "clipped": True,
        "dossier_item": dossier_item,
        "extracted_claims": [c.model_dump(mode="json") for c in doc.claims],
        "agent_analysis": chat_res,
    }


@app.get("/api/workspaces/{workspace_id}/export/obsidian", response_class=PlainTextResponse)
def export_workspace_obsidian(
    workspace_id: str,
    redact: bool = Query(False, description="Mask emails, phone numbers, DOBs, and IDs"),
) -> str:
    """Export verified dossier and 8D knowledge graph as an Obsidian Markdown note."""
    snapshot = store.get_graph(workspace_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Workspace not found")
    dossier = store.list_dossier_items(workspace_id)
    return export_obsidian_markdown(snapshot, dossier, redact=redact)


@app.get("/api/workspaces/{workspace_id}/export/stix")
def export_workspace_stix(
    workspace_id: str,
    redact: bool = Query(False, description="Mask emails, phone numbers, DOBs, and IDs"),
) -> JSONResponse:
    """Export workspace entities, relationships, and dossier as a STIX 2.1 JSON bundle."""
    snapshot = store.get_graph(workspace_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Workspace not found")
    dossier = store.list_dossier_items(workspace_id)
    return JSONResponse(content=export_stix_bundle(snapshot, dossier, redact=redact))


@app.get("/llms.txt", response_class=PlainTextResponse)
def serve_llms_txt() -> str:
    path = REPO_ROOT / "llms.txt"
    return path.read_text(encoding="utf-8") if path.exists() else "# Stalker++\n"


@app.get("/llms-full.txt", response_class=PlainTextResponse)
def serve_llms_full_txt() -> str:
    path = REPO_ROOT / "llms-full.txt"
    return path.read_text(encoding="utf-8") if path.exists() else "# Stalker++\n"


@app.get("/api/catalog.json")
def serve_catalog_json() -> JSONResponse:
    path = REPO_ROOT / "catalog.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="catalog.json not found")
    return JSONResponse(content=json.loads(path.read_text(encoding="utf-8")))


@app.get("/assets/{asset_path:path}")
def serve_frontend_asset(asset_path: str) -> FileResponse:
    target = (FRONTEND_DIST_DIR / "assets" / asset_path).resolve()
    assets_root = (FRONTEND_DIST_DIR / "assets").resolve()
    if not str(target).startswith(str(assets_root)) or not target.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(target)


@app.get("/", response_class=HTMLResponse)
def serve_workbench_ui() -> str:
    built_index = FRONTEND_DIST_DIR / "index.html"
    if built_index.is_file():
        return built_index.read_text(encoding="utf-8")
    return WORKBENCH_HTML


@app.get("/legacy", response_class=HTMLResponse)
def serve_legacy_workbench_ui() -> str:
    return WORKBENCH_HTML


@app.get("/api/evaluation/benchmark")
async def evaluation_benchmark_endpoint() -> dict[str, Any]:
    return await run_thesis_benchmark()


@app.post("/api/mcp")
async def mcp_http_endpoint(request: dict[str, Any]) -> dict[str, Any]:
    return await handle_mcp_request(request, store)
