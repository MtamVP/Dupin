# DUPIN MASTER PLAN — Bí kíp Kiến trúc & Lộ trình Nâng cấp

> **Vai trò tài liệu**: Đây là **kim chỉ nam thiết kế & kế hoạch triển khai** cho giai đoạn tiến hóa tiếp theo của **Dupin**. Tài liệu này tách biệt hoàn toàn với `README.md`, tổng hợp nguyên lý cốt lõi của hệ thống điều tra OSINT theo tư duy tối ưu hóa tập ứng viên, kết hợp kết quả thẩm định kiến trúc khách quan và lộ trình thực thi theo từng giai đoạn có kiểm chứng.

---

## 0. Điểm neo An toàn & Quy trình Phục hồi (Rollback Safety)

Trước khi thực hiện bất kỳ thay đổi mã nguồn nào theo kế hoạch này, trạng thái ổn định **Dupin v2.0 (85/85 pytest passed, Vite production build clean)** đã được khóa an toàn tại 2 lớp độc lập:

1. **GitHub Remote Snapshot & Tag**:
   - Branch `main` tại commit `0f97ec8` (CI xanh 100%: `backend-tests` 85/85 passed + `frontend-build` passed)
   - Git Tag: `v2.0-stable-backup`
   - Khôi phục tức thì bằng Git: `git checkout v2.0-stable-backup`
2. **Bản sao lưu cục bộ đầy đủ (bao gồm cả cấu hình, SQLite data & `Dupin.exe`, đã loại trừ khỏi Git qua `.gitignore`)**:
   - Thư mục: `backups/dupin-stable-backup-20261124/` (148 tệp · 26.85 MB: toàn bộ `backend/app`, `backend/tests`, `backend/data`, `frontend/src`, `frontend/dist`, `desktop`, `docs`, `extension`, `plugins`, `research`, `searxng`, `.github`, `docker-compose.yml`, `Dupin.exe`, tài liệu).
3. **Quy trình Thử nghiệm Cô lập (Clean-Lab Workflow — không làm bẩn dữ liệu v2)**:
   - **Nhánh Git riêng**: Toàn bộ kế hoạch mới triển khai trên nhánh `feat/v3-master-plan`; **chỉ merge vào `main` sau khi tất cả giai đoạn kiểm chứng thành công**.
   - **File SQLite thử nghiệm riêng (`backend/data/stalker_v3_lab.db`)**:
     1. Copy `backend/data/stalker_pp.db` → `backend/data/stalker_v3_lab.db` (dùng chung `.stalker_key`).
     2. Xóa trắng các bảng điều tra **chỉ trong `stalker_v3_lab.db`** (`workspaces`, `messages`, `nodes`, `edges`, `dossier_items`, `source_feedback`, `blackboard_logs`, `search_cache`), **giữ nguyên 100%** bảng `api_keys` và `local_config` (toàn bộ Gemini/Serper keys + SearXNG/Ollama).
     3. Chạy bản thử nghiệm v3 với `STALKER_DB_PATH=data/stalker_v3_lab.db` để test từ trạng thái **web trắng 0 hồ sơ cũ** trong khi `stalker_pp.db` thật (chứa toàn bộ các cuộc điều tra v2) không bị chạm tới 1 byte nào.
   - **Automated Tests & Evaluation Harness**: Luôn chạy trên SQLite trắng tạm (`tmp_path`), cô lập hoàn toàn khỏi cả 2 file DB trên.

> **Nguyên tắc kỷ luật**: Mọi giai đoạn triển khai mới đều phải phát triển trên nhánh riêng hoặc kiểm chứng qua bộ test hồi quy trước khi hợp nhất; nếu kiểm chứng thất bại, hoàn toàn có thể quay về nguyên trạng `v2.0-stable-backup` mà không mất bản chất hiện tại của Dupin.

---

## Phần I — Bí kíp Cốt lõi: Tư duy Điều tra Tổng quát của Dupin

Đa số các pipeline LLM/OSINT hiện nay mắc cùng một sai lầm nền tảng: **coi mọi từ khóa đầu vào bình đẳng như nhau** rồi ghép cứng `"a" "b" "c"` vào máy tìm kiếm. Dupin thế hệ mới vận hành theo **4 nguyên lý tổng quát** áp dụng cho mọi ngành nghề và đối tượng (không giới hạn ở học sinh/sinh viên):

