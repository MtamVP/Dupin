import { useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Ban,
  BookmarkCheck,
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  ExternalLink,
  Eye,
  FileText,
  Folder,
  Globe,
  ImagePlus,
  Link2,
  MapPin,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  Pencil,
  Pin,
  Plug,
  Plus,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Square,
  Sun,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  X,
  Zap,
} from 'lucide-react'
import { api } from './api'
import { IntegrationsModal } from './components/IntegrationsModal'
import { MapPickerModal } from './components/MapPickerModal'
import { RightPanel } from './components/RightPanel'
import { TRANSLATIONS } from './i18n'
import { safeExternalUrl } from './utils'
import type {
  AssistantPayload,
  ChatMessage,
  DossierItem,
  GeoPoint,
  GraphSnapshotData,
  Lang,
  PluginInfo,
  SourceItem,
  ThemeMode,
  TimelineEvent,
  Workspace,
} from './types'

type PipelinePillStage = {
  label: string
  pillClass:
    | 'timeline-pill-read'
    | 'timeline-pill-grep'
    | 'timeline-pill-thinking'
    | 'timeline-pill-edit'
    | 'timeline-pill-done'
}

function classifyPipelineStage(text: string): PipelinePillStage {
  const low = (text || '').toLowerCase()
  if (low.includes('xong') || low.includes('hoàn tất') || low.includes('done') || low.includes('synthesis') || low.includes('tổng hợp')) {
    return { label: 'Done', pillClass: 'timeline-pill-done' }
  }
  if (
    low.includes('shield') ||
    low.includes('l2') ||
    low.includes('gatekeeper') ||
    low.includes('lọc') ||
    low.includes('veto')
  ) {
    return { label: 'L2 Shield', pillClass: 'timeline-pill-grep' }
  }
  if (
    low.includes('mcts') ||
    low.includes('core') ||
    low.includes('l4') ||
    low.includes('reader') ||
    low.includes('critic') ||
    low.includes('entity') ||
    low.includes('backprop')
  ) {
    return { label: 'L4 Core', pillClass: 'timeline-pill-edit' }
  }
  if (
    low.includes('searxng') ||
    low.includes('serper') ||
    low.includes('ddgs') ||
    low.includes('l3') ||
    low.includes('react') ||
    low.includes('collector') ||
    low.includes('search') ||
    low.includes('google') ||
    low.includes('tìm kiếm') ||
    low.includes('plugin') ||
    low.includes('hop')
  ) {
    return { label: 'L3 SearXNG', pillClass: 'timeline-pill-thinking' }
  }
  return { label: 'L1 Intake', pillClass: 'timeline-pill-read' }
}

function normalizeUrl(u?: string) {
  return String(u || '')
    .trim()
    .replace(/\/+$/, '')
    .toLowerCase()
}

function extractDomain(u?: string) {
  try {
    return new URL(String(u || '')).hostname.replace(/^www\./, '')
  } catch {
    return ''
  }
}

function readStored<T extends string>(key: string, fallback: T, allowed: readonly T[]): T {
  try {
    const v = localStorage.getItem(key) as T | null
    if (v && allowed.includes(v)) return v
  } catch {
    // ignore storage errors
  }
  return fallback
}

function readStoredBool(key: string, fallback: boolean): boolean {
  try {
    const v = localStorage.getItem(key)
    if (v === 'true') return true
    if (v === 'false') return false
  } catch {
    // ignore
  }
  return fallback
}

function readStoredNum(key: string, fallback: number, min: number, max: number): number {
  try {
    const raw = localStorage.getItem(key)
    if (raw !== null) {
      const n = Number(raw)
      if (!Number.isNaN(n)) return Math.min(max, Math.max(min, n))
    }
  } catch {
    // ignore
  }
  return fallback
}

function foldVietnameseText(str: string): string {
  return (str || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/đ/g, 'd')
    .replace(/\s+/g, ' ')
    .trim()
}

