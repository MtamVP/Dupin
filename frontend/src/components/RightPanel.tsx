import { useState } from 'react'
import {
  AlertTriangle,
  BookmarkCheck,
  Check,
  Clock,
  Download,
  ExternalLink,
  Eye,
  FileSearch,
  FileText,
  Pencil,
  Plus,
  Trash2,
  X,
} from 'lucide-react'
import { api } from '../api'
import { TRANSLATIONS } from '../i18n'
import { safeExternalUrl } from '../utils'
import type { DossierItem, Lang, SourceItem, TimelineEvent } from '../types'

interface Props {
  lang: Lang
  workspaceId: string | null
  dossierItems: DossierItem[]
  timelineEvents: TimelineEvent[]
  inspectedSource: SourceItem | null
  targetTerms: string[]
  activeTab: 'dossier' | 'timeline' | 'inspector'
  onTabChange: (tab: 'dossier' | 'timeline' | 'inspector') => void
  onDossierChanged: () => Promise<void>
  onSourceUpdated: (updated: SourceItem) => void
}

export function RightPanel({
  lang,
  workspaceId,
  dossierItems,
  timelineEvents,
  inspectedSource,
  targetTerms,
  activeTab,
  onTabChange,
  onDossierChanged,
  onSourceUpdated,
}: Props) {
  const t = TRANSLATIONS[lang]

  const [fieldKey, setFieldKey] = useState('')
  const [fieldVal, setFieldVal] = useState('')
  const [sourceUrl, setSourceUrl] = useState('')
  const [manualNotice, setManualNotice] = useState('')
  const [redactExport, setRedactExport] = useState(false)
  const [inspectLoading, setInspectLoading] = useState(false)
  const [inspectError, setInspectError] = useState('')

  // Inline editing state (replaces native browser window.prompt for desktop-app UX)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingVal, setEditingVal] = useState('')

  async function handleManualAdd() {
    if (!workspaceId || !fieldKey.trim() || !fieldVal.trim()) return
    try {
      const saved = await api.addDossier(workspaceId, {
        field_key: fieldKey.trim(),
        field_value: fieldVal.trim(),
        source_url: sourceUrl.trim(),
      })
      if (saved.already_exists) {
        setManualNotice(t.dossierDuplicateNotice)
        setTimeout(() => setManualNotice(''), 3000)
        return
      }
      setFieldKey('')
      setFieldVal('')
      setSourceUrl('')
      setManualNotice('')
      await onDossierChanged()
    } catch (e) {
      setManualNotice(e instanceof Error ? e.message : 'Error')
    }
  }

  async function handleSaveInlineEdit(itemId: string) {
    if (!editingVal.trim()) return
    try {
      await api.updateDossier(itemId, editingVal.trim())
      setEditingId(null)
      setEditingVal('')
      await onDossierChanged()
    } catch (e) {
      setManualNotice(e instanceof Error ? e.message : 'Error')
    }
  }

  async function handleDelete(itemId: string) {
    try {
      await api.deleteDossier(itemId)
      await onDossierChanged()
    } catch (e) {
      setManualNotice(e instanceof Error ? e.message : 'Error')
    }
  }

  async function handleDeepInspectPdf() {
    if (!inspectedSource) return
    setInspectLoading(true)
    setInspectError('')
    try {
      const res = await api.inspectDocument(inspectedSource.url, targetTerms)
      if (!res.ok) {
        setInspectError(res.error || t.inspectDocErrorFallback)
      } else {
        onSourceUpdated({
          ...inspectedSource,
          deep_inspected: true,
          doc_type: res.doc_type,
          scanned_pdf: res.scanned_pages_detected,
          pdf_excerpts: res.excerpts,
        })
      }
    } catch (e) {
      setInspectError(e instanceof Error ? e.message : t.inspectDocErrorFallback)
    } finally {
      setInspectLoading(false)
    }
  }

  function triggerExport(kind: 'obsidian' | 'stix' | 'csv') {
    if (!workspaceId) return
    const q = redactExport ? '?redact=true' : ''
    window.open(`/api/workspaces/${workspaceId}/export/${kind}${kind === 'csv' ? '' : q}`, '_blank')
  }

  return (
    <aside
      className="flex h-full w-92 shrink-0 flex-col border-l"
      style={{ background: 'var(--color-canvas)', borderColor: 'var(--color-hairline)' }}
    >
      {/* Underline Tabs (DESIGN.md: underline tabs, ink active, muted inactive, NO orange/pill) */}
      <div
        className="app-chrome flex items-center gap-4 border-b px-4"
        style={{ borderColor: 'var(--color-hairline)' }}
      >
        {(
          [
            ['dossier', t.tabDossier(dossierItems.length), BookmarkCheck],
            ['timeline', t.tabTimeline(timelineEvents.length), Clock],
            ['inspector', t.tabInspector, Eye],
          ] as const
        ).map(([id, label, Icon]) => {
          const isActive = activeTab === id
          return (
            <button
              key={id}
              onClick={() => onTabChange(id)}
              className="flex h-12 items-center gap-1.5 border-b-2 text-[13px] font-medium transition-colors"
              style={{
                borderColor: isActive ? 'var(--color-ink)' : 'transparent',
                color: isActive ? 'var(--color-ink)' : 'var(--color-muted)',
              }}
            >
              <Icon className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">{label}</span>
            </button>
          )
        })}
      </div>

      {/* Tab 1: Verified Dossier */}
      {activeTab === 'dossier' && (
        <>
          <div
            className="app-chrome flex flex-wrap items-center justify-between gap-2 border-b px-4 py-2.5 text-[12px]"
            style={{ borderColor: 'var(--color-hairline)' }}
          >
            <label className="flex cursor-pointer items-center gap-1.5" style={{ color: 'var(--color-body)' }}>
              <input
                type="checkbox"
                checked={redactExport}
                onChange={(e) => setRedactExport(e.target.checked)}
                style={{ accentColor: 'var(--color-ink)' }}
              />
              <span>{t.redactPiiLabel}</span>
            </label>
            <div className="flex items-center gap-1.5">
              <button
                onClick={() => triggerExport('obsidian')}
                title={t.exportObsidianTitle}
                className="btn-secondary inline-flex h-7 items-center gap-1 px-2 text-[12px]"
              >
                <Download className="h-3 w-3" />
                <span>Obsidian</span>
              </button>
              <button
                onClick={() => triggerExport('stix')}
                title={t.exportStixTitle}
                className="btn-secondary inline-flex h-7 items-center px-2 text-[12px]"
              >
                STIX 2.1
              </button>
              <button
                onClick={() => triggerExport('csv')}
                title={t.exportCsvTitle}
                className="btn-secondary inline-flex h-7 items-center px-2 text-[12px]"
              >
                CSV
              </button>
            </div>
          </div>

          <div className="flex-1 space-y-2.5 overflow-y-auto p-4">
            {dossierItems.length === 0 ? (
              <p className="text-[13px] leading-[1.5]" style={{ color: 'var(--color-muted)' }}>
                {t.dossierEmptyBeforeBold}
                {t.dossierEmptyBold1}
                {t.dossierEmptyMid}
                {t.dossierEmptyBold2}
                {t.dossierEmptyAfter}
              </p>
            ) : (
              dossierItems.map((it) => {
                const isEditing = editingId === it.id
                return (
                  <div
                    key={it.id}
                    className="border p-3"
                    style={{
                      background: 'var(--color-surface-card)',
                      borderColor: 'var(--color-hairline)',
                      borderRadius: 'var(--radius-lg)',
                    }}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-[12px] font-medium" style={{ color: 'var(--color-muted)' }}>
                        {it.field_key}
                      </span>
                      <div className="flex items-center gap-1">
                        {isEditing ? (
                          <>
                            <button
                              onClick={() => handleSaveInlineEdit(it.id)}
                              className="p-1"
                              style={{ color: 'var(--color-semantic-success)' }}
                              title={t.saveBtn}
                            >
                              <Check className="h-3.5 w-3.5" />
                            </button>
                            <button
                              onClick={() => setEditingId(null)}
                              className="p-1"
                              style={{ color: 'var(--color-muted)' }}
                              title={t.cancelBtn}
                            >
                              <X className="h-3.5 w-3.5" />
                            </button>
                          </>
                        ) : (
                          <>
                            <button
                              onClick={() => {
                                setEditingId(it.id)
                                setEditingVal(it.field_value)
                              }}
                              className="p-1"
                              style={{ color: 'var(--color-muted)' }}
                              title={t.editTooltip}
                            >
                              <Pencil className="h-3.5 w-3.5" />
                            </button>
                            <button
                              onClick={() => handleDelete(it.id)}
                              className="p-1"
                              style={{ color: 'var(--color-muted)' }}
                              title={t.deleteTooltip}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </>
                        )}
                      </div>
                    </div>

                    {isEditing ? (
                      <textarea
                        rows={2}
                        autoFocus
                        value={editingVal}
                        onChange={(e) => setEditingVal(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' && !e.shiftKey) {
                            e.preventDefault()
                            handleSaveInlineEdit(it.id)
                          } else if (e.key === 'Escape') {
                            setEditingId(null)
                          }
                        }}
                        className="mt-1.5 w-full border p-2 text-[13px] outline-none"
                        style={{
                          background: 'var(--color-canvas-soft)',
                          borderColor: 'var(--color-hairline-strong)',
                          borderRadius: 'var(--radius-sm)',
                          color: 'var(--color-ink)',
                        }}
                      />
                    ) : (
                      <div className="mt-1 text-[14px] leading-[1.5]" style={{ color: 'var(--color-ink)' }}>
                        {it.field_value}
                      </div>
                    )}

                    {safeExternalUrl(it.source_url) && (
                      <a
                        href={safeExternalUrl(it.source_url)!}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="mt-1.5 inline-flex max-w-full items-center gap-1 truncate font-mono text-[11px] hover:underline"
                        style={{ color: 'var(--color-muted)' }}
                      >
                        <ExternalLink className="h-3 w-3 shrink-0" />
                        <span className="truncate">{it.source_url}</span>
                      </a>
                    )}
                  </div>
                )
              })
            )}
          </div>

          <div
            className="space-y-2 border-t p-4"
            style={{ borderColor: 'var(--color-hairline)', background: 'var(--color-canvas)' }}
          >
            {manualNotice && (
              <div className="text-[12px]" style={{ color: 'var(--color-semantic-error)' }}>
                {manualNotice}
              </div>
            )}
            <div className="flex gap-2">
              <input
                value={fieldKey}
                onChange={(e) => setFieldKey(e.target.value)}
                placeholder={t.dossierKeyPlaceholder}
                className="h-9 w-2/5 border px-2.5 text-[13px] outline-none"
                style={{
                  background: 'var(--color-surface-card)',
                  borderColor: 'var(--color-hairline)',
                  borderRadius: 'var(--radius-md)',
                  color: 'var(--color-ink)',
                }}
              />
              <input
                value={fieldVal}
                onChange={(e) => setFieldVal(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleManualAdd()}
                placeholder={t.dossierValPlaceholder}
                className="h-9 flex-1 border px-2.5 text-[13px] outline-none"
                style={{
                  background: 'var(--color-surface-card)',
                  borderColor: 'var(--color-hairline)',
                  borderRadius: 'var(--radius-md)',
                  color: 'var(--color-ink)',
                }}
              />
            </div>
            <div className="flex gap-2">
              <input
                value={sourceUrl}
                onChange={(e) => setSourceUrl(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleManualAdd()}
                placeholder={t.dossierUrlPlaceholder}
                className="h-9 flex-1 border px-2.5 font-mono text-[12px] outline-none"
                style={{
                  background: 'var(--color-surface-card)',
                  borderColor: 'var(--color-hairline)',
                  borderRadius: 'var(--radius-md)',
                  color: 'var(--color-ink)',
                }}
              />
              <button
                onClick={handleManualAdd}
                disabled={!fieldKey.trim() || !fieldVal.trim()}
                className="btn-secondary inline-flex h-9 items-center gap-1 px-3 text-[13px] disabled:opacity-45"
              >
                <Plus className="h-3.5 w-3.5" />
                <span>{t.addBtn}</span>
              </button>
            </div>
          </div>
        </>
      )}

      {/* Tab 2: Chronological Timeline */}
      {activeTab === 'timeline' && (
        <div className="flex-1 overflow-y-auto p-4">
          {timelineEvents.length === 0 ? (
            <p className="text-[13px] leading-[1.5]" style={{ color: 'var(--color-muted)' }}>
              {t.timelineEmpty}
            </p>
          ) : (
            <div className="relative ml-2 border-l pl-4" style={{ borderColor: 'var(--color-hairline-strong)' }}>
              {timelineEvents.map((ev, idx) => {
                const isConflict = ev.status === 'CONFLICT'
                const isVerified = ev.status === 'VERIFIED'
                return (
                  <div key={`${ev.year}-${idx}`} className="relative mb-4">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[13px] font-medium" style={{ color: 'var(--color-ink)' }}>
                        {ev.date_label}
                      </span>
                      <span
                        className="border px-1.5 py-0.5 font-mono text-[11px]"
                        style={{
                          background: 'var(--color-canvas-soft)',
                          borderColor: 'var(--color-hairline)',
                          borderRadius: 'var(--radius-xs)',
                          color: isConflict
                            ? 'var(--color-semantic-error)'
                            : isVerified
                              ? 'var(--color-semantic-success)'
                              : 'var(--color-muted)',
                        }}
                      >
                        {isConflict ? t.statusConflict : isVerified ? t.statusVerified : t.statusCandidate}
                      </span>
                    </div>
                    <div className="mt-1 text-[13px] leading-[1.5]" style={{ color: 'var(--color-body)' }}>
                      {ev.event}
                    </div>
                    {safeExternalUrl(ev.source_url) && (
                      <a
                        href={safeExternalUrl(ev.source_url)!}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="mt-0.5 inline-flex max-w-full items-center gap-1 truncate font-mono text-[11px] hover:underline"
                        style={{ color: 'var(--color-muted)' }}
                      >
                        <ExternalLink className="h-3 w-3 shrink-0" />
                        <span className="truncate">{ev.source_url}</span>
                      </a>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* Tab 3: Evidence & Deep PDF Inspector */}
      {activeTab === 'inspector' && (
        <div className="flex-1 overflow-y-auto p-4 text-[13px]">
          {!inspectedSource ? (
            <p className="text-[13px] leading-[1.5]" style={{ color: 'var(--color-muted)' }}>
              {t.inspectorEmptyBeforeBold}
              {t.inspectorEmptyBold}
              {t.inspectorEmptyAfter}
            </p>
          ) : (
            <div className="space-y-3">
              <div
                className="border p-3.5"
                style={{
                  background: 'var(--color-surface-card)',
                  borderColor: 'var(--color-hairline)',
                  borderRadius: 'var(--radius-lg)',
                }}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="text-[14px] font-medium leading-snug" style={{ color: 'var(--color-ink)' }}>
                    {inspectedSource.title}
                  </div>
                  {safeExternalUrl(inspectedSource.url) && (
                    <a
                      href={safeExternalUrl(inspectedSource.url)!}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="shrink-0 p-1"
                      style={{ color: 'var(--color-muted)' }}
                      title={t.openOriginalTooltip}
                    >
                      <ExternalLink className="h-3.5 w-3.5" />
                    </a>
                  )}
                </div>
                <div className="mt-1 break-all font-mono text-[11px]" style={{ color: 'var(--color-muted)' }}>
                  {inspectedSource.url}
                </div>
                <div className="mt-2.5 flex flex-wrap gap-1.5">
                  <span
                    className="border px-1.5 py-0.5 font-mono text-[11px]"
                    style={{
                      background: 'var(--color-canvas-soft)',
                      borderColor: 'var(--color-hairline)',
                      borderRadius: 'var(--radius-xs)',
                      color: 'var(--color-ink)',
                    }}
                  >
                    {t.matchScoreLabel(inspectedSource.match_score)}
                  </span>
                  {(inspectedSource.matched_clues || []).map((c) => (
                    <span
                      key={c}
                      className="border px-1.5 py-0.5 font-mono text-[11px]"
                      style={{
                        background: 'var(--color-canvas-soft)',
                        borderColor: 'var(--color-hairline)',
                        borderRadius: 'var(--radius-xs)',
                        color: 'var(--color-body)',
                      }}
                    >
                      {c}
                    </span>
                  ))}
                </div>
              </div>

              <div
                className="border p-3.5"
                style={{
                  background: 'var(--color-surface-card)',
                  borderColor: 'var(--color-hairline)',
                  borderRadius: 'var(--radius-lg)',
                }}
              >
                <div className="mb-1.5 flex items-center gap-1.5 text-[13px] font-medium" style={{ color: 'var(--color-ink)' }}>
                  <FileText className="h-3.5 w-3.5" style={{ color: 'var(--color-muted)' }} />
                  <span>{t.indexedExcerptTitle}</span>
                </div>
                <p className="leading-[1.5]" style={{ color: 'var(--color-body)' }}>
                  {inspectedSource.snippet || t.noSnippetFallback}
                </p>
              </div>

              {(inspectedSource.url.toLowerCase().split('?')[0].match(/\.(pdf|xlsx)$/) ||
                /\/(download|downloadfile|getfile|viewfile|storage\/download|attachments?|tai-file)/i.test(
                  inspectedSource.url,
                ) ||
                /(static2\.vietstock\.vn|cafef1\.mediacdn\.vn)/i.test(inspectedSource.url)) && (
                <button
                  disabled={inspectLoading}
                  onClick={handleDeepInspectPdf}
                  className="btn-secondary flex h-9 w-full items-center justify-center gap-1.5 text-[13px] disabled:opacity-50"
                >
                  <FileSearch className="h-3.5 w-3.5" />
                  <span>{inspectLoading ? t.inspectDocLoading : t.inspectDocBtn}</span>
                </button>
              )}

              {inspectError && (
                <div
                  className="border p-2.5 text-[12px]"
                  style={{
                    background: 'var(--color-surface-card)',
                    borderColor: 'var(--color-hairline)',
                    borderRadius: 'var(--radius-md)',
                    color: 'var(--color-semantic-error)',
                  }}
                >
                  {inspectError}
                </div>
              )}

              {inspectedSource.scanned_pdf && (
                <div
                  className="flex items-start gap-2 border p-2.5 text-[12px]"
                  style={{
                    background: 'var(--color-canvas-soft)',
                    borderColor: 'var(--color-hairline)',
                    borderRadius: 'var(--radius-md)',
                    color: 'var(--color-body)',
                  }}
                >
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <span>
                    {t.scannedPdfNoticeBefore}
                    {t.scannedPdfNoticeBold}
                    {t.scannedPdfNoticeAfter}
                  </span>
                </div>
              )}

              {inspectedSource.pdf_excerpts && inspectedSource.pdf_excerpts.length > 0 && (
                <div className="space-y-2">
                  <div className="caption-uppercase">
                    {t.extractedLinesTitle(inspectedSource.pdf_excerpts.length)}
                  </div>
                  {inspectedSource.pdf_excerpts.map((ex, i) => (
                    <div
                      key={i}
                      className="border p-3"
                      style={{
                        background: 'var(--color-surface-card)',
                        borderColor: 'var(--color-hairline)',
                        borderRadius: 'var(--radius-lg)',
                      }}
                    >
                      <div
                        className="mb-1 flex items-center justify-between font-mono text-[11px]"
                        style={{ color: 'var(--color-muted)' }}
                      >
                        <span>
                          {ex.page ? t.pageLabel(ex.page) : t.sheetRowLabel(ex.sheet || 'Sheet', ex.row || 1)}
                        </span>
                        <span>{t.matchedTermsLabel(ex.matched_terms.join(', '))}</span>
                      </div>
                      <pre
                        className="whitespace-pre-wrap font-mono text-[12px] leading-[1.5]"
                        style={{ color: 'var(--color-ink)' }}
                      >
                        {ex.context}
                      </pre>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </aside>
  )
}