### Nguyên lý 1: Cực tiểu hóa Tập Ứng viên theo Độ chọn lọc (Selectivity-First / Cardinality Minimization)

Xem các manh mối đầu vào như các tham số $a, b, c$ trong mô hình suy luận $y = x_0 a + x_1 b + x_2 c$, trong đó mỗi tham số có **độ chọn lọc (selectivity)** rất khác nhau đối với tập dân số $U$:

| Bậc chọn lọc | Kích thước tập ứng viên $\|S\|$ | Loại manh mối | Chiến lược xử lý |
|---|---|---|---|
| **Bậc 0 — Định danh đơn nhất** | $\|S\| \approx 1$ | SĐT, Email, MSSV/Mã nhân sự, CCCD, MST, Handle hiếm, ORCID | **Đánh thẳng** không cần vật chứa trung gian. |
| **Bậc 1 — Vật chứa có biên giới (Bounded Container)** | $\|S\| \sim 10^1 - 10^3$ | Trường + Khóa, Công ty/Phòng ban/Team, Lab/Khoa ĐH, GitHub Org, Danh bạ Bệnh viện/Hãng luật, Bảng xếp hạng giải đấu/cuộc thi | **Kéo vật chứa (Container-First)** về trước (dù là bảng HTML, PDF, Excel hay ảnh), sau đó lọc mờ theo tên bên trong tập nhỏ này. |
| **Bậc 2 — Thuộc tính rộng** | $\|S\| \sim 10^4 - 10^7$ | Tên chưa đầy đủ, Năm sinh, Tỉnh/Thành phố, Chức danh chung | **Không bắn đơn lẻ ra toàn web** để cầu may; chỉ dùng để thu hẹp bên trong Bậc 1 (ví dụ $c \cap b$) hoặc hỏi thêm người dùng 1 mỏ neo Bậc 1 nếu chỉ có toàn Bậc 2. |

**Bản chất toán học**: Thay vì thả một cái tên thiếu chữ ($a$) ra biển $10^5$ người, hãy dùng vật chứa có biên giới ($c$) kết hợp khung thời gian ($b$) để ép "tỷ lệ chọi" từ `1 / 100.000` xuống `1 / 500`, rồi mới áp bộ lọc tên linh hoạt bên trong tập nhỏ đó.

---

### Nguyên lý 2: Phân hoạch Ngữ cảnh Độc lập (Disjoint-Context Partitioning)

**Tuyệt đối không `AND` mù quáng mọi thuộc tính đầu vào vào cùng một truy vấn.**

- Các thuộc tính **cùng tồn tại trên 1 tài liệu** (ví dụ: *Tổ chức X + Khung thời gian T + Tên*) thuộc cùng một **Nhóm Ngữ cảnh Đồng xuất hiện (Co-occurring Context Group)** -> được ghép để xác định đúng vật chứa.
- Các thuộc tính thuộc **các giai đoạn thời gian hoặc miền tách rời (Disjoint Life-Stages)** (ví dụ: *Trường cấp 2 vs. Trường cấp 3*, *Công ty cũ vs. Công ty hiện tại*) hiếm khi xuất hiện trong cùng một văn bản công khai -> **phải tách thành các nhánh độc lập**, không ép `"a" "b" "c"` gây Recall = 0.

---

### Nguyên lý 3: Khớp mờ Tên có Cấu trúc (Structured Partial-Name Matching)

Khi đầu vào chỉ có tên chưa đầy đủ (2 từ), hệ thống không được coi mọi chuỗi 2 từ như nhau, mà phải phân loại dựa trên **ngữ pháp họ tên**:

1. **Dạng A — Thiếu tên đệm (`<Họ> + <Tên chính>`, từ đầu thuộc tập Họ)**:
   - Mẫu khớp bên trong vật chứa: kẹp đầu-đuôi `^<Họ>\s+(?:<ChữĐệm>\s+){0,2}<Tên>$`.
   - Phủ quyết cứng trường hợp dư từ tên riêng phía sau (`<Họ> ... <Tên> <ExtraCapitalizedToken>`).
