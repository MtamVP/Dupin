import { useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  AlertCircle,
  ArrowUp,
  Ban,
  BookmarkCheck,
  Check,
  ChevronRight,
  Copy,
  ExternalLink,
  Eye,
  FileText,
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
  Plug,
  Plus,
  Search,
  ShieldCheck,
  Square,
  Sun,
  Trash2,
  X,
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

export default function App() {
  const [theme, setTheme] = useState<ThemeMode>(() => readStored('stalker_theme', 'light', ['light', 'dark']))
  const [lang, setLang] = useState<Lang>(() => readStored('stalker_lang', 'vi', ['vi', 'en']))
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(() => readStoredBool('stalker_sidebar', true))
  const [rightOpen, setRightOpen] = useState<boolean>(() => readStoredBool('stalker_right', true))

  const t = TRANSLATIONS[lang]

  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [sessionFilter, setSessionFilter] = useState('')
  const [activeWsId, setActiveWsId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [dossierItems, setDossierItems] = useState<DossierItem[]>([])
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
  const [urlInsertOpen, setUrlInsertOpen] = useState(false)
  const [urlDraft, setUrlDraft] = useState('')

  // Toast feedback
  const [toastMsg, setToastMsg] = useState<string | null>(null)
  const toastTimerRef = useRef<number | null>(null)

  // Composer & Per-Workspace Concurrent Streaming state
  const [prompt, setPrompt] = useState('')
  const [model, setModel] = useState('gemini-3.5-flash-lite')
  const [deepMode, setDeepMode] = useState(true)
  const [runningByWs, setRunningByWs] = useState<Record<string, boolean>>({})
  const [streamLinesByWs, setStreamLinesByWs] = useState<Record<string, string[]>>({})
  const [pendingUserMsgByWs, setPendingUserMsgByWs] = useState<Record<string, ChatMessage | null>>({})

  // Attachments
  const [imgB64, setImgB64] = useState<string | null>(null)
  const [imgMime, setImgMime] = useState('image/png')
  const [imgName, setImgName] = useState('')
  const [fileText, setFileText] = useState<string | null>(null)
  const [fileName, setFileName] = useState('')
  const [geoPoint, setGeoPoint] = useState<GeoPoint | null>(null)

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

  // Auto-grow composer textarea cleanly (desktop feel)
  useEffect(() => {
    const el = composerRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(180, Math.max(48, el.scrollHeight))}px`
  }, [prompt])

  // Global desktop keyboard shortcuts (Ctrl/Cmd+K new session, Ctrl/Cmd+B sidebar, Ctrl/Cmd+\ right panel)
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const mod = e.ctrlKey || e.metaKey
      if (!mod) return
      if (e.key.toLowerCase() === 'k') {
        e.preventDefault()
        handleCreateSession().catch(() => undefined)
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
    const [dosRes, msgRes] = await Promise.all([api.listDossier(wsId), api.listMessages(wsId)])
    if (activeWsIdRef.current !== wsId) return
    setDossierItems(dosRes.items || [])
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

  const filteredWorkspaces = useMemo(() => {
    const q = sessionFilter.trim().toLowerCase()
    if (!q) return workspaces
    return workspaces.filter((w) => w.name.toLowerCase().includes(q))
  }, [workspaces, sessionFilter])

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
      const res = await api.listDossier(activeWsId)
      setDossierItems(res.items || [])
      showToast(saved.already_exists ? t.sourceAlreadyPinnedToast : t.sourcePinnedToast)
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Error saving source')
    }
  }

  function handleCopyText(text: string) {
    navigator.clipboard.writeText(text)
    showToast(t.copiedToast)
  }

  async function handleSend(overridePrompt?: string) {
    const text = (overridePrompt ?? prompt).trim()
    const targetWsId = activeWsId
    if (!text || !targetWsId || runningByWs[targetWsId]) return

    const curImg = imgB64
    const curMime = imgMime
    const curFile = fileText
    const curGeo = geoPoint

    if (!overridePrompt) setPrompt('')
    setImgB64(null)
    setFileText(null)
    setGeoPoint(null)

    let displayUser = text
    if (curGeo) displayUser += ` [${t.mapChipPrefix}: ${curGeo.label} (${curGeo.lat.toFixed(4)}, ${curGeo.lng.toFixed(4)})]`
    if (curImg) displayUser += ` [${t.imageChipPrefix}: ${imgName || 'Screenshot'}]`
    if (curFile) displayUser += ` [${t.fileChipPrefix}: ${fileName}]`

    const userMsg: ChatMessage = { role: 'user', content: displayUser }
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
    const reader = new FileReader()
    reader.onload = () => {
      const parts = String(reader.result || '').split(',')
      setImgB64(parts.length > 1 ? parts[1] : null)
      setImgMime(file.type || 'image/png')
      setImgName(file.name || 'Screenshot')
    }
    reader.readAsDataURL(file)
  }

  function handleTextUpload(file?: File) {
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => {
      setFileText(String(reader.result || '').slice(0, 8000))
      setFileName(file.name)
    }
    reader.readAsText(file)
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

  return (
    <div
      className="flex h-full w-full overflow-hidden"
      onClick={() => {
        if (ctxMenuOpen) setCtxMenuOpen(false)
        if (confirmDeleteWsId) setConfirmDeleteWsId(null)
      }}
    >
      {/* Region 1: Collapsible Left Sidebar (canvas floor, no block border, flat 14px/500 list) */}
      {sidebarOpen && (
        <aside
          className="app-chrome flex h-full w-64 shrink-0 flex-col px-3 py-4"
          style={{ background: 'var(--color-canvas)' }}
        >
          {/* Wordmark + Brand Mark (Cursor Orange reserved ONLY for logo & primary CTA) */}
          <div className="flex items-center justify-between gap-2 px-2 pb-4">
            <div className="flex min-w-0 items-center gap-2.5">
              <div
                className="grid h-7 w-7 shrink-0 place-items-center font-mono text-[12px] font-medium"
                style={{
                  background: 'var(--color-primary)',
                  color: 'var(--color-on-primary)',
                  borderRadius: 'var(--radius-md)',
                }}
              >
                D
              </div>
              <div className="min-w-0">
                <div className="display-heading truncate text-[18px] leading-tight">Dupin</div>
                <div className="truncate font-mono text-[11px]" style={{ color: 'var(--color-muted)' }}>
                  {t.appSubtitle}
                </div>
              </div>
            </div>
            <button
              onClick={() => setTheme((th) => (th === 'dark' ? 'light' : 'dark'))}
              className="grid h-8 w-8 shrink-0 place-items-center transition-colors"
              style={{ color: 'var(--color-body)', borderRadius: 'var(--radius-md)' }}
              title={t.toggleThemeTooltip}
            >
              {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </button>
          </div>

          <div className="space-y-2 pb-3">
            <button
              onClick={handleCreateSession}
              className="btn-secondary flex h-9 w-full items-center justify-center gap-1.5 px-3"
            >
              <Plus className="h-3.5 w-3.5" />
              <span>{t.newSession}</span>
            </button>
            {workspaces.length > 3 && (
              <div className="relative">
                <Search
                  className="pointer-events-none absolute top-2.5 left-2.5 h-3.5 w-3.5"
                  style={{ color: 'var(--color-muted)' }}
                />
                <input
                  value={sessionFilter}
                  onChange={(e) => setSessionFilter(e.target.value)}
                  placeholder={t.searchSessionsPlaceholder}
                  className="h-8 w-full border pr-2.5 pl-8 text-[13px] outline-none"
                  style={{
                    background: 'var(--color-surface-card)',
                    borderColor: 'var(--color-hairline)',
                    borderRadius: 'var(--radius-md)',
                    color: 'var(--color-ink)',
                  }}
                />
              </div>
            )}
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
                return (
                  <div
                    key={ws.id}
                    onClick={() => {
                      if (isRenaming) return
                      activeWsIdRef.current = ws.id
                      setActiveWsId(ws.id)
                      loadSessionData(ws.id).catch(() => undefined)
                    }}
                    className="group flex flex-col gap-1.5 px-2.5 py-2 text-[14px] font-medium transition-colors"
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
                          <span className="flex min-w-0 items-center gap-2">
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
                          <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
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
                              <Pencil className="h-3.5 w-3.5" />
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
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        </>
                      )}
                    </div>

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

          {/* Minimal Hairline Status Footer */}
          <div
            className="space-y-1 border-t pt-3 text-[12px]"
            style={{ borderColor: 'var(--color-hairline)', color: 'var(--color-muted)' }}
          >
            <div className="flex items-center justify-between font-mono text-[11px]">
              <span className="truncate">
                {searxPlugin?.health.detail.includes('SearXNG') ? 'SearXNG ∥ ddgs' : 'ddgs Metasearch'}
              </span>
              <span>{t.pluginsCount(plugins.length)}</span>
            </div>
            <div className="flex items-center gap-1.5 text-[11px]">
              <ShieldCheck className="h-3.5 w-3.5 shrink-0" style={{ color: 'var(--color-muted)' }} />
              <span>{t.localFirstBadge}</span>
            </div>
          </div>
        </aside>
      )}

      {/* Main Center Stage (Regions 2 & 3: Chat Frame + Pipeline Timeline) */}
      <main
        className="relative flex min-w-0 flex-1 flex-col border-l"
        style={{ background: 'var(--color-canvas)', borderColor: 'var(--color-hairline)' }}
      >
        {/* Top Bar */}
        <header
          className="app-chrome flex h-14 shrink-0 items-center justify-between border-b px-5"
          style={{ borderColor: 'var(--color-hairline)', background: 'var(--color-canvas)' }}
        >
          <div className="flex min-w-0 items-center gap-3">
            <button
              onClick={() => setSidebarOpen((s) => !s)}
              className="grid h-8 w-8 shrink-0 place-items-center transition-colors"
              style={{ color: 'var(--color-body)', borderRadius: 'var(--radius-md)' }}
              title={t.toggleSidebarTooltip}
            >
              {sidebarOpen ? <PanelLeftClose className="h-4 w-4" /> : <PanelLeftOpen className="h-4 w-4" />}
            </button>
            <h1 className="display-heading truncate text-[18px] leading-tight">
              {activeWs?.name || 'Dupin'}
            </h1>
            {latestAssistantPayload?.graph_stats && (
              <span
                className="hidden font-mono text-[12px] sm:inline-block"
                style={{ color: 'var(--color-muted)' }}
              >
                {t.entitiesEdges(
                  latestAssistantPayload.graph_stats.nodes,
                  latestAssistantPayload.graph_stats.edges,
                )}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setLang((l) => (l === 'vi' ? 'en' : 'vi'))}
              className="btn-secondary inline-flex h-8 items-center gap-1.5 px-2.5 font-mono text-[12px]"
              title={t.switchLangTooltip}
            >
              <Globe className="h-3.5 w-3.5" style={{ color: 'var(--color-muted)' }} />
              <span>{lang === 'vi' ? 'VI' : 'EN'}</span>
            </button>
            <button
              onClick={() => setHubOpen(true)}
              className="btn-secondary inline-flex h-8 items-center gap-1.5 px-3 text-[13px]"
            >
              <Plug className="h-3.5 w-3.5" style={{ color: 'var(--color-muted)' }} />
              <span className="hidden md:inline">{t.integrationsBtn}</span>
            </button>
            <button
              onClick={() => setRightOpen((o) => !o)}
              className="inline-flex h-8 items-center gap-1.5 border px-3 text-[13px] font-medium transition-colors"
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
                return (
                  <div key={idx} className="flex justify-start">
                    <div
                      className="w-fit max-w-[640px] border px-4 py-3 text-[15px] leading-[1.5]"
                      style={{
                        background: 'var(--color-surface-card)',
                        borderColor: 'var(--color-hairline)',
                        borderRadius: 'var(--radius-lg)',
                        color: 'var(--color-ink)',
                      }}
                    >
                      {msg.content}
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
                    <button
                      onClick={() => handleCopyText(markdownText)}
                      className="shrink-0 p-1.5 text-[12px] transition-colors"
                      style={{ color: 'var(--color-muted)' }}
                      title={t.copyReportTooltip}
                    >
                      <Copy className="h-3.5 w-3.5" />
                    </button>
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
                          const isPinned = pinnedUrlSet.has(normalizeUrl(src.url))
                          const domain = extractDomain(src.url)
                          return (
                            <div
                              key={si}
                              className="flex flex-col justify-between gap-3 border p-4 sm:flex-row sm:items-start"
                              style={{
                                background: 'var(--color-surface-card)',
                                borderColor: 'var(--color-hairline)',
                                borderRadius: 'var(--radius-lg)',
                              }}
                            >
                              <div className="min-w-0 flex-1">
                                <div className="flex flex-wrap items-center gap-2">
                                  {safeExternalUrl(src.url) ? (
                                    <a
                                      href={safeExternalUrl(src.url)!}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="inline-flex items-center gap-1 text-[14px] font-medium hover:underline"
                                      style={{ color: 'var(--color-ink)' }}
                                    >
                                      <span>{src.title || src.url}</span>
                                      <ExternalLink className="h-3.5 w-3.5 shrink-0" style={{ color: 'var(--color-muted)' }} />
                                    </a>
                                  ) : (
                                    <span className="text-[14px] font-medium" style={{ color: 'var(--color-ink)' }}>
                                      {src.title || src.url}
                                    </span>
                                  )}
                                  {domain && (
                                    <span className="font-mono text-[12px]" style={{ color: 'var(--color-muted)' }}>
                                      {domain}
                                    </span>
                                  )}
                                  {src.match_score > 0 && (
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
                                  {src.deep_inspected && (
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
                                >
                                  {isPinned ? <Check className="h-3.5 w-3.5" /> : <Plus className="h-3.5 w-3.5" />}
                                  <span>{isPinned ? t.savedBadge : t.saveToDossierBtn}</span>
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
            {/* Context Attachment Chips */}
            {(imgB64 || fileText || geoPoint) && (
              <div className="flex flex-wrap gap-1.5">
                {imgB64 && (
                  <span
                    className="inline-flex items-center gap-1.5 border px-2 py-0.5 text-[12px]"
                    style={{
                      background: 'var(--color-canvas-soft)',
                      borderColor: 'var(--color-hairline)',
                      borderRadius: 'var(--radius-sm)',
                      color: 'var(--color-ink)',
                    }}
                  >
                    {t.imageChipPrefix}: {imgName}
                    <button onClick={() => setImgB64(null)} style={{ color: 'var(--color-muted)' }}>
                      ×
                    </button>
                  </span>
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
                    {t.fileChipPrefix}: {fileName}
                    <button onClick={() => setFileText(null)} style={{ color: 'var(--color-muted)' }}>
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
                    setCtxMenuOpen((o) => !o)
                  }}
                  className="grid h-8 w-8 place-items-center border"
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
                    className="absolute bottom-10 left-0 z-30 w-60 border p-1.5"
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
                      className="flex w-full items-center gap-2 px-2.5 py-2 text-left text-[13px]"
                      style={{ color: 'var(--color-ink)', borderRadius: 'var(--radius-sm)' }}
                    >
                      <ImagePlus className="h-3.5 w-3.5" style={{ color: 'var(--color-muted)' }} />
                      <span>{t.attachImage}</span>
                    </button>
                    <button
                      onClick={() => {
                        setCtxMenuOpen(false)
                        fileInputRef.current?.click()
                      }}
                      className="flex w-full items-center gap-2 px-2.5 py-2 text-left text-[13px]"
                      style={{ color: 'var(--color-ink)', borderRadius: 'var(--radius-sm)' }}
                    >
                      <FileText className="h-3.5 w-3.5" style={{ color: 'var(--color-muted)' }} />
                      <span>{t.attachFile}</span>
                    </button>
                    <button
                      onClick={() => {
                        setCtxMenuOpen(false)
                        setMapOpen(true)
                      }}
                      className="flex w-full items-center gap-2 px-2.5 py-2 text-left text-[13px]"
                      style={{ color: 'var(--color-ink)', borderRadius: 'var(--radius-sm)' }}
                    >
                      <MapPin className="h-3.5 w-3.5" style={{ color: 'var(--color-muted)' }} />
                      <span>{t.pickMapLocation}</span>
                    </button>
                    <button
                      onClick={() => {
                        setCtxMenuOpen(false)
                        setUrlInsertOpen(true)
                      }}
                      className="flex w-full items-center gap-2 px-2.5 py-2 text-left text-[13px]"
                      style={{ color: 'var(--color-ink)', borderRadius: 'var(--radius-sm)' }}
                    >
                      <Link2 className="h-3.5 w-3.5" style={{ color: 'var(--color-muted)' }} />
                      <span>{t.insertPublicUrl}</span>
                    </button>
                  </div>
                )}

                <select
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  className="h-8 bg-transparent px-2 text-[13px] font-medium outline-none"
                  style={{ color: 'var(--color-body)' }}
                >
                  <option value="gemini-3.5-flash-lite" style={{ background: 'var(--color-surface-card)' }}>
                    Gemini 3.5 Flash-Lite ({t.modelDefaultTag})
                  </option>
                  <option value="gemini-4-hydrogen" style={{ background: 'var(--color-surface-card)' }}>
                    Gemini 4 Hydrogen
                  </option>
                  <option value="gemini-3.6-flash" style={{ background: 'var(--color-surface-card)' }}>
                    Gemini 3.6 Flash
                  </option>
                  <option value="gemini-3.1-flash-lite" style={{ background: 'var(--color-surface-card)' }}>
                    Gemini 3.1 Flash-Lite
                  </option>
                  <option value="gemini-3.8-flash" style={{ background: 'var(--color-surface-card)' }}>
                    Gemini 3.8 Flash
                  </option>
                </select>
              </div>

              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => setDeepMode((d) => !d)}
                  className="inline-flex h-8 items-center gap-2 px-1 text-[13px] font-medium"
                  style={{ color: 'var(--color-body)' }}
                  title={t.deepReactTooltip}
                >
                  <span>Deep ReAct</span>
                  <span
                    className="relative h-4 w-7 transition-colors"
                    style={{
                      background: deepMode ? 'var(--color-ink)' : 'var(--color-hairline-strong)',
                      borderRadius: 'var(--radius-pill)',
                    }}
                  >
                    <span
                      className="absolute top-0.5 left-0.5 h-3 w-3 transition-transform"
                      style={{
                        background: 'var(--color-surface-card)',
                        borderRadius: 'var(--radius-pill)',
                        transform: deepMode ? 'translateX(12px)' : 'translateX(0)',
                      }}
                    />
                  </span>
                </button>

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
                    disabled={!prompt.trim()}
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
              accept=".txt,.md,.csv,.json,.log"
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
      {rightOpen && (
        <RightPanel
          lang={lang}
          workspaceId={activeWsId}
          dossierItems={dossierItems}
          timelineEvents={timelineEvents}
          inspectedSource={inspectedSource}
          targetTerms={currentTargetTerms}
          activeTab={rightTab}
          onTabChange={setRightTab}
          onDossierChanged={async () => {
            if (!activeWsId) return
            const res = await api.listDossier(activeWsId)
            setDossierItems(res.items || [])
          }}
          onSourceUpdated={(updated) => setInspectedSource(updated)}
        />
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
