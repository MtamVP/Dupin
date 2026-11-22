import { useEffect, useState } from 'react'
import { Check, Copy, Cpu, KeyRound, Layers, Lock, Plug, Puzzle, Server, Trash2, X } from 'lucide-react'
import { api } from '../api'
import { TRANSLATIONS } from '../i18n'
import type { APIKeyItem, Lang, LocalHostConfig, PipelineArchitectureInfo, PluginInfo } from '../types'

interface Props {
  lang: Lang
  open: boolean
  onClose: () => void
  onPluginsUpdated?: (plugins: PluginInfo[]) => void
}

type TabKey = 'keys' | 'local' | 'plugins' | 'pipeline' | 'mcp'

export function IntegrationsModal({ lang, open, onClose, onPluginsUpdated }: Props) {
  const t = TRANSLATIONS[lang]

  const [tab, setTab] = useState<TabKey>('keys')
  const [keys, setKeys] = useState<APIKeyItem[]>([])
  const [plugins, setPlugins] = useState<PluginInfo[]>([])
  const [archInfo, setArchInfo] = useState<PipelineArchitectureInfo | null>(null)
  const [localCfg, setLocalCfg] = useState<LocalHostConfig>({
    active_mode: 'auto',
    ollama_base_url: 'http://localhost:11434',
    ollama_model: 'qwen2.5:7b',
    searxng_url: '',
  })
  const [mcpCfg, setMcpCfg] = useState({
    antigravity_config: '',
    claude_code_cli: '',
    codex_cursor_config: '',
  })

  // New key form
  const [kName, setKName] = useState('')
  const [kProvider, setKProvider] = useState<'gemini' | 'openai' | 'serper' | 'tavily' | 'github'>('gemini')
  const [kSecret, setKSecret] = useState('')
  const [kModel, setKModel] = useState('')

  // Probe statuses
  const [ollamaStatus, setOllamaStatus] = useState('')
  const [searxStatus, setSearxStatus] = useState<{ ok: boolean; warn?: boolean; msg: string } | null>(null)
  const [saveMsg, setSaveMsg] = useState('')
  const [mcpTestMsg, setMcpTestMsg] = useState('')
  const [copiedId, setCopiedId] = useState('')

  async function refreshAll() {
    const [kRes, lRes, pRes, mRes, aRes] = await Promise.all([
      api.listKeys(),
      api.getLocalHost(),
      api.listPlugins(),
      api.getMcpConfig(),
      api.getPipelineArchitecture().catch(() => null),
    ])
    setKeys(kRes.keys || [])
    setLocalCfg(lRes)
    setPlugins(pRes.plugins || [])
    onPluginsUpdated?.(pRes.plugins || [])
    setMcpCfg(mRes)
    if (aRes) setArchInfo(aRes)
  }

  useEffect(() => {
    if (!open) return
    refreshAll().catch(() => undefined)
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  async function handleAddKey() {
    if (!kName.trim() || !kSecret.trim()) return
    try {
      await api.addKey({
        name: kName.trim(),
        provider: kProvider,
        api_key: kSecret.trim(),
        model: kModel.trim(),
      })
      setKName('')
      setKSecret('')
      setKModel('')
      const res = await api.listKeys()
      setKeys(res.keys || [])
    } catch (e) {
      setSaveMsg(e instanceof Error ? e.message : 'Error')
    }
  }

  async function handleToggleKey(id: string, enabled: boolean) {
    try {
      await api.toggleKey(id, enabled)
      const res = await api.listKeys()
      setKeys(res.keys || [])
    } catch {
      // ignore transient error
    }
  }

  async function handleDeleteKey(id: string) {
    try {
      await api.deleteKey(id)
      const res = await api.listKeys()
      setKeys(res.keys || [])
    } catch {
      // ignore transient error
    }
  }

  async function handleSaveLocal() {
    try {
      await api.saveLocalHost(localCfg)
      setSaveMsg(t.savedLocalHostMsg)
      const pRes = await api.listPlugins()
      setPlugins(pRes.plugins || [])
      onPluginsUpdated?.(pRes.plugins || [])
      setTimeout(() => setSaveMsg(''), 3000)
    } catch (e) {
      setSaveMsg(e instanceof Error ? e.message : 'Error')
    }
  }

  async function handleProbeOllama() {
    setOllamaStatus(t.ollamaScanning)
    try {
      const res = await api.probeOllama(localCfg.ollama_base_url)
      setOllamaStatus(
        res.reachable
          ? t.ollamaModelsResult(res.models.join(', ') || t.ollamaNoModels)
          : t.ollamaUnreachable(localCfg.ollama_base_url),
      )
    } catch {
      setOllamaStatus(t.ollamaUnreachable(localCfg.ollama_base_url))
    }
  }

  async function handleProbeSearxng() {
    const target = localCfg.searxng_url.trim() || 'http://localhost:8888'
    setLocalCfg((c) => ({ ...c, searxng_url: target }))
    setSearxStatus({ ok: false, msg: t.searxngTesting })
    try {
      const res = await api.probeSearxng(target)
      if (res.reachable && res.json_enabled) {
        const eng = res.engines.length ? ` · Engines: ${res.engines.join(', ')}` : ''
        setSearxStatus({ ok: true, msg: t.searxngOk(res.sample_count, eng) })
      } else if (res.reachable && !res.json_enabled) {
        setSearxStatus({ ok: false, warn: true, msg: res.error })
      } else {
        setSearxStatus({ ok: false, msg: t.searxngFail(target) })
      }
    } catch {
      setSearxStatus({ ok: false, msg: t.searxngFail(target) })
    }
  }

  async function handleTestMcp() {
    try {
      const res = await api.testMcp()
      const names = (res.result?.tools || []).map((tool) => tool.name)
      setMcpTestMsg(t.mcpTestResult(names.length, names.join(', ')))
    } catch (e) {
      setMcpTestMsg(e instanceof Error ? e.message : 'MCP Error')
    }
  }

  function copyStr(id: string, text: string) {
    navigator.clipboard.writeText(text)
    setCopiedId(id)
    setTimeout(() => setCopiedId(''), 1500)
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-xs"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        className="flex h-[85vh] max-h-[760px] w-full max-w-3xl flex-col overflow-hidden rounded-xl border"
        style={{ background: 'var(--color-surface-card)', borderColor: 'var(--color-hairline-strong)' }}
      >
        <div
          className="app-chrome flex shrink-0 items-center justify-between border-b px-4 py-3"
          style={{ borderColor: 'var(--border)' }}
        >
          <div className="flex items-center gap-2 text-sm font-semibold">
            <Plug className="h-4 w-4 text-blue-500" />
            <span>{t.hubTitle}</span>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1 text-slate-400 hover:bg-white/10 hover:text-white"
            title={t.cancelBtn}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Tabs */}
        <div
          className="app-chrome flex shrink-0 flex-wrap gap-1.5 border-b px-4 py-2.5"
          style={{ borderColor: 'var(--border)', background: 'var(--bg-sidebar)' }}
        >
          {(
            [
              ['keys', t.hubTabKeys, KeyRound],
              ['local', t.hubTabLocal, Server],
              ['plugins', t.hubTabPlugins(plugins.length), Puzzle],
              ['pipeline', t.hubTabPipeline, Layers],
              ['mcp', t.hubTabMcp, Cpu],
            ] as const
          ).map(([id, label, Icon]) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className="flex h-8 items-center gap-1.5 rounded-lg border px-3 text-xs font-medium transition"
              style={{
                background: tab === id ? 'var(--accent-soft)' : 'transparent',
                borderColor: tab === id ? 'var(--accent)' : 'var(--border)',
                color: tab === id ? 'var(--accent)' : 'var(--ink-secondary)',
              }}
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
            </button>
          ))}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {tab === 'keys' && (
            <div className="flex flex-col gap-3">
              <div
                className="flex items-center gap-2 rounded-xl border px-3 py-2 text-xs"
                style={{ background: 'var(--ok-soft)', borderColor: 'transparent', color: 'var(--ok)' }}
              >
                <Lock className="h-3.5 w-3.5 shrink-0" />
                <span>
                  {t.fernetNoticeBefore}
                  <b>{t.fernetNoticeBold}</b>
                  {t.fernetNoticeAfter}
                </span>
              </div>

              <div
                className="flex flex-col gap-2 rounded-xl border p-3"
                style={{ background: 'var(--bg-sidebar)', borderColor: 'var(--border)' }}
              >
                <div className="flex gap-2">
                  <input
                    value={kName}
                    onChange={(e) => setKName(e.target.value)}
                    placeholder={t.keyNamePlaceholder}
                    className="h-8 flex-1 rounded-lg border px-2.5 text-xs outline-none"
                    style={{ background: 'var(--bg)', borderColor: 'var(--border-strong)', color: 'var(--ink)' }}
                  />
                  <select
                    value={kProvider}
                    onChange={(e) => setKProvider(e.target.value as APIKeyItem['provider'])}
                    className="h-8 rounded-lg border px-2 text-xs outline-none"
                    style={{ background: 'var(--bg)', borderColor: 'var(--border-strong)', color: 'var(--ink)' }}
                  >
                    <option value="gemini">Gemini</option>
                    <option value="serper">Serper (Google Search)</option>
                    <option value="openai">OpenAI / Compatible</option>
                    <option value="github">GitHub Token</option>
                  </select>
                </div>
                <div className="flex gap-2">
                  <input
                    type="password"
                    value={kSecret}
                    onChange={(e) => setKSecret(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleAddKey()}
                    placeholder={t.keySecretPlaceholder}
                    className="h-8 flex-1 rounded-lg border px-2.5 text-xs outline-none"
                    style={{ background: 'var(--bg)', borderColor: 'var(--border-strong)', color: 'var(--ink)' }}
                  />
                  <input
                    value={kModel}
                    onChange={(e) => setKModel(e.target.value)}
                    placeholder={t.keyModelPlaceholder}
                    className="h-8 w-44 rounded-lg border px-2.5 text-xs outline-none"
                    style={{ background: 'var(--bg)', borderColor: 'var(--border-strong)', color: 'var(--ink)' }}
                  />
                  <button
                    onClick={handleAddKey}
                    disabled={!kName.trim() || !kSecret.trim()}
                    className="h-8 rounded-lg bg-blue-600 px-3 text-xs font-medium text-white transition hover:bg-blue-500 disabled:opacity-45"
                  >
                    {t.addKeyBtn}
                  </button>
                </div>
              </div>

              <div className="flex flex-col gap-2">
                {keys.length === 0 ? (
                  <div
                    className="rounded-xl border border-dashed p-5 text-center text-xs"
                    style={{ borderColor: 'var(--border)', color: 'var(--ink-muted)' }}
                  >
                    {t.noKeysEmpty}
                  </div>
                ) : (
                  keys.map((k) => (
                    <div
                      key={k.id}
                      className="flex items-center justify-between gap-2 rounded-xl border px-3 py-2 text-xs"
                      style={{ background: 'var(--bg-sidebar)', borderColor: 'var(--border)' }}
                    >
                      <div>
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="font-semibold">{k.name}</span>
                          <span
                            className="rounded px-1.5 py-0.5 font-mono text-[10px]"
                            style={{ background: 'var(--bg-subtle)', color: 'var(--ink-secondary)' }}
                          >
                            {k.provider}
                          </span>
                          <span
                            className="rounded px-1.5 py-0.5 font-mono text-[10px]"
                            style={{
                              background: k.status === 'ACTIVE' ? 'var(--ok-soft)' : 'var(--neg-soft)',
                              color: k.status === 'ACTIVE' ? 'var(--ok)' : 'var(--neg)',
                            }}
                          >
                            {k.status}
                          </span>
                          {k.encrypted && (
                            <span
                              className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 font-mono text-[10px]"
                              style={{ background: 'var(--accent-soft)', color: 'var(--accent)' }}
                            >
                              <Lock className="h-2.5 w-2.5" />
                              Fernet
                            </span>
                          )}
                        </div>
                        <div className="mt-1 font-mono text-[11px]" style={{ color: 'var(--ink-muted)' }}>
                          {k.masked_key} {k.model ? `· ${k.model}` : ''} · {t.keyUsageLabel(k.usage_count, k.error_count)}
                        </div>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <button
                          onClick={() => handleToggleKey(k.id, !k.enabled)}
                          className="h-7 rounded border px-2 text-[11px] transition hover:border-blue-500"
                          style={{ borderColor: 'var(--border-strong)', color: 'var(--ink-secondary)' }}
                        >
                          {k.enabled ? t.disableBtn : t.enableBtn}
                        </button>
                        <button
                          onClick={() => handleDeleteKey(k.id)}
                          className="rounded p-1.5 text-red-400 hover:bg-red-500/10"
                          title={t.deleteKeyTooltip}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}

          {tab === 'local' && (
            <div className="flex flex-col gap-3 text-xs">
              <div>
                <label className="mb-1 block font-medium" style={{ color: 'var(--ink-secondary)' }}>
                  {t.orchestrationModeLabel}
                </label>
                <select
                  value={localCfg.active_mode}
                  onChange={(e) =>
                    setLocalCfg({ ...localCfg, active_mode: e.target.value as LocalHostConfig['active_mode'] })
                  }
                  className="h-9 w-full rounded-lg border px-2.5 text-xs outline-none"
                  style={{ background: 'var(--bg)', borderColor: 'var(--border-strong)', color: 'var(--ink)' }}
                >
                  <option value="auto">{t.modeAuto}</option>
                  <option value="gemini_pool">{t.modeGeminiPool}</option>
                  <option value="ollama_local">{t.modeOllamaLocal}</option>
                  <option value="metasearch_only">{t.modeMetasearchOnly}</option>
                </select>
              </div>

              <div>
                <label className="mb-1 block font-medium" style={{ color: 'var(--ink-secondary)' }}>
                  {t.ollamaHostLabel}
                </label>
                <div className="flex gap-2">
                  <input
                    value={localCfg.ollama_base_url}
                    onChange={(e) => setLocalCfg({ ...localCfg, ollama_base_url: e.target.value })}
                    className="h-9 flex-1 rounded-lg border px-3 text-xs outline-none"
                    style={{ background: 'var(--bg)', borderColor: 'var(--border-strong)', color: 'var(--ink)' }}
                  />
                  <button
                    onClick={handleProbeOllama}
                    className="h-9 rounded-lg border px-3 font-medium transition hover:border-blue-500"
                    style={{ borderColor: 'var(--border-strong)', color: 'var(--ink)' }}
                  >
                    {t.probeOllamaBtn}
                  </button>
                </div>
                <input
                  value={localCfg.ollama_model}
                  onChange={(e) => setLocalCfg({ ...localCfg, ollama_model: e.target.value })}
                  placeholder={t.ollamaModelPlaceholder}
                  className="mt-2 h-9 w-full rounded-lg border px-3 text-xs outline-none"
                  style={{ background: 'var(--bg)', borderColor: 'var(--border-strong)', color: 'var(--ink)' }}
                />
                {ollamaStatus && (
                  <div className="mt-1 text-[11px]" style={{ color: 'var(--ink-muted)' }}>
                    {ollamaStatus}
                  </div>
                )}
              </div>

              <div>
                <label className="mb-1 block font-medium" style={{ color: 'var(--ink-secondary)' }}>
                  {t.searxngLabel}
                </label>
                <div className="flex gap-2">
                  <input
                    value={localCfg.searxng_url}
                    onChange={(e) => setLocalCfg({ ...localCfg, searxng_url: e.target.value })}
                    placeholder="http://localhost:8888"
                    className="h-9 flex-1 rounded-lg border px-3 text-xs outline-none"
                    style={{ background: 'var(--bg)', borderColor: 'var(--border-strong)', color: 'var(--ink)' }}
                  />
                  <button
                    onClick={handleProbeSearxng}
                    className="h-9 rounded-lg border px-3 font-medium transition hover:border-blue-500"
                    style={{ borderColor: 'var(--border-strong)', color: 'var(--ink)' }}
                  >
                    {t.testSearxngBtn}
                  </button>
                </div>
                {searxStatus ? (
                  <div
                    className="mt-1.5 text-[11px]"
                    style={{
                      color: searxStatus.ok
                        ? 'var(--ok)'
                        : searxStatus.warn
                          ? 'var(--warn)'
                          : 'var(--neg)',
                    }}
                  >
                    {searxStatus.msg}
                  </div>
                ) : (
                  <div className="mt-1.5 text-[11px]" style={{ color: 'var(--ink-muted)' }}>
                    {t.searxngHintPrefix}
                    <code className="font-mono">docker compose up -d</code>
                    {t.searxngHintOr}
                    <code className="font-mono">cd searxng &amp;&amp; docker compose up -d</code>
                  </div>
                )}
              </div>

              <div className="flex items-center justify-between pt-2">
                <span className="text-[11px]" style={{ color: 'var(--ok)' }}>
                  {saveMsg}
                </span>
                <button
                  onClick={handleSaveLocal}
                  className="h-9 rounded-lg bg-blue-600 px-4 font-semibold text-white transition hover:bg-blue-500"
                >
                  {t.saveLocalHostBtn}
                </button>
              </div>
            </div>
          )}

          {tab === 'plugins' && (
            <div className="flex flex-col gap-2.5">
              <div className="text-xs" style={{ color: 'var(--ink-secondary)' }}>
                {t.pluginsHeaderBefore}
                <code className="font-mono">backend/app/plugins/</code>
                {t.pluginsHeaderMid}
                <code className="font-mono">plugins/</code>
                {t.pluginsHeaderAfter}
              </div>
              {plugins.map((p) => (
                <div
                  key={p.id}
                  className="rounded-xl border p-3 text-xs"
                  style={{ background: 'var(--bg-sidebar)', borderColor: 'var(--border)' }}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold">{p.name}</span>
                      <span
                        className="rounded px-1.5 py-0.5 font-mono text-[10px]"
                        style={{ background: 'var(--bg-subtle)', color: 'var(--ink-secondary)' }}
                      >
                        {p.category} · v{p.version}
                      </span>
                    </div>
                    <span
                      className="rounded px-2 py-0.5 font-mono text-[10px] font-medium"
                      style={{
                        background: p.health.ready ? 'var(--ok-soft)' : 'var(--neg-soft)',
                        color: p.health.ready ? 'var(--ok)' : 'var(--neg)',
                      }}
                    >
                      {p.health.ready ? 'READY' : 'OFFLINE'}
                    </span>
                  </div>
                  <p className="mt-1 text-[11px] leading-relaxed" style={{ color: 'var(--ink-secondary)' }}>
                    {p.description}
                  </p>
                  <div className="mt-1.5 font-mono text-[10px]" style={{ color: 'var(--ink-muted)' }}>
                    {p.health.detail}
                  </div>
                </div>
              ))}
            </div>
          )}

          {tab === 'pipeline' && (
            <div className="flex flex-col gap-3 text-xs">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-semibold">{t.pipelineHeader}</span>
                {archInfo && (
                  <span
                    className="rounded px-2 py-0.5 font-mono text-[10px] font-semibold"
                    style={{
                      background: archInfo.username_engine.manifest.valid ? 'var(--ok-soft)' : 'var(--neg-soft)',
                      color: archInfo.username_engine.manifest.valid ? 'var(--ok)' : 'var(--neg)',
                    }}
                  >
                    {archInfo.username_engine.manifest.valid ? t.pipelineValidBadge : t.pipelineInvalidBadge}
                  </span>
                )}
              </div>

              {archInfo && (
                <>
                  <div
                    className="rounded-xl border px-3 py-2 font-mono text-[11px]"
                    style={{ background: 'var(--accent-soft)', borderColor: 'transparent', color: 'var(--accent)' }}
                  >
                    {t.pipelineManifestSummary(
                      archInfo.username_engine.manifest.total_sites,
                      archInfo.username_engine.manifest.verified_json_api_sites,
                      archInfo.username_engine.circuit_breaker.open_count,
                    )}
                  </div>

                  <div className="space-y-2">
                    {archInfo.layers.map((ly) => {
                      const isCore = ly.ring === 'innermost_core'
                      const isShield = ly.ring === 'outer_filter'
                      return (
                        <div
                          key={ly.layer}
                          className="rounded-xl border p-3"
                          style={{
                            background: 'var(--bg-sidebar)',
                            borderColor: isCore
                              ? 'rgba(59,130,246,0.5)'
                              : isShield
                                ? 'rgba(245,158,11,0.45)'
                                : 'var(--border)',
                          }}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-2">
                              <span
                                className="rounded px-1.5 py-0.5 font-mono text-[10px] font-bold"
                                style={{
                                  background: isCore
                                    ? 'var(--accent-soft)'
                                    : isShield
                                      ? 'var(--warn-soft)'
                                      : 'var(--bg-subtle)',
                                  color: isCore
                                    ? 'var(--accent)'
                                    : isShield
                                      ? 'var(--warn)'
                                      : 'var(--ink)',
                                }}
                              >
                                L{ly.layer}
                              </span>
                              <span className="font-semibold">{ly.name}</span>
                            </div>
                            <code className="font-mono text-[10px]" style={{ color: 'var(--ink-muted)' }}>
                              {ly.module}
                            </code>
                          </div>
                          <ul className="mt-1.5 list-disc space-y-0.5 pl-4 text-[11px]" style={{ color: 'var(--ink-secondary)' }}>
                            {ly.responsibilities.map((r, ri) => (
                              <li key={ri}>{r}</li>
                            ))}
                          </ul>
                        </div>
                      )
                    })}
                  </div>
                </>
              )}
            </div>
          )}

          {tab === 'mcp' && (
            <div className="flex flex-col gap-3 text-xs">
              <div className="flex items-center justify-between gap-2">
                <span style={{ color: 'var(--ink-secondary)' }}>{t.mcpHeader}</span>
                <button
                  onClick={handleTestMcp}
                  className="h-8 rounded-lg border px-3 text-xs font-medium transition hover:border-blue-500"
                  style={{ borderColor: 'var(--border-strong)', color: 'var(--ink)' }}
                >
                  {t.testMcpBtn}
                </button>
              </div>
              {mcpTestMsg && (
                <div className="font-mono text-[11px]" style={{ color: 'var(--accent)' }}>
                  {mcpTestMsg}
                </div>
              )}

              {(
                [
                  ['ag', 'Antigravity (mcp_config.json)', mcpCfg.antigravity_config],
                  ['cl', 'Claude Code (CLI)', mcpCfg.claude_code_cli],
                  ['cx', 'Codex / Cursor (HTTP MCP)', mcpCfg.codex_cursor_config],
                ] as const
              ).map(([id, title, code]) => (
                <div key={id}>
                  <div className="mb-1 flex items-center justify-between">
                    <span className="font-semibold">{title}</span>
                    <button
                      onClick={() => copyStr(id, code)}
                      className="inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[11px] transition hover:border-blue-500"
                      style={{ borderColor: 'var(--border-strong)', color: 'var(--ink-secondary)' }}
                    >
                      {copiedId === id ? <Check className="h-3 w-3 text-green-400" /> : <Copy className="h-3 w-3" />}
                      {copiedId === id ? t.copiedBtn : t.copyBtn}
                    </button>
                  </div>
                  <pre
                    className="overflow-x-auto rounded-xl border p-2.5 font-mono text-[11px]"
                    style={{ background: 'var(--bg-sidebar)', borderColor: 'var(--border)' }}
                  >
                    {code}
                  </pre>
                </div>
              ))}

              <div
                className="rounded-xl border p-3"
                style={{ background: 'var(--bg-sidebar)', borderColor: 'var(--border)' }}
              >
                <div className="font-semibold">{t.extCardTitle}</div>
                <p className="mt-1 text-[11px] leading-relaxed" style={{ color: 'var(--ink-secondary)' }}>
                  {t.extCardBody}
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