2. **Dạng B — Thiếu Họ (`<Tên đệm> + <Tên chính>`, từ đầu KHÔNG thuộc tập Họ)**:
   - Mẫu khớp bên trong vật chứa: khớp đuôi `^<HọBấtKỳ>\s+<TênĐệm>\s+<Tên>$`.
   - **Bắt buộc rẽ nhánh song song**: Nếu trong cùng vật chứa có $\ge 2$ ứng viên khớp đuôi tên (hoặc nhiều tổ chức trùng tên ở các tỉnh khác nhau), tuyệt đối không tự đoán 1 người — phải giữ các nhánh ứng viên song song kèm thuộc tính phân tách (Họ đầy đủ, ngày sinh, đơn vị, tỉnh thành) để đối chiếu tiếp hoặc đưa ra thẻ **Co-Steer** cho con người chốt.
3. **Dạng C — Quá mơ hồ (chỉ 1 chữ tên, không có mỏ neo Bậc 0)**:
   - Không chạy vét cạn mù quáng gây rác; chủ động trả về **Information Deficit Prompt** gợi ý người dùng bổ sung ít nhất 1 mỏ neo Bậc 1 (tổ chức, địa phương, năm sinh hoặc handle).

---

### Nguyên lý 4: Chọn Playbook theo Hình dạng Input & Leo thang Manh mối Có điều kiện (Conditional Clue Escalation)

- **Playbook Routing (Tổng quát hóa, chống overfitting)**:
  - *Vật chứa giáo dục/nhân sự* (`tên >= 2 từ` + `tổ chức` + `khung thời gian`) -> Playbook **Container-First Roster**.
  - *Dấu vết số* (`username / email / domain`) -> Playbook **Digital Footprint Pivot** (Username Recon, GitHub, Gravatar, Passive DNS/CT Logs).
  - *Hồ sơ nghề nghiệp/học thuật* (`tên đầy đủ` + `công ty / ngành / nghiên cứu`) -> Playbook **Professional & Registry** (OpenAlex, ORCID, cổng doanh nghiệp, báo chí).
- **Vòng lặp Leo thang 2-Hop có Hàng rào Chống Khuếch đại Sai số (Error Amplification Guard)**:
  - **Hop 1**: Chạy Playbook phù hợp với bộ manh mối khởi đầu.
  - **Điều kiện kích hoạt Hop 2 (Strict Escalation Gate)**: Chỉ tự động quay ngược lại chạy Hop 2 **nếu và chỉ nếu** Hop 1 mở khóa được ít nhất **1 mỏ neo Bậc 0 mới độ tin cậy cao** (ví dụ: nâng từ tên 2 chữ -> *Họ tên đầy đủ*, từ năm sinh -> *Ngày sinh chính xác `DD/MM/YYYY`*, hoặc tìm thấy mới *MSSV / Email / Tổ chức mới xác thực*) **VÀ** không có tranh chấp đồng âm chưa giải quyết (nếu có $\ge 2$ ứng viên mơ hồ -> **dừng và hỏi Co-Steer**, không tự leo thang!).
  - **Cross-Stage Bridging**: Dùng mỏ neo Bậc 0 vừa mở khóa ở Hop 1 làm **cầu nối** để truy vấn sang các ngữ cảnh độc lập khác (giai đoạn trước/sau) mà trước đó không thể `AND` trực tiếp.
  - **Điều kiện dừng**: Tối đa 2 Hop (hoặc ngân sách thời gian cấu hình) hoặc khi Hop hiện tại không mở khóa thêm mỏ neo mới nào (**Saturation**).

---

## Phần II — Ranh giới Kiến trúc (Giữ gì & Không làm gì)

