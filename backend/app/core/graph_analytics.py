"""Advanced Network Science Algorithms: Adamic-Adar Link Prediction, Bridge Nodes & Communities."""

from __future__ import annotations

import math
from typing import Any

import networkx as nx
from networkx.algorithms import community


def predict_hidden_links(g: nx.Graph, top_k: int = 10) -> list[dict[str, Any]]:
    """Predict missing/implicit connections between unconnected nodes using Adamic-Adar & Jaccard.

    In OSINT, sharing a rare neighbor (e.g., a small university lab or specific project)
    is weighted exponentially higher than sharing a common hub (e.g., a major city).
    """
    simple_g = nx.Graph(g)
    if simple_g.number_of_nodes() < 3:
        return []

    predictions: list[dict[str, Any]] = []
    nodes = list(simple_g.nodes())

    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            u, v = nodes[i], nodes[j]
            if simple_g.has_edge(u, v):
                continue
            common = list(nx.common_neighbors(simple_g, u, v))
            if not common:
                continue

            # Adamic-Adar index: sum(1 / log(degree(w))) over common neighbors w
            aa_score = 0.0
            bridge_labels: list[str] = []
            for w in common:
                deg_w = simple_g.degree(w)
                aa_score += 1.0 / math.log(max(2.0, float(deg_w)))
                bridge_labels.append(str(simple_g.nodes[w].get("label", w)))

            deg_u = simple_g.degree(u)
            deg_v = simple_g.degree(v)
            union_size = deg_u + deg_v - len(common)
            jaccard = len(common) / max(1, union_size)

            combined_prob = round(min(0.99, 1.0 - math.exp(-0.6 * aa_score) + 0.2 * jaccard), 4)
            predictions.append(
                {
                    "source_id": u,
                    "source_label": simple_g.nodes[u].get("label", u),
                    "target_id": v,
                    "target_label": simple_g.nodes[v].get("label", v),
                    "adamic_adar_score": round(aa_score, 4),
                    "jaccard_score": round(jaccard, 4),
                    "predicted_probability": combined_prob,
                    "shared_bridges": bridge_labels,
                }
            )

    predictions.sort(key=lambda x: x["adamic_adar_score"], reverse=True)
    return predictions[:top_k]


def analyze_communities_and_bridges(g: nx.Graph) -> dict[str, Any]:
    """Identify tight entity clusters and high-betweenness 'bridge' nodes connecting them."""
    simple_g = nx.Graph(g)
    if simple_g.number_of_nodes() == 0:
        return {"communities": [], "bridge_nodes": []}

    comm_sets = list(community.label_propagation_communities(simple_g))
    communities_out: list[dict[str, Any]] = []
    for idx, cset in enumerate(comm_sets):
        members = [
            {
                "id": nid,
                "label": simple_g.nodes[nid].get("label", nid),
                "type": simple_g.nodes[nid].get("type", "Unknown"),
            }
            for nid in cset
        ]
        communities_out.append({"community_id": idx, "size": len(members), "members": members})

    betweenness = nx.betweenness_centrality(simple_g)
    bridges = [
        {
            "node_id": nid,
            "label": simple_g.nodes[nid].get("label", nid),
            "type": simple_g.nodes[nid].get("type", "Unknown"),
            "betweenness_centrality": round(score, 4),
        }
        for nid, score in sorted(betweenness.items(), key=lambda item: item[1], reverse=True)
        if score > 0
    ]

    return {
        "communities": communities_out,
        "bridge_nodes": bridges[:10],
    }
