/** Sanitize external href values to allow only http:// and https:// (blocks javascript:/data: XSS). */
export function safeExternalUrl(raw?: string): string | null {
  const s = String(raw || '').trim()
  if (!s) return null
  try {
    const parsed = new URL(s)
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return parsed.href
    }
  } catch {
    return null
  }
  return null
}
