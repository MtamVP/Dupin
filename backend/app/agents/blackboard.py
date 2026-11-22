"""Shared Investigation Blackboard coordinating Multi-Agent MCTS state and human checkpoints."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.core.schemas import new_id, utc_now

MCTSStatus = Literal[
    "OPEN",
    "EXPANDED",
    "DEAD_END_BACKTRACKED",
    "CHECKPOINT_PAUSED",
]


class MCTSNode(BaseModel):
    """A node in the Language Agent Tree Search (LATS / MCTS) hypothesis tree."""

    id: str = Field(default_factory=new_id)
    parent_id: Optional[str] = None
    query: str
    strategy: str = "general"
    target_label: str = ""
    depth: int = 0
    prior_score: float = 0.6
    visits: int = 0
    total_reward: float = 0.0
    status: MCTSStatus = "OPEN"
    notes: str = ""

    def ucb1_score(self, parent_visits: int, exploration_c: float = 1.1) -> float:
        """Compute Upper Confidence Bound 1 + Prior (PUCT/UCB1) score for hypothesis selection."""
        if self.visits == 0:
            return self.prior_score + exploration_c
        mean_reward = self.total_reward / self.visits
        explore = exploration_c * math.sqrt(math.log(max(1, parent_visits)) / self.visits)
        return round(0.5 * mean_reward + 0.5 * self.prior_score + explore, 4)


class HumanCheckpoint(BaseModel):
    """Interactive pause point asking the human analyst to disambiguate ambiguous leads."""

    id: str = Field(default_factory=new_id)
    question: str
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    resolved: bool = False
    selected_option: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)


class AgentTraceEvent(BaseModel):
    """Explainable step-by-step log entry recorded by agents onto the Blackboard."""

    timestamp: datetime = Field(default_factory=utc_now)
    agent: str
    action: str
    detail: str
    reward: Optional[float] = None


class InvestigationBlackboard(BaseModel):
    """Central shared memory board for Planner, Collector, Reader, Resolver, and Critic agents."""

    id: str = Field(default_factory=new_id)
    workspace_id: str
    target_name: str
    playbook_id: str = "vietnam_student_alumni"
    seed_context: dict[str, Any] = Field(default_factory=dict)
    negative_keywords: list[str] = Field(default_factory=list)
    visited_queries: set[str] = Field(default_factory=set)
    tree: dict[str, MCTSNode] = Field(default_factory=dict)
    checkpoints: list[HumanCheckpoint] = Field(default_factory=list)
    trace: list[AgentTraceEvent] = Field(default_factory=list)

    def log(self, agent: str, action: str, detail: str, reward: Optional[float] = None) -> None:
        self.trace.append(
            AgentTraceEvent(agent=agent, action=action, detail=detail, reward=reward)
        )

    def add_hypothesis(
        self,
        query: str,
        strategy: str,
        prior_score: float = 0.65,
        parent_id: Optional[str] = None,
        depth: int = 0,
    ) -> Optional[MCTSNode]:
        clean_q = query.strip()
        if not clean_q or clean_q.lower() in self.visited_queries:
            return None
        node = MCTSNode(
            parent_id=parent_id,
            query=clean_q,
            strategy=strategy,
            target_label=self.target_name,
            depth=depth,
            prior_score=prior_score,
        )
        self.tree[node.id] = node
        return node

    def backpropagate(self, node_id: str, reward: float) -> None:
        """Propagate information-gain reward up the MCTS tree and mark dead-ends for backtracking."""
        curr_id: Optional[str] = node_id
        first = True
        while curr_id and curr_id in self.tree:
            node = self.tree[curr_id]
            node.visits += 1
            node.total_reward = round(node.total_reward + reward, 4)
            if first:
                if reward < 0.15:
                    node.status = "DEAD_END_BACKTRACKED"
                else:
                    node.status = "EXPANDED"
                first = False
            curr_id = node.parent_id
