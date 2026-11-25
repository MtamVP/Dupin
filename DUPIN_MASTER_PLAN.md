# DUPIN MASTER PLAN — Kiến trúc Agentic OSINT & Lộ trình Nâng cấp v3

> **Vai trò tài liệu**: Đây là **kim chỉ nam kiến trúc & kế hoạch triển khai chuẩn** cho thế hệ **Dupin v3**, tách biệt hoàn toàn với `README.md`. Bản kế hoạch này đã được rà soát qua 2 vòng phản biện kỹ thuật độc lập để bịt kín các kẽ hở về phương pháp đo lường, cấu trúc cache, ngữ pháp tên tiếng Việt, giới hạn phần cứng 8GB VRAM và tính tổng quát ngoài ngành giáo dục.
>
> **Mục tiêu cuối cùng (North Star)**: Đưa Dupin tiến hóa từ pipeline chạy luật cứng 1 chiều (v2) lên **Agentic OSINT** — sử dụng **LLM để tự suy luận chiến thuật và điều khiển việc tìm kiếm thông tin thông qua một Harness Model chặt chẽ (Model-Agnostic)**: chạy mượt với các model phổ thông trên Ollama cục bộ (8GB VRAM), cắm trực tiếp qua MCP cho các AI Agent lớn, hỗ trợ Cloud API + `gemini-decision-1` tùy chọn, và vẫn giữ nguyên đường Zero-Key. Tuyệt đối **không hardcode** danh sách tên miền hay mẹo cấp học vào tầng công cụ; mọi kết quả đều đi qua **L2 Deterministic Shield + Persistent Cache + Critic Grounding**.

---

## 0. Điểm neo An toàn & Quy trình Thử nghiệm Cô lập (Rollback & Clean-Lab)

Trạng thái ổn định **Dupin v2.0 (CI xanh 100%: `backend-tests` 85/85 passed + `frontend-build` passed)** đã được khóa an toàn tại 2 lớp độc lập trước khi viết bất kỳ dòng code v3 nào:

1. **GitHub Remote Snapshot & Tag**:
   - Branch `main` tại commit `0f97ec8` · Git Tag: `v2.0-stable-backup`.
   - Khôi phục tức thì bằng Git: `git checkout v2.0-stable-backup`.
2. **Bản sao lưu cục bộ 1-1 (đã loại trừ khỏi Git qua `.gitignore`)**:
   - Thư mục `backups/dupin-stable-backup-20261124/` (**148 tệp · 26.85 MB**: toàn bộ `backend/app`, `backend/tests`, `backend/data`, `frontend/src`, `frontend/dist`, `desktop`, `docs`, `extension`, `plugins`, `searxng`, `.github`, `docker-compose.yml`, `Dupin.exe`, tài liệu).
3. **Quy trình Thử nghiệm Cô lập (Clean-Lab Workflow — không làm bẩn dữ liệu v2)**:
   - **Nhánh Git riêng**: Toàn bộ kế hoạch v3 triển khai trên nhánh `feat/v3-master-plan`; **chỉ merge vào `main` sau khi vượt qua đủ 4 cổng kiểm duyệt ở Phần IV**.
   - **File SQLite thử nghiệm riêng (`backend/data/stalker_v3_lab.db`)**:
     1. Copy `backend/data/stalker_pp.db` → `backend/data/stalker_v3_lab.db` (dùng chung `.stalker_key`).
     2. Xóa trắng các bảng điều tra **chỉ trong `stalker_v3_lab.db`** (`workspaces`, `chat_messages`, `nodes`, `edges`, `dossier_items`, `source_feedback`, `blackboards`, `http_cache`), **giữ nguyên 100%** bảng `api_keys` và `local_host_config`.
     3. Chạy nhánh v3 với `STALKER_DB_PATH=data/stalker_v3_lab.db` để kiểm chứng từ trạng thái **web trắng 0 hồ sơ cũ**, trong khi `stalker_pp.db` thật (chứa toàn bộ hồ sơ v2) không bị chạm tới 1 byte nào.
   - **Tập dữ liệu kiểm chứng cục bộ**: `backend/data/train.json` & `backend/data/train.csv` (20 ca · 79 link xác nhận, được `.gitignore` bảo vệ tuyệt đối).
   - **Automated Tests**: Luôn chạy trên SQLite trắng tạm (`tmp_path`), cô lập hoàn toàn khỏi cả 2 file DB trên.

