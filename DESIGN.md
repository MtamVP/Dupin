---
version: alpha
name: Cursor-design-analysis
description: An AI-first code editor whose marketing site reads like a quietly-confident developer-tools brand with a warm-cream editorial canvas (`#f7f7f4`) instead of the typical dark IDE atmosphere. Near-black warm ink (`#26251e`) carries body and display alike — display sits at weight 400 with negative letter-spacing for a magazine feel rather than a bold tech voice. The single brand voltage is **Cursor Orange** (`#f54e00`) reserved for primary CTAs and the wordmark. A signature pastel timeline palette (peach, mint, blue, lavender, gold) marks AI-action stages (Thinking / Reading / Editing / Grepping / Done) — only inside in-product timeline visualizations. Cards use minimal hairlines, no shadows, generous 80px section rhythm. CursorGothic for display/body, JetBrains Mono on every code surface (which is roughly half the page).

colors:
  primary: "#f54e00"
  primary-active: "#d04200"
  ink: "#26251e"
  body: "#5a5852"
  body-strong: "#26251e"
  muted: "#807d72"
  muted-soft: "#a09c92"
  hairline: "#e6e5e0"
  hairline-soft: "#efeee8"
  hairline-strong: "#cfcdc4"
  canvas: "#f7f7f4"
  canvas-soft: "#fafaf7"
  surface-card: "#ffffff"
  surface-strong: "#e6e5e0"
  on-primary: "#ffffff"
  timeline-thinking: "#dfa88f"
  timeline-grep: "#9fc9a2"
  timeline-read: "#9fbbe0"
  timeline-edit: "#c0a8dd"
  timeline-done: "#c08532"
  semantic-error: "#cf2d56"
  semantic-success: "#1f8a65"
---

# DESIGN.md — Dupin Editorial Light & Warm Dark System

## Áp dụng cho Dupin
Đây là app công cụ, không phải trang marketing. Bỏ qua hero, pricing, footer, CTA band, testimonial.
Chỉ lấy: màu, font, độ đậm, bo góc, khoảng cách, nguyên tắc hairline và không bóng đổ.

- Nền trang: `canvas` `#f7f7f4`. Card/ô nhập: trắng `#ffffff`, viền 1px `hairline`. Cấm bóng đổ.
- Sidebar: nền `canvas`, không viền khối. Mục đang chọn chỉ đổi sang nền `surface-strong`, chữ `ink`. Tên điều tra dạng danh sách phẳng, 14px/500.
- Khung chat: không bong bóng. Tin nhắn người dùng là khối trắng viền `hairline`, rộng vừa. Câu trả lời AI là văn bản phẳng trên nền `canvas`, 16px/1.5, tối đa 760px.
- Display weight 400, tiêu đề dùng letter-spacing âm (`-1.5%`). Không in đậm tiêu đề lớn.
- Màu cam `#f54e00` chỉ dùng cho nút gửi/nút chính và logo. Không dùng cho link, tab, badge.
- Danh sách truy vấn: mỗi dòng một truy vấn, JetBrains Mono 13px, nền `canvas-soft`, bo 8px. Nút Copy/Google là text button, chỉ hiện khi hover.
- Tiến trình pipeline (L1 Intake, L2 Shield, L3 SearXNG, L4 Core): hiển thị thành timeline pill pastel:
  - Intake = `timeline-read`
  - Shield = `timeline-grep`
  - SearXNG = `timeline-thinking`
  - Core = `timeline-edit`
  - Xong = `timeline-done`
  Mỗi bước một dòng, pill + mô tả thường, không dùng chấm xanh.
- Pill pastel chỉ dùng cho tiến trình pipeline, không dùng ở nơi khác.
- Nhãn nhóm như "Truy vấn mở rộng" dùng `caption-uppercase` 11px/600 đúng 1 kiểu, chỉ cho nhãn nhóm. Mọi chữ khác là chữ thường bình thường.
- Panel phải: tab gạch chân, trạng thái trống là một dòng chữ `muted`, không khung nét đứt.
- Font: Inter 400 với letter-spacing -1.5% cho display; Code/query/ID dùng JetBrains Mono.
