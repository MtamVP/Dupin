# AGENTS.md — Hướng dẫn Vận hành Stalker++ dành cho AI Agents

Tài liệu này dành cho các AI Coding & Research Agents (**Antigravity, Claude Code, Codex, Cursor, ChatGPT**) khi đọc, vận hành hoặc mở rộng kho mã nguồn **Stalker++**.

## 1. Sứ mệnh & Bản chất Hệ thống
**Stalker++** là hệ thống **Local-First Multi-Agent OSINT & 8D Entity Resolution Knowledge Graph** chạy trên máy người dùng. Thay vì quét username máy móc như các công cụ OSINT thế hệ cũ, Stalker++ hợp tác cùng con người để:
- Bóc tách dữ liệu công khai (Public OSINT only) thành **8 nhóm đặc trưng đa chiều** (`FeatureCategory`) có độ bất định và ràng buộc loại trừ (`NEGATIVE`).
- Điều tra theo cây giả thuyết **MCTS (UCB1)** có quay lui (`DEAD_END_BACKTRACKED`) và vòng lặp **Reflexion** tự học từ khóa loại trừ.
- Kiểm chứng trích dẫn gốc chống ảo giác (**CriticVerifierAgent**) và dự đoán liên kết ẩn (**Adamic-Adar**).

> **Ranh giới Bắt buộc (Ethical & Legal Guardrails):**
> - Chỉ xử lý dữ liệu công khai (Public OSINT).
> - Tuyệt đối không vượt tường đăng nhập, không tự động giải/vượt CAPTCHA, không cào dữ liệu riêng tư.
> - Với nền tảng đóng (như Facebook), sử dụng cơ chế **Human-in-the-loop** (sinh Boolean Dork cho con người kiểm tra và nhận snippet công khai người dùng cung cấp).

## 2. Bản đồ cho AI (AI-Native Entrypoints)
- `llms.txt`: Bản đồ tóm tắt toàn bộ công cụ, thuật toán, API và Playbook.
- `llms-full.txt`: Tài liệu kỹ thuật đầy đủ đã chọn lọc để nạp vào context AI trong 1 lần đọc.
- `catalog.json`: Danh mục máy đọc được (machine-readable) toàn bộ Agents, Connectors, MCP Tools, Playbooks và Endpoints.
- `SKILL.md`: Định nghĩa Skill chuẩn để cài Stalker++ trực tiếp vào AI Agent.

## 3. Cách AI Agent Kết nối & Điều khiển Stalker++ (MCP & CLI)

### Cách 1: Qua MCP Server (Stdio)
```powershell
cd backend
.\.venv\Scripts\python.exe -m app.mcp_server
```
### Cách 2: Qua MCP HTTP Endpoint (JSON-RPC 2.0)
Khởi chạy server (`uvicorn app.main:app --port 8000`) và gửi POST tới `http://127.0.0.1:8000/api/mcp` với các method `initialize`, `tools/list`, `tools/call`:
- `stalker_generate_dorks`: Sinh Boolean Search Dorks tiếng Việt đa biến thể + từ khóa loại trừ.
- `stalker_ingest_snippet`: Nạp snippet công khai & tự động rút trích claims.
- `stalker_analyze_and_verify`: Chạy chuỗi `ReaderAgent -> CriticVerifierAgent` ghi node/edge đã kiểm chứng + kiểm toán dòng thời gian.
- `stalker_resolve_entities`: So khớp 2 node trên cả 8 chiều bằng `EntityResolutionAgent` (có phủ quyết `NEGATIVE`).
- `stalker_search_graph`: Tìm kiếm ứng viên qua SQLite FTS5 (BM25) + Jaro-Winkler.
- `stalker_suggest_pivots`: Xếp hạng điểm neo có Độ lợi Thông tin (Information Gain) cao nhất.

## 4. Quy trình Kiểm thử Bắt buộc khi Sửa Code
Mọi thay đổi mã nguồn đều phải vượt qua toàn bộ bộ kiểm thử trước khi hoàn tất:
```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -v
```