---

## Phần I — Cơ sở Lý thuyết & 4 Nguyên lý Điều tra Tổng quát

Thay vì coi mọi từ khóa đầu vào bình đẳng như nhau rồi bắn truy vấn cứng `"a" "b" "c"` lên máy tìm kiếm, Dupin v3 vận hành dựa trên **Cost-Based Query Optimization** (Tối ưu truy vấn theo chi phí/độ chọn lọc) và **Blocking** trong bài toán Entity Resolution:

### Nguyên lý 1: Phổ Chọn lọc Động & Cực tiểu hóa Phễu Tập Ứng viên (Dynamic Selectivity-First & Cardinality Minimization)

- **Mô hình Lượng thông tin (Self-Information / Entropy)**:
  - Mỗi manh mối $k$ mang lượng thông tin $I(k) = -\log_2 P(k)$ (manh mối càng hiếm, xác suất xuất hiện $P(k)$ càng nhỏ → sức mạnh thu hẹp không gian mẫu $U$ càng lớn).
  - Chiến thuật cốt lõi: chọn nhóm điều kiện đồng xuất hiện $Q$ sao cho **cực tiểu hóa kích thước tập ứng viên $|S(Q)|$** với điều kiện **xác suất tồn tại danh sách công khai $P_{\text{emit}}(Q)$ cao**, kéo tập $S(Q)$ về cục bộ rồi chạy hàm khớp mờ $\text{match}(a, r)$ trên từng phần tử $r \in S(Q)$.
- **Phổ chọn lọc là ĐỘNG theo độ hiếm thực tế (Dynamic IDF-like Selectivity)**, không khóa cứng theo loại nhãn:
  - **Bậc 0 — Định danh đơn nhất ($|S| \approx 1$)**: SĐT, Email, MSSV/Mã nhân sự, CCCD, MST, Handle hiếm, ORCID — *hoặc một họ tên cực hiếm ($|S| \sim 5\text{--}30$)* → đánh trực tiếp.
  - **Bậc 1 — Vật chứa có biên giới ($|S| \sim 10^1 - 10^3$)**: Phải đánh giá đồng thời theo **2 trục** — *kích thước $|S|$* và *tính phát hành danh sách ($P_{\text{emit}}$)*:
    - **`List-emitting` (phát hành danh sách tập trung)**: Trường học + khóa, kỳ thi, giải đấu, danh bạ hành nghề (bác sĩ/luật sư), phòng lab đại học, ban tổ chức hội thảo → **Container-First thắng tuyệt đối** (kéo vật chứa về rồi lọc mờ cục bộ).
    - **`Profile-emitting` (không phát hành danh sách tập trung)**: Công ty tư nhân, startup, phòng ban/đội dự án nội bộ → **không đốt lượt săn file danh sách ảo**, chuyển sang quét chéo hồ sơ cá nhân (LinkedIn, GitHub, báo chí, Sherlock/Maigret).
  - **Bậc 2 — Thuộc tính rộng ($|S| \sim 10^4 - 10^7$)**: Tên phổ biến/thiếu chữ, năm sinh, tỉnh/thành phố, chức danh chung — *hoặc tổ chức khổng lồ ($|S| \ge 10^4$) khi chưa ghép lát cắt phụ (khóa, khoa, phòng ban, chi nhánh, năm)* → dùng để cắt hẹp Bậc 1 hoặc yêu cầu bổ sung mỏ neo nếu đầu vào chỉ có toàn Bậc 2.

---

### Nguyên lý 2: Phân hoạch Ngữ cảnh Độc lập (Disjoint-Context Partitioning)

