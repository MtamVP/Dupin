# Security Policy

## Scope & Ethical Boundaries
Stalker++ is designed strictly for **defensive research, journalism, due diligence, and educational analysis of publicly accessible information (OSINT)**.
- All data stays **local-first** on the operator's machine (SQLite + local SearXNG + optional local Ollama).
- API keys stored via the Integration Hub are encrypted at rest with **Fernet** (`backend/app/core/crypto.py`) using a machine-local key file (`backend/data/.stalker_key`) excluded from Git.
- Never commit `backend/data/*.db`, `backend/data/.stalker_key`, or `.env` files.

## Reporting a Vulnerability
If you discover a security issue (such as SSRF, XSS in the workbench UI, path traversal, or secret exposure), please report it privately to the repository maintainers via GitHub Security Advisories rather than opening a public issue.
