---
name: stalker-pp-osint
description: Local-first Multi-Agent OSINT, 8-Dimensional Entity Resolution, MCTS Hypothesis Search, Stylometry, and Adamic-Adar Knowledge Graph analysis. Use when investigating public digital footprints, synthesizing scattered public clues into an explainable graph, generating Vietnamese Boolean search dorks, or auditing entity timelines.
---

# Stalker++ OSINT & Entity Resolution Skill

Use this skill to collaborate with the human analyst on public Open Source Intelligence (OSINT) and Digital Footprint Self-Audit investigations.

## Core Capabilities
1. **Vietnamese & Multilingual Boolean Dorking**: Generate high-entropy search dorks combining accented/unaccented names, school/location abbreviations (`HCMUT`, `ĐHBK`, `TPHCM`, `HN`), and negative filters (`-"..."`).
2. **Neuro-Symbolic Extraction & Anti-Hallucination Audit**: Run `ReaderAgent` + `CriticVerifierAgent` on public bios, webpages, or human-provided snippets to extract 8D `FeatureClaim`s (`POSITIVE` & `NEGATIVE`) with mandatory `evidence_quote` grounding.
3. **8-Dimensional Entity Resolution**: Disambiguate candidate profiles using Jaro-Winkler, Vietnamese phonetics, handle anatomy (`minhtuan_dev02` vs `tuanm_2002_dev`), writing stylometry, Gravatar MD5, and `NEGATIVE` constraint vetoes.
4. **MCTS (UCB1) Investigation & Reflexion**: Run iterative hypothesis-driven search with automatic backtracking on noisy dead-ends and dynamic distractor keyword filtering.
5. **Network Science Analytics & Datasets**: Predict hidden links via **Adamic-Adar**, detect bridge nodes via **Betweenness Centrality**, and export to `.gexf`, `.jsonl`, and `.csv`.

## Quick Start for AI Agents
- Read `catalog.json` or `llms.txt` to inspect all available tools and playbooks.
- Start the local API & Cytoscape.js UI:
  `cd backend && .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000`
- Connect via MCP JSON-RPC 2.0 at `POST http://127.0.0.1:8000/api/mcp` or stdio `python -m app.mcp_server`.