- **Tuyệt đối không `AND` mù quáng mọi thuộc tính đầu vào vào cùng 1 truy vấn.**
- Các thuộc tính **đồng xuất hiện trên cùng tài liệu** (Tổ chức $X$ + Khung thời gian $T$ + Tên) được gom vào cùng 1 **Nhóm Ngữ cảnh**.
- Các thuộc tính thuộc **giai đoạn thời gian hoặc miền tách rời** (cấp học cũ vs. cấp học mới, công ty cũ vs. công ty hiện tại) phải **tách thành các nhánh độc lập** để tránh giao tập rỗng (`Recall = 0`), chỉ nối lại với nhau bằng cầu nối mỏ neo Bậc 0 sau khi đã mở khóa được ở bước trước.

---

### Nguyên lý 3: Khớp mờ Tên có Cấu trúc & Xử lý Giao thoa Họ/Tên đệm (Structured Partial-Name Matching)

Không dùng nhánh `if/else` loại trừ tuyệt đối cho tên rút gọn 2 từ, vì trong tiếng Việt nhiều từ **vừa là Họ phổ biến vừa là Tên đệm thông dụng** (`Hoàng`, `Mai`, `Hà`, `Thái`, `Lâm`, `Dương`, `Châu`, `Cao`, `Đoàn`, `Lương`, `Ngọc`, `Bảo`, `Gia`, `Kim`, `Minh`...):

1. **Dạng A — Thiếu tên đệm (`<Họ> + <Tên chính>`)**:
   - Mẫu khớp kẹp đầu-đuôi: `^<Họ>\s+(?:<ChữĐệm>\s+){0,3}<Tên>$` (biên `{0,3}` để không loại nhầm tên 5 chữ hoặc họ kép); phủ quyết cứng trường hợp dư từ tên riêng phía sau (`suffix_name_mismatch`).
2. **Dạng B — Thiếu Họ (`<Tên đệm> + <Tên chính>`)**:
   - Mẫu khớp đuôi: `^<HọBấtKỳ>\s+<TênĐệm>\s+<Tên>$` + **bắt buộc rẽ nhánh song song** (không tự chốt 1 người khi có $\ge 2$ ứng viên khớp).
3. **Tập Giao thoa (`AMBIGUOUS_SURNAME_MIDDLE`)**:
   - Khi từ đầu rơi vào tập vừa là Họ vừa là Tên đệm → chạy **hợp của cả Dạng A $\cup$ Dạng B** (ưu tiên điểm cao hơn cho Dạng A nếu khớp mạnh, nhưng vẫn giữ ứng viên Dạng B trong nhánh song song / thẻ Co-Steer để không lọc rớt người mang họ khác).
4. **Dạng C — Quá mơ hồ (chỉ 1 chữ tên, không có mỏ neo Bậc 0)**:
   - Không đoán mò sinh rác; trả về **Information Deficit Prompt** yêu cầu người dùng bổ sung ít nhất 1 mỏ neo phân tách.

---

### Nguyên lý 4: Agentic Reasoning trong Harness Chặt & Cầu nối Đa giai đoạn (Model-Agnostic Agentic Loop)

- **LLM làm bộ não chiến thuật, Code Dupin làm Vũ khí & Lá chắn**:
  - Thay vì lập trình cứng từng kịch bản bằng `if/else`, Agent chạy vòng lặp có ngân sách (`Think → Call Tool → Observe → Decide`, tối đa 4–6 bước) với đầu vào là **Working Memory đã được L2 Gatekeeper nén gọn** và đầu ra khóa cứng **Structured JSON Schema** (`thought`, `missing_clue`, `tool`, `args`, `stop`).
- **Nguyên tắc xử lý dữ liệu quá khứ tổng quát (không hardcode cấp học hay tên web)**:
  - Khi giai đoạn $T$ không tìm thấy dấu vết trực tiếp, Agent tự cân nhắc: (a) tra cứu kho lưu trữ lịch sử qua `search_wayback_cdx`, hoặc (b) tìm tài liệu ở giai đoạn kế tiếp $T+1$ nơi thường ghi lại xuất xứ của $T$ (hồ sơ tuyển sinh, CV, tiểu sử, thông báo bổ nhiệm...). Nếu vẫn không có dấu vết số hóa, dừng sớm và báo trung thực.
