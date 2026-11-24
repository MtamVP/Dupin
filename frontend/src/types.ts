export type Lang = 'vi' | 'en'
export type ThemeMode = 'dark' | 'light'

export interface Workspace {
  id: string
  name: string
  description: string
  pinned?: boolean
  search_summary?: string
  last_active_at?: string
  created_at: string
}

export interface PdfExcerpt {
  page?: number
  sheet?: string
  row?: number
  matched_terms: string[]
  line: string
  context: string
}

export interface SourceItem {
  title: string
  url: string
  snippet: string
  match_score: number
  matched_clues?: string[]
  deep_inspected?: boolean
  doc_type?: string
  scanned_pdf?: boolean
  pdf_excerpts?: PdfExcerpt[]
}

export interface DorkItem {
  strategy: string
  query: string
}

export interface ReasoningStep {
  agent: string
  action: string
  detail: string
  timestamp?: string
}

export interface TimelineEvent {
  year: number
  date_label: string
  event: string
  source_url: string
  status: 'VERIFIED' | 'CANDIDATE' | 'CONFLICT'
}

export interface DisambiguationCard {
  title: string
  url: string
  reason: string
  suggested_negative: string
  snippet: string
}

export interface ParsedClues {
  target_name?: string
  birth_date?: string
  birth_year?: number | null
  organizations?: string[]
  locations?: string[]
  aliases?: string[]
  keywords?: string[]
  negative_keywords?: string[]
  related_people?: { name: string; relation: string }[]
}

export interface GatekeeperStats {
  total_inspected: number
  accepted: number
  rejected: number
  rejected_by_reason: Record<string, number>
}

export interface InvestigationBranchNode {
  branch_id: string
  parent_id?: string | null
  depth: number
  hypothesis_type: string
  label: string
  query?: string
  status: string
  score: number
  discovered_facts?: Record<string, unknown>
  evidence_urls?: string[]
  conflict_reason?: string
  children_ids?: string[]
}

export interface InvestigationTreeTelemetry {
  activated: boolean
  activation_reason: string
  total_branches: number
  backtracked_count: number
  pruned_count: number
  confirmed_expansions?: Array<{
    branch_id: string
    full_name: string
    birth_date?: string
    class_code?: string
    score: number
    corroborating_hits: number
  }>
  nodes: InvestigationBranchNode[]
}

export interface PipelineTelemetry {
  architecture: string
  gatekeeper?: GatekeeperStats
  layer_timings_ms?: Record<string, number>
  investigation_tree?: InvestigationTreeTelemetry
}

export interface AssistantPayload {
  blackboard_id?: string
  assistant_reply: string
  parsed_clues?: ParsedClues
  discovered_sources?: SourceItem[]
  suggested_dorks?: DorkItem[]
  reasoning_steps?: ReasoningStep[]
  learned_negative_keywords?: string[]
  recommended_pivots?: Array<Record<string, unknown>>
  hidden_links?: Array<Record<string, unknown>>
  timeline_events?: TimelineEvent[]
  disambiguation_cards?: DisambiguationCard[]
  graph_stats?: { nodes: number; edges: number }
  pipeline_telemetry?: PipelineTelemetry
}

export interface ChatMessage {
  id?: string
  role: 'user' | 'assistant'
  content: string
  payload?: AssistantPayload & {
    image_preview_url?: string
    has_image?: boolean
  }
  created_at?: string
}

export interface DossierItem {
  id: string
  workspace_id: string
  category: string
  field_key: string
  field_value: string
  source_url: string
  note: string
  updated_at: string
  already_exists?: boolean
}

export interface APIKeyItem {
  id: string
  name: string
  provider: 'gemini' | 'openai' | 'serper' | 'tavily' | 'github'
  masked_key: string
  encrypted?: boolean
  model: string
  enabled: boolean
  usage_count: number
  error_count: number
  status: 'ACTIVE' | 'COOLDOWN' | 'DISABLED'
  cooldown_remaining_sec: number
}

export interface LocalHostConfig {
  active_mode: 'auto' | 'gemini_pool' | 'ollama_local' | 'openai_pool' | 'metasearch_only'
  ollama_base_url: string
  ollama_model: string
  searxng_url: string
}

export interface PluginInfo {
  id: string
  name: string
  version: string
  category: string
  description: string
  local_only: boolean
  capabilities: string[]
  health: {
    ready: boolean
    detail: string
    engines?: string[]
  }
}

export interface PipelineLayerSpec {
  layer: number
  code: string
  ring: string
  name: string
  module: string
  responsibilities: string[]
}

export interface PipelineArchitectureInfo {
  architecture: string
  layers: PipelineLayerSpec[]
  username_engine: {
    manifest: {
      valid: boolean
      total_sites: number
      verified_json_api_sites: number
      html_check_sites: number
      errors: string[]
    }
    circuit_breaker: {
      open_circuits: string[]
      open_count: number
    }
  }
}

export interface GeoPoint {
  lat: number
  lng: number
  label: string
}

export interface GraphFeatureClaim {
  category: string
  key: string
  value: unknown
  polarity: 'POSITIVE' | 'NEGATIVE'
  confidence: number
  source_url: string
  evidence_quote: string
}

export interface GraphNodeItem {
  id: string
  workspace_id: string
  type: string
  label: string
  normalized_label: string
  claims: GraphFeatureClaim[]
  confidence: number
}

export interface GraphEdgeItem {
  id: string
  workspace_id: string
  source_id: string
  target_id: string
  relation: string
  confidence: number
  status: string
  evidence_quote: string
  source_url: string
}

export interface GraphSnapshotData {
  workspace: Workspace
  nodes: GraphNodeItem[]
  edges: GraphEdgeItem[]
}