### 1. Những tài sản cốt lõi PHẢI GIỮ VỮNG
- **Layer 2 Deterministic Gatekeeper**: Giữ vai trò phủ quyết cứng cho mọi bất biến toán học & cấu trúc (`user_rejected_source`, `junk_url`, `negative_keyword`, `temporal_seniority_veto`, `temporal_grade_age_veto`, `dob_mismatch_veto`, `suffix_name_mismatch`, `is_vn_major_code`, `Strong-Match Retention`). Tuyệt đối không giao các luật cứng này cho LLM.
- **3-Format Roster Scanner**: Bảng HTML tách cột + PDF/XLSX (120 trang) + Vision OCR ảnh danh sách.
- **Hệ sinh thái OSINT tích hợp (Sherlock / Maigret v2, SpiderFoot Event Bus, Passive Recon, PhoneInfoga)**: Giữ trọn vẹn toàn bộ 55+ nền tảng username recon, 11 plugins sự kiện, Gravatar/OpenPGP/RDAP/crt.sh/OpenAlex/ORCID/GitHub — **không cắt bỏ**, mà tối ưu hóa cơ chế kích hoạt và lọc nhiễu ở Giai đoạn 4.
- **Layer 4 Core Trust**: 8D Entity Resolution (Log-Odds Bayes + giảm chấn buồng vang $1/\sqrt{k}$ + Negative Veto) và Critic Verbatim Quote Grounding.
- **Local-First & Zero-Key Resilience**: Chạy mượt cả khi không có API key thương mại (SearXNG + ddgs + Ollama).

### 2. Những thứ KHÔNG đập đi viết lại vội (tránh lãng phí & rủi ro hồi quy)
- **Không đập bỏ MCTS (UCB1) ở `planner.py` và Graph Analytics ở `graph_analytics.py`**: Hiện tại các module này chạy in-memory trong vài mili-giây, đã có test bao phủ sạch và không phải nguyên nhân gây chậm hay sai. Chỉ cần không đẻ thêm độ phức tạp cho MCTS, và chỉ hiển thị các chỉ số phân tích mạng lưới (Adamic-Adar, Betweenness) trên UI khi đồ thị đủ quy mô ($\ge 15$ node).
- **Chưa chèn `L2.5 Local Reranker` (BGE-Reranker / Ollama 2B–4B) ngay lúc này**: Tránh làm nặng gói cài đặt (1–2 GB RAM/disk) và tăng độ trễ khi chưa có bộ đo kiểm chứng. Chỉ xem xét dạng **optional plugin** ở Giai đoạn 5 khi mở rộng sang domain doanh nghiệp/đa ngôn ngữ và Evaluation Harness chứng minh được lợi ích thực tế.
- **Chưa tách Progressive Streaming 2 pha ghi đè báo cáo**: Giải quyết bài toán độ trễ bằng **Persistent Cache** trước để giữ state frontend/SSE đơn giản và nhất quán.

---

## Phần III — Lộ trình Triển khai theo 4 Giai đoạn

### Giai đoạn 1: Persistent OCR / PDF / HTML Cache (Ưu tiên #1 — Đòn bẩy tốc độ & chi phí)
- **Mục tiêu**: Giảm thời gian chạy lại / tra cứu cùng vật chứa từ **40–100 giây xuống < 1–3 giây**, tiết kiệm 90%+ quota Gemini Vision, **0% rủi ro** phá vỡ logic hiện tại.
- **Thiết kế kỹ thuật**:
  - Thêm bảng `document_parse_cache` trong SQLite cục bộ (`stalker_pp.db`), dùng chung giữa các workspace:
    - Khóa chính: `url_hash` (SHA-256 của URL đã chuẩn hóa) + `content_sha256` (hash nội dung file/ảnh).
    - Các cột: `doc_type` (`html_table` | `pdf` | `xlsx` | `vision_ocr`), `extracted_text`, `metadata_json`, `etag`, `created_at`, `expires_at` (TTL mặc định 30 ngày cho danh sách lịch sử, 7 ngày cho trang động).
  - Tích hợp trong `backend/app/connectors/document_reader.py`: kiểm tra cache trước khi parse PDF/XLSX hoặc gọi Vision OCR; chỉ ghi cache khi trích xuất thành công (không cache lỗi 429/timeout).
  - Thêm nút/API dọn cache khi cần trong Settings.
- **Tiêu chí hoàn tất**: Chạy lặp lại cùng 1 URL ảnh/PDF cho thấy 0 lần gọi Vision API ở lần 2; toàn bộ 85+ pytest pass.

---