- **Hàng rào chống Silent Drift & Error Amplification**:
  - Chỉ tự leo thang bước tiếp theo khi bước trước mở khóa được **mỏ neo Bậc 0 mới độ tin cậy cao** và không có tranh chấp đa ứng viên.
  - Với đầu vào tên rút gọn 2 chữ, chỉ tự leo thang nếu khớp thêm ràng buộc xác nhận (như năm sinh/ngày sinh), luôn gắn nhãn giả thuyết kèm nút quay lui 1-click; nếu có $\ge 2$ ứng viên mơ hồ → dừng và phát thẻ **Co-Steer**.

---

## Phần II — Ranh giới Kiến trúc (Giữ gì & Không đập đi viết lại gì)

### 1. Tài sản cốt lõi PHẢI GIỮ VỮNG
- **Layer 2 Deterministic Gatekeeper**: Phủ quyết cứng cho mọi bất biến toán học & cấu trúc (`user_rejected_source`, `junk_url`, `negative_keyword`, `temporal_seniority_veto`, `temporal_grade_age_veto`, `dob_mismatch_veto`, `suffix_name_mismatch`, `is_vn_major_code`, `Strong-Match Retention`). Tuyệt đối không giao luật cứng cho LLM.
- **3-Format Roster Scanner**: Bảng HTML tách cột + PDF/XLSX (120 trang) + Vision OCR ảnh danh sách.
- **Hệ sinh thái OSINT tích hợp**: Giữ trọn vẹn Sherlock/Maigret v2 (55+ nền tảng), SpiderFoot Event Bus (11 plugins), Passive Recon (DoH, RDAP, crt.sh, Gravatar, OpenPGP, Wayback, OpenAlex, ORCID, GitHub), PhoneInfoga — tối ưu cách kích hoạt ở Giai đoạn 4.
- **Layer 4 Core Trust**: 8D Entity Resolution (Log-Odds Bayes + giảm chấn $1/\sqrt{k}$ + Negative Veto) và Critic Verbatim Quote Grounding.
- **Zero-Key & Local-First Resilience**: Luôn chạy được cả khi không có GPU lẫn không có API key thương mại.

### 2. Những thứ KHÔNG đập đi viết lại vội
- **Không đập bỏ MCTS (UCB1) ở `planner.py` và Graph Analytics ở `graph_analytics.py`**: Đang chạy in-memory trong vài mili-giây, đã có test đầy đủ và không gây chậm; chỉ không đẻ thêm độ phức tạp và chỉ hiện phân tích mạng lưới nâng cao trên UI khi đồ thị có $\ge 15$ node.
- **Chưa cài `BGE-Reranker` nặng 1–2 GB ngay lúc này**: Chỉ cân nhắc dạng optional plugin ở Giai đoạn 5 sau khi Evaluation Harness chứng minh được lợi ích.
- **Chưa tách Progressive Streaming 2 pha ghi đè báo cáo**: Giải quyết độ trễ bằng Persistent Cache trước để giữ state frontend/SSE đơn giản, nhất quán.

---

## Phần III — Lộ trình Triển khai 4 Giai đoạn (+ GĐ 5 Tùy chọn)