function formatRelativeAge(iso?: string): string {
  if (!iso) return ''
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return ''
  const diffSec = Math.max(0, Math.floor((Date.now() - t) / 1000))
  if (diffSec < 60) return 'now'
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h`
  const diffDay = Math.floor(diffHr / 24)
  return `${diffDay}d`
}

type ComposerDraft = {
  prompt: string
  imgB64: string | null
  imgMime: string
  imgName: string
  imgExifSummary: string
  fileText: string | null
  fileName: string
  fileSummary: string
  geoPoint: GeoPoint | null
}

const EMPTY_DRAFT: ComposerDraft = {
  prompt: '',
  imgB64: null,
  imgMime: 'image/png',
  imgName: '',
  imgExifSummary: '',
  fileText: null,
  fileName: '',
  fileSummary: '',
  geoPoint: null,
}

const AGENT_MODELS = [
  { id: 'gemini-4-hydrogen', label: 'Gemini 4 Hydrogen', tier: 'New' },
  { id: 'gemini-3.8-flash', label: 'Gemini 3.8 Flash', tier: 'Flash' },
  { id: 'gemini-3.6-flash', label: 'Gemini 3.6 Flash', tier: 'Balanced' },
  { id: 'gemini-3.5-flash-lite', label: 'Gemini 3.5 Flash-Lite', tier: 'Fast' },
  { id: 'gemini-3.1-flash-lite', label: 'Gemini 3.1 Flash-Lite', tier: 'Lite' },
] as const

export default function App() {
  const [theme, setTheme] = useState<ThemeMode>(() => readStored('stalker_theme', 'dark', ['light', 'dark']))
  const [lang, setLang] = useState<Lang>(() => readStored('stalker_lang', 'vi', ['vi', 'en']))
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(() => readStoredBool('stalker_sidebar', true))
  const [rightOpen, setRightOpen] = useState<boolean>(() => readStoredBool('stalker_right', true))
  const [leftWidth, setLeftWidth] = useState<number>(() => readStoredNum('stalker_left_width', 256, 200, 460))
  const [rightWidth, setRightWidth] = useState<number>(() => readStoredNum('stalker_right_width', 368, 300, 620))
  const [resizingSide, setResizingSide] = useState<'left' | 'right' | null>(null)

  const t = TRANSLATIONS[lang]

  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [sessionFilter, setSessionFilter] = useState('')
  const [pinnedOnlyFilter, setPinnedOnlyFilter] = useState(false)
  const [activeWsId, setActiveWsId] = useState<string | null>(null)
  const [wsHistory, setWsHistory] = useState<string[]>([])
  const [wsHistoryIdx, setWsHistoryIdx] = useState<number>(-1)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [dossierItems, setDossierItems] = useState<DossierItem[]>([])
  const [rejectedUrlSet, setRejectedUrlSet] = useState<Set<string>>(() => new Set())
  const [graphSnapshot, setGraphSnapshot] = useState<GraphSnapshotData | null>(null)
  const [graphPopupOpen, setGraphPopupOpen] = useState(false)
  const [plugins, setPlugins] = useState<PluginInfo[]>([])

  // Inline session rename & delete confirmation (desktop-app UX, zero window.prompt/confirm)
  const [renamingWsId, setRenamingWsId] = useState<string | null>(null)
  const [renamingValue, setRenamingValue] = useState('')
  const [confirmDeleteWsId, setConfirmDeleteWsId] = useState<string | null>(null)

  // Right panel state
  const [rightTab, setRightTab] = useState<'dossier' | 'timeline' | 'inspector'>('dossier')
  const [inspectedSource, setInspectedSource] = useState<SourceItem | null>(null)

  // Modals & Popovers
  const [hubOpen, setHubOpen] = useState(false)
  const [mapOpen, setMapOpen] = useState(false)
  const [ctxMenuOpen, setCtxMenuOpen] = useState(false)
  const [modelPopupOpen, setModelPopupOpen] = useState(false)
  const [modePopupOpen, setModePopupOpen] = useState(false)
  const [cmdPaletteOpen, setCmdPaletteOpen] = useState(false)
  const [cmdQuery, setCmdQuery] = useState('')
  const [urlInsertOpen, setUrlInsertOpen] = useState(false)
  const [urlDraft, setUrlDraft] = useState('')
  const [bioFormOpen, setBioFormOpen] = useState(false)
  const [bioFields, setBioFields] = useState({
    name: '',
    phoneOrEmail: '',
    idCode: '',
    org: '',
    dob: '',
    locOrNeg: '',
  })

  // Toast feedback
  const [toastMsg, setToastMsg] = useState<string | null>(null)
  const toastTimerRef = useRef<number | null>(null)

  // Composer & Per-Workspace Concurrent Streaming + Isolated Per-Workspace Drafts
  const [draftsByWs, setDraftsByWs] = useState<Record<string, ComposerDraft>>({})
  const [model, setModel] = useState('gemini-3.5-flash-lite')
  const [deepMode, setDeepMode] = useState(true)
  const [runningByWs, setRunningByWs] = useState<Record<string, boolean>>({})
  const [streamLinesByWs, setStreamLinesByWs] = useState<Record<string, string[]>>({})
  const [pendingUserMsgByWs, setPendingUserMsgByWs] = useState<Record<string, ChatMessage | null>>({})

  const activeDraftKey = activeWsId || '__default__'
  const currentDraft = draftsByWs[activeDraftKey] || EMPTY_DRAFT
  const prompt = currentDraft.prompt
  const imgB64 = currentDraft.imgB64
  const imgMime = currentDraft.imgMime
  const imgName = currentDraft.imgName
  const imgExifSummary = currentDraft.imgExifSummary
  const fileText = currentDraft.fileText
  const fileName = currentDraft.fileName
  const fileSummary = currentDraft.fileSummary
  const geoPoint = currentDraft.geoPoint

  function patchDraftForWs(
    wsKey: string,
    patch: Partial<ComposerDraft> | ((prev: ComposerDraft) => Partial<ComposerDraft>),
  ) {
    setDraftsByWs((prev) => {
      const base = prev[wsKey] || EMPTY_DRAFT
      const delta = typeof patch === 'function' ? patch(base) : patch
      return { ...prev, [wsKey]: { ...base, ...delta } }
    })
  }

  function setPrompt(val: string | ((prev: string) => string)) {
    const key = activeWsIdRef.current || activeDraftKey
    patchDraftForWs(key, (d) => ({ prompt: typeof val === 'function' ? val(d.prompt) : val }))
  }
  function setImgB64(val: string | null) {
    const key = activeWsIdRef.current || activeDraftKey
    patchDraftForWs(key, { imgB64: val })
  }
  function setImgMime(val: string) {
    const key = activeWsIdRef.current || activeDraftKey
    patchDraftForWs(key, { imgMime: val })
  }
  function setImgName(val: string) {
    const key = activeWsIdRef.current || activeDraftKey
    patchDraftForWs(key, { imgName: val })
  }
  function setImgExifSummary(val: string) {
    const key = activeWsIdRef.current || activeDraftKey
    patchDraftForWs(key, { imgExifSummary: val })
  }
  function setFileText(val: string | null) {
    const key = activeWsIdRef.current || activeDraftKey
    patchDraftForWs(key, { fileText: val })
  }
  function setFileName(val: string) {
    const key = activeWsIdRef.current || activeDraftKey
    patchDraftForWs(key, { fileName: val })
  }
  function setFileSummary(val: string) {
    const key = activeWsIdRef.current || activeDraftKey
    patchDraftForWs(key, { fileSummary: val })
  }
  function setGeoPoint(val: GeoPoint | null) {
    const key = activeWsIdRef.current || activeDraftKey
    patchDraftForWs(key, { geoPoint: val })
  }

  const activeWsIdRef = useRef<string | null>(null)
  const abortControllersRef = useRef<Record<string, AbortController>>({})
  const chatEndRef = useRef<HTMLDivElement | null>(null)
  const composerRef = useRef<HTMLTextAreaElement | null>(null)
  const imgInputRef = useRef<HTMLInputElement | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const sending = activeWsId ? Boolean(runningByWs[activeWsId]) : false
  const streamLines = activeWsId ? streamLinesByWs[activeWsId] || [] : []

  function showToast(msg: string) {
    setToastMsg(msg)
    if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current)
    toastTimerRef.current = window.setTimeout(() => setToastMsg(null), 2400)
  }

  useEffect(() => {
    activeWsIdRef.current = activeWsId
  }, [activeWsId])

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    try {
      localStorage.setItem('stalker_theme', theme)
    } catch {
      // ignore
    }
  }, [theme])

  useEffect(() => {
    document.documentElement.setAttribute('lang', lang)
    document.title = lang === 'vi' ? 'Dupin — Trợ lý OSINT 5 Tầng' : 'Dupin — 5-Layer OSINT Workbench'
    try {
      localStorage.setItem('stalker_lang', lang)
    } catch {
      // ignore
    }
  }, [lang])

  useEffect(() => {
    try {
      localStorage.setItem('stalker_sidebar', String(sidebarOpen))
    } catch {
      // ignore
    }
  }, [sidebarOpen])

  useEffect(() => {
    try {
      localStorage.setItem('stalker_right', String(rightOpen))
    } catch {
      // ignore
    }
  }, [rightOpen])

  useEffect(() => {
    try {
      localStorage.setItem('stalker_left_width', String(leftWidth))
    } catch {
      // ignore
    }
  }, [leftWidth])

  useEffect(() => {
    try {
      localStorage.setItem('stalker_right_width', String(rightWidth))
    } catch {
      // ignore
    }
  }, [rightWidth])

  useEffect(() => {
    if (!resizingSide) return
    const onMove = (e: MouseEvent) => {
      if (resizingSide === 'left') {
        const next = Math.min(460, Math.max(200, e.clientX))
        setLeftWidth(next)
      } else {
        const next = Math.min(620, Math.max(300, window.innerWidth - e.clientX))
        setRightWidth(next)
      }
    }
    const onUp = () => setResizingSide(null)
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [resizingSide])

  // Auto-grow composer textarea cleanly (desktop feel)
  useEffect(() => {
    const el = composerRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(180, Math.max(48, el.scrollHeight))}px`
  }, [prompt])

  // Global desktop keyboard shortcuts (Ctrl/Cmd+K new session, Ctrl/Cmd+P command palette, Ctrl/Cmd+B sidebar, Ctrl/Cmd+\ right panel)
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setCtxMenuOpen(false)
        setModelPopupOpen(false)
        setModePopupOpen(false)
        setCmdPaletteOpen(false)
        setGraphPopupOpen(false)
        return
      }
      const mod = e.ctrlKey || e.metaKey
      if (!mod) return
      if (e.key.toLowerCase() === 'k') {
        e.preventDefault()
        handleCreateSession().catch(() => undefined)
      } else if (e.key.toLowerCase() === 'p') {
        e.preventDefault()
        setCmdPaletteOpen((v) => !v)
      } else if (e.key.toLowerCase() === 'b') {
        e.preventDefault()
        setSidebarOpen((s) => !s)
      } else if (e.key === '\\') {
        e.preventDefault()
        setRightOpen((r) => !r)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [workspaces.length, lang])

  function selectWorkspaceWithHistory(wsId: string) {
    activeWsIdRef.current = wsId
    setActiveWsId(wsId)
    setWsHistory((prev) => {
      const sliced = prev.slice(0, wsHistoryIdx + 1)
      if (sliced[sliced.length - 1] === wsId) return sliced
      const next = [...sliced, wsId]
      setWsHistoryIdx(next.length - 1)
      return next
    })
    loadSessionData(wsId).catch(() => undefined)
  }

  function handleNavigateHistory(delta: -1 | 1) {
    const nextIdx = wsHistoryIdx + delta
    if (nextIdx < 0 || nextIdx >= wsHistory.length) return
    const targetId = wsHistory[nextIdx]
    if (!workspaces.some((w) => w.id === targetId)) return
    setWsHistoryIdx(nextIdx)
    activeWsIdRef.current = targetId
    setActiveWsId(targetId)
    loadSessionData(targetId).catch(() => undefined)
  }

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamLines.length])

  async function refreshWorkspaces(selectId?: string) {
    let list = await api.listWorkspaces()
    if (list.length === 0) {
      const created = await api.createWorkspace(`${t.defaultSessionPrefix} #1`)
      list = [created]
    }
    setWorkspaces(list)
    const nextId =
      selectId && list.some((w) => w.id === selectId)
        ? selectId
        : activeWsId && list.some((w) => w.id === activeWsId)
          ? activeWsId
          : list[0].id
    activeWsIdRef.current = nextId
    setActiveWsId(nextId)
    await loadSessionData(nextId)
  }

  async function loadSessionData(wsId: string) {
    const [dosRes, msgRes, fbRes, graphRes] = await Promise.all([
      api.listDossier(wsId),
      api.listMessages(wsId),
      api.listSourceFeedback(wsId).catch(() => ({ items: [] })),
      api.getGraphSnapshot(wsId).catch(() => null),
    ])
    if (activeWsIdRef.current !== wsId) return
    setDossierItems(dosRes.items || [])
    setGraphSnapshot(graphRes)
    const rej = new Set<string>()
    for (const fb of fbRes.items || []) {
      if (fb.verdict === 'REJECTED') {
        const n = normalizeUrl(fb.source_url)
        if (n) rej.add(n)
      }
    }
    setRejectedUrlSet(rej)
    const loadedMsgs = msgRes.messages || []
    const pending = pendingUserMsgByWs[wsId]
    if (
      pending &&
      runningByWs[wsId] &&
      (loadedMsgs.length === 0 || loadedMsgs[loadedMsgs.length - 1].content !== pending.content)
    ) {
      setMessages([...loadedMsgs, pending])
    } else {
      setMessages(loadedMsgs)
    }
    setInspectedSource(null)
  }

  useEffect(() => {
    refreshWorkspaces().catch(() => undefined)
    api
      .listPlugins()
      .then((r) => setPlugins(r.plugins || []))
      .catch(() => undefined)
  }, [])

  const pinnedSessionsCount = useMemo(
    () => workspaces.filter((w) => Boolean(w.pinned)).length,
    [workspaces],
  )

  const filteredWorkspaces = useMemo(() => {
    const qRaw = sessionFilter.trim().toLowerCase()
    const qFolded = foldVietnameseText(sessionFilter)
    const tokens = qFolded ? qFolded.split(' ').filter(Boolean) : []

    const list = workspaces.filter((w) => {
      if (pinnedOnlyFilter && !w.pinned) return false
      if (!qRaw) return true
      const hayRaw = `${w.name} ${w.description || ''} ${w.search_summary || ''}`.toLowerCase()
      if (hayRaw.includes(qRaw)) return true
      const hayFolded = foldVietnameseText(hayRaw)
      return tokens.every((tok) => hayFolded.includes(tok))
    })

    return [...list].sort((a, b) => {
      const pa = a.pinned ? 1 : 0
      const pb = b.pinned ? 1 : 0
      if (pa !== pb) return pb - pa
      const ta = a.last_active_at || a.created_at || ''
      const tb = b.last_active_at || b.created_at || ''
      return tb.localeCompare(ta)
    })
  }, [workspaces, sessionFilter, pinnedOnlyFilter])

  const pinnedUrlSet = useMemo(() => {
    const s = new Set<string>()
    dossierItems.forEach((it) => {
      const n = normalizeUrl(it.source_url)
      if (n) s.add(n)
    })
    return s
  }, [dossierItems])

  const latestAssistantPayload = useMemo<AssistantPayload | null>(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'assistant' && messages[i].payload) {
        return messages[i].payload!
      }
    }
    return null
  }, [messages])

  const timelineEvents = useMemo<TimelineEvent[]>(() => {
    return latestAssistantPayload?.timeline_events || []
  }, [latestAssistantPayload])

  const currentTargetTerms = useMemo<string[]>(() => {
    const p = latestAssistantPayload?.parsed_clues
    const terms: string[] = []
    if (p?.target_name) terms.push(p.target_name)
    if (p?.birth_date) terms.push(p.birth_date)
    return terms
  }, [latestAssistantPayload])

  async function handleCreateSession() {
    try {
      const created = await api.createWorkspace(`${t.defaultSessionPrefix} #${workspaces.length + 1}`)
      await refreshWorkspaces(created.id)
      composerRef.current?.focus()
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Error creating session')
    }
  }

  async function handleCommitRename(ws: Workspace) {
    const next = renamingValue.trim()
    setRenamingWsId(null)
    if (!next || next === ws.name) return
    try {
      await api.renameWorkspace(ws.id, next)
      await refreshWorkspaces(ws.id)
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Error renaming session')
    }
  }

  async function handleTogglePinSession(ws: Workspace) {
    const nextPinned = !Boolean(ws.pinned)
    try {
      await api.pinWorkspace(ws.id, nextPinned)
      setWorkspaces((prev) =>
        prev.map((w) => (w.id === ws.id ? { ...w, pinned: nextPinned } : w)),
      )
      showToast(
        nextPinned
          ? lang === 'vi'
            ? `Đã ghim phiên "${ws.name}" lên đầu`
            : `Pinned "${ws.name}" to top`
          : lang === 'vi'
            ? `Đã bỏ ghim "${ws.name}"`
            : `Unpinned "${ws.name}"`,
      )
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Error pinning session')
    }
  }

  async function handlePinExcerptToDossier(title: string, content: string) {
    if (!activeWsId) return
    try {
      const cleanVal = content.replace(/\s+/g, ' ').trim().slice(0, 600)
      await api.addDossier(activeWsId, {
        field_key: title,
        field_value: cleanVal,
      })
      const [res, gRes] = await Promise.all([
        api.listDossier(activeWsId),
        api.getGraphSnapshot(activeWsId).catch(() => null),
      ])
      setDossierItems(res.items || [])
      if (gRes) setGraphSnapshot(gRes)
      showToast(
        lang === 'vi'
          ? 'Đã ghim đoạn điều tra vào Hồ sơ đã xác nhận'
          : 'Pinned investigation excerpt to Verified Dossier',
      )
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Error pinning excerpt')
    }
  }

  async function handleConfirmDeleteSession(ws: Workspace) {
    setConfirmDeleteWsId(null)
    abortControllersRef.current[ws.id]?.abort()
    delete abortControllersRef.current[ws.id]
    try {
      await api.deleteWorkspace(ws.id)
      const fallback = workspaces.find((w) => w.id !== ws.id)?.id
      await refreshWorkspaces(fallback)
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Error deleting session')
    }
  }

  function handleStop(wsId?: string | null) {
    const targetId = wsId || activeWsId
    if (!targetId) return
    const ctrl = abortControllersRef.current[targetId]
    if (ctrl) {
      ctrl.abort()
      delete abortControllersRef.current[targetId]
    }
    setStreamLinesByWs((prev) => {
      const next = { ...prev }
      delete next[targetId]
      return next
    })
    setPendingUserMsgByWs((prev) => ({ ...prev, [targetId]: null }))
    setRunningByWs((prev) => ({ ...prev, [targetId]: false }))
    if (activeWsIdRef.current === targetId) {
      setMessages((prev) => [...prev, { role: 'assistant', content: t.stoppedByUserMsg }])
    }
  }

  async function handlePinSource(src: SourceItem) {
    if (!activeWsId) return
    if (pinnedUrlSet.has(normalizeUrl(src.url))) {
      showToast(t.sourceAlreadyPinnedToast)
      return
    }
    try {
      const saved = await api.addDossier(activeWsId, {
        field_key: lang === 'vi' ? 'Nguồn đã xác nhận' : 'Verified Source',
        field_value: `${src.title || src.url} — ${(src.snippet || '').slice(0, 140)}`,
        source_url: src.url,
      })
      const norm = normalizeUrl(src.url)
      if (rejectedUrlSet.has(norm)) {
        await api.removeSourceFeedback(activeWsId, src.url).catch(() => undefined)
        setRejectedUrlSet((prev) => {
          const next = new Set(prev)
          next.delete(norm)
          return next
        })
      }
      const [res, gRes] = await Promise.all([
        api.listDossier(activeWsId),
        api.getGraphSnapshot(activeWsId).catch(() => null),
      ])
      setDossierItems(res.items || [])
      if (gRes) setGraphSnapshot(gRes)
      showToast(saved.already_exists ? t.sourceAlreadyPinnedToast : t.sourcePinnedToast)
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Error saving source')
    }
  }

  async function handleToggleRejectSource(src: SourceItem) {
    if (!activeWsId) return
    const norm = normalizeUrl(src.url)
    const isAlreadyRejected = rejectedUrlSet.has(norm)
    try {
      if (isAlreadyRejected) {
        await api.removeSourceFeedback(activeWsId, src.url)
        setRejectedUrlSet((prev) => {
          const next = new Set(prev)
          next.delete(norm)
          return next
        })
        showToast(lang === 'vi' ? 'Đã bỏ đánh dấu sai nguồn này' : 'Removed negative source mark')
      } else {
        await api.addSourceFeedback(activeWsId, {
          source_url: src.url,
          verdict: 'REJECTED',
          title: src.title || src.url,
        })
        setRejectedUrlSet((prev) => new Set(prev).add(norm))
        showToast(
          lang === 'vi'
            ? 'Đã đánh dấu không đúng — các lượt tìm sau sẽ vĩnh viễn bỏ qua nguồn này'
            : 'Marked irrelevant — future searches will permanently skip this source',
        )
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Error updating source feedback')
    }
  }

  function handleCopyText(text: string) {
    navigator.clipboard.writeText(text)
    showToast(t.copiedToast)
  }

  async function handleSend(overridePrompt?: string) {
    const rawText = (overridePrompt ?? prompt).trim()
    const targetWsId = activeWsId
    const hasAttachment = Boolean(imgB64 || fileText || geoPoint)
    if ((!rawText && !hasAttachment) || !targetWsId || runningByWs[targetWsId]) return

    const curImg = imgB64
    const curMime = imgMime
    const curFile = fileText
    const curGeo = geoPoint
    const text =
      rawText ||
      (lang === 'vi'
        ? 'Phân tích dữ liệu đính kèm (Vision OCR / Đồng phục / EXIF / Tài liệu) và truy vết mục tiêu'
        : 'Analyze attached multimodal evidence (Vision OCR / Uniform / EXIF / Document) and investigate target')

    if (!overridePrompt) patchDraftForWs(targetWsId, { prompt: '' })
    const nowIso = new Date().toISOString()
    setWorkspaces((prev) =>
      prev.map((w) => (w.id === targetWsId ? { ...w, last_active_at: nowIso } : w)),
    )
    patchDraftForWs(targetWsId, {
      imgB64: null,
      imgName: '',
      imgExifSummary: '',
      fileText: null,
      fileName: '',
      fileSummary: '',
      geoPoint: null,
    })

    let displayUser = text
    if (curGeo) displayUser += ` [${t.mapChipPrefix}: ${curGeo.label} (${curGeo.lat.toFixed(4)}, ${curGeo.lng.toFixed(4)})]`
    if (curImg) displayUser += ` [${t.imageChipPrefix}: ${imgName || 'Screenshot'}]`
    if (curFile) displayUser += ` [${t.fileChipPrefix}: ${fileName}]`

    const userMsg: ChatMessage = {
      role: 'user',
      content: displayUser,
      payload: curImg
        ? {
            assistant_reply: '',
            has_image: true,
            image_preview_url: `data:${curMime || 'image/png'};base64,${curImg}`,
          }
        : undefined,
    }
    setRunningByWs((prev) => ({ ...prev, [targetWsId]: true }))
    setPendingUserMsgByWs((prev) => ({ ...prev, [targetWsId]: userMsg }))
    setStreamLinesByWs((prev) => ({ ...prev, [targetWsId]: [t.streamStartLine] }))
    setMessages((prev) => [...prev, userMsg])

    const controller = new AbortController()
    abortControllersRef.current[targetWsId] = controller

    try {
      await api.streamChat(
        targetWsId,
        {
          prompt: text,
          live_search: true,
          deep_mode: deepMode,
          model_override: model,
          image_b64: curImg,
          image_mime: curMime,
          geo_point: curGeo,
          attached_file_text: curFile,
        },
        (line) =>
          setStreamLinesByWs((prev) => ({
            ...prev,
            [targetWsId]: [...(prev[targetWsId] || []), line],
          })),
        (payload) => {
          const doneIso = new Date().toISOString()
          setWorkspaces((prev) =>
            prev.map((w) => (w.id === targetWsId ? { ...w, last_active_at: doneIso } : w)),
          )
          setStreamLinesByWs((prev) => {
            const next = { ...prev }
            delete next[targetWsId]
            return next
          })
          setPendingUserMsgByWs((prev) => ({ ...prev, [targetWsId]: null }))
          if (activeWsIdRef.current === targetWsId) {
            setMessages((prev) => [
              ...prev,
              { role: 'assistant', content: payload.assistant_reply, payload },
            ])
            Promise.all([
              api.getGraphSnapshot(targetWsId).catch(() => null),
              api.listDossier(targetWsId).catch(() => null),
            ])
              .then(([g, d]) => {
                if (activeWsIdRef.current !== targetWsId) return
                if (g) setGraphSnapshot(g)
                if (d?.items) setDossierItems(d.items)
              })
              .catch(() => undefined)
          }
        },
        controller.signal,
      )
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        return
      }
      setStreamLinesByWs((prev) => {
        const next = { ...prev }
        delete next[targetWsId]
        return next
      })
      setPendingUserMsgByWs((prev) => ({ ...prev, [targetWsId]: null }))
      if (activeWsIdRef.current === targetWsId) {
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: `${t.streamErrorPrefix}: ${err instanceof Error ? err.message : String(err)}`,
          },
        ])
      }
    } finally {
      if (abortControllersRef.current[targetWsId] === controller) {
        delete abortControllersRef.current[targetWsId]
      }
      setRunningByWs((prev) => ({ ...prev, [targetWsId]: false }))
    }
  }

  function handleImageUpload(file?: File) {
    if (!file) return
    const targetWs = activeWsIdRef.current || activeDraftKey
    const reader = new FileReader()
    reader.onload = async () => {
      const parts = String(reader.result || '').split(',')
      const b64 = parts.length > 1 ? parts[1] : null
      patchDraftForWs(targetWs, {
        imgB64: b64,
        imgMime: file.type || 'image/png',
        imgName: file.name || 'Screenshot',
        imgExifSummary: '',
      })
      if (b64) {
        try {
          const exif = await api.extractImageExif(file.name || 'image.jpg', b64)
          if (exif.has_exif && exif.summary_text) {
            patchDraftForWs(targetWs, { imgExifSummary: exif.summary_text })
          }
          if (typeof exif.gps_lat === 'number' && typeof exif.gps_lng === 'number') {
            patchDraftForWs(targetWs, (d) =>
              d.geoPoint
                ? {}
                : {
                    geoPoint: {
                      lat: exif.gps_lat!,
                      lng: exif.gps_lng!,
                      label: 'EXIF GPS',
                    },
                  },
            )
          }
        } catch {
          // ignore local EXIF extraction errors
        }
      }
    }
    reader.readAsDataURL(file)
  }

  function handleTextUpload(file?: File) {
    if (!file) return
    const targetWs = activeWsIdRef.current || activeDraftKey
    const ext = (file.name.split('.').pop() || '').toLowerCase()
    if (['pdf', 'xlsx', 'xlsm', 'vcf', 'csv', 'tsv'].includes(ext)) {
      const reader = new FileReader()
      reader.onload = async () => {
        const parts = String(reader.result || '').split(',')
        const b64 = parts.length > 1 ? parts[1] : ''
        if (!b64) return
        patchDraftForWs(targetWs, {
          fileName: file.name,
          fileSummary: lang === 'vi' ? 'Đang trích xuất...' : 'Extracting...',
        })
        try {
          const res = await api.extractLocalFile(file.name, b64)
          if (res.ok && res.extracted_text) {
            patchDraftForWs(targetWs, {
              fileText: res.extracted_text.slice(0, 12000),
              fileSummary: res.summary || ext.toUpperCase(),
            })
          } else {
            showToast(res.error || 'Cannot extract document')
          }
        } catch (err) {
          showToast(err instanceof Error ? err.message : 'File extraction error')
        }
      }
      reader.readAsDataURL(file)
      return
    }
    const reader = new FileReader()
    reader.onload = () => {
      const txt = String(reader.result || '').slice(0, 10000)
      patchDraftForWs(targetWs, {
        fileText: txt,
        fileName: file.name,
        fileSummary: `${txt.length} chars`,
      })
    }
    reader.readAsText(file)
  }

  function handleApplyBioForm(runImmediately: boolean) {
    const segs: string[] = []
    if (bioFields.name.trim()) segs.push(`Họ và tên: ${bioFields.name.trim()}`)
    if (bioFields.dob.trim()) segs.push(`Năm sinh: ${bioFields.dob.trim()}`)
    if (bioFields.org.trim()) segs.push(`Đơn vị công tác: ${bioFields.org.trim()}`)
    if (bioFields.phoneOrEmail.trim()) segs.push(`Điện thoại: ${bioFields.phoneOrEmail.trim()}`)
    if (bioFields.idCode.trim()) segs.push(bioFields.idCode.trim())
    if (bioFields.locOrNeg.trim()) segs.push(bioFields.locOrNeg.trim())
    const built = segs.join(', ')
    if (!built) return
    setBioFormOpen(false)
    setBioFields({ name: '', phoneOrEmail: '', idCode: '', org: '', dob: '', locOrNeg: '' })
    if (runImmediately) {
      handleSend(built)
    } else {
      setPrompt((prev) => `${prev ? prev + ', ' : ''}${built}`)
    }
  }

  function handlePaste(e: React.ClipboardEvent<HTMLTextAreaElement>) {
    const items = e.clipboardData?.items
    if (!items) return
    for (const it of items) {
      if (it.type.startsWith('image/')) {
        const f = it.getAsFile()
        if (f) handleImageUpload(f)
      }
    }
  }

  const activeWs = workspaces.find((w) => w.id === activeWsId)
  const searxPlugin = plugins.find((p) => p.id === 'parallel_metasearch')
  const activeModelMeta =
    AGENT_MODELS.find((m) => m.id === model) || AGENT_MODELS[0]

  return (
    <div
      className="flex h-full w-full overflow-hidden"
      onClick={() => {
        if (ctxMenuOpen) setCtxMenuOpen(false)
        if (modelPopupOpen) setModelPopupOpen(false)
        if (modePopupOpen) setModePopupOpen(false)
        if (confirmDeleteWsId) setConfirmDeleteWsId(null)
      }}
    >
      {/* Region 1: Animated Collapsible & Resizable Left Sidebar */}
      <aside
        className={`${resizingSide === 'left' ? '' : 'agy-sidebar-drawer'} app-chrome relative flex h-full shrink-0 flex-col`}
        style={{
          width: sidebarOpen ? `${leftWidth}px` : '0px',
          opacity: sidebarOpen ? 1 : 0,
          background: 'var(--color-sidebar)',
        }}
      >
        {sidebarOpen && (
          <div
            onMouseDown={(e) => {
              e.preventDefault()
              setResizingSide('left')
            }}
            onDoubleClick={() => setLeftWidth(256)}
            className="group absolute top-0 right-0 z-30 h-full w-1.5 cursor-col-resize"
            title={
              lang === 'vi'
                ? 'Kéo để chỉnh độ rộng thanh bên trái (Nháy đúp để về mặc định 256px)'
                : 'Drag to resize left sidebar (Double-click to reset 256px)'
            }
          >
            <div
              className="ml-auto h-full w-[2px] opacity-0 transition-opacity group-hover:opacity-100"
              style={{ background: 'var(--color-hairline-strong)' }}
            />
          </div>
        )}
        <div className="flex h-full flex-col px-3 py-3" style={{ width: `${leftWidth}px` }}>
          {/* Top Antigravity IDE Toolbar Row: Brand Mark, Sidebar Toggle, Back, Forward, Quick Search, Theme */}
          <div className="flex items-center justify-between gap-1 px-1 pb-3">
            <div className="flex items-center gap-1">
              <div
                className="grid h-6 w-6 shrink-0 place-items-center font-mono text-[11px] font-semibold"
                style={{
                  background: 'var(--color-primary)',
                  color: 'var(--color-on-primary)',
                  borderRadius: 'var(--radius-sm)',
                }}
                title="Dupin — 5-Layer OSINT Agent"
              >
                D
              </div>
              <button
                onClick={() => setSidebarOpen(false)}
                className="agy-menu-item grid h-7 w-7 place-items-center"
                style={{ color: 'var(--color-muted)', borderRadius: 'var(--radius-sm)' }}
                title={t.toggleSidebarTooltip}
              >
                <PanelLeftClose className="h-3.5 w-3.5" />
              </button>
              <button
                disabled={wsHistoryIdx <= 0}
                onClick={() => handleNavigateHistory(-1)}
                className="agy-menu-item grid h-7 w-7 place-items-center disabled:opacity-35"
                style={{ color: 'var(--color-muted)', borderRadius: 'var(--radius-sm)' }}
                title={lang === 'vi' ? 'Phiên trước' : 'Previous session'}
              >
                <ArrowLeft className="h-3.5 w-3.5" />
              </button>
              <button
                disabled={wsHistoryIdx < 0 || wsHistoryIdx >= wsHistory.length - 1}
                onClick={() => handleNavigateHistory(1)}
                className="agy-menu-item grid h-7 w-7 place-items-center disabled:opacity-35"
                style={{ color: 'var(--color-muted)', borderRadius: 'var(--radius-sm)' }}
                title={lang === 'vi' ? 'Phiên tiếp theo' : 'Next session'}
              >
                <ArrowRight className="h-3.5 w-3.5" />
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  setCmdPaletteOpen(true)
                }}
                className="agy-menu-item grid h-7 w-7 place-items-center"
                style={{ color: 'var(--color-muted)', borderRadius: 'var(--radius-sm)' }}
                title={lang === 'vi' ? 'Tìm nhanh (Ctrl+P)' : 'Quick Search (Ctrl+P)'}
              >
                <Search className="h-3.5 w-3.5" />
              </button>
            </div>
            <button
              onClick={() => setTheme((th) => (th === 'dark' ? 'light' : 'dark'))}
              className="agy-menu-item grid h-7 w-7 shrink-0 place-items-center"
              style={{ color: 'var(--color-muted)', borderRadius: 'var(--radius-sm)' }}
              title={t.toggleThemeTooltip}
            >
              {theme === 'dark' ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
            </button>
          </div>

          {/* Primary Action + Session Filter */}
          <div className="space-y-2 pb-3">
            <button
              onClick={handleCreateSession}
              className="agy-menu-item flex h-9 w-full items-center gap-2 border px-3 text-[13px] font-medium"
              style={{
                background: 'var(--color-surface-card)',
                borderColor: 'var(--color-hairline-strong)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--color-ink)',
              }}
            >
              <Plus className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">{t.newSession}</span>
            </button>

            <div className="space-y-1.5">
              <div className="relative">
                <Search
                  className="pointer-events-none absolute top-2.5 left-2.5 h-3.5 w-3.5"
                  style={{ color: 'var(--color-muted)' }}
                />
                <input
                  value={sessionFilter}
                  onChange={(e) => setSessionFilter(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Escape') setSessionFilter('')
                  }}
                  placeholder={
                    lang === 'vi'
                      ? 'Tìm tên, trường, MSSV, SĐT...'
                      : 'Search name, org, ID, phone...'
                  }
                  className="h-8 w-full border pr-7 pl-8 text-[13px] outline-none"
                  style={{
                    background: 'var(--color-surface-card)',
                    borderColor: 'var(--color-hairline)',
                    borderRadius: 'var(--radius-md)',
                    color: 'var(--color-ink)',
                  }}
                />
                {sessionFilter && (
                  <button
                    onClick={() => setSessionFilter('')}
                    className="absolute top-1.5 right-1.5 grid h-5 w-5 place-items-center"
                    style={{ color: 'var(--color-muted)' }}
                    title={lang === 'vi' ? 'Xóa bộ lọc' : 'Clear filter'}
                  >
                    <X className="h-3 w-3" />
                  </button>
                )}
              </div>
              {pinnedSessionsCount > 0 && (
                <div className="flex items-center justify-between px-0.5 text-[11px]">
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => setPinnedOnlyFilter(false)}
                      className="border px-2 py-0.5 transition-colors"
                      style={{
                        background: !pinnedOnlyFilter ? 'var(--color-surface-strong)' : 'transparent',
                        borderColor: 'var(--color-hairline)',
                        borderRadius: 'var(--radius-xs)',
                        color: !pinnedOnlyFilter ? 'var(--color-ink)' : 'var(--color-muted)',
                      }}
                    >
                      {lang === 'vi' ? `Tất cả (${workspaces.length})` : `All (${workspaces.length})`}
                    </button>
                    <button
                      onClick={() => setPinnedOnlyFilter((p) => !p)}
                      className="inline-flex items-center gap-1 border px-2 py-0.5 transition-colors"
                      style={{
                        background: pinnedOnlyFilter ? 'var(--color-surface-strong)' : 'transparent',
                        borderColor: 'var(--color-hairline)',
                        borderRadius: 'var(--radius-xs)',
                        color: pinnedOnlyFilter ? 'var(--color-ink)' : 'var(--color-muted)',
                      }}
                    >
                      <Pin className="h-2.5 w-2.5" />
                      <span>
                        {lang === 'vi' ? `Đã ghim (${pinnedSessionsCount})` : `Pinned (${pinnedSessionsCount})`}
                      </span>
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="flex-1 space-y-0.5 overflow-y-auto pb-2">
            {filteredWorkspaces.length === 0 ? (
              <div className="px-2 py-4 text-[13px]" style={{ color: 'var(--color-muted)' }}>
                {t.noMatchingSessions}
              </div>
            ) : (
              filteredWorkspaces.map((ws) => {
                const active = ws.id === activeWsId
                const isRunning = Boolean(runningByWs[ws.id])
                const isRenaming = renamingWsId === ws.id
                const isConfirmDelete = confirmDeleteWsId === ws.id
                const isPinned = Boolean(ws.pinned)
                const relAge = formatRelativeAge(ws.last_active_at || ws.created_at)
                return (
                  <div
                    key={ws.id}
                    onClick={() => {
                      if (isRenaming) return
                      selectWorkspaceWithHistory(ws.id)
                    }}
                    className="agy-nav-row group flex flex-col gap-1 px-2.5 py-2 text-[13px] font-medium"
                    style={{
                      background: active ? 'var(--color-surface-strong)' : 'transparent',
                      color: active ? 'var(--color-ink)' : 'var(--color-body)',
                      borderRadius: 'var(--radius-md)',
                      cursor: isRenaming ? 'default' : 'pointer',
                    }}
                  >
                    <div className="flex items-center justify-between gap-2">
                      {isRenaming ? (
                        <div className="flex flex-1 items-center gap-1" onClick={(e) => e.stopPropagation()}>
                          <input
                            autoFocus
                            value={renamingValue}
                            onChange={(e) => setRenamingValue(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') handleCommitRename(ws)
                              else if (e.key === 'Escape') setRenamingWsId(null)
                            }}
                            className="h-7 flex-1 border px-2 text-[13px] font-normal outline-none"
                            style={{
                              background: 'var(--color-surface-card)',
                              borderColor: 'var(--color-hairline-strong)',
                              borderRadius: 'var(--radius-sm)',
                              color: 'var(--color-ink)',
                            }}
                          />
                          <button
                            onClick={() => handleCommitRename(ws)}
                            className="p-1"
                            style={{ color: 'var(--color-semantic-success)' }}
                            title={t.saveBtn}
                          >
                            <Check className="h-3.5 w-3.5" />
                          </button>
                          <button
                            onClick={() => setRenamingWsId(null)}
                            className="p-1"
                            style={{ color: 'var(--color-muted)' }}
                            title={t.cancelBtn}
                          >
                            <X className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      ) : (
                        <>
                          <span className="flex min-w-0 items-center gap-1.5">
                            {isPinned ? (
                              <Pin
                                className="h-3 w-3 shrink-0"
                                style={{ color: 'var(--color-ink)' }}
                              />
                            ) : (
                              <Folder
                                className="h-3.5 w-3.5 shrink-0"
                                style={{ color: 'var(--color-muted)' }}
                              />
                            )}
                            <span className="truncate">{ws.name}</span>
                            {isRunning && (
                              <span
                                className="shrink-0 font-mono text-[11px]"
                                style={{ color: 'var(--color-muted)' }}
                                title={t.backgroundRunningTooltip}
                              >
                                …
                              </span>
                            )}
                          </span>
                          <div className="flex shrink-0 items-center gap-0.5">
                            {relAge && (
                              <span
                                className="font-mono text-[11px] group-hover:hidden"
                                style={{ color: 'var(--color-muted)' }}
                              >
                                {relAge}
                              </span>
                            )}
                            <div className="hidden items-center gap-0.5 group-hover:flex">
                              <button
                                onClick={(e) => {
                                  e.stopPropagation()
                                  handleTogglePinSession(ws)
                                }}
                                className="p-1"
                                style={{ color: isPinned ? 'var(--color-ink)' : 'var(--color-muted)' }}
                                title={
                                  isPinned
                                    ? lang === 'vi'
                                      ? 'Bỏ ghim phiên điều tra'
                                      : 'Unpin session'
                                    : lang === 'vi'
                                      ? 'Ghim phiên điều tra lên đầu'
                                      : 'Pin session to top'
                                }
                              >
                                <Pin className="h-3 w-3" />
                              </button>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation()
                                  setConfirmDeleteWsId(null)
                                  setRenamingWsId(ws.id)
                                  setRenamingValue(ws.name)
                                }}
                                className="p-1"
                                style={{ color: 'var(--color-muted)' }}
                                title={t.renameTooltip}
                              >
                                <Pencil className="h-3 w-3" />
                              </button>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation()
                                  setRenamingWsId(null)
                                  setConfirmDeleteWsId(ws.id)
                                }}
                                className="p-1"
                                style={{ color: 'var(--color-muted)' }}
                                title={t.deleteTooltip}
                              >
                                <Trash2 className="h-3 w-3" />
                              </button>
                            </div>
                          </div>
                        </>
                      )}
                    </div>
                    {sessionFilter.trim() && ws.search_summary && !isRenaming && (
                      <div
                        className="truncate text-[11px] font-normal"
                        style={{ color: 'var(--color-muted)' }}
                        title={ws.search_summary}
                      >
                        {ws.search_summary}
                      </div>
                    )}

                    {isConfirmDelete && (
                      <div
                        className="flex items-center justify-end gap-2 border-t pt-1.5"
                        style={{ borderColor: 'var(--color-hairline)' }}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <button
                          onClick={() => setConfirmDeleteWsId(null)}
                          className="text-[12px]"
                          style={{ color: 'var(--color-muted)' }}
                        >
                          {t.cancelBtn}
                        </button>
                        <button
                          onClick={() => handleConfirmDeleteSession(ws)}
                          className="px-2 py-0.5 text-[12px] font-medium"
                          style={{
                            background: 'var(--color-semantic-error)',
                            color: 'var(--color-on-primary)',
                            borderRadius: 'var(--radius-xs)',
                          }}
                        >
                          {t.confirmDeleteBtn}
                        </button>
                      </div>
                    )}
                  </div>
                )
              })
            )}
          </div>

          {/* Antigravity Settings Footer */}
          <div
            className="space-y-1.5 border-t pt-2.5 text-[12px]"
            style={{ borderColor: 'var(--color-hairline)', color: 'var(--color-muted)' }}
          >
            <button
              onClick={() => setHubOpen(true)}
              className="agy-nav-row flex h-8 w-full items-center justify-between gap-2 px-2 text-[13px]"
              style={{ color: 'var(--color-body)', borderRadius: 'var(--radius-sm)' }}
            >
              <span className="flex min-w-0 items-center gap-2">
                <Settings className="h-3.5 w-3.5 shrink-0" style={{ color: 'var(--color-muted)' }} />
                <span className="truncate">{lang === 'vi' ? 'Cài đặt (Settings)' : 'Settings'}</span>
              </span>
              <span className="shrink-0 font-mono text-[11px]" style={{ color: 'var(--color-muted)' }}>
                {searxPlugin?.health.detail.includes('SearXNG') ? 'SearXNG' : 'ddgs'}
              </span>
            </button>
          </div>
        </div>
      </aside>

      {/* Main Center Stage (Regions 2 & 3: Chat Frame + Pipeline Timeline) */}
      <main
        className="relative flex min-w-0 flex-1 flex-col border-l"
        style={{ background: 'var(--color-canvas)', borderColor: 'var(--color-hairline)' }}
      >
        {/* Top Bar (Antigravity Breadcrumb Header: Dupin / <Workspace Name>) */}
        <header
          className="app-chrome flex h-12 shrink-0 items-center justify-between border-b px-4"
          style={{ borderColor: 'var(--color-hairline)', background: 'var(--color-canvas)' }}
        >
          <div className="flex min-w-0 items-center gap-2">
            {!sidebarOpen && (
              <button
                onClick={() => setSidebarOpen(true)}
                className="agy-menu-item grid h-7 w-7 shrink-0 place-items-center"
                style={{ color: 'var(--color-body)', borderRadius: 'var(--radius-sm)' }}
                title={t.toggleSidebarTooltip}
              >
                <PanelLeftOpen className="h-4 w-4" />
              </button>
            )}
            <div className="flex min-w-0 items-center gap-1.5 text-[13px]">
              <span className="font-medium" style={{ color: 'var(--color-muted)' }}>
                Dupin
              </span>
              <span style={{ color: 'var(--color-muted-soft)' }}>/</span>
              <h1 className="truncate font-medium" style={{ color: 'var(--color-ink)' }}>
                {activeWs?.name || 'Investigation'}
              </h1>
            </div>
            {activeWs && (
              <button
                onClick={() => handleTogglePinSession(activeWs)}
                className="agy-menu-item inline-flex h-6 items-center gap-1 border px-1.5 text-[11px]"
                style={{
                  background: activeWs.pinned ? 'var(--color-surface-strong)' : 'var(--color-surface-card)',
                  borderColor: 'var(--color-hairline)',
                  borderRadius: 'var(--radius-xs)',
                  color: activeWs.pinned ? 'var(--color-ink)' : 'var(--color-muted)',
                }}
                title={
                  activeWs.pinned
                    ? lang === 'vi'
                      ? 'Đã ghim phiên điều tra — bấm để bỏ ghim'
                      : 'Session pinned — click to unpin'
                    : lang === 'vi'
                      ? 'Ghim phiên điều tra này lên đầu'
                      : 'Pin this session to top'
                }
              >
                <Pin className="h-2.5 w-2.5" />
                <span className="hidden sm:inline">
                  {activeWs.pinned
                    ? lang === 'vi'
                      ? 'Đã ghim'
                      : 'Pinned'
                    : lang === 'vi'
                      ? 'Ghim'
                      : 'Pin'}
                </span>
              </button>
            )}
            {(graphSnapshot || latestAssistantPayload?.graph_stats) && (
              <button
                onClick={async () => {
                  if (activeWsId) {
                    api
                      .getGraphSnapshot(activeWsId)
                      .then((g) => setGraphSnapshot(g))
                      .catch(() => undefined)
                  }
                  setGraphPopupOpen(true)
                }}
                className="agy-menu-item hidden h-6 items-center gap-1 border px-2 font-mono text-[11px] sm:inline-flex"
                style={{
                  background: 'var(--color-surface-card)',
                  borderColor: 'var(--color-hairline)',
                  borderRadius: 'var(--radius-xs)',
                  color: 'var(--color-body)',
                }}
                title={
                  lang === 'vi'
                    ? 'Bấm để xem chi tiết từng Thực thể và Liên kết kèm dẫn chứng trong Đồ thị Tri thức'
                    : 'Click to inspect every Entity and Link with evidence in the Knowledge Graph'
                }
              >
                <span>
                  {t.entitiesEdges(
                    graphSnapshot?.nodes.length ?? latestAssistantPayload?.graph_stats?.nodes ?? 0,
                    graphSnapshot?.edges.length ?? latestAssistantPayload?.graph_stats?.edges ?? 0,
                  )}
                </span>
                <ChevronDown className="h-3 w-3" style={{ color: 'var(--color-muted)' }} />
              </button>
            )}
          </div>
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setLang((l) => (l === 'vi' ? 'en' : 'vi'))}
              className="btn-secondary inline-flex h-7 items-center gap-1 px-2 font-mono text-[11px]"
              title={t.switchLangTooltip}
            >
              <Globe className="h-3 w-3" style={{ color: 'var(--color-muted)' }} />
              <span>{lang === 'vi' ? 'VI' : 'EN'}</span>
            </button>
            <button
              onClick={() => setHubOpen(true)}
              className="btn-secondary inline-flex h-7 items-center gap-1 px-2.5 text-[12px]"
            >
              <Plug className="h-3 w-3" style={{ color: 'var(--color-muted)' }} />
              <span className="hidden md:inline">{t.integrationsBtn}</span>
            </button>
            <button
              onClick={() => setRightOpen((o) => !o)}
              className="inline-flex h-7 items-center gap-1.5 border px-2.5 text-[12px] font-medium transition-colors"
              style={{
                background: rightOpen ? 'var(--color-surface-strong)' : 'var(--color-surface-card)',
                borderColor: 'var(--color-hairline-strong)',
                color: 'var(--color-ink)',
                borderRadius: 'var(--radius-md)',
              }}
            >
              {rightOpen ? <PanelRightClose className="h-3.5 w-3.5" /> : <PanelRightOpen className="h-3.5 w-3.5" />}
              <span className="hidden sm:inline">{t.dossierToggleBtn(dossierItems.length)}</span>
            </button>
          </div>
        </header>

        {/* Scrollable Chat Stream (max-w-[760px] editorial column) */}
        <div className="flex-1 overflow-y-auto px-6 py-8">
          <div className="mx-auto flex w-full max-w-[760px] flex-col gap-8">
            {messages.length === 0 && !sending && (
              <div className="py-10">
                <h2 className="display-heading text-[26px] leading-[1.25]">{t.heroTitle}</h2>
                <p
                  className="mt-3 max-w-[640px] text-[16px] leading-[1.5]"
                  style={{ color: 'var(--color-body)' }}
                >
                  {t.heroLeadBeforeCode}
                  <code
                    className="border px-1.5 py-0.5 font-mono text-[13px]"
                    style={{
                      background: 'var(--color-canvas-soft)',
                      borderColor: 'var(--color-hairline)',
                      borderRadius: 'var(--radius-xs)',
                      color: 'var(--color-ink)',
                    }}
                  >
                    {t.heroLeadCode}
                  </code>
                  {t.heroLeadAfterCode}
                </p>
                <div className="mt-8 grid grid-cols-1 gap-3 sm:grid-cols-2">
                  {t.quickPrompts.map(([title, sample]) => (
                    <button
                      key={title}
                      onClick={() => {
                        setPrompt(sample)
                        composerRef.current?.focus()
                      }}
                      className="border p-4 text-left transition-colors"
                      style={{
                        background: 'var(--color-surface-card)',
                        borderColor: 'var(--color-hairline)',
                        borderRadius: 'var(--radius-lg)',
                      }}
                    >
                      <div className="text-[14px] font-medium" style={{ color: 'var(--color-ink)' }}>
                        {title}
                      </div>
                      <div
                        className="mt-1.5 line-clamp-2 font-mono text-[13px] leading-[1.5]"
                        style={{ color: 'var(--color-muted)' }}
                      >
                        {sample}
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((msg, idx) => {
              if (msg.role === 'user') {
                const previewImgUrl = msg.payload?.image_preview_url
                return (
                  <div key={idx} className="flex justify-start">
                    <div
                      className="w-fit max-w-[640px] space-y-2 border px-4 py-3 text-[15px] leading-[1.5]"
                      style={{
                        background: 'var(--color-surface-card)',
                        borderColor: 'var(--color-hairline)',
                        borderRadius: 'var(--radius-lg)',
                        color: 'var(--color-ink)',
                      }}
                    >
                      {previewImgUrl && (
                        <a
                          href={previewImgUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="block w-fit overflow-hidden border"
                          style={{
                            borderColor: 'var(--color-hairline-strong)',
                            borderRadius: 'var(--radius-md)',
                          }}
                        >
                          <img
                            src={previewImgUrl}
                            alt="Uploaded evidence"
                            className="max-h-40 max-w-[260px] object-cover"
                          />
                        </a>
                      )}
                      <div className="whitespace-pre-wrap break-words">{msg.content}</div>
                    </div>
                  </div>
                )
              }

              const payload = msg.payload
              const p = payload?.parsed_clues
              const tele = payload?.pipeline_telemetry
              const gate = tele?.gatekeeper
              const totalMs = tele?.layer_timings_ms?.total_ms
              const markdownText = payload?.assistant_reply || msg.content

              const pipelineSummaryRows: Array<{
                label: string
                pillClass: PipelinePillStage['pillClass']
                text: string
              }> = []
              if (tele) {
                const intakeDesc = [
                  p?.target_name ? `${t.clueTarget}: ${p.target_name}` : '',
                  p?.birth_date ? `${t.clueDob}: ${p.birth_date}` : '',
                  ...(p?.organizations || []).map((o) => `${t.clueOrg}: ${o}`),
                ]
                  .filter(Boolean)
                  .join(' · ')
                pipelineSummaryRows.push({
                  label: 'L1 Intake',
                  pillClass: 'timeline-pill-read',
                  text: intakeDesc || t.pipelineTelemetryLabel,
                })
                if (gate && gate.total_inspected > 0) {
                  const reasons = Object.entries(gate.rejected_by_reason || {})
                    .slice(0, 3)
                    .map(([reason, count]) => `${t.rejectReasons[reason] || reason}: ${count}`)
                    .join(', ')
                  pipelineSummaryRows.push({
                    label: 'L2 Shield',
                    pillClass: 'timeline-pill-grep',
                    text: `${t.l2ShieldLabel(gate.rejected, gate.total_inspected)}${reasons ? ` (${reasons})` : ''}`,
                  })
                }
                const searchSteps = (payload?.reasoning_steps || []).filter((s) =>
                  s.action.includes('REACT_ROUND'),
                )
                if (searchSteps.length > 0) {
                  pipelineSummaryRows.push({
                    label: 'L3 SearXNG',
                    pillClass: 'timeline-pill-thinking',
                    text: `${searchSteps.length} truy vấn tìm kiếm đa nguồn (${payload?.discovered_sources?.length || 0} nguồn giữ lại)`,
                  })
                }
                const coreSteps = (payload?.reasoning_steps || []).filter(
                  (s) => s.action.includes('MCTS') || s.action.includes('READER') || s.action.includes('CRITIC'),
                )
                if (coreSteps.length > 0) {
                  pipelineSummaryRows.push({
                    label: 'L4 Core',
                    pillClass: 'timeline-pill-edit',
                    text: coreSteps[coreSteps.length - 1].detail.slice(0, 110),
                  })
                }
                pipelineSummaryRows.push({
                  label: 'Done',
                  pillClass: 'timeline-pill-done',
                  text:
                    typeof totalMs === 'number'
                      ? `${t.pipelineTelemetryLabel} · ${(totalMs / 1000).toFixed(1)}s`
                      : t.pipelineTelemetryLabel,
                })
              }

              return (
                <div key={idx} className="flex flex-col gap-5">
                  {/* Metadata & Copy Row */}
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex flex-wrap items-center gap-1.5">
                      {p?.target_name && (
                        <span
                          className="border px-2 py-0.5 font-mono text-[12px]"
                          style={{
                            background: 'var(--color-canvas-soft)',
                            borderColor: 'var(--color-hairline)',
                            borderRadius: 'var(--radius-sm)',
                            color: 'var(--color-ink)',
                          }}
                        >
                          {t.clueTarget}: {p.target_name}
                        </span>
                      )}
                      {p?.birth_date && (
                        <span
                          className="border px-2 py-0.5 font-mono text-[12px]"
                          style={{
                            background: 'var(--color-canvas-soft)',
                            borderColor: 'var(--color-hairline)',
                            borderRadius: 'var(--radius-sm)',
                            color: 'var(--color-body)',
                          }}
                        >
                          {t.clueDob}: {p.birth_date}
                        </span>
                      )}
                      {(p?.organizations || []).map((o) => (
                        <span
                          key={o}
                          className="border px-2 py-0.5 font-mono text-[12px]"
                          style={{
                            background: 'var(--color-canvas-soft)',
                            borderColor: 'var(--color-hairline)',
                            borderRadius: 'var(--radius-sm)',
                            color: 'var(--color-body)',
                          }}
                        >
                          {t.clueOrg}: {o}
                        </span>
                      ))}
                      {(p?.related_people || []).map((rp) => (
                        <span
                          key={`${rp.relation}-${rp.name}`}
                          className="border px-2 py-0.5 font-mono text-[12px]"
                          style={{
                            background: 'var(--color-canvas-soft)',
                            borderColor: 'var(--color-hairline-strong)',
                            borderRadius: 'var(--radius-sm)',
                            color: 'var(--color-ink)',
                          }}
                        >
                          {t.clueRelation} ({rp.relation}): {rp.name}
                        </span>
                      ))}
                      {(payload?.learned_negative_keywords || []).map((n) => (
                        <span
                          key={n}
                          className="border px-2 py-0.5 font-mono text-[12px]"
                          style={{
                            background: 'var(--color-canvas-soft)',
                            borderColor: 'var(--color-hairline)',
                            borderRadius: 'var(--radius-sm)',
                            color: 'var(--color-semantic-error)',
                          }}
                        >
                          {t.clueExclude}: -{n}
                        </span>
                      ))}
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      <button
                        onClick={() =>
                          handlePinExcerptToDossier(
                            lang === 'vi'
                              ? `Đoạn điều tra đã ghim (${p?.target_name || 'OSINT'})`
                              : `Pinned Investigation Excerpt (${p?.target_name || 'OSINT'})`,
                            markdownText,
                          )
                        }
                        className="inline-flex items-center gap-1 border px-2 py-1 text-[11px] transition-colors"
                        style={{
                          background: 'var(--color-surface-card)',
                          borderColor: 'var(--color-hairline)',
                          borderRadius: 'var(--radius-xs)',
                          color: 'var(--color-body)',
                        }}
                        title={
                          lang === 'vi'
                            ? 'Ghim đoạn phân tích điều tra này vào Hồ sơ đã xác nhận'
                            : 'Pin this investigation summary to Verified Dossier'
                        }
                      >
                        <Pin className="h-3 w-3" />
                        <span>{lang === 'vi' ? 'Ghim đoạn' : 'Pin excerpt'}</span>
                      </button>
                      <button
                        onClick={() => handleCopyText(markdownText)}
                        className="shrink-0 p-1.5 text-[12px] transition-colors"
                        style={{ color: 'var(--color-muted)' }}
                        title={t.copyReportTooltip}
                      >
                        <Copy className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>

                  {/* Region 3: Pipeline Progress Timeline (Pastel Pills ONLY here, 1 step per row, no dots) */}
                  {pipelineSummaryRows.length > 0 && (
                    <div
                      className="space-y-2 border p-4"
                      style={{
                        background: 'var(--color-surface-card)',
                        borderColor: 'var(--color-hairline)',
                        borderRadius: 'var(--radius-lg)',
                      }}
                    >
                      {pipelineSummaryRows.map((row, ri) => (
                        <div key={ri} className="flex items-center gap-3">
                          <span className={`timeline-pill ${row.pillClass}`}>{row.label}</span>
                          <span className="min-w-0 truncate text-[13px]" style={{ color: 'var(--color-body)' }}>
                            {row.text}
                          </span>
                        </div>
                      ))}

                      {tele?.investigation_tree?.activated && tele.investigation_tree.nodes.length > 0 && (
                        <details
                          className="border-t pt-2.5"
                          style={{ borderColor: 'var(--color-hairline-soft)' }}
                        >
                          <summary
                            className="flex cursor-pointer list-none items-center gap-1.5 text-[13px] font-medium"
                            style={{ color: 'var(--color-ink)' }}
                          >
                            <ChevronRight className="h-3.5 w-3.5" style={{ color: 'var(--color-muted)' }} />
                            <span>
                              {lang === 'vi'
                                ? `Cây quyết định Chia-để-trị (${tele.investigation_tree.total_branches} nhánh · ${tele.investigation_tree.backtracked_count} quay lui · ${tele.investigation_tree.pruned_count} cắt tỉa)`
                                : `Divide-and-Conquer Decision Tree (${tele.investigation_tree.total_branches} branches · ${tele.investigation_tree.backtracked_count} backtracked · ${tele.investigation_tree.pruned_count} pruned)`}
                            </span>
                          </summary>
                          <div className="mt-3 space-y-1.5">
                            {tele.investigation_tree.nodes.map((node) => {
                              const statusColor =
                                node.status === 'CONFIRMED'
                                  ? 'var(--color-semantic-success)'
                                  : node.status.startsWith('PRUNED') || node.status === 'DEAD_END_BACKTRACKED'
                                    ? 'var(--color-semantic-error)'
                                    : 'var(--color-muted)'
                              return (
                                <div
                                  key={node.branch_id}
                                  className="flex flex-wrap items-center gap-2 border-l py-1 pl-2.5 text-[12px]"
                                  style={{
                                    marginLeft: `${Math.min(node.depth, 3) * 16}px`,
                                    borderColor: 'var(--color-hairline-strong)',
                                  }}
                                >
                                  <span className="font-mono text-[11px]" style={{ color: 'var(--color-muted)' }}>
                                    {node.branch_id}
                                  </span>
                                  <span
                                    className="border px-1.5 py-0.5 font-mono text-[10px]"
                                    style={{
                                      background: 'var(--color-canvas-soft)',
                                      borderColor: 'var(--color-hairline)',
                                      borderRadius: 'var(--radius-xs)',
                                      color: statusColor,
                                    }}
                                  >
                                    {node.status}
                                  </span>
                                  <span className="font-medium" style={{ color: 'var(--color-ink)' }}>
                                    {node.label}
                                  </span>
                                  <span className="font-mono text-[11px]" style={{ color: 'var(--color-muted)' }}>
                                    ({node.score.toFixed(1)})
                                  </span>
                                  {node.conflict_reason && (
                                    <span className="text-[11px]" style={{ color: 'var(--color-semantic-error)' }}>
                                      — {node.conflict_reason}
                                    </span>
                                  )}
                                </div>
                              )
                            })}
                          </div>
                        </details>
                      )}

                      {payload?.reasoning_steps && payload.reasoning_steps.length > 0 && (
                        <details
                          className="border-t pt-2.5"
                          style={{ borderColor: 'var(--color-hairline-soft)' }}
                        >
                          <summary
                            className="flex cursor-pointer list-none items-center gap-1.5 text-[13px] font-medium"
                            style={{ color: 'var(--color-muted)' }}
                          >
                            <ChevronRight className="h-3.5 w-3.5" />
                            <span>{t.reasoningTraceTitle(payload.reasoning_steps.length)}</span>
                          </summary>
                          <div className="mt-3 space-y-2">
                            {payload.reasoning_steps.map((s, si) => {
                              const st = classifyPipelineStage(`${s.agent} ${s.action} ${s.detail}`)
                              return (
                                <div key={si} className="flex items-start gap-2.5">
                                  <span className={`timeline-pill ${st.pillClass}`}>{st.label}</span>
                                  <span
                                    className="min-w-0 font-mono text-[12px] leading-[1.5] break-words"
                                    style={{ color: 'var(--color-body)' }}
                                  >
                                    {s.detail}
                                  </span>
                                </div>
                              )
                            })}
                          </div>
                        </details>
                      )}
                    </div>
                  )}

                  {/* Flat AI Prose on Canvas (16px / 1.5, max-w-760px, no card/bubble) */}
                  <div className="md-prose">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdownText}</ReactMarkdown>
                  </div>

                  {/* Human-in-the-Loop Disambiguation / Co-Steer */}
                  {payload?.disambiguation_cards && payload.disambiguation_cards.length > 0 && (
                    <div className="space-y-2.5">
                      <div className="caption-uppercase flex items-center gap-1.5">
                        <AlertCircle className="h-3.5 w-3.5" />
                        <span>{t.coSteerTitle}</span>
                      </div>
                      <div className="space-y-2">
                        {payload.disambiguation_cards.map((card, ci) => (
                          <div
                            key={ci}
                            className="flex flex-col justify-between gap-2.5 border p-3.5 sm:flex-row sm:items-center"
                            style={{
                              background: 'var(--color-surface-card)',
                              borderColor: 'var(--color-hairline)',
                              borderRadius: 'var(--radius-lg)',
                            }}
                          >
                            <div className="min-w-0">
                              <div className="truncate text-[14px] font-medium" style={{ color: 'var(--color-ink)' }}>
                                {card.title}
                              </div>
                              <div className="mt-0.5 text-[13px]" style={{ color: 'var(--color-muted)' }}>
                                {card.reason}
                              </div>
                            </div>
                            <div className="flex shrink-0 items-center gap-2">
                              {card.suggested_negative && (
                                <button
                                  onClick={() => handleSend(`-${card.suggested_negative}`)}
                                  className="inline-flex h-8 items-center gap-1 border px-2.5 text-[13px] font-medium"
                                  style={{
                                    background: 'var(--color-surface-card)',
                                    borderColor: 'var(--color-hairline)',
                                    borderRadius: 'var(--radius-md)',
                                    color: 'var(--color-semantic-error)',
                                  }}
                                >
                                  <Ban className="h-3 w-3" />
                                  <span>{t.excludeAction(card.suggested_negative)}</span>
                                </button>
                              )}
                              <button
                                onClick={() =>
                                  handlePinSource({
                                    title: card.title,
                                    url: card.url,
                                    snippet: card.snippet,
                                    match_score: 2,
                                  })
                                }
                                disabled={pinnedUrlSet.has(normalizeUrl(card.url))}
                                className="btn-secondary inline-flex h-8 items-center gap-1 px-2.5 text-[13px] disabled:opacity-50"
                              >
                                <BookmarkCheck
                                  className="h-3.5 w-3.5"
                                  style={{ color: 'var(--color-semantic-success)' }}
                                />
                                <span>
                                  {pinnedUrlSet.has(normalizeUrl(card.url)) ? t.pinnedBadge : t.confirmTargetAction}
                                </span>
                              </button>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Discovered Public Sources */}
                  {payload?.discovered_sources && payload.discovered_sources.length > 0 && (
                    <div className="space-y-2.5">
                      <div className="caption-uppercase">
                        {t.discoveredSourcesTitle(payload.discovered_sources.length)}
                      </div>
                      <div className="space-y-2">
                        {payload.discovered_sources.map((src, si) => {
                          const normSrcUrl = normalizeUrl(src.url)
                          const isPinned = pinnedUrlSet.has(normSrcUrl)
                          const isRejected = rejectedUrlSet.has(normSrcUrl)
                          const domain = extractDomain(src.url)
                          return (
                            <div
                              key={si}
                              className="flex flex-col justify-between gap-3 border p-4 transition-opacity sm:flex-row sm:items-start"
                              style={{
                                background: 'var(--color-surface-card)',
                                borderColor: 'var(--color-hairline)',
                                borderRadius: 'var(--radius-lg)',
                                opacity: isRejected ? 0.45 : 1,
                              }}
                            >
                              <div className="min-w-0 flex-1">
                                <div className="flex flex-wrap items-center gap-2">
                                  {safeExternalUrl(src.url) ? (
                                    <a
                                      href={safeExternalUrl(src.url)!}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className={`inline-flex items-center gap-1 text-[14px] font-medium hover:underline ${
                                        isRejected ? 'line-through' : ''
                                      }`}
                                      style={{ color: 'var(--color-ink)' }}
                                    >
                                      <span>{src.title || src.url}</span>
                                      <ExternalLink className="h-3.5 w-3.5 shrink-0" style={{ color: 'var(--color-muted)' }} />
                                    </a>
                                  ) : (
                                    <span
                                      className={`text-[14px] font-medium ${isRejected ? 'line-through' : ''}`}
                                      style={{ color: 'var(--color-ink)' }}
                                    >
                                      {src.title || src.url}
                                    </span>
                                  )}
                                  {domain && (
                                    <span className="font-mono text-[12px]" style={{ color: 'var(--color-muted)' }}>
                                      {domain}
                                    </span>
                                  )}
                                  {isRejected && (
                                    <span
                                      className="border px-1.5 py-0.5 font-mono text-[11px]"
                                      style={{
                                        background: 'var(--color-canvas-soft)',
                                        borderColor: 'var(--color-hairline)',
                                        borderRadius: 'var(--radius-xs)',
                                        color: 'var(--color-semantic-error)',
                                      }}
                                    >
                                      {lang === 'vi' ? 'Đã loại bỏ' : 'Dismissed'}
                                    </span>
                                  )}
                                  {!isRejected && src.match_score > 0 && (
                                    <span
                                      className="border px-1.5 py-0.5 font-mono text-[11px]"
                                      style={{
                                        background: 'var(--color-canvas-soft)',
                                        borderColor: 'var(--color-hairline)',
                                        borderRadius: 'var(--radius-xs)',
                                        color: src.match_score >= 5 ? 'var(--color-semantic-success)' : 'var(--color-body)',
                                      }}
                                    >
                                      {t.matchScoreBadge(src.match_score)}
                                    </span>
                                  )}
                                  {!isRejected && src.deep_inspected && (
                                    <span
                                      className="border px-1.5 py-0.5 font-mono text-[11px]"
                                      style={{
                                        background: 'var(--color-canvas-soft)',
                                        borderColor: 'var(--color-hairline)',
                                        borderRadius: 'var(--radius-xs)',
                                        color: 'var(--color-semantic-success)',
                                      }}
                                    >
                                      {t.pdfDeepBadge}
                                    </span>
                                  )}
                                </div>
                                <p className="mt-1.5 text-[14px] leading-[1.5]" style={{ color: 'var(--color-body)' }}>
                                  {src.snippet}
                                </p>
                                {src.pdf_excerpts && src.pdf_excerpts.length > 0 && (
                                  <div
                                    className="mt-2 border px-3 py-2 font-mono text-[13px]"
                                    style={{
                                      background: 'var(--color-canvas-soft)',
                                      borderColor: 'var(--color-hairline)',
                                      borderRadius: 'var(--radius-md)',
                                      color: 'var(--color-ink)',
                                    }}
                                  >
                                    {t.pageLabel(src.pdf_excerpts[0].page || 1)}: {src.pdf_excerpts[0].line}
                                  </div>
                                )}
                              </div>
                              <div className="flex shrink-0 items-center gap-1.5">
                                <button
                                  onClick={() => {
                                    setInspectedSource(src)
                                    setRightOpen(true)
                                    setRightTab('inspector')
                                  }}
                                  className="btn-secondary inline-flex h-8 items-center gap-1 px-2.5 text-[13px]"
                                >
                                  <Eye className="h-3.5 w-3.5" style={{ color: 'var(--color-muted)' }} />
                                  <span>{t.inspectCitationBtn}</span>
                                </button>
                                <button
                                  disabled={isPinned}
                                  onClick={() => handlePinSource(src)}
                                  className="inline-flex h-8 items-center gap-1 border px-2.5 text-[13px] font-medium"
                                  style={
                                    isPinned
                                      ? {
                                          background: 'var(--color-canvas-soft)',
                                          borderColor: 'var(--color-hairline)',
                                          borderRadius: 'var(--radius-md)',
                                          color: 'var(--color-semantic-success)',
                                          cursor: 'default',
                                        }
                                      : {
                                          background: 'var(--color-surface-card)',
                                          borderColor: 'var(--color-hairline-strong)',
                                          borderRadius: 'var(--radius-md)',
                                          color: 'var(--color-ink)',
                                        }
                                  }
                                  title={
                                    lang === 'vi'
                                      ? 'Xác nhận hữu ích & lưu vào Hồ sơ'
                                      : 'Confirm useful & pin to Dossier'
                                  }
                                >
                                  {isPinned ? <Check className="h-3.5 w-3.5" /> : <ThumbsUp className="h-3.5 w-3.5" />}
                                  <span>{isPinned ? t.savedBadge : t.saveToDossierBtn}</span>
                                </button>
                                <button
                                  onClick={() => handleToggleRejectSource(src)}
                                  className="inline-flex h-8 items-center gap-1 border px-2 text-[12px] font-medium transition-colors"
                                  style={
                                    isRejected
                                      ? {
                                          background: 'var(--color-canvas-soft)',
                                          borderColor: 'var(--color-hairline)',
                                          borderRadius: 'var(--radius-md)',
                                          color: 'var(--color-semantic-error)',
                                        }
                                      : {
                                          background: 'var(--color-surface-card)',
                                          borderColor: 'var(--color-hairline)',
                                          borderRadius: 'var(--radius-md)',
                                          color: 'var(--color-muted)',
                                        }
                                  }
                                  title={
                                    isRejected
                                      ? lang === 'vi'
                                        ? 'Đã đánh dấu không đúng — bấm để hoàn tác'
                                        : 'Marked irrelevant — click to undo'
                                      : lang === 'vi'
                                        ? 'Đánh dấu không đúng / Không hữu ích (lượt sau sẽ không bao giờ hiện lại)'
                                        : 'Mark irrelevant / Not useful (permanently excluded from future turns)'
                                  }
                                >
                                  <ThumbsDown className="h-3.5 w-3.5" />
                                  <span className="hidden md:inline">
                                    {isRejected
                                      ? lang === 'vi'
                                        ? 'Đã loại'
                                        : 'Excluded'
                                      : lang === 'vi'
                                        ? 'Không đúng'
                                        : 'Not right'}
                                  </span>
                                </button>
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}

                  {/* Suggested Queries: 1 query/row, JetBrains Mono 13px, canvas-soft, 8px radius, hover-only text actions */}
                  {payload?.suggested_dorks && payload.suggested_dorks.length > 0 && (
                    <div className="space-y-2">
                      <div className="caption-uppercase">{t.suggestedDorksTitle}</div>
                      <div className="space-y-1.5">
                        {payload.suggested_dorks.map((d, di) => (
                          <div
                            key={di}
                            className="group flex items-center justify-between gap-3 border px-3 py-2"
                            style={{
                              background: 'var(--color-canvas-soft)',
                              borderColor: 'var(--color-hairline)',
                              borderRadius: 'var(--radius-md)',
                            }}
                          >
                            <code
                              className="min-w-0 truncate font-mono text-[13px] leading-[1.5]"
                              style={{ color: 'var(--color-ink)' }}
                            >
                              {d.query}
                            </code>
                            <div className="flex shrink-0 items-center gap-3 opacity-0 transition-opacity group-hover:opacity-100">
                              <button
                                onClick={() => handleCopyText(d.query)}
                                className="text-[13px] font-medium hover:underline"
                                style={{ color: 'var(--color-ink)' }}
                                title={t.copyDorkTooltip}
                              >
                                Copy
                              </button>
                              <a
                                href={`https://www.google.com/search?udm=50&q=${encodeURIComponent(d.query)}`}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-[13px] font-medium hover:underline"
                                style={{ color: 'var(--color-ink)' }}
                              >
                                Google AI
                              </a>
                              <a
                                href={`https://www.google.com/search?q=${encodeURIComponent(d.query)}`}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-[13px] font-medium hover:underline"
                                style={{ color: 'var(--color-ink)' }}
                              >
                                Google
                              </a>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Action Footer Row (`Sao chép`, `Ghim vào Hồ sơ`, elapsed time) */}
                  <div className="flex flex-wrap items-center gap-2 px-1 pt-1 text-[12px]" style={{ color: 'var(--color-muted)' }}>
                    <button
                      onClick={() => handleCopyText(markdownText)}
                      className="agy-menu-item inline-flex items-center gap-1.5 border px-2.5 py-1 text-[12px]"
                      style={{
                        background: 'var(--color-surface-card)',
                        borderColor: 'var(--color-hairline)',
                        borderRadius: 'var(--radius-sm)',
                        color: 'var(--color-body)',
                      }}
                      title={t.copyReportTooltip}
                    >
                      <Copy className="h-3.5 w-3.5" />
                      <span>{lang === 'vi' ? 'Sao chép báo cáo' : 'Copy report'}</span>
                    </button>
                    <button
                      onClick={() =>
                        handlePinExcerptToDossier(
                          lang === 'vi'
                            ? `Đoạn điều tra đã ghim (${p?.target_name || 'OSINT'})`
                            : `Pinned Investigation Excerpt (${p?.target_name || 'OSINT'})`,
                          markdownText,
                        )
                      }
                      className="agy-menu-item inline-flex items-center gap-1.5 border px-2.5 py-1 text-[12px]"
                      style={{
                        background: 'var(--color-surface-card)',
                        borderColor: 'var(--color-hairline)',
                        borderRadius: 'var(--radius-sm)',
                        color: 'var(--color-body)',
                      }}
                      title={
                        lang === 'vi'
                          ? 'Ghim đoạn phân tích điều tra này vào Hồ sơ đã xác nhận'
                          : 'Pin this investigation summary to Verified Dossier'
                      }
                    >
                      <Pin className="h-3.5 w-3.5" />
                      <span>{lang === 'vi' ? 'Ghim vào Hồ sơ' : 'Pin to Dossier'}</span>
                    </button>
                    {typeof totalMs === 'number' && (
                      <span className="ml-1 font-mono text-[11px]" style={{ color: 'var(--color-muted)' }}>
                        {(totalMs / 1000).toFixed(1)}s
                      </span>
                    )}
                  </div>
                </div>
              )
            })}

            {/* Live Pipeline Stream Progress (Pastel Pills ONLY, 1 step per line, NO dots) */}
            {streamLines.length > 0 && (
              <div
                className="space-y-2 border p-4"
                style={{
                  background: 'var(--color-surface-card)',
                  borderColor: 'var(--color-hairline)',
                  borderRadius: 'var(--radius-lg)',
                }}
              >
                {streamLines.map((ln, li) => {
                  const st = classifyPipelineStage(ln)
                  return (
                    <div key={li} className="flex items-center gap-3">
                      <span className={`timeline-pill ${st.pillClass}`}>{st.label}</span>
                      <span className="text-[13px] leading-[1.5]" style={{ color: 'var(--color-body)' }}>
                        {ln}
                      </span>
                    </div>
                  )
                })}
              </div>
            )}

            <div ref={chatEndRef} />
          </div>
        </div>

        {/* Hairline Toast (NO drop shadow) */}
        {toastMsg && (
          <div
            className="pointer-events-none absolute right-6 bottom-32 z-40 border px-3.5 py-2 text-[13px] font-medium"
            style={{
              background: 'var(--color-surface-card)',
              borderColor: 'var(--color-hairline-strong)',
              borderRadius: 'var(--radius-md)',
              color: 'var(--color-ink)',
            }}
          >
            {toastMsg}
          </div>
        )}

        {/* Composer (white card, 1px hairline, Cursor Orange ONLY on primary Send CTA) */}
        <div className="shrink-0 px-6 pb-4 pt-2" style={{ background: 'var(--color-canvas)' }}>
          <div
            className="relative mx-auto flex w-full max-w-[760px] flex-col gap-2 border px-4 py-3"
            style={{
              background: 'var(--color-surface-card)',
              borderColor: 'var(--color-hairline)',
              borderRadius: 'var(--radius-lg)',
            }}
          >
            {/* Context Attachment Previews (Antigravity-style Image Thumbnail + Chips) */}
            {(imgB64 || fileText || geoPoint) && (
              <div className="flex flex-wrap items-end gap-2">
                {imgB64 && (
                  <div
                    className="group relative flex items-center gap-2 border p-1.5"
                    style={{
                      background: 'var(--color-canvas-soft)',
                      borderColor: 'var(--color-hairline-strong)',
                      borderRadius: 'var(--radius-md)',
                    }}
                  >
                    <div className="relative h-14 w-14 shrink-0 overflow-hidden" style={{ borderRadius: 'var(--radius-sm)' }}>
                      <img
                        src={`data:${imgMime || 'image/png'};base64,${imgB64}`}
                        alt={imgName || 'Preview'}
                        className="h-full w-full object-cover"
                      />
                    </div>
                    <div className="flex min-w-0 flex-col gap-0.5 pr-4">
                      <span
                        className="max-w-[180px] truncate text-[12px] font-medium"
                        style={{ color: 'var(--color-ink)' }}
                        title={imgName}
                      >
                        {imgName || 'Screenshot'}
                      </span>
                      {imgExifSummary && (
                        <span
                          className="max-w-[180px] truncate font-mono text-[10px]"
                          style={{ color: 'var(--color-muted)' }}
                          title={imgExifSummary}
                        >
                          {imgExifSummary}
                        </span>
                      )}
                      <div className="flex items-center gap-2 text-[10px]">
                        <a
                          href="https://lens.google.com/"
                          target="_blank"
                          rel="noopener noreferrer"
                          className="font-mono hover:underline"
                          style={{ color: 'var(--color-muted)' }}
                          title="Google Lens Visual Verify"
                        >
                          Lens ↗
                        </a>
                        <a
                          href="https://yandex.com/images/"
                          target="_blank"
                          rel="noopener noreferrer"
                          className="font-mono hover:underline"
                          style={{ color: 'var(--color-muted)' }}
                          title="Yandex Images Visual Verify"
                        >
                          Yandex ↗
                        </a>
                      </div>
                    </div>
                    <button
                      onClick={() => {
                        setImgB64(null)
                        setImgName('')
                        setImgExifSummary('')
                      }}
                      className="absolute top-1 right-1 grid h-4 w-4 place-items-center rounded-full text-[11px] transition-colors"
                      style={{
                        background: 'var(--color-surface-strong)',
                        color: 'var(--color-ink)',
                      }}
                      title={lang === 'vi' ? 'Gỡ ảnh' : 'Remove image'}
                    >
                      ×
                    </button>
                  </div>
                )}
                {fileText && (
                  <span
                    className="inline-flex items-center gap-1.5 border px-2 py-0.5 text-[12px]"
                    style={{
                      background: 'var(--color-canvas-soft)',
                      borderColor: 'var(--color-hairline)',
                      borderRadius: 'var(--radius-sm)',
                      color: 'var(--color-ink)',
                    }}
                  >
                    <span>
                      {t.fileChipPrefix}: {fileName}
                      {fileSummary ? ` (${fileSummary})` : ''}
                    </span>
                    <button
                      onClick={() => {
                        setFileText(null)
                        setFileSummary('')
                      }}
                      style={{ color: 'var(--color-muted)' }}
                    >
                      ×
                    </button>
                  </span>
                )}
                {geoPoint && (
                  <span
                    className="inline-flex items-center gap-1.5 border px-2 py-0.5 text-[12px]"
                    style={{
                      background: 'var(--color-canvas-soft)',
                      borderColor: 'var(--color-hairline)',
                      borderRadius: 'var(--radius-sm)',
                      color: 'var(--color-ink)',
                    }}
                  >
                    {t.mapChipPrefix}: {geoPoint.label} ({geoPoint.lat.toFixed(4)}, {geoPoint.lng.toFixed(4)})
                    <button onClick={() => setGeoPoint(null)} style={{ color: 'var(--color-muted)' }}>
                      ×
                    </button>
                  </span>
                )}
              </div>
            )}

            {/* Inline Multi-Field Structured Bio Form (for users with partial clues across multiple dimensions) */}
            {bioFormOpen && (
              <div
                className="space-y-2 border p-3"
                style={{
                  background: 'var(--color-canvas-soft)',
                  borderColor: 'var(--color-hairline)',
                  borderRadius: 'var(--radius-md)',
                }}
              >
                <div className="flex items-center justify-between">
                  <span className="caption-uppercase">
                    {lang === 'vi'
                      ? 'Biểu mẫu Đa trường (Chỉ cần điền 1 hoặc nhiều ô bất kỳ)'
                      : 'Multi-Field Clue Form (Fill any 1 or more fields)'}
                  </span>
                  <button onClick={() => setBioFormOpen(false)} style={{ color: 'var(--color-muted)' }}>
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                  <input
                    value={bioFields.name}
                    onChange={(e) => setBioFields((f) => ({ ...f, name: e.target.value }))}
                    placeholder={lang === 'vi' ? 'Họ tên / Tên gọi...' : 'Full or partial name...'}
                    className="h-8 border px-2.5 text-[13px] outline-none"
                    style={{
                      background: 'var(--color-surface-card)',
                      borderColor: 'var(--color-hairline)',
                      borderRadius: 'var(--radius-sm)',
                      color: 'var(--color-ink)',
                    }}
                  />
                  <input
                    value={bioFields.phoneOrEmail}
                    onChange={(e) => setBioFields((f) => ({ ...f, phoneOrEmail: e.target.value }))}
                    placeholder={lang === 'vi' ? 'SĐT / Email / Username...' : 'Phone / Email / Handle...'}
                    className="h-8 border px-2.5 font-mono text-[12px] outline-none"
                    style={{
                      background: 'var(--color-surface-card)',
                      borderColor: 'var(--color-hairline)',
                      borderRadius: 'var(--radius-sm)',
                      color: 'var(--color-ink)',
                    }}
                  />
                  <input
                    value={bioFields.idCode}
                    onChange={(e) => setBioFields((f) => ({ ...f, idCode: e.target.value }))}
                    placeholder={lang === 'vi' ? 'MSSV / CCCD / MST / SBD / Biển số...' : 'Student ID / National ID / Tax ID...'}
                    className="h-8 border px-2.5 font-mono text-[12px] outline-none"
                    style={{
                      background: 'var(--color-surface-card)',
                      borderColor: 'var(--color-hairline)',
                      borderRadius: 'var(--radius-sm)',
                      color: 'var(--color-ink)',
                    }}
                  />
                  <input
                    value={bioFields.org}
                    onChange={(e) => setBioFields((f) => ({ ...f, org: e.target.value }))}
                    placeholder={lang === 'vi' ? 'Trường học / Công ty / Khoa...' : 'School / University / Company...'}
                    className="h-8 border px-2.5 text-[13px] outline-none"
                    style={{
                      background: 'var(--color-surface-card)',
                      borderColor: 'var(--color-hairline)',
                      borderRadius: 'var(--radius-sm)',
                      color: 'var(--color-ink)',
                    }}
                  />
                  <input
                    value={bioFields.dob}
                    onChange={(e) => setBioFields((f) => ({ ...f, dob: e.target.value }))}
                    placeholder={lang === 'vi' ? 'Ngày sinh (DD/MM/YYYY) / Năm sinh...' : 'DOB or Birth Year...'}
                    className="h-8 border px-2.5 font-mono text-[12px] outline-none"
                    style={{
                      background: 'var(--color-surface-card)',
                      borderColor: 'var(--color-hairline)',
                      borderRadius: 'var(--radius-sm)',
                      color: 'var(--color-ink)',
                    }}
                  />
                  <input
                    value={bioFields.locOrNeg}
                    onChange={(e) => setBioFields((f) => ({ ...f, locOrNeg: e.target.value }))}
                    placeholder={lang === 'vi' ? 'Tỉnh/Thành hoặc -từ_khóa_loại_trừ' : 'Location or -negative_keyword'}
                    className="h-8 border px-2.5 text-[13px] outline-none"
                    style={{
                      background: 'var(--color-surface-card)',
                      borderColor: 'var(--color-hairline)',
                      borderRadius: 'var(--radius-sm)',
                      color: 'var(--color-ink)',
                    }}
                  />
                </div>
                <div className="flex justify-end gap-2 pt-1">
                  <button
                    type="button"
                    onClick={() => handleApplyBioForm(false)}
                    className="btn-secondary h-7 px-2.5 text-[12px]"
                  >
                    {lang === 'vi' ? 'Chèn vào ô nhập' : 'Insert to Prompt'}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleApplyBioForm(true)}
                    className="btn-primary h-7 px-3 text-[12px]"
                  >
                    {lang === 'vi' ? 'Chạy điều tra ngay' : 'Investigate Now'}
                  </button>
                </div>
              </div>
            )}

            {/* Inline URL Insertion Bar */}
            {urlInsertOpen && (
              <div
                className="flex items-center gap-2 border p-1.5"
                style={{
                  background: 'var(--color-canvas-soft)',
                  borderColor: 'var(--color-hairline)',
                  borderRadius: 'var(--radius-md)',
                }}
              >
                <Link2 className="ml-1 h-3.5 w-3.5 shrink-0" style={{ color: 'var(--color-muted)' }} />
                <input
                  autoFocus
                  value={urlDraft}
                  onChange={(e) => setUrlDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && urlDraft.trim()) {
                      setPrompt((prev) => `${prev ? prev + ', ' : ''}${urlDraft.trim()}`)
                      setUrlDraft('')
                      setUrlInsertOpen(false)
                    } else if (e.key === 'Escape') {
                      setUrlInsertOpen(false)
                    }
                  }}
                  placeholder={t.insertUrlPlaceholder}
                  className="h-7 flex-1 bg-transparent px-1 font-mono text-[13px] outline-none"
                  style={{ color: 'var(--color-ink)' }}
                />
                <button
                  onClick={() => {
                    if (urlDraft.trim()) {
                      setPrompt((prev) => `${prev ? prev + ', ' : ''}${urlDraft.trim()}`)
                      setUrlDraft('')
                    }
                    setUrlInsertOpen(false)
                  }}
                  className="btn-secondary h-7 px-2.5 text-[13px]"
                >
                  {t.insertUrlAddBtn}
                </button>
                <button
                  onClick={() => setUrlInsertOpen(false)}
                  className="p-1"
                  style={{ color: 'var(--color-muted)' }}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            )}

            <textarea
              ref={composerRef}
              rows={2}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onPaste={handlePaste}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  handleSend()
                }
              }}
              placeholder={t.composerPlaceholder}
              className="w-full resize-none bg-transparent text-[15px] leading-[1.5] outline-none"
              style={{ color: 'var(--color-ink)' }}
            />

            <div className="app-chrome flex items-center justify-between gap-2 pt-1">
              <div className="relative flex items-center gap-1.5">
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    setModelPopupOpen(false)
                    setModePopupOpen(false)
                    setCtxMenuOpen((o) => !o)
                  }}
                  className="agy-menu-item grid h-8 w-8 place-items-center border"
                  style={{
                    background: 'var(--color-canvas-soft)',
                    borderColor: 'var(--color-hairline)',
                    borderRadius: 'var(--radius-md)',
                    color: 'var(--color-body)',
                  }}
                  title={t.addContextTooltip}
                >
                  <Plus className="h-4 w-4" />
                </button>

                {ctxMenuOpen && (
                  <div
                    onClick={(e) => e.stopPropagation()}
                    className="agy-popover-up absolute bottom-10 left-0 z-30 w-72 border p-1.5"
                    style={{
                      background: 'var(--color-surface-card)',
                      borderColor: 'var(--color-hairline-strong)',
                      borderRadius: 'var(--radius-lg)',
                    }}
                  >
                    <button
                      onClick={() => {
                        setCtxMenuOpen(false)
                        imgInputRef.current?.click()
                      }}
                      className="agy-menu-item flex w-full items-center gap-2 px-2.5 py-2 text-left text-[13px]"
                      style={{ color: 'var(--color-ink)', borderRadius: 'var(--radius-sm)' }}
                    >
                      <ImagePlus className="h-3.5 w-3.5 shrink-0" style={{ color: 'var(--color-muted)' }} />
                      <span>
                        {lang === 'vi'
                          ? 'Đính kèm ảnh (Vision OCR / Đồng phục / EXIF)'
                          : 'Attach Image (Vision OCR / Uniform / EXIF)'}
                      </span>
                    </button>
                    <button
                      onClick={() => {
                        setCtxMenuOpen(false)
                        fileInputRef.current?.click()
                      }}
                      className="agy-menu-item flex w-full items-center gap-2 px-2.5 py-2 text-left text-[13px]"
                      style={{ color: 'var(--color-ink)', borderRadius: 'var(--radius-sm)' }}
                    >
                      <FileText className="h-3.5 w-3.5 shrink-0" style={{ color: 'var(--color-muted)' }} />
                      <span>
                        {lang === 'vi'
                          ? 'Đính kèm PDF / Excel / CSV / vCard / TXT'
                          : 'Attach PDF / Excel / CSV / vCard / TXT'}
                      </span>
                    </button>
                    <button
                      onClick={() => {
                        setCtxMenuOpen(false)
                        setBioFormOpen((o) => !o)
                      }}
                      className="agy-menu-item flex w-full items-center gap-2 px-2.5 py-2 text-left text-[13px]"
                      style={{ color: 'var(--color-ink)', borderRadius: 'var(--radius-sm)' }}
                    >
                      <ShieldCheck className="h-3.5 w-3.5 shrink-0" style={{ color: 'var(--color-muted)' }} />
                      <span>
                        {lang === 'vi'
                          ? 'Biểu mẫu Hồ sơ đa trường (SĐT / CCCD / MSSV)'
                          : 'Multi-Field Bio Form (Phone / ID / School)'}
                      </span>
                    </button>
                    <button
                      onClick={() => {
                        setCtxMenuOpen(false)
                        setMapOpen(true)
                      }}
                      className="agy-menu-item flex w-full items-center gap-2 px-2.5 py-2 text-left text-[13px]"
                      style={{ color: 'var(--color-ink)', borderRadius: 'var(--radius-sm)' }}
                    >
                      <MapPin className="h-3.5 w-3.5 shrink-0" style={{ color: 'var(--color-muted)' }} />
                      <span>{t.pickMapLocation}</span>
                    </button>
                    <button
                      onClick={() => {
                        setCtxMenuOpen(false)
                        setUrlInsertOpen(true)
                      }}
                      className="agy-menu-item flex w-full items-center gap-2 px-2.5 py-2 text-left text-[13px]"
                      style={{ color: 'var(--color-ink)', borderRadius: 'var(--radius-sm)' }}
                    >
                      <Link2 className="h-3.5 w-3.5 shrink-0" style={{ color: 'var(--color-muted)' }} />
                      <span>
                        {lang === 'vi'
                          ? 'Chèn URL công khai (Scribd / Studocu / PDF)'
                          : 'Insert Public URL (Scribd / Studocu / PDF)'}
                      </span>
                    </button>
                  </div>
                )}

                {/* Antigravity Model Selector Popover Button (`Gemini 4 Hydrogen Medium v`) */}
                <div className="relative">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      setCtxMenuOpen(false)
                      setModePopupOpen(false)
                      setModelPopupOpen((v) => !v)
                    }}
                    className="agy-menu-item inline-flex h-8 items-center gap-1.5 px-2.5 text-[13px]"
                    style={{
                      color: 'var(--color-ink)',
                      borderRadius: 'var(--radius-md)',
                    }}
                  >
                    <span className="font-medium">{activeModelMeta.label}</span>
                    <span className="text-[12px]" style={{ color: 'var(--color-muted)' }}>
                      {activeModelMeta.tier}
                    </span>
                    <ChevronDown className="h-3.5 w-3.5" style={{ color: 'var(--color-muted)' }} />
                  </button>

                  {modelPopupOpen && (
                    <div
                      onClick={(e) => e.stopPropagation()}
                      className="agy-popover-up absolute bottom-10 left-0 z-30 w-64 space-y-0.5 border p-1.5"
                      style={{
                        background: 'var(--color-surface-card)',
                        borderColor: 'var(--color-hairline-strong)',
                        borderRadius: 'var(--radius-lg)',
                      }}
                    >
                      <div className="px-2.5 py-1 text-[11px] font-medium" style={{ color: 'var(--color-muted)' }}>
                        {lang === 'vi' ? 'Chọn Mô hình Agent' : 'Select Agent Model'}
                      </div>
                      {AGENT_MODELS.map((m) => {
                        const selected = m.id === model
                        return (
                          <button
                            key={m.id}
                            type="button"
                            onClick={() => {
                              setModel(m.id)
                              setModelPopupOpen(false)
                            }}
                            className="agy-menu-item flex w-full items-center justify-between px-2.5 py-1.5 text-left text-[13px]"
                            style={{
                              background: selected ? 'var(--color-surface-strong)' : 'transparent',
                              borderRadius: 'var(--radius-sm)',
                              color: 'var(--color-ink)',
                            }}
                          >
                            <span className="flex items-center gap-1.5">
                              <span className="font-medium">{m.label}</span>
                              <span className="text-[11px]" style={{ color: 'var(--color-muted)' }}>
                                {m.tier}
                              </span>
                            </span>
                            {selected && <Check className="h-3.5 w-3.5" style={{ color: 'var(--color-ink)' }} />}
                          </button>
                        )
                      })}
                    </div>
                  )}
                </div>
              </div>

              <div className="relative flex items-center gap-2">
                {/* Antigravity Execution Mode Popover (`Deep ReAct v` / `Turbo v`) */}
                <div className="relative">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      setCtxMenuOpen(false)
                      setModelPopupOpen(false)
                      setModePopupOpen((v) => !v)
                    }}
                    className="agy-menu-item inline-flex h-8 items-center gap-1.5 border px-2.5 text-[12px] font-medium"
                    style={{
                      background: 'var(--color-canvas-soft)',
                      borderColor: 'var(--color-hairline)',
                      borderRadius: 'var(--radius-md)',
                      color: 'var(--color-ink)',
                    }}
                    title={t.deepReactTooltip}
                  >
                    {deepMode ? (
                      <Sparkles className="h-3.5 w-3.5" style={{ color: 'var(--color-muted)' }} />
                    ) : (
                      <Zap className="h-3.5 w-3.5" style={{ color: 'var(--color-muted)' }} />
                    )}
                    <span>{deepMode ? 'Deep ReAct' : 'Turbo'}</span>
                    <ChevronDown className="h-3.5 w-3.5" style={{ color: 'var(--color-muted)' }} />
                  </button>

                  {modePopupOpen && (
                    <div
                      onClick={(e) => e.stopPropagation()}
                      className="agy-popover-up-right absolute right-0 bottom-10 z-30 w-64 space-y-1 border p-1.5"
                      style={{
                        background: 'var(--color-surface-card)',
                        borderColor: 'var(--color-hairline-strong)',
                        borderRadius: 'var(--radius-lg)',
                      }}
                    >
                      <button
                        type="button"
                        onClick={() => {
                          setDeepMode(true)
                          setModePopupOpen(false)
                        }}
                        className="agy-menu-item flex w-full items-start justify-between gap-2 px-2.5 py-2 text-left"
                        style={{
                          background: deepMode ? 'var(--color-surface-strong)' : 'transparent',
                          borderRadius: 'var(--radius-sm)',
                        }}
                      >
                        <div>
                          <div className="flex items-center gap-1.5 text-[13px] font-medium" style={{ color: 'var(--color-ink)' }}>
                            <Sparkles className="h-3.5 w-3.5" />
                            <span>Deep ReAct (5-Layer)</span>
                          </div>
                          <div className="mt-0.5 text-[11px]" style={{ color: 'var(--color-muted)' }}>
                            {lang === 'vi'
                              ? 'Quét 2 vòng + Đọc sâu PDF/Studocu/Scribd + Cây MCTS'
                              : '2-round pivot + Deep PDF/Studocu/Scribd + MCTS tree'}
                          </div>
                        </div>
                        {deepMode && <Check className="mt-0.5 h-3.5 w-3.5 shrink-0" style={{ color: 'var(--color-ink)' }} />}
                      </button>

                      <button
                        type="button"
                        onClick={() => {
                          setDeepMode(false)
                          setModePopupOpen(false)
                        }}
                        className="agy-menu-item flex w-full items-start justify-between gap-2 px-2.5 py-2 text-left"
                        style={{
                          background: !deepMode ? 'var(--color-surface-strong)' : 'transparent',
                          borderRadius: 'var(--radius-sm)',
                        }}
                      >
                        <div>
                          <div className="flex items-center gap-1.5 text-[13px] font-medium" style={{ color: 'var(--color-ink)' }}>
                            <Zap className="h-3.5 w-3.5" />
                            <span>Turbo (Fast Recon)</span>
                          </div>
                          <div className="mt-0.5 text-[11px]" style={{ color: 'var(--color-muted)' }}>
                            {lang === 'vi'
                              ? 'Tìm nhanh 1 vòng tốc độ cao'
                              : 'Single-round high-speed reconnaissance'}
                          </div>
                        </div>
                        {!deepMode && <Check className="mt-0.5 h-3.5 w-3.5 shrink-0" style={{ color: 'var(--color-ink)' }} />}
                      </button>
                    </div>
                  )}
                </div>

                {sending ? (
                  <button
                    type="button"
                    onClick={() => handleStop(activeWsId)}
                    className="grid h-9 w-9 place-items-center"
                    style={{
                      background: 'var(--color-semantic-error)',
                      color: 'var(--color-on-primary)',
                      borderRadius: 'var(--radius-md)',
                    }}
                    title={t.stopTooltip}
                  >
                    <Square className="h-3.5 w-3.5 fill-current" />
                  </button>
                ) : (
                  <button
                    disabled={!prompt.trim() && !imgB64 && !fileText && !geoPoint}
                    onClick={() => handleSend()}
                    className="btn-primary grid h-9 w-9 place-items-center disabled:opacity-40"
                    title={t.sendTooltip}
                  >
                    <ArrowUp className="h-4 w-4" />
                  </button>
                )}
              </div>
            </div>

            <input
              ref={imgInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => handleImageUpload(e.target.files?.[0])}
            />
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.xlsx,.xlsm,.csv,.tsv,.vcf,.txt,.md,.json,.log"
              className="hidden"
              onChange={(e) => handleTextUpload(e.target.files?.[0])}
            />
          </div>
          <div
            className="app-chrome mx-auto mt-2 hidden max-w-[760px] text-center font-mono text-[11px] sm:block"
            style={{ color: 'var(--color-muted)' }}
          >
            {t.shortcutsHint}
          </div>
        </div>
      </main>

      {/* Right Panel: Verified Dossier + Timeline + Evidence Inspector */}
      <RightPanel
        lang={lang}
        open={rightOpen}
        width={rightWidth}
        isResizing={resizingSide === 'right'}
        onWidthChange={setRightWidth}
        onStartResize={(e) => {
          e.preventDefault()
          setResizingSide('right')
        }}
        workspaceId={activeWsId}
        dossierItems={dossierItems}
        timelineEvents={timelineEvents}
        inspectedSource={inspectedSource}
        targetTerms={currentTargetTerms}
        activeTab={rightTab}
        onTabChange={setRightTab}
        onDossierChanged={async () => {
          if (!activeWsId) return
          const [res, gRes] = await Promise.all([
            api.listDossier(activeWsId),
            api.getGraphSnapshot(activeWsId).catch(() => null),
          ])
          setDossierItems(res.items || [])
          if (gRes) setGraphSnapshot(gRes)
        }}
        onSourceUpdated={(updated) => setInspectedSource(updated)}
      />

      {/* Antigravity Quick Search / Command Palette Modal (Ctrl+P) */}
      {cmdPaletteOpen && (
        <div
          onClick={() => setCmdPaletteOpen(false)}
          className="fixed inset-0 z-50 flex items-start justify-center pt-20"
          style={{ background: 'var(--color-backdrop)' }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="agy-dropdown-in w-full max-w-lg border p-3"
            style={{
              background: 'var(--color-surface-card)',
              borderColor: 'var(--color-hairline-strong)',
              borderRadius: 'var(--radius-lg)',
            }}
          >
            <div className="flex items-center gap-2 border-b pb-2.5" style={{ borderColor: 'var(--color-hairline)' }}>
              <Search className="h-4 w-4 shrink-0" style={{ color: 'var(--color-muted)' }} />
              <input
                autoFocus
                value={cmdQuery}
                onChange={(e) => setCmdQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Escape') setCmdPaletteOpen(false)
                }}
                placeholder={
                  lang === 'vi'
                    ? 'Tìm nhanh phiên điều tra, kịch bản, hoặc lệnh (Ctrl+P)...'
                    : 'Search investigations, playbooks, or actions (Ctrl+P)...'
                }
                className="flex-1 bg-transparent text-[14px] outline-none"
                style={{ color: 'var(--color-ink)' }}
              />
              <button onClick={() => setCmdPaletteOpen(false)} style={{ color: 'var(--color-muted)' }}>
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="mt-2 max-h-72 space-y-1 overflow-y-auto">
              <div className="px-2 py-1 text-[11px] font-medium" style={{ color: 'var(--color-muted)' }}>
                {lang === 'vi' ? 'Lệnh Nhanh (Quick Actions)' : 'Quick Actions'}
              </div>
              <button
                onClick={() => {
                  setCmdPaletteOpen(false)
                  handleCreateSession()
                }}
                className="agy-menu-item flex w-full items-center justify-between px-2.5 py-1.5 text-left text-[13px]"
                style={{ borderRadius: 'var(--radius-sm)', color: 'var(--color-ink)' }}
              >
                <span className="flex items-center gap-2">
                  <Plus className="h-3.5 w-3.5" style={{ color: 'var(--color-muted)' }} />
                  <span>{t.newSession}</span>
                </span>
                <span className="font-mono text-[11px]" style={{ color: 'var(--color-muted)' }}>
                  Ctrl+K
                </span>
              </button>
              <button
                onClick={() => {
                  setCmdPaletteOpen(false)
                  setHubOpen(true)
                }}
                className="agy-menu-item flex w-full items-center justify-between px-2.5 py-1.5 text-left text-[13px]"
                style={{ borderRadius: 'var(--radius-sm)', color: 'var(--color-ink)' }}
              >
                <span className="flex items-center gap-2">
                  <Settings className="h-3.5 w-3.5" style={{ color: 'var(--color-muted)' }} />
                  <span>{lang === 'vi' ? 'Mở Cài đặt & Khóa API (Gemini / Serper / MCP)' : 'Open Settings & API Keys'}</span>
                </span>
                <span className="font-mono text-[11px]" style={{ color: 'var(--color-muted)' }}>
                  MCP
                </span>
              </button>
              <div className="pt-2 px-2 py-1 text-[11px] font-medium" style={{ color: 'var(--color-muted)' }}>
                {lang === 'vi' ? 'Phiên Điều tra (Projects)' : 'Investigation Projects'}
              </div>
              {workspaces
                .filter((w) => {
                  if (!cmdQuery.trim()) return true
                  const hay = foldVietnameseText(`${w.name} ${w.search_summary || ''}`)
                  const q = foldVietnameseText(cmdQuery)
                  return hay.includes(q)
                })
                .slice(0, 8)
                .map((w) => (
                  <button
                    key={w.id}
                    onClick={() => {
                      setCmdPaletteOpen(false)
                      setCmdQuery('')
                      selectWorkspaceWithHistory(w.id)
                    }}
                    className="agy-menu-item flex w-full flex-col gap-0.5 px-2.5 py-1.5 text-left"
                    style={{ borderRadius: 'var(--radius-sm)' }}
                  >
                    <div className="flex items-center justify-between text-[13px]">
                      <span className="flex items-center gap-1.5 font-medium" style={{ color: 'var(--color-ink)' }}>
                        {w.pinned ? <Pin className="h-3 w-3" /> : <Folder className="h-3.5 w-3.5" style={{ color: 'var(--color-muted)' }} />}
                        <span>{w.name}</span>
                      </span>
                      <span className="font-mono text-[11px]" style={{ color: 'var(--color-muted)' }}>
                        {formatRelativeAge(w.last_active_at || w.created_at)}
                      </span>
                    </div>
                    {w.search_summary && (
                      <div className="truncate text-[11px]" style={{ color: 'var(--color-muted)' }}>
                        {w.search_summary}
                      </div>
                    )}
                  </button>
                ))}
            </div>
          </div>
        </div>
      )}

      {/* Knowledge Graph Entities & Edges Inspector Popup Modal */}
      {graphPopupOpen && (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center pt-14 px-4"
          style={{ background: 'var(--color-backdrop)' }}
          onClick={() => setGraphPopupOpen(false)}
        >
          <div
            className="agy-dropdown-in flex max-h-[82vh] w-full max-w-[780px] flex-col border p-4"
            style={{
              background: 'var(--color-surface-card)',
              borderColor: 'var(--color-hairline-strong)',
              borderRadius: 'var(--radius-lg)',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div
              className="flex items-center justify-between border-b pb-3"
              style={{ borderColor: 'var(--color-hairline)' }}
            >
              <div>
                <h2 className="text-[15px] font-semibold" style={{ color: 'var(--color-ink)' }}>
                  {lang === 'vi'
                    ? `Đồ thị Tri thức 8 Chiều — ${graphSnapshot?.nodes.length || 0} Thực thể · ${graphSnapshot?.edges.length || 0} Liên kết`
                    : `8D Knowledge Graph — ${graphSnapshot?.nodes.length || 0} Entities · ${graphSnapshot?.edges.length || 0} Links`}
                </h2>
                <p className="text-[12px]" style={{ color: 'var(--color-muted)' }}>
                  {lang === 'vi'
                    ? 'Danh sách toàn bộ các thực thể và mối liên hệ đã trích xuất, gộp khử trùng lặp trong phiên điều tra này.'
                    : 'All deduplicated entities and relationships extracted in this investigation session.'}
                </p>
              </div>
              <button
                onClick={() => setGraphPopupOpen(false)}
                className="agy-menu-item p-1"
                style={{ color: 'var(--color-muted)', borderRadius: 'var(--radius-xs)' }}
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="mt-3 grid min-h-0 flex-1 grid-cols-1 gap-4 overflow-y-auto md:grid-cols-2">
              {/* Column 1: Entities (Nodes) */}
              <div className="space-y-2">
                <div className="caption-uppercase">
                  {lang === 'vi'
                    ? `Thực thể (${graphSnapshot?.nodes.length || 0})`
                    : `Entities (${graphSnapshot?.nodes.length || 0})`}
                </div>
                {!graphSnapshot || graphSnapshot.nodes.length === 0 ? (
                  <div
                    className="border p-3 text-[12px]"
                    style={{
                      background: 'var(--color-canvas-soft)',
                      borderColor: 'var(--color-hairline)',
                      borderRadius: 'var(--radius-md)',
                      color: 'var(--color-muted)',
                    }}
                  >
                    {lang === 'vi' ? 'Chưa có thực thể nào.' : 'No entities yet.'}
                  </div>
                ) : (
                  <div className="space-y-2">
                    {graphSnapshot.nodes.map((n, ni) => {
                      const typeLabelVi: Record<string, string> = {
                        Person: 'Cá nhân',
                        Org: 'Trường / Tổ chức',
                        Location: 'Địa điểm',
                        Alias: 'Biệt danh / Tài khoản',
                        TechnicalArtifact: 'Định danh Kỹ thuật',
                        Event: 'Sự kiện',
                      }
                      const readableClaims = (n.claims || []).filter(
                        (c) => c.key !== 'stylometry_vector' && c.key !== 'temporal_activity_signature',
                      )
                      return (
                        <div
                          key={n.id}
                          className="space-y-1.5 border p-2.5"
                          style={{
                            background: 'var(--color-canvas-soft)',
                            borderColor: 'var(--color-hairline)',
                            borderRadius: 'var(--radius-md)',
                          }}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-[13px] font-semibold" style={{ color: 'var(--color-ink)' }}>
                              #{ni + 1}. {n.label}
                            </span>
                            <div className="flex shrink-0 items-center gap-1.5">
                              <span
                                className="border px-1.5 py-0.5 font-mono text-[10px]"
                                style={{
                                  background: 'var(--color-surface-card)',
                                  borderColor: 'var(--color-hairline)',
                                  borderRadius: 'var(--radius-xs)',
                                  color: 'var(--color-body)',
                                }}
                              >
                                {lang === 'vi' ? typeLabelVi[n.type] || n.type : n.type}
                              </span>
                              <span className="font-mono text-[10px]" style={{ color: 'var(--color-muted)' }}>
                                {Math.round((n.confidence || 0) * 100)}%
                              </span>
                              <button
                                onClick={async () => {
                                  if (!activeWsId) return
                                  await api.deleteGraphNode(n.id).catch(() => undefined)
                                  const g = await api.getGraphSnapshot(activeWsId).catch(() => null)
                                  if (g) setGraphSnapshot(g)
                                }}
                                className="agy-menu-item p-0.5"
                                style={{ color: 'var(--color-muted)', borderRadius: 'var(--radius-xs)' }}
                                title={lang === 'vi' ? 'Xóa thực thể không đúng này' : 'Remove this inaccurate entity'}
                              >
                                <Trash2 className="h-3 w-3" />
                              </button>
                            </div>
                          </div>
                          {readableClaims.length > 0 && (
                            <div className="space-y-1 border-t pt-1.5" style={{ borderColor: 'var(--color-hairline)' }}>
                              {readableClaims.slice(0, 8).map((c, ci) => {
                                const extUrl = safeExternalUrl(c.source_url)
                                return (
                                  <div
                                    key={ci}
                                    className="group flex flex-wrap items-center justify-between gap-1 text-[11px]"
                                    style={{
                                      color:
                                        c.polarity === 'NEGATIVE'
                                          ? 'var(--color-semantic-error)'
                                          : 'var(--color-body)',
                                    }}
                                  >
                                    <span className="min-w-0 truncate">
                                      <strong style={{ color: 'var(--color-ink)' }}>{c.key}:</strong>{' '}
                                      {String(c.value ?? '')}
                                    </span>
                                    <div className="flex shrink-0 items-center gap-1.5">
                                      {extUrl ? (
                                        <a
                                          href={extUrl}
                                          target="_blank"
                                          rel="noopener noreferrer"
                                          className="font-mono text-[10px] hover:underline"
                                          style={{ color: 'var(--color-muted)' }}
                                        >
                                          [Nguồn ↗]
                                        </a>
                                      ) : (
                                        <span className="font-mono text-[10px]" style={{ color: 'var(--color-muted)' }}>
                                          {c.source_url === 'manual://user_verified'
                                            ? lang === 'vi'
                                              ? '[Đã ghim Hồ sơ]'
                                              : '[Pinned Dossier]'
                                            : c.source_url === 'user://prompt'
                                              ? lang === 'vi'
                                                ? '[Từ câu hỏi]'
                                                : '[User prompt]'
                                              : ''}
                                        </span>
                                      )}
                                      <button
                                        onClick={async () => {
                                          if (!activeWsId) return
                                          await api
                                            .deleteGraphNodeClaim(n.id, c.key, String(c.value ?? ''))
                                            .catch(() => undefined)
                                          const g = await api.getGraphSnapshot(activeWsId).catch(() => null)
                                          if (g) setGraphSnapshot(g)
                                        }}
                                        className="opacity-60 hover:opacity-100"
                                        style={{ color: 'var(--color-muted)' }}
                                        title={
                                          lang === 'vi'
                                            ? 'Xóa thông tin sai này khỏi thực thể'
                                            : 'Remove this inaccurate claim'
                                        }
                                      >
                                        <X className="h-3 w-3" />
                                      </button>
                                    </div>
                                  </div>
                                )
                              })}
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>

              {/* Column 2: Relationships / Edges */}
              <div className="space-y-2">
                <div className="caption-uppercase">
                  {lang === 'vi'
                    ? `Liên kết (${graphSnapshot?.edges.length || 0})`
                    : `Links (${graphSnapshot?.edges.length || 0})`}
                </div>
                {!graphSnapshot || graphSnapshot.edges.length === 0 ? (
                  <div
                    className="border p-3 text-[12px]"
                    style={{
                      background: 'var(--color-canvas-soft)',
                      borderColor: 'var(--color-hairline)',
                      borderRadius: 'var(--radius-md)',
                      color: 'var(--color-muted)',
                    }}
                  >
                    {lang === 'vi' ? 'Chưa có liên kết nào.' : 'No links yet.'}
                  </div>
                ) : (
                  <div className="space-y-2">
                    {graphSnapshot.edges.map((e, ei) => {
                      const nodeMap = new Map((graphSnapshot.nodes || []).map((n) => [n.id, n.label]))
                      const srcLabel = nodeMap.get(e.source_id) || e.source_id.slice(0, 8)
                      const dstLabel = nodeMap.get(e.target_id) || e.target_id.slice(0, 8)
                      const relLabelVi: Record<string, string> = {
                        STUDIED_OR_WORKED_AT: 'Học tập / Công tác tại',
                        STUDIED_AT: 'Học tại',
                        WORKS_AT: 'Làm việc tại',
                        LOCATED_IN: 'Tại địa điểm',
                        SPECIALIZES_IN: 'Chuyên ngành / Lĩnh vực',
                        RELATED_TO: 'Liên quan tới',
                        CHILD_OF: 'Là con của',
                        PARENT_OF: 'Là phụ huynh của',
                        GRANDPARENT_OF: 'Là ông/bà của',
                        SIBLING_OF: 'Anh/Chị/Em với',
                        SPOUSE_OF: 'Vợ/Chồng của',
                        PARTNER_OF: 'Người yêu / Bạn đời của',
                        RELATIVE_OF: 'Họ hàng / Người thân của',
                        CLASSMATE_OF: 'Bạn học / Cùng lớp với',
                        STUDENT_OF: 'Học trò / Sinh viên của',
                        MENTOR_OF: 'Giảng viên / Cố vấn của',
                        COLLEAGUE_OF: 'Đồng nghiệp / Cộng sự với',
                        MANAGER_OF: 'Quản lý / Sếp của',
                        SUBORDINATE_OF: 'Nhân viên / Trợ lý của',
                        ROOMMATE_OR_NEIGHBOR_OF: 'Bạn cùng phòng / Hàng xóm của',
                        FRIEND_OR_ASSOCIATE_OF: 'Bạn bè / Liên hệ với',
                        OWNS_ACCOUNT: 'Sở hữu tài khoản',
                        ALSO_KNOWN_AS: 'Biệt danh / Tên gọi khác',
                        POSSIBLE_SAME_ENTITY: 'Nghi ngờ cùng một người',
                      }
                      const extUrl = safeExternalUrl(e.source_url)
                      return (
                        <div
                          key={e.id}
                          className="space-y-1 border p-2.5"
                          style={{
                            background: 'var(--color-canvas-soft)',
                            borderColor: 'var(--color-hairline)',
                            borderRadius: 'var(--radius-md)',
                          }}
                        >
                          <div className="flex flex-wrap items-center justify-between gap-1 text-[12px]">
                            <span className="font-semibold" style={{ color: 'var(--color-ink)' }}>
                              #{ei + 1}. {srcLabel} → {dstLabel}
                            </span>
                            <div className="flex shrink-0 items-center gap-1.5">
                              <span
                                className="border px-1.5 py-0.5 font-mono text-[10px]"
                                style={{
                                  background: 'var(--color-surface-card)',
                                  borderColor: 'var(--color-hairline)',
                                  borderRadius: 'var(--radius-xs)',
                                  color:
                                    e.status === 'VERIFIED'
                                      ? 'var(--color-semantic-success)'
                                      : 'var(--color-muted)',
                                }}
                              >
                                {e.status} · {Math.round((e.confidence || 0) * 100)}%
                              </span>
                              <button
                                onClick={async () => {
                                  if (!activeWsId) return
                                  await api.deleteGraphEdge(e.id).catch(() => undefined)
                                  const g = await api.getGraphSnapshot(activeWsId).catch(() => null)
                                  if (g) setGraphSnapshot(g)
                                }}
                                className="agy-menu-item p-0.5"
                                style={{ color: 'var(--color-muted)', borderRadius: 'var(--radius-xs)' }}
                                title={lang === 'vi' ? 'Xóa liên kết sai này' : 'Remove this inaccurate link'}
                              >
                                <Trash2 className="h-3 w-3" />
                              </button>
                            </div>
                          </div>
                          <div className="text-[11px] font-medium" style={{ color: 'var(--color-body)' }}>
                            {lang === 'vi' ? relLabelVi[e.relation] || e.relation : e.relation}
                          </div>
                          {e.evidence_quote && (
                            <div className="text-[11px]" style={{ color: 'var(--color-muted)' }}>
                              “{e.evidence_quote}”
                            </div>
                          )}
                          <div className="pt-0.5 text-[10px]" style={{ color: 'var(--color-muted)' }}>
                            {extUrl ? (
                              <a
                                href={extUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="font-mono hover:underline"
                                style={{ color: 'var(--color-ink)' }}
                              >
                                {e.source_url} ↗
                              </a>
                            ) : (
                              <span className="font-mono">
                                {e.source_url === 'user://prompt'
                                  ? lang === 'vi'
                                    ? 'Nguồn: Manh mối bạn cung cấp'
                                    : 'Source: User prompt clue'
                                  : e.source_url}
                              </span>
                            )}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      <IntegrationsModal
        lang={lang}
        open={hubOpen}
        onClose={() => setHubOpen(false)}
        onPluginsUpdated={(p) => setPlugins(p)}
      />
      <MapPickerModal lang={lang} open={mapOpen} onClose={() => setMapOpen(false)} onSelect={(pt) => setGeoPoint(pt)} />
    </div>
  )
}
