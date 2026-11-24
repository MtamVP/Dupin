import type { Lang } from './types'

export interface Translations {
  appSubtitle: string
  // Sidebar
  newSession: string
  defaultSessionPrefix: string
  searchSessionsPlaceholder: string
  noMatchingSessions: string
  backgroundRunningTooltip: string
  renameTooltip: string
  deleteTooltip: string
  confirmDeleteBtn: string
  cancelBtn: string
  toggleSidebarTooltip: string
  toggleThemeTooltip: string
  localFirstBadge: string
  pluginsCount: (n: number) => string
  // Header
  entitiesEdges: (nodes: number, edges: number) => string
  switchLangTooltip: string
  integrationsBtn: string
  dossierToggleBtn: (count: number) => string
  // Empty State
  heroTitle: string
  heroLeadBeforeCode: string
  heroLeadCode: string
  heroLeadAfterCode: string
  quickPrompts: [string, string][]
  // Message cards
  clueTarget: string
  clueDob: string
  clueOrg: string
  clueRelation: string
  clueExclude: string
  reasoningTraceTitle: (steps: number) => string
  pipelineTelemetryLabel: string
  l2ShieldLabel: (rejected: number, total: number) => string
  copyReportTooltip: string
  copiedToast: string
  // Co-Steer
  coSteerTitle: string
  excludeAction: (neg: string) => string
  confirmTargetAction: string
  pinnedBadge: string
  // Sources
  discoveredSourcesTitle: (n: number) => string
  matchScoreBadge: (score: number) => string
  pdfDeepBadge: string
  pageLabel: (p: number) => string
  inspectCitationBtn: string
  saveToDossierBtn: string
  savedBadge: string
  sourcePinnedToast: string
  sourceAlreadyPinnedToast: string
  // Dorks
  suggestedDorksTitle: string
  copyDorkTooltip: string
  // Streaming & Stop
  streamStartLine: string
  stoppedByUserMsg: string
  streamErrorPrefix: string
  stopTooltip: string
  sendTooltip: string
  // Composer & Attachments
  composerPlaceholder: string
  addContextTooltip: string
  attachImage: string
  attachFile: string
  pickMapLocation: string
  insertPublicUrl: string
  insertUrlPlaceholder: string
  insertUrlAddBtn: string
  imageChipPrefix: string
  fileChipPrefix: string
  mapChipPrefix: string
  modelDefaultTag: string
  deepReactTooltip: string
  shortcutsHint: string
  // RightPanel
  tabDossier: (n: number) => string
  tabTimeline: (n: number) => string
  tabInspector: string
  redactPiiLabel: string
  exportObsidianTitle: string
  exportStixTitle: string
  exportCsvTitle: string
  dossierEmptyBeforeBold: string
  dossierEmptyBold1: string
  dossierEmptyMid: string
  dossierEmptyBold2: string
  dossierEmptyAfter: string
  dossierDuplicateNotice: string
  dossierKeyPlaceholder: string
  dossierValPlaceholder: string
  dossierUrlPlaceholder: string
  addBtn: string
  saveBtn: string
  editTooltip: string
  timelineEmpty: string
  statusConflict: string
  statusVerified: string
  statusCandidate: string
  inspectorEmptyBeforeBold: string
  inspectorEmptyBold: string
  inspectorEmptyAfter: string
  openOriginalTooltip: string
  matchScoreLabel: (s: number) => string
  indexedExcerptTitle: string
  noSnippetFallback: string
  inspectDocLoading: string
  inspectDocBtn: string
  inspectDocErrorFallback: string
  scannedPdfNoticeBefore: string
  scannedPdfNoticeBold: string
  scannedPdfNoticeAfter: string
  extractedLinesTitle: (n: number) => string
  sheetRowLabel: (sheet: string, row: number) => string
  matchedTermsLabel: (terms: string) => string
  // Integrations Modal
  hubTitle: string
  hubTabKeys: string
  hubTabLocal: string
  hubTabPlugins: (n: number) => string
  hubTabPipeline: string
  hubTabMcp: string
  fernetNoticeBefore: string
  fernetNoticeBold: string
  fernetNoticeAfter: string
  keyNamePlaceholder: string
  keySecretPlaceholder: string
  keyModelPlaceholder: string
  addKeyBtn: string
  noKeysEmpty: string
  keyUsageLabel: (used: number, err: number) => string
  disableBtn: string
  enableBtn: string
  deleteKeyTooltip: string
  orchestrationModeLabel: string
  modeAuto: string
  modeGeminiPool: string
  modeOllamaLocal: string
  modeMetasearchOnly: string
  ollamaHostLabel: string
  probeOllamaBtn: string
  ollamaScanning: string
  ollamaModelsResult: (models: string) => string
  ollamaNoModels: string
  ollamaUnreachable: (url: string) => string
  ollamaModelPlaceholder: string
  searxngLabel: string
  testSearxngBtn: string
  searxngTesting: string
  searxngOk: (count: number, engines: string) => string
  searxngFail: (url: string) => string
  searxngHintPrefix: string
  searxngHintOr: string
  saveLocalHostBtn: string
  savedLocalHostMsg: string
  pluginsHeaderBefore: string
  pluginsHeaderMid: string
  pluginsHeaderAfter: string
  pipelineHeader: string
  pipelineManifestSummary: (sites: number, jsonApis: number, openCircuits: number) => string
  pipelineValidBadge: string
  pipelineInvalidBadge: string
  mcpHeader: string
  testMcpBtn: string
  mcpTestResult: (n: number, names: string) => string
  copiedBtn: string
  copyBtn: string
  extCardTitle: string
  extCardBody: string
  // Map Picker
  mapTitle: string
  mapPlaceholder: string
  mapSearchBtn: string
  mapLockedCoords: (lat: string, lng: string) => string
  mapLocating: string
  mapFoundCoords: (lat: string, lng: string) => string
  mapShownFallback: string
  mapShownSimple: string
  mapCurrentCoords: (lat: string, lng: string) => string
  mapAttachBtn: string
  // Gatekeeper reject reasons
  rejectReasons: Record<string, string>
}