### Giai đoạn 1: Persistent Document Cache & Local Evidence Snapshot Viewer
- **Mục tiêu**: Giảm thời gian tra cứu lặp lại từ **40–100 giây xuống < 1–3 giây**, tiết kiệm 90%+ quota Vision OCR, đồng thời cho phép người dùng **tự kiểm chứng dẫn chứng ngay trong UI kể cả khi web gốc trả 503/403**.
- **Thiết kế kỹ thuật (tránh lỗi con gà và quả trứng)**:
  - **Bảng 1 — `document_url_cache` (khóa chính: `url_hash`)**:
    - Các cột: `url_hash` (PK, SHA-256 của canonical URL), `url`, `content_sha256` (FK/index sang bảng 2), `etag`, `http_status`, `created_at`, `expires_at` (TTL mặc định 30 ngày cho tài liệu tĩnh, 7 ngày cho trang động).
    - Kiểm tra **trước khi gửi request mạng**; nếu trang gốc hết hạn nhưng trả về `503 / 403 / timeout`, tự động **fallback sang bản cache cũ** kèm cờ cảnh báo.
  - **Bảng 2 — `content_parse_cache` (khóa chính: `content_sha256`)**:
    - Các cột: `content_sha256` (PK), `doc_type` (`html_table` | `pdf` | `xlsx` | `vision_ocr`), `extracted_text`, `metadata_json` (lưu kèm **`column_headers`** của bảng biểu để luôn ghim dòng tiêu đề cột khi cắt lát trích dẫn ở dòng sâu), `created_at`.
    - Cho phép tái sử dụng ngay kết quả OCR/PDF khi 2 URL khác nhau trỏ tới cùng 1 nội dung file/ảnh.
  - **Local Evidence Snapshot Viewer**: Nút `Trích dẫn` trên UI đọc trực tiếp từ cache để hiển thị **`column_headers` + ±10 dòng ngữ cảnh xung quanh dòng khớp** (kèm link Wayback dự phòng nếu có).
  - Thêm API/nút dọn cache trong Settings; tuyệt đối không cache kết quả lỗi 429/timeout.
- **Tiêu chí hoàn tất**: Chạy lặp lại cùng 1 URL ảnh/PDF đạt 0 lần gọi Vision API ở lần 2; xem được trích dẫn có tiêu đề cột ngay khi giả lập web gốc trả 503; 100% pytest pass.

---

### Giai đoạn 2: Dual-Layer Evaluation Harness (Tách 2 tầng đo độc lập)
- **Mục tiêu**: Giải quyết triệt để **nghịch lý Snapshot đóng băng vs. Agent tự sinh query mới**, bảo đảm mọi thay đổi ở L1–L4 đều có số liệu chứng minh khách quan.
- **Thiết kế kỹ thuật**:
  - **Tầng 1 — Component Replay Suite (`backend/tests/eval_harness/component_replay/`, Offline 100%, chạy trên mọi commit CI < 10s)**:
    - Dùng snapshot đóng băng để chấm riêng các thành phần *nhận đầu vào cố định*:
      - `L2 Gatekeeper` (`Gatekeeper False-Rejection Rate` & độ chính xác lọc đồng âm/lệch năm sinh/mã ngành/dư chữ).
      - `3-Format Roster Scanner` & `Structured Partial-Name Matcher` (Dạng A, Dạng B, Tập giao thoa `AMBIGUOUS_SURNAME_MIDDLE`, tên 5 chữ).
      - `8D Entity Resolution` & `Critic Verbatim Quote Grounding` (`Ungrounded Claim Rate`).
    - Dùng **100% dữ liệu tổng hợp/ẩn danh** cho các file commit lên Git.
  - **Tầng 2 — Agentic Strategy Eval (`backend/tests/eval_harness/agentic_corpus/`, Local-Only dùng `backend/data/train.json`)**:
    - Dựng **Local Noisy Corpus bằng chính SQLite FTS5 (BM25)**: nạp toàn bộ nội dung 79 nguồn đúng từ `train.json` **trộn lẫn** với vài trăm đến vài nghìn trang nhiễu, đồng âm, rác đã crawl sẵn từ SERP.
    - Cho phép Agent v3 tự do sinh query mới, tách nhánh, đổi chiến thuật trên tập chỉ mục có nhiễu này — vừa chạy offline lặp lại được, vừa đo chuẩn `Precision@K` và `Recall@K` mà không rơi vào bẫy *Cache-Miss* hay *Closed-World Illusion*.