### Giai đoạn 2: Frozen-Snapshot Evaluation Harness (Ưu tiên #2 — Bảo hiểm chống Regression & Overfitting)
- **Mục tiêu**: Mọi chỉnh sửa ở L1/L2/L3/L4 về sau đều có **số liệu đo lường khách quan**, chấm dứt tình trạng sửa ca mới làm rớt ca cũ.
- **Thiết kế kỹ thuật**:
  - Xây dựng bộ **Record-and-Replay** đặt tại `backend/tests/eval_harness/` (dữ liệu thật nếu có chỉ lưu cục bộ trong `.gitignore`, các ca commit lên Git sử dụng **dữ liệu tổng hợp/ẩn danh 100%**).
  - Tập Golden Dataset tối thiểu **30–50 ca chuẩn hóa**, phủ đủ 5 nhóm:
    1. Đồng âm nặng (trùng tên, khác năm sinh, dư chữ tên/biệt danh, mã ngành 7 số).
    2. Bảng HTML tách cột / PDF / Excel / OCR ảnh danh sách.
    3. Tên rút gọn 2 chữ (cả Dạng A *thiếu đệm* lẫn Dạng B *thiếu họ*).
    4. Đa ngữ cảnh tách rời (2 tổ chức thuộc 2 giai đoạn khác nhau).
    5. Ca âm tính (Negative cases — không có dữ liệu thật, để đo tỷ lệ False Positive).
  - Tự động xuất báo cáo **4 chỉ số cốt lõi**:
    - `Precision@K` (tỷ lệ nguồn đúng trong top K).
    - `Recall@K` (tỷ lệ không làm rơi mất nguồn đúng đã biết).
    - `Gatekeeper False-Rejection Rate` (tỷ lệ L2 chặn oan nguồn đúng).
    - `Ungrounded Claim Rate` (tỷ lệ claim không có trích dẫn gốc).
- **Tiêu chí hoàn tất**: Chạy 1 lệnh `pytest tests/eval_harness` trong < 10 giây (không cần mạng live), in bảng điểm baseline của `v2.0-stable-backup`.

---

### Giai đoạn 3: Strict Local-Only Toggle & Chuẩn hóa Thương hiệu `Dupin`
- **Mục tiêu**: Đáp ứng yêu cầu bảo mật/tuân thủ dữ liệu cá nhân (không rò rỉ PII ra Cloud API khi bật chế độ cục bộ) và thống nhất nhận diện chuyên nghiệp `Dupin`.
- **Thiết kế kỹ thuật**:
  - **Strict Local-Only Guard**: Khi `active_mode == "local_only"`, khóa cứng ở tầng connector (`web_search.py`, `document_reader.py`, `layer3_collectors.py`, `layer5_synthesis.py`): chỉ cho phép gọi `SearXNG` cục bộ + `Ollama` cục bộ (kể cả Vision OCR dùng model Vision trên Ollama hoặc bỏ qua Cloud Vision kèm cảnh báo rõ trên UI), tuyệt đối không gửi họ tên/ngày sinh/ảnh ra Serper hay Gemini Cloud.
  - **Rebranding sạch `Stalker++` -> `Dupin`**: Dọn đồng bộ tên gọi trên UI, `AGENTS.md`, `SKILL.md`, `llms.txt`, `llms-full.txt`, `catalog.json` (giữ bí danh tương thích ngược ở tên MCP tool nội bộ nếu cần để không phá client cũ).
- **Tiêu chí hoàn tất**: Test tự động chứng minh ở chế độ `local_only`, mọi outbound call tới `serper.dev` và `generativelanguage.googleapis.com` đều bị chặn 100%.

---

