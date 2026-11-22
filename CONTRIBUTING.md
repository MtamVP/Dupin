# Contributing to Stalker++

Thank you for helping make **Stalker++** a trustworthy, local-first, human-in-the-loop OSINT workbench.

## Ethical & Legal Guardrails (Mandatory)
- **Public OSINT only**: Never submit code that bypasses authentication walls, defeats CAPTCHAs, or scrapes private/non-public user data.
- **Zero overfitting**: Search strategies, parsers, and relevance filters must generalize cleanly across institutions and targets.
- **No secret leaks**: Never commit API keys, `.stalker_key`, or real private datasets.

## Local Development Setup
```bash
# Backend
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m pytest -v

# Frontend (React + TypeScript + Tailwind)
cd frontend
npm install
npm run dev    # Dev server on :5173 proxying to :8000
npm run build  # Production bundle served automatically by FastAPI at :8000
```

## Adding a Community Plugin
See [`plugins/README.md`](plugins/README.md) to drop a self-contained `ConnectorPlugin` into `plugins/`.
