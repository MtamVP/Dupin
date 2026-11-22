import { useEffect, useState } from 'react'
import { MapPin, Search, X } from 'lucide-react'
import { TRANSLATIONS } from '../i18n'
import type { GeoPoint, Lang } from '../types'

interface Props {
  lang: Lang
  open: boolean
  onClose: () => void
  onSelect: (point: GeoPoint) => void
}

export function MapPickerModal({ lang, open, onClose, onSelect }: Props) {
  const t = TRANSLATIONS[lang]
  const [query, setQuery] = useState('')
  const [lat, setLat] = useState(10.762622)
  const [lng, setLng] = useState(106.660172)
  const [label, setLabel] = useState(lang === 'vi' ? 'TP. Hồ Chí Minh' : 'Ho Chi Minh City')
  const [status, setStatus] = useState('')
  const [mapSrc, setMapSrc] = useState('https://maps.google.com/maps?q=10.762622,106.660172&z=13&output=embed')

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  async function searchAddress() {
    const q = query.trim()
    if (!q) return
    const coordMatch = q.match(/(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)/)
    if (coordMatch) {
      const nLat = parseFloat(coordMatch[1])
      const nLng = parseFloat(coordMatch[2])
      setLat(nLat)
      setLng(nLng)
      setLabel(q)
      setMapSrc(`https://maps.google.com/maps?q=${nLat},${nLng}&z=15&output=embed`)
      setStatus(t.mapLockedCoords(nLat.toFixed(5), nLng.toFixed(5)))
      return
    }
    setMapSrc(`https://maps.google.com/maps?q=${encodeURIComponent(q)}&z=15&output=embed`)
    setLabel(q)
    setStatus(t.mapLocating)
    try {
      const res = await fetch(
        `https://nominatim.openstreetmap.org/search?format=json&limit=1&q=${encodeURIComponent(q)}`,
      )
      const arr = await res.json()
      if (Array.isArray(arr) && arr.length > 0) {
        const nLat = parseFloat(arr[0].lat)
        const nLng = parseFloat(arr[0].lon)
        setLat(nLat)
        setLng(nLng)
        setLabel(arr[0].display_name?.split(',').slice(0, 2).join(', ') || q)
        setStatus(t.mapFoundCoords(nLat.toFixed(5), nLng.toFixed(5)))
      } else {
        setStatus(t.mapShownFallback)
      }
    } catch {
      setStatus(t.mapShownSimple)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-xs"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        className="flex w-full max-w-2xl flex-col overflow-hidden rounded-xl border"
        style={{ background: 'var(--color-surface-card)', borderColor: 'var(--color-hairline-strong)' }}
      >
        <div
          className="app-chrome flex items-center justify-between border-b px-4 py-3"
          style={{ borderColor: 'var(--border)' }}
        >
          <div className="flex items-center gap-2 text-sm font-semibold">
            <MapPin className="h-4 w-4 text-blue-500" />
            <span>{t.mapTitle}</span>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1 text-slate-400 hover:bg-white/10 hover:text-white"
            title={t.cancelBtn}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex flex-col gap-3 p-4">
          <div className="flex gap-2">
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && searchAddress()}
              placeholder={t.mapPlaceholder}
              className="h-9 flex-1 rounded-lg border px-3 text-sm outline-none focus:border-blue-500"
              style={{ background: 'var(--bg)', borderColor: 'var(--border-strong)', color: 'var(--ink)' }}
            />
            <button
              onClick={searchAddress}
              className="flex h-9 items-center gap-1.5 rounded-lg bg-blue-600 px-3.5 text-xs font-medium text-white transition hover:bg-blue-500"
            >
              <Search className="h-3.5 w-3.5" />
              {t.mapSearchBtn}
            </button>
          </div>

          <iframe
            title="Google Maps Picker"
            src={mapSrc}
            className="h-80 w-full rounded-xl border"
            style={{ borderColor: 'var(--border)' }}
            loading="lazy"
          />

          <div className="flex items-center justify-between gap-2 text-xs">
            <span className="font-mono text-[11px]" style={{ color: 'var(--ink-secondary)' }}>
              {status || t.mapCurrentCoords(lat.toFixed(5), lng.toFixed(5))}
            </span>
            <div className="flex gap-2">
              <button
                onClick={onClose}
                className="h-8 rounded-lg border px-3 text-xs font-medium transition hover:bg-white/5"
                style={{ borderColor: 'var(--border-strong)', color: 'var(--ink-secondary)' }}
              >
                {t.cancelBtn}
              </button>
              <button
                onClick={() => {
                  onSelect({ lat, lng, label: label || `${lat.toFixed(4)}, ${lng.toFixed(4)}` })
                  onClose()
                }}
                className="h-8 rounded-lg bg-blue-600 px-3.5 text-xs font-semibold text-white transition hover:bg-blue-500"
              >
                {t.mapAttachBtn}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