- **Tiêu chí hoàn tất**: Chạy 1 lệnh in ra bảng điểm baseline đầy đủ của `v2.0-stable-backup` trên cả Tầng 1 và Tầng 2.

---

### Giai đoạn 3: `Zero Cloud-AI (Local Engine)` Toggle & Chuẩn hóa Thương hiệu `Dupin`
- **Mục tiêu**: Bảo vệ người dùng muốn kiểm soát rò rỉ dữ liệu lên Cloud API thương mại và chuẩn hóa nhận diện chuyên nghiệp `Dupin`.
- **Thiết kế kỹ thuật**:
  - **Chế độ `Zero Cloud-AI (Local Engine)`**: Khi bật `active_mode == "local_only"`, khóa cứng ở tầng connector (`web_search.py`, `document_reader.py`, `layer3_collectors.py`, `layer5_synthesis.py`): **chặn 100% mọi outbound call tới `serper.dev`, `generativelanguage.googleapis.com` (Gemini / `gemini-decision-1`) và OpenAI**, chỉ chạy `SearXNG` cục bộ + `Ollama` cục bộ.
  - **Minh bạch phạm vi trên UI & Tài liệu**: Ghi chú rõ đây là chế độ *Zero Cloud-AI / API Telemetry* (không gửi dữ liệu lên máy chủ LLM/Serper thương mại), đồng thời lưu ý trung thực rằng truy vấn tìm kiếm công khai vẫn đi ra ngoài qua SearXNG cục bộ (không gây hiểu nhầm kiểu mạng air-gapped hoàn toàn).
  - **Rebranding sạch `Stalker++` → `Dupin`**: Đồng bộ trên UI, `AGENTS.md`, `SKILL.md`, `llms.txt`, `llms-full.txt`, `catalog.json`, `.github/workflows/ci.yml` (giữ tương thích ngược alias tên MCP tool nếu cần).
- **Tiêu chí hoàn tất**: Test tự động chứng minh khi bật `local_only`, 100% request tới Serper/Gemini/OpenAI bị chặn tuyệt đối.

---

### Giai đoạn 4: Model-Agnostic Agentic OSINT Harness, Atomic Tools & Online Canary Gate
- **Mục tiêu**: Hiện thực hóa trọn vẹn **North Star Agentic OSINT** — LLM tự suy luận chiến thuật thông qua Harness chặt chẽ trên bộ công cụ nguyên tử tổng quát.
- **Thiết kế kỹ thuật**:
  1. **Bộ Công cụ Nguyên tử Tổng quát (`Atomic Detective Tools`, dùng chung Web UI & MCP)**:
     - `search_web` · `scan_portal_3format` · `read_doc_cached` (tổng quát mọi tài liệu công khai, không hardcode tên trang) · `search_wayback_cdx` · `scan_username_maigret` · `decode_anchors` · `verify_and_save_claim`.
     - Mọi tool đều được bọc bởi **L2 Deterministic Gatekeeper** và **GĐ1 Persistent Cache**.
  2. **4 Chế độ Chạy cho Cộng đồng GitHub (Model-Agnostic)**:
     - **Zero-Key**: Đường Deterministic Pipeline + SearXNG/ddgs.
     - **MCP Agentic**: AI Agent lớn (Antigravity, Claude Code, Cursor, Codex) trực tiếp cầm bộ Atomic Tools của Dupin — **0 tốn quota API bên trong Dupin**.
     - **Local Agentic Harness (Ollama 4B–7B trên 8GB VRAM)**: Vòng lặp `Think → Call Tool → Observe → Decide` (tối đa 4–6 bước), ép Structured JSON + Working Memory nén gọn — **0 rate limit 429**.
     - **Chống VRAM Thrashing trên 8GB VRAM**: Khi chạy local 8GB VRAM, ưu tiên dùng **1 model đa phương thức duy nhất (Text + Vision như `gemma4:e2b` hoặc `gemma3:4b`)** để không phải unload/reload VRAM giữa vòng lặp; nếu dùng model Text riêng thì tách pha gom batch OCR (hoặc OCR nhẹ chạy CPU cho ảnh bảng chữ in sắc nét).
     - **Cloud Accelerated (tùy chọn)**: Gemini Flash / OpenAI + tùy chọn **`gemini-decision-1`** (150–250 ms, 0 output token, xác suất hiệu chuẩn `0.01..0.99`) cho vùng xám L2.5, sàng lọc ảnh trước khi OCR (Multimodal Triage), và chấm ngưỡng cổng Leo thang *(tự động tắt khi bật `Zero Cloud-AI`)*.
  3. **Tối ưu Sherlock / Maigret v2 & SpiderFoot Event Bus**:
     - **Auto-Trigger**: Tự động trích xuất handle/local-part/social slug mới phát hiện ở bước trước để kích hoạt Sherlock/Maigret v2.
     - **Chống False Positive**: Đối chiếu chéo tên hiển thị / bio / tổ chức qua L2 Gatekeeper + cache probe ngắn hạn.
     - **Phân biệt Hạ tầng Tổ chức vs. Dấu vết Cá nhân**: Không quét lặp hạ tầng domain lớn; ưu tiên Gravatar MD5, GitHub repos/commits, ORCID/OpenAlex, bio cross-links, Wayback profile.
  4. **Trajectory Logger (chạy nền)**: Tự động ghi vết suy luận thành công (đã ẩn danh hóa) phục vụ đánh giá và tùy chọn chưng cất ở GĐ5.
  5. **Online Canary Suite (Nghiệm thu bắt buộc cuối GĐ4 trước khi merge `main`)**:
     - Chạy live thật trên **10–15 ca ground-truth công khai** qua Serper / SearXNG / Wayback để kiểm chứng hiệu năng thực tế ngoài đời, bù đắp hoàn toàn cho giới hạn của tập offline.