### Giai đoạn 4: Selectivity-First Playbook Router & Conditional Clue Escalation (Triển khai Bí kíp Phần I)
- **Mục tiêu**: Hiện thực hóa toàn bộ **4 nguyên lý ở Phần I** thành bộ lập kế hoạch truy vấn tổng quát, có đo đạc trước/sau bằng Evaluation Harness ở Giai đoạn 2.
- **Thiết kế kỹ thuật**:
  1. **Clue Selectivity Classifier (`backend/app/pipeline/query_planner.py`)**: Phân loại mỗi mảnh input vào Bậc 0 / Bậc 1 / Bậc 2; nhận diện cấu trúc tên 2 chữ (Dạng A *Họ+Tên* vs. Dạng B *Đệm+Tên* vs. Dạng C *1 chữ*).
  2. **Disjoint-Context Partitioner**: Gom các thuộc tính cùng ngữ cảnh (Tổ chức + Khung thời gian) và tách riêng các tổ chức khác giai đoạn thành các nhánh độc lập.
  3. **Container-First Playbook Execution**: Ưu tiên lấy vật chứa Bậc 1 trước khi có tên rút gọn + tổ chức, áp bộ lọc khớp mờ có cấu trúc (Dạng A kẹp đầu-đuôi / Dạng B khớp đuôi + rẽ nhánh song song).
  4. **Conditional 2-Hop Escalation Loop**:
     - Sau Hop 1, chạy bộ đánh giá **Escalation Gate**: kiểm tra xem có mở khóa được mỏ neo Bậc 0 mới độ tin cậy cao (và không có tranh chấp đa ứng viên chưa chốt) hay không.
     - Nếu đạt -> cập nhật `InvestigationContext` tạm thời cho Hop 2 và chạy bắc cầu sang các nhánh ngữ cảnh còn thiếu (sử dụng chung Persistent Cache từ Giai đoạn 1).
     - Nếu có $\ge 2$ ứng viên mơ hồ -> dừng leo thang và phát thẻ **Co-Steer** để người dùng chọn đúng nhánh.
  5. **Tối ưu hóa Hệ sinh thái Sherlock / Maigret v2 & SpiderFoot Event Bus (khắc phục điểm yếu hiện tại)**:
     - **Auto-Trigger ở Hop 2**: Thay vì chỉ chạy khi người dùng tự gõ `@handle`, tự động trích xuất handle/local-part/social slug mới phát hiện từ Hop 1 (ví dụ từ email cá nhân, GitHub, PDF, link mạng xã hội) để kích hoạt Sherlock/Maigret v2 có chọn lọc.
     - **Chống False Positive cho Username trùng lặp**: Đối chiếu chéo tên hiển thị / bio / tổ chức / địa điểm trên hồ sơ tìm được qua L2 Gatekeeper thay vì chỉ dựa vào HTTP 200; nâng cấp bộ nhận diện Soft-404 & cache kết quả probe ngắn hạn để tránh bị nền tảng chặn bot.
     - **Phân biệt Hạ tầng Tổ chức vs. Dấu vết Cá nhân trong SpiderFoot Event Bus**: Khi email thuộc domain trường học/doanh nghiệp lớn (như `@<student_domain>`), không lãng phí tài nguyên quét lại hạ tầng tổ chức nhiều lần mà ưu tiên các plugin mang lại dấu vết cá nhân thực sự (Gravatar MD5, GitHub commits/repos, ORCID/OpenAlex, bio cross-links, Wayback profile).
- **Tiêu chí hoàn tất**:
  - Evaluation Harness (Giai đoạn 2) ghi nhận **Recall@K tăng rõ rệt** trên nhóm ca tên rút gọn & đa giai đoạn, trong khi **Precision@K và False-Rejection Rate không suy giảm** so với baseline `v2.0-stable-backup`.

---

### Giai đoạn 5 (Tùy chọn mở rộng về sau)
- **L2.5 Optional Local Reranker**: Chỉ bật khi người dùng mở rộng sang domain doanh nghiệp/báo chí đa ngôn ngữ, chạy trên vùng xám (`score 1..3`) và phải chứng minh vượt baseline trên Evaluation Harness.
- **Online Canary Suite**: 10–15 ca public ground-truth chạy định kỳ hàng tuần để phát hiện sớm khi Serper, SearXNG hoặc cấu trúc DOM cổng thông tin thay đổi.

---

## Phần IV — Quy chuẩn Kiểm duyệt trước khi Merge mỗi Giai đoạn

Mỗi giai đoạn trong Phần III chỉ được phép hoàn tất khi thỏa mãn đủ **4 cổng kiểm duyệt**:

1. **Zero Regression**: Toàn bộ bộ kiểm thử `pytest` (85 tests nền + tests mới) đạt 100% pass.
2. **Frontend & Build Integrity**: `cd frontend && npm run build` (`tsc -b && vite build`) đạt 0 lỗi.
3. **Evaluation Gate (từ Giai đoạn 2 trở đi)**: Không tụt `Precision@K` hoặc `Recall@K` trên bất kỳ ca cũ nào trong Frozen-Snapshot Suite.
4. **Rollback Readiness**: Không ghi đè bản backup cục bộ `backups/dupin-stable-backup-20261124/` và giữ nguyên git tag `v2.0-stable-backup`.
