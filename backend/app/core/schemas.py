"""Core Pydantic schemas for Stalker++ multi-dimensional OSINT Knowledge Graph."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(timezone.utc)


def new_id() -> str:
    """Generate a new UUID4 string."""
    return str(uuid4())


class FeatureCategory(str, Enum):
    """Eight-dimensional feature ontology surrounding an OSINT entity."""

    IDENTITY = "identity"
    SPATIOTEMPORAL = "spatiotemporal"
    EDUCATION_CAREER = "education_career"
    INTERESTS_SKILLS = "interests_skills"
    STYLOMETRY_BEHAVIOR = "stylometry_behavior"
    TECHNICAL_ARTIFACT = "technical_artifact"
    RELATIONAL = "relational"
    NEGATIVE_CONSTRAINT = "negative_constraint"
    CUSTOM = "custom"


NodeType = Literal[
    "Person",
    "Alias",
    "Org",
    "Location",
    "Topic",
    "TechnicalArtifact",
    "Event",
]

EdgeStatus = Literal["VERIFIED", "HYPOTHESIS", "REJECTED"]
Polarity = Literal["POSITIVE", "NEGATIVE"]


class FeatureClaim(BaseModel):
    """A single attributed claim about an entity with provenance and uncertainty."""

    category: FeatureCategory = FeatureCategory.CUSTOM
    key: str = Field(..., min_length=1, description="Feature key, e.g. birth_year_range")
    value: Any = Field(..., description="Flexible value: string, range [2001, 2003], or vector")
    polarity: Polarity = "POSITIVE"
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    source_url: str = ""
    evidence_quote: str = ""
    discovered_at: datetime = Field(default_factory=utc_now)


class NodeCreate(BaseModel):
    """Payload to create or merge a Knowledge Graph node."""

    type: NodeType
    label: str = Field(..., min_length=1)
    claims: list[FeatureClaim] = Field(default_factory=list)
    dynamic_traits: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(0.5, ge=0.0, le=1.0)


class Node(NodeCreate):
    """Persisted Knowledge Graph node."""

    id: str = Field(default_factory=new_id)
    workspace_id: str
    normalized_label: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class EdgeCreate(BaseModel):
    """Payload to create a directed relationship edge with evidence."""

    source_id: str
    target_id: str
    relation: str = Field(..., min_length=1)
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    status: EdgeStatus = "HYPOTHESIS"
    evidence_quote: str = ""
    source_url: str = ""
    time_range: Optional[tuple[str, str]] = None


class Edge(EdgeCreate):
    """Persisted Knowledge Graph edge."""

    id: str = Field(default_factory=new_id)
    workspace_id: str
    discovered_at: datetime = Field(default_factory=utc_now)


class EdgeStatusUpdate(BaseModel):
    """Human-in-the-loop review update for an edge."""

    status: EdgeStatus
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)


class Hypothesis(BaseModel):
    """Investigation hypothesis queued by the Planner Agent."""

    id: str = Field(default_factory=new_id)
    workspace_id: str
    query: str
    target_node_id: Optional[str] = None
    priority_score: float = 0.5
    depth: int = 0
    status: Literal["PENDING", "RUNNING", "DONE", "PRUNED"] = "PENDING"
    rationale: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class WorkspaceCreate(BaseModel):
    """Payload to create an isolated investigation workspace."""

    name: str = Field(..., min_length=1, max_length=120)
    description: str = ""


class Workspace(WorkspaceCreate):
    """Persisted investigation workspace."""

    id: str = Field(default_factory=new_id)
    created_at: datetime = Field(default_factory=utc_now)


class GraphSnapshot(BaseModel):
    """Full workspace graph returned to UI or MCP clients."""

    workspace: Workspace
    nodes: list[Node]
    edges: list[Edge]
