import type {
  APIKeyItem,
  AssistantPayload,
  ChatMessage,
  DossierItem,
  GeoPoint,
  LocalHostConfig,
  PipelineArchitectureInfo,
  PluginInfo,
  Workspace,
} from './types'

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    const txt = await res.text().catch(() => res.statusText)
    throw new Error(txt || `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  listWorkspaces: () => jsonFetch<Workspace[]>('/api/workspaces'),
  createWorkspace: (name: string) =>
    jsonFetch<Workspace>('/api/workspaces', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, description: 'OSINT Agent Session' }),
    }),
  renameWorkspace: (id: string, name: string) =>
    jsonFetch<Workspace>(`/api/workspaces/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    }),
  deleteWorkspace: (id: string) =>
    jsonFetch<{ deleted: boolean }>(`/api/workspaces/${id}`, { method: 'DELETE' }),

  listMessages: (workspaceId: string) =>
    jsonFetch<{ messages: ChatMessage[] }>(`/api/workspaces/${workspaceId}/messages`),

  listDossier: (workspaceId: string) =>
    jsonFetch<{ items: DossierItem[] }>(`/api/workspaces/${workspaceId}/dossier`),
  addDossier: (
    workspaceId: string,
    payload: { field_key: string; field_value: string; source_url?: string; category?: string },
  ) =>
    jsonFetch<DossierItem>(`/api/workspaces/${workspaceId}/dossier`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  updateDossier: (itemId: string, field_value: string) =>
    jsonFetch<DossierItem>(`/api/dossier/${itemId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ field_value }),
    }),
  deleteDossier: (itemId: string) =>
    jsonFetch<{ deleted: boolean }>(`/api/dossier/${itemId}`, { method: 'DELETE' }),

  listKeys: () => jsonFetch<{ keys: APIKeyItem[] }>('/api/integrations/keys'),
  addKey: (payload: { name: string; provider: string; api_key: string; model?: string }) =>
    jsonFetch<APIKeyItem>('/api/integrations/keys', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  toggleKey: (id: string, enabled: boolean) =>
    jsonFetch<APIKeyItem>(`/api/integrations/keys/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    }),
  deleteKey: (id: string) =>
    jsonFetch<{ deleted: boolean }>(`/api/integrations/keys/${id}`, { method: 'DELETE' }),

  getLocalHost: () => jsonFetch<LocalHostConfig>('/api/integrations/local'),
  saveLocalHost: (cfg: LocalHostConfig) =>
    jsonFetch<LocalHostConfig>('/api/integrations/local', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cfg),
    }),
  probeOllama: (baseUrl: string) =>
    jsonFetch<{ reachable: boolean; models: string[]; error?: string }>(
      `/api/integrations/ollama/models?base_url=${encodeURIComponent(baseUrl)}`,
    ),
  probeSearxng: (baseUrl: string) =>
    jsonFetch<{
      reachable: boolean
      json_enabled: boolean
      sample_count: number
      engines: string[]
      error: string
    }>(`/api/integrations/searxng/test?base_url=${encodeURIComponent(baseUrl)}`),

  listPlugins: () => jsonFetch<{ plugins: PluginInfo[] }>('/api/plugins'),
  getPipelineArchitecture: () => jsonFetch<PipelineArchitectureInfo>('/api/pipeline/architecture'),
  getMcpConfig: () =>
    jsonFetch<{
      http_endpoint: string
      stdio_command: string
      antigravity_config: string
      claude_code_cli: string
      codex_cursor_config: string
    }>('/api/integrations/mcp-config'),
  testMcp: () =>
    jsonFetch<{ result?: { tools?: { name: string }[] } }>('/api/mcp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list' }),
    }),

  inspectDocument: (url: string, target_terms: string[]) =>
    jsonFetch<{
      ok: boolean
      url: string
      doc_type?: string
      total_pages?: number
      scanned_pages_detected?: boolean
      header_hint?: string
      excerpts: { page?: number; sheet?: string; row?: number; matched_terms: string[]; line: string; context: string }[]
      error?: string
    }>('/api/tools/inspect-document', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, target_terms }),
    }),

  streamChat: async (
    workspaceId: string,
    body: {
      prompt: string
      live_search: boolean
      deep_mode: boolean
      model_override: string
      image_b64?: string | null
      image_mime?: string
      geo_point?: GeoPoint | null
      attached_file_text?: string | null
    },
    onStatus: (line: string) => void,
    onDone: (payload: AssistantPayload) => void,
    signal?: AbortSignal,
  ) => {
    const res = await fetch(`/api/workspaces/${workspaceId}/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    })
    if (!res.ok || !res.body) {
      throw new Error(`HTTP ${res.status}`)
    }
    const reader = res.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const blocks = buffer.split('\n\n')
      buffer = blocks.pop() || ''
      for (const block of blocks) {
        const evMatch = block.match(/event:\s*(\w+)/)
        const dataMatch = block.match(/data:\s*(.+)/s)
        if (!evMatch || !dataMatch) continue
        const evType = evMatch[1]
        let payload: Record<string, unknown>
        try {
          payload = JSON.parse(dataMatch[1])
        } catch {
          continue
        }
        if (evType === 'status') onStatus(String(payload.step || ''))
        else if (evType === 'step') onStatus(`[${payload.agent}] ${payload.action}: ${payload.detail}`)
        else if (evType === 'error') throw new Error(String(payload.error || 'Investigation stream error'))
        else if (evType === 'done') onDone(payload as unknown as AssistantPayload)
      }
    }
  },
}