- **Tiêu chí hoàn tất**:
  - Đạt cải thiện rõ rệt `Recall@K` trên Tầng 2 (`Local Noisy Corpus`) lẫn **Online Canary Suite**, trong khi `Precision@K` và `False-Rejection Rate` trên Tầng 1 không suy giảm so với baseline `v2.0-stable-backup`.
  - Chạy trọn vẹn vòng lặp Agentic Harness trên Ollama 8GB VRAM không bị VRAM thrashing hay lỗi parse JSON.

---

### Giai đoạn 5 (Tùy chọn mở rộng về sau — không bắt buộc cho người dùng GitHub)
- **QLoRA Trajectory Distillation (`dupin-detective-4b-GGUF`)**: Khi gom đủ 100–300 vết suy luận sạch từ Trajectory Logger, fine-tune QLoRA 4-bit (Unsloth trên Google Colab miễn phí) và phát hành tùy chọn trên HuggingFace (`ollama run hf.co/...`).
- **L2.5 Optional Local Reranker**: Chỉ bật khi mở rộng mạnh sang domain doanh nghiệp/báo chí đa ngôn ngữ và chứng minh vượt baseline trên cả 2 tầng Evaluation Harness.

---

## Phần IV — 4 Cổng Kiểm duyệt Bắt buộc trước khi Merge vào `main`

Mỗi giai đoạn trong Phần III chỉ được phép hoàn tất khi thỏa mãn đủ **4 cổng kiểm duyệt**:

1. **Zero Regression**: Toàn bộ bộ kiểm thử `pytest` (85 tests nền + tests mới) đạt 100% pass.
2. **Frontend & Build Integrity**: `cd frontend && npm run build` (`tsc -b && vite build`) đạt 0 lỗi.
3. **Dual Evaluation Gate (từ GĐ2 trở đi)**: Không suy giảm `Precision@K`, `Recall@K`, `False-Rejection Rate` ở Tầng 1 & Tầng 2; riêng GĐ4 phải vượt qua **Online Canary Suite** chạy live thật.
4. **Rollback Readiness**: Giữ nguyên vẹn thư mục `backups/dupin-stable-backup-20261124/` và git tag `v2.0-stable-backup`.
