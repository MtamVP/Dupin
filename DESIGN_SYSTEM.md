# Stalker++ Master Design System (`DESIGN_SYSTEM.md`)

Thiết kế theo quy chuẩn chống giao diện kiểu "AI Slop" (tham khảo `nextlevelbuilder/ui-ux-pro-max-skill`): ưu tiên phong cách **Swiss Analytical / Intelligence Workbench** (tương tự Palantir Foundry, Linear, Obsidian, Maltego) thay vì giao diện dark-mode xanh neon + emoji rập khuôn.

## 1. Hệ thống Màu sắc (High-Contrast Precision)
- **Chế độ Mặc định (Precision Light — Paper & Ink)**:
  - Canvas nền đồ thị: `#F6F7F9` (lưới chấm kiến trúc `#D5DAE3` cách nhau `20px`).
  - Bề mặt panel: `#FFFFFF`, đường kẻ phân tách `1px solid #E2E5EC`.
  - Chữ chính: `#111318` (độ tương phản > 14:1), chữ phụ `#525866` (> 6:1).
  - Màu nhấn duy nhất: **Cobalt Ink `#1D4ED8`** (hover `#1E40AF`).
- **Chế độ Tối tùy chọn (Neutral Carbon Dark)**:
  - Canvas `#0E1015`, Panel `#151821`, Viền `#242936` — trung tính hoàn toàn, không ánh tím/xanh neon.
- **Màu Trạng thái Ngữ nghĩa**:
  - `VERIFIED`: `#15803D` / nền `#DCFCE7`
  - `HYPOTHESIS`: `#B45309` / nền `#FEF3C7`
  - `REJECTED` / `NEGATIVE`: `#B91C1C` / nền `#FEE2E2`

## 2. Kiểu chữ (Typography)
- **UI & Văn bản**: `IBM Plex Sans` (rõ nét, chuẩn kỹ thuật, hỗ trợ dấu tiếng Việt hoàn hảo).
- **Dữ liệu, ID, Confidence, Dork, URL**: `IBM Plex Mono` kèm `font-variant-numeric: tabular-nums`.

## 3. Anti-Pattern Checklist (Tuyệt đối loại bỏ)
- Không dùng gradient tím/hồng/xanh neon phát sáng.
- Không dùng **Emoji** làm icon giao diện — thay thế 100% bằng **inline SVG 16px nét mảnh 1.75px** đồng nhất.
- Không nhồi nhét toàn bộ form vào 1 cột dài; tách gọn bằng **Segmented Tabs** ở thanh trái (`Investigate` | `Ingest` | `Dorks`) và thanh phải (`Inspector` | `Trace` | `Analytics` | `Benchmark`).
- Mọi nút đều có `cursor: pointer`, trạng thái hover/active rõ ràng, vòng `:focus-visible` chuẩn bàn phím và thời gian chuyển cảnh `150ms`.