export const TRANSLATIONS: Record<Lang, Translations> = {
  vi: {
    appSubtitle: '5-Layer OSINT Co-Pilot',
    newSession: 'Cuộc điều tra mới',
    defaultSessionPrefix: 'Điều tra',
    searchSessionsPlaceholder: 'Lọc phiên điều tra...',
    noMatchingSessions: 'Không có phiên nào khớp từ khóa.',
    backgroundRunningTooltip: 'Đang chạy điều tra nền...',
    renameTooltip: 'Đổi tên',
    deleteTooltip: 'Xóa',
    confirmDeleteBtn: 'Xác nhận xóa',
    cancelBtn: 'Hủy',
    toggleSidebarTooltip: 'Thu gọn / Mở thanh phiên (Ctrl+B)',
    toggleThemeTooltip: 'Chuyển giao diện Sáng / Tối',
    localFirstBadge: 'Local-First · Public OSINT Only',
    pluginsCount: (n) => `${n} plugins`,
    entitiesEdges: (nodes, edges) => `${nodes} thực thể · ${edges} liên kết`,
    switchLangTooltip: 'Chuyển ngôn ngữ giao diện (VI / EN)',
    integrationsBtn: 'Kết nối & Plugins',
    dossierToggleBtn: (count) => `Hồ sơ (${count})`,
    heroTitle: 'Bạn đang tìm ai hoặc cần xác minh thông tin gì?',
    heroLeadBeforeCode: 'Nhập bất kỳ thông tin nào bạn có — tên, trường, công ty, SĐT, MSSV, hoặc dán một tấm ảnh. Thêm ',
    heroLeadCode: '-từ_khóa',
    heroLeadAfterCode: ' để loại bỏ kết quả trùng tên không liên quan.',
    quickPrompts: [
      ['Hồ sơ học giả & công bố khoa học', 'Geoffrey Hinton, University of Toronto'],
      ['Kỹ sư phần mềm & dự án mã nguồn mở', 'Guido van Rossum, Python, Microsoft'],
      [
        'Sinh viên & bảng điểm / danh sách trường',
        'Nguyễn Minh Anh, THPT Demo, 15/06/2005, UEH, IELTS 7.0, 31251029999',
      ],
      ['Lọc trùng tên kèm từ khóa loại trừ', 'Nguyễn Văn An, HCMUT, @nva_dev02, -ca sĩ'],
    ],
    clueTarget: 'Mục tiêu',
    clueDob: 'Ngày sinh',
    clueOrg: 'Tổ chức',
    clueRelation: 'Liên quan',
    clueExclude: 'Loại trừ',
    reasoningTraceTitle: (steps) => `Quá trình suy luận Multi-Agent (${steps} bước)`,
    pipelineTelemetryLabel: 'Pipeline 5 tầng',
    l2ShieldLabel: (rejected, total) => `L2 Shield chặn ${rejected}/${total} nhiễu`,
    copyReportTooltip: 'Sao chép báo cáo Markdown',
    copiedToast: 'Đã sao chép vào clipboard',
    coSteerTitle: 'Phát hiện nghi ngờ trùng tên — Cần bạn xác nhận (Co-Steer)',
    excludeAction: (neg) => `Loại trừ "-${neg}"`,
    confirmTargetAction: 'Đúng là người này',
    pinnedBadge: 'Đã ghim',
    discoveredSourcesTitle: (n) => `Nguồn công khai tìm được (${n})`,
    matchScoreBadge: (score) => `Khớp ${score}`,
    pdfDeepBadge: 'PDF Đọc sâu',
    pageLabel: (p) => `Trang ${p}`,
    inspectCitationBtn: 'Trích dẫn',
    saveToDossierBtn: 'Lưu Hồ sơ',
    savedBadge: 'Đã lưu',
    sourcePinnedToast: 'Đã lưu nguồn vào Hồ sơ Tổng hợp',
    sourceAlreadyPinnedToast: 'Nguồn này đã có trong Hồ sơ Tổng hợp',
    suggestedDorksTitle: 'Truy vấn mở rộng (Google AI Mode)',
    copyDorkTooltip: 'Sao chép truy vấn',
    streamStartLine: 'Đang khởi chạy Pipeline 5 tầng (L1 Intake -> L2 Shield -> L3 SearXNG ∥ ddgs -> L4 Core)...',
    stoppedByUserMsg: 'Đã dừng tiến trình điều tra theo yêu cầu của bạn.',
    streamErrorPrefix: 'Lỗi kết nối stream',
    stopTooltip: 'Dừng tiến trình đang chạy',
    sendTooltip: 'Gửi truy vấn (Enter)',
    composerPlaceholder:
      'Nhập tên, trường, SĐT, MSSV, hoặc dán ảnh (Ctrl+V)...',
    addContextTooltip: 'Thêm ngữ cảnh (Ảnh, File, Bản đồ, URL)',
    attachImage: 'Đính kèm ảnh (Vision OCR)',
    attachFile: 'Đính kèm file văn bản / CSV',
    pickMapLocation: 'Chọn địa điểm Google Maps',
    insertPublicUrl: 'Chèn URL công khai',
    insertUrlPlaceholder: 'https://example.edu.vn/danh-sach.pdf',
    insertUrlAddBtn: 'Chèn',
    imageChipPrefix: 'Ảnh',
    fileChipPrefix: 'Tệp',
    mapChipPrefix: 'Tọa độ',
    modelDefaultTag: 'Mặc định',
    deepReactTooltip: 'Bật Deep ReAct (Mirror Pivot + Đọc sâu PDF/Excel)',
    shortcutsHint: 'Enter gửi · Shift+Enter xuống dòng · Ctrl+K phiên mới · Ctrl+B thanh bên',
    tabDossier: (n) => `Hồ sơ (${n})`,
    tabTimeline: (n) => `Timeline (${n})`,
    tabInspector: 'Trích dẫn',
    redactPiiLabel: 'Ẩn danh PII khi xuất',
    exportObsidianTitle: 'Xuất Obsidian Markdown (.md)',
    exportStixTitle: 'Xuất chuẩn tình báo mạng STIX 2.1 JSON',
    exportCsvTitle: 'Xuất bảng CSV Excel',
    dossierEmptyBeforeBold: 'Chưa có thông tin nào được ghim vào ',
    dossierEmptyBold1: 'Hồ sơ Tổng hợp',
    dossierEmptyMid: '. Bấm ',
    dossierEmptyBold2: 'Lưu Hồ sơ',
    dossierEmptyAfter: ' ở kết quả chat hoặc thêm thủ công bên dưới.',
    dossierDuplicateNotice: 'Thông tin hoặc nguồn này đã có trong Hồ sơ Tổng hợp.',
    dossierKeyPlaceholder: 'Tên trường (vd: MSSV)',
    dossierValPlaceholder: 'Giá trị đã xác nhận...',
    dossierUrlPlaceholder: 'URL nguồn (tùy chọn)',
    addBtn: 'Thêm',
    saveBtn: 'Lưu',
    editTooltip: 'Chỉnh sửa',
    timelineEmpty:
      'Chưa có mốc thời gian nào. Hãy chạy một lượt điều tra để xây dựng Dòng thời gian kiểm chứng mâu thuẫn tuổi tác.',
    statusConflict: 'XUNG ĐỘT TUỔI',
    statusVerified: 'XÁC THỰC',
    statusCandidate: 'ỨNG VIÊN',
    inspectorEmptyBeforeBold: 'Bấm nút ',
    inspectorEmptyBold: 'Trích dẫn',
    inspectorEmptyAfter: ' trên bất kỳ thẻ nguồn nào bên khung chat để kiểm tra dòng khớp PDF/Web tại đây.',
    openOriginalTooltip: 'Mở trang gốc',
    matchScoreLabel: (s) => `Điểm khớp: ${s}`,
    indexedExcerptTitle: 'Trích đoạn chỉ mục',
    noSnippetFallback: 'Không có đoạn mô tả.',
    inspectDocLoading: 'Đang tải & quét bảng PDF/Excel...',
    inspectDocBtn: 'Đọc sâu file PDF/Excel này ngay',
    inspectDocErrorFallback: 'Không đọc được nội dung tài liệu này.',
    scannedPdfNoticeBefore: 'File PDF này là bản ',
    scannedPdfNoticeBold: 'scan ảnh',
    scannedPdfNoticeAfter:
      ' (không có lớp chữ). Bạn có thể chụp màn hình dòng liên quan rồi dán Ctrl+V vào ô chat để Vision OCR đọc chi tiết.',
    extractedLinesTitle: (n) => `Dòng trích xuất trực tiếp từ tài liệu (${n})`,
    sheetRowLabel: (sheet, row) => `${sheet} · Dòng ${row}`,
    matchedTermsLabel: (terms) => `Khớp: ${terms}`,
    hubTitle: 'Kết nối, Plugins & Kiến trúc 5 Tầng',
    hubTabKeys: 'API Key Pool',
    hubTabLocal: 'Host Local',
    hubTabPlugins: (n) => `Plugins (${n})`,
    hubTabPipeline: 'Kiến trúc 5 Tầng',
    hubTabMcp: 'MCP & Extension',
    fernetNoticeBefore: 'Tất cả API Key được ',
    fernetNoticeBold: 'mã hóa Fernet tại nghỉ',
    fernetNoticeAfter: ' trong SQLite nội bộ và tự động xoay vòng Round-Robin khi gặp HTTP 429.',
    keyNamePlaceholder: 'Tên gợi nhớ (vd: Gemini #1, Serper #1)',
    keySecretPlaceholder: 'Dán API Key bí mật...',
    keyModelPlaceholder: 'Model mặc định (tùy chọn)',
    addKeyBtn: '+ Thêm',
    noKeysEmpty: 'Chưa có API Key nào trong Pool.',
    keyUsageLabel: (used, err) => `Dùng: ${used} · Lỗi: ${err}`,
    disableBtn: 'Tắt',
    enableBtn: 'Bật',
    deleteKeyTooltip: 'Xóa Key',
    orchestrationModeLabel: 'Chế độ điều phối AI & Tìm kiếm',
    modeAuto: 'Tự động (Gemini Pool + SearXNG ∥ ddgs)',
    modeGeminiPool: 'Ưu tiên Gemini API Pool',
    modeOllamaLocal: '100% Host Local (Ollama + SearXNG ∥ ddgs)',
    modeMetasearchOnly: 'Chỉ Metasearch (Không gọi LLM)',
    ollamaHostLabel: 'Ollama Local Host',
    probeOllamaBtn: 'Quét Ollama',
    ollamaScanning: 'Đang quét Ollama...',
    ollamaModelsResult: (models) => `Model local: ${models}`,
    ollamaNoModels: 'Chưa tải model',
    ollamaUnreachable: (url) => `Không kết nối được Ollama tại ${url}`,
    ollamaModelPlaceholder: 'Ollama model (vd: qwen2.5:7b)',
    searxngLabel: 'SearXNG Local URL (chạy song song với ddgs)',
    testSearxngBtn: 'Test SearXNG',
    searxngTesting: 'Đang kiểm tra SearXNG JSON API...',
    searxngOk: (count, engines) => `SearXNG OK (${count} kết quả mẫu${engines}) — sẵn sàng chạy song song với ddgs.`,
    searxngFail: (url) => `Không kết nối được SearXNG tại ${url}. Chạy: cd searxng && docker compose up -d`,
    searxngHintPrefix: 'Khởi chạy 1 lệnh: ',
    searxngHintOr: ' hoặc ',
    saveLocalHostBtn: 'Lưu Host Local',
    savedLocalHostMsg: 'Đã lưu cấu hình Host Local.',
    pluginsHeaderBefore: 'Các plugin chuẩn hóa từ ',
    pluginsHeaderMid: ' và thư mục mở rộng ',
    pluginsHeaderAfter: ':',
    pipelineHeader: 'Kiến trúc Đồng tâm 5 Tầng (Lọc ngoài -> Thu thập đa kênh -> Lõi 8D MCTS)',
    pipelineManifestSummary: (sites, jsonApis, openCircuits) =>
      `Sherlock/Maigret v2: ${sites} nền tảng (${jsonApis} JSON API xác thực) · Circuit Breaker đang mở: ${openCircuits}`,
    pipelineValidBadge: 'MANIFEST HỢP LỆ',
    pipelineInvalidBadge: 'MANIFEST LỖI',
    mcpHeader: 'Kết nối Antigravity, Claude Code, Codex / Cursor qua MCP (11 Tools)',
    testMcpBtn: 'Test MCP',
    mcpTestResult: (n, names) => `MCP OK (${n} tools): ${names}`,
    copiedBtn: 'Đã copy',
    copyBtn: 'Copy',
    extCardTitle: 'Chrome / Edge Companion Extension (Human-in-the-Loop)',
    extCardBody:
      'Mở chrome://extensions -> bật Developer mode -> Load unpacked -> chọn thư mục extension/ trong repo. Khi duyệt trang công khai (Facebook, LinkedIn, cổng trường), bấm biểu tượng Dupin để đẩy snippet sạch thẳng vào Hồ sơ Tổng hợp.',
    mapTitle: 'Chọn địa điểm / tọa độ (Google Maps)',
    mapPlaceholder: 'Nhập tên trường, địa chỉ hoặc tọa độ (vd: Đại học UEH, 10.7830, 106.6950)...',
    mapSearchBtn: 'Tìm',
    mapLockedCoords: (lat, lng) => `Đã khóa tọa độ ${lat}, ${lng}`,
    mapLocating: 'Đang định vị tọa độ...',
    mapFoundCoords: (lat, lng) => `Đã lấy tọa độ: ${lat}, ${lng}`,
    mapShownFallback: 'Đã hiển thị trên Google Maps (giữ tọa độ mặc định).',
    mapShownSimple: 'Đã hiển thị trên Google Maps.',
    mapCurrentCoords: (lat, lng) => `Tọa độ hiện tại: ${lat}, ${lng}`,
    mapAttachBtn: 'Đính kèm tọa độ này',
    rejectReasons: {
      junk_url: 'URL rác',
      negative_veto: 'Loại trừ',
      temporal_seniority_veto: 'Lệch học hàm/tuổi',
      temporal_grade_age_veto: 'Lệch năm học/tuổi',
      no_target_match: 'Không khớp mục tiêu',
      low_score_pruned: 'Điểm thấp',
      user_rejected_source: 'Đã đánh dấu sai',
      unverified_rotated_out: 'Nhường chỗ tin mới',
    },
  },
  en: {
    appSubtitle: '5-Layer OSINT Co-Pilot',
    newSession: 'New Investigation',
    defaultSessionPrefix: 'Investigation',
    searchSessionsPlaceholder: 'Filter investigations...',
    noMatchingSessions: 'No matching investigations.',
    backgroundRunningTooltip: 'Running in background...',
    renameTooltip: 'Rename',
    deleteTooltip: 'Delete',
    confirmDeleteBtn: 'Confirm delete',
    cancelBtn: 'Cancel',
    toggleSidebarTooltip: 'Toggle Sidebar (Ctrl+B)',
    toggleThemeTooltip: 'Switch Light / Dark theme',
    localFirstBadge: 'Local-First · Public OSINT Only',
    pluginsCount: (n) => `${n} plugins`,
    entitiesEdges: (nodes, edges) => `${nodes} entities · ${edges} edges`,
    switchLangTooltip: 'Switch UI language (VI / EN)',
    integrationsBtn: 'Integrations & Plugins',
    dossierToggleBtn: (count) => `Dossier (${count})`,
    heroTitle: 'Who or what are you looking for?',
    heroLeadBeforeCode: 'Start with any clue you have — a name, school, company, phone number, ID, or paste a photo. Use ',
    heroLeadCode: '-keyword',
    heroLeadAfterCode: ' to filter out namesakes.',
    quickPrompts: [
      ['Academic profile & publications', 'Geoffrey Hinton, University of Toronto'],
      ['Software engineer & open-source work', 'Guido van Rossum, Python, Microsoft'],
      ['Domain & organization footprint', 'Example Research Lab, https://example.org'],
      ['Filter out namesakes with exclusions', 'Alex Chen, Stanford University, 2001-05-14, -actor'],
    ],
    clueTarget: 'Target',
    clueDob: 'DOB',
    clueOrg: 'Org',
    clueRelation: 'Related',
    clueExclude: 'Exclude',
    reasoningTraceTitle: (steps) => `Multi-Agent Reasoning Trace (${steps} steps)`,
    pipelineTelemetryLabel: '5-Layer Pipeline',
    l2ShieldLabel: (rejected, total) => `L2 Shield filtered ${rejected}/${total} noise`,
    copyReportTooltip: 'Copy Markdown report',
    copiedToast: 'Copied to clipboard',
    coSteerTitle: 'Potential Homonym Detected — Confirmation Needed (Co-Steer)',
    excludeAction: (neg) => `Exclude "-${neg}"`,
    confirmTargetAction: 'Confirm match',
    pinnedBadge: 'Pinned',
    discoveredSourcesTitle: (n) => `Public Sources Found (${n})`,
    matchScoreBadge: (score) => `Score ${score}`,
    pdfDeepBadge: 'Deep PDF',
    pageLabel: (p) => `Page ${p}`,
    inspectCitationBtn: 'Inspect',
    saveToDossierBtn: 'Pin to Dossier',
    savedBadge: 'Pinned',
    sourcePinnedToast: 'Source pinned to Verified Dossier',
    sourceAlreadyPinnedToast: 'Source is already in Verified Dossier',
    suggestedDorksTitle: 'Extended Search Dorks (Google AI Mode)',
    copyDorkTooltip: 'Copy search dork',
    streamStartLine: 'Starting 5-Layer Concentric Pipeline (L1 Intake -> L2 Shield -> L3 SearXNG ∥ ddgs -> L4 Core)...',
    stoppedByUserMsg: 'Investigation stopped at your request.',
    streamErrorPrefix: 'Stream connection error',
    stopTooltip: 'Stop running investigation',
    sendTooltip: 'Send query (Enter)',
    composerPlaceholder:
      'Enter a name, school, phone, ID, or paste an image (Ctrl+V)...',
    addContextTooltip: 'Add context (Image, File, Map, URL)',
    attachImage: 'Attach Image (Vision OCR)',
    attachFile: 'Attach Text / CSV File',
    pickMapLocation: 'Pick Google Maps Location',
    insertPublicUrl: 'Insert Public URL',
    insertUrlPlaceholder: 'https://example.edu/public-list.pdf',
    insertUrlAddBtn: 'Insert',
    imageChipPrefix: 'Image',
    fileChipPrefix: 'File',
    mapChipPrefix: 'Geo',
    modelDefaultTag: 'Default',
    deepReactTooltip: 'Toggle Deep ReAct (Mirror Pivots + Deep PDF/Excel Reader)',
    shortcutsHint: 'Enter to send · Shift+Enter newline · Ctrl+K new session · Ctrl+B sidebar',
    tabDossier: (n) => `Dossier (${n})`,
    tabTimeline: (n) => `Timeline (${n})`,
    tabInspector: 'Inspector',
    redactPiiLabel: 'Redact PII on export',
    exportObsidianTitle: 'Export Obsidian Markdown (.md)',
    exportStixTitle: 'Export STIX 2.1 Threat Intel JSON',
    exportCsvTitle: 'Export CSV Table',
    dossierEmptyBeforeBold: 'No facts pinned to the ',
    dossierEmptyBold1: 'Verified Dossier',
    dossierEmptyMid: ' yet. Click ',
    dossierEmptyBold2: 'Pin to Dossier',
    dossierEmptyAfter: ' on any chat source or add an entry manually below.',
    dossierDuplicateNotice: 'This fact or source URL is already in the Verified Dossier.',
    dossierKeyPlaceholder: 'Field (e.g., Cohort, ID)',
    dossierValPlaceholder: 'Verified value...',
    dossierUrlPlaceholder: 'Source URL (optional)',
    addBtn: 'Add',
    saveBtn: 'Save',
    editTooltip: 'Edit',
    timelineEmpty:
      'No chronological milestones yet. Run an investigation to build an age-consistency verified Timeline.',
    statusConflict: 'AGE CONFLICT',
    statusVerified: 'VERIFIED',
    statusCandidate: 'CANDIDATE',
    inspectorEmptyBeforeBold: 'Click ',
    inspectorEmptyBold: 'Inspect',
    inspectorEmptyAfter: ' on any discovered source card to view exact web snippets or PDF/Excel row extractions.',
    openOriginalTooltip: 'Open original page',
    matchScoreLabel: (s) => `Match score: ${s}`,
    indexedExcerptTitle: 'Indexed Excerpt',
    noSnippetFallback: 'No snippet available.',
    inspectDocLoading: 'Downloading & scanning PDF/Excel tables...',
    inspectDocBtn: 'Deep-Inspect PDF/Excel Document Now',
    inspectDocErrorFallback: 'Unable to parse this document.',
    scannedPdfNoticeBefore: 'This PDF appears to be a ',
    scannedPdfNoticeBold: 'scanned image',
    scannedPdfNoticeAfter:
      ' without a text layer. Capture the relevant row and press Ctrl+V into chat for Vision OCR extraction.',
    extractedLinesTitle: (n) => `Directly Extracted Rows (${n})`,
    sheetRowLabel: (sheet, row) => `${sheet} · Row ${row}`,
    matchedTermsLabel: (terms) => `Matched: ${terms}`,
    hubTitle: 'Integrations, Plugins & 5-Layer Architecture',
    hubTabKeys: 'API Key Pool',
    hubTabLocal: 'Local Host',
    hubTabPlugins: (n) => `Plugins (${n})`,
    hubTabPipeline: '5-Layer Pipeline',
    hubTabMcp: 'MCP & Extension',
    fernetNoticeBefore: 'All API keys are ',
    fernetNoticeBold: 'Fernet-encrypted at rest',
    fernetNoticeAfter: ' in local SQLite with automatic Round-Robin rotation and HTTP 429 cooldown failover.',
    keyNamePlaceholder: 'Label (e.g., Gemini #1, Serper #1)',
    keySecretPlaceholder: 'Paste secret API key...',
    keyModelPlaceholder: 'Default model (optional)',
    addKeyBtn: '+ Add',
    noKeysEmpty: 'No API keys configured in the pool yet.',
    keyUsageLabel: (used, err) => `Uses: ${used} · Errors: ${err}`,
    disableBtn: 'Disable',
    enableBtn: 'Enable',
    deleteKeyTooltip: 'Delete Key',
    orchestrationModeLabel: 'AI & Search Orchestration Mode',
    modeAuto: 'Automatic (Gemini Pool + SearXNG ∥ ddgs)',
    modeGeminiPool: 'Prefer Gemini API Pool',
    modeOllamaLocal: '100% Local Host (Ollama + SearXNG ∥ ddgs)',
    modeMetasearchOnly: 'Metasearch Only (No LLM calls)',
    ollamaHostLabel: 'Ollama Local Host',
    probeOllamaBtn: 'Probe Ollama',
    ollamaScanning: 'Probing Ollama...',
    ollamaModelsResult: (models) => `Local models: ${models}`,
    ollamaNoModels: 'No models pulled',
    ollamaUnreachable: (url) => `Cannot reach Ollama at ${url}`,
    ollamaModelPlaceholder: 'Ollama model (e.g., qwen2.5:7b)',
    searxngLabel: 'SearXNG Local URL (runs in parallel with ddgs)',
    testSearxngBtn: 'Test SearXNG',
    searxngTesting: 'Testing SearXNG JSON API...',
    searxngOk: (count, engines) => `SearXNG OK (${count} sample hits${engines}) — ready to run in parallel with ddgs.`,
    searxngFail: (url) => `Cannot reach SearXNG at ${url}. Run: cd searxng && docker compose up -d`,
    searxngHintPrefix: 'Start in 1 command: ',
    searxngHintOr: ' or ',
    saveLocalHostBtn: 'Save Local Host',
    savedLocalHostMsg: 'Local host configuration saved.',
    pluginsHeaderBefore: 'Standardized plugins loaded from ',
    pluginsHeaderMid: ' and custom directory ',
    pluginsHeaderAfter: ':',
    pipelineHeader: '5-Layer Concentric Architecture (Outer Filter -> Multi-Channel Collectors -> Inner 8D MCTS Core)',
    pipelineManifestSummary: (sites, jsonApis, openCircuits) =>
      `Sherlock/Maigret v2: ${sites} platforms (${jsonApis} verified JSON APIs) · Open circuits: ${openCircuits}`,
    pipelineValidBadge: 'MANIFEST VALID',
    pipelineInvalidBadge: 'MANIFEST ERROR',
    mcpHeader: 'Connect Antigravity, Claude Code, Codex / Cursor via MCP (11 Tools)',
    testMcpBtn: 'Test MCP',
    mcpTestResult: (n, names) => `MCP OK (${n} tools): ${names}`,
    copiedBtn: 'Copied',
    copyBtn: 'Copy',
    extCardTitle: 'Chrome / Edge Companion Extension (Human-in-the-Loop)',
    extCardBody:
      'Open chrome://extensions -> enable Developer mode -> Load unpacked -> select the extension/ folder. While browsing public pages, click the Dupin icon to clip verified snippets directly into your Dossier.',
    mapTitle: 'Pick Location / Coordinates (Google Maps)',
    mapPlaceholder: 'Enter institution, address, or coordinates (e.g., MIT Cambridge, 42.3601, -71.0942)...',
    mapSearchBtn: 'Search',
    mapLockedCoords: (lat, lng) => `Locked coordinates ${lat}, ${lng}`,
    mapLocating: 'Resolving coordinates...',
    mapFoundCoords: (lat, lng) => `Resolved coordinates: ${lat}, ${lng}`,
    mapShownFallback: 'Displayed on Google Maps (keeping fallback coordinates).',
    mapShownSimple: 'Displayed on Google Maps.',
    mapCurrentCoords: (lat, lng) => `Current coordinates: ${lat}, ${lng}`,
    mapAttachBtn: 'Attach Coordinates',
    rejectReasons: {
      junk_url: 'Junk URL',
      negative_veto: 'Excluded',
      temporal_seniority_veto: 'Seniority mismatch',
      temporal_grade_age_veto: 'Grade/Age conflict',
      no_target_match: 'Off-target',
      low_score_pruned: 'Low score',
      user_rejected_source: 'User rejected',
      unverified_rotated_out: 'Rotated for fresh hits',
    },
  },
}
