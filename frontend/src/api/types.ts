export interface Page<T> {
  items: T[]
  total: number
}

export interface Source {
  id: number
  name: string
  channel: string
  collector_kind: string
  url: string
  config: Record<string, unknown>
  engine?: string
  preset?: string
  object_type?: string
  tier: string
  status: string
  enabled: boolean
  fetch_interval_minutes: number
  quality_score: number
  consecutive_failures: number
  last_error: string | null
  last_fetch_at: string | null
  last_success_at: string | null
  created_at: string
}

export interface RecommendedSource {
  key: string
  name: string
  channel: string
  collector_kind: string
  url: string
  config: Record<string, unknown>
  tier: string
  category?: string | null
  description?: string | null
}

export interface DiscoverCandidate {
  name: string
  url: string
  ok: boolean
  entries: number
  latest: string | null
  title: string | null
  error: string | null
  already_exists: boolean
}

export interface DiscoverResult {
  source_url: string
  ok_count: number
  candidates: DiscoverCandidate[]
}

export interface SourceStat {
  source_id: number
  candidates: number
  ingested: number
  avg_score: number | null
  last_item_at: string | null
}

export interface Score {
  heat: number
  relevance: number
  freshness: number
  total: number
  detail: Record<string, unknown>
}

export interface Item {
  id: number
  channel: string
  content_type: string
  title: string
  url: string
  author: string | null
  published_at: string | null
  lang: string | null
  tags: string[]
  status: string
  first_seen_at: string | null
  source_id: number | null
  source_name: string | null
  translated_title: string | null
  summary: string | null
  collect_name: string | null
  collect_keywords: string[]
  keyword_hits: string[]
  origin: string | null
  score: Score | null
}

export interface ItemRef {
  kind: 'digest' | 'article'
  id: number
  title: string
  created_at: string | null
}

export interface ItemDetail extends Item {
  raw_text: string | null
  translated_text: string | null
  card: Record<string, unknown> | null
  references: ItemRef[]
}

export interface DigestMeta {
  scope?: 'global' | 'topic'
  topic?: string | null
  keywords?: string[]
  window_hours?: number
  news_count?: number
  news_materials?: number
  github_count?: number
  /** 「日期 + 第 N 批」索引,生成时由后端写入;历史数据缺失时前端回推。 */
  batch?: { date: string; index: number }
  [key: string]: unknown
}

export interface Digest {
  id: number
  title: string
  lead: string | null
  content_md: string
  highlights: string[]
  period_start: string | null
  period_end: string | null
  item_count: number
  status: string
  model: string | null
  meta?: DigestMeta
  created_at: string
}

export interface ArticleMeta {
  topic?: string | null
  keywords?: string[]
  window_hours?: number
  target_words?: number
  kept?: number
  sections?: string[]
  cited_refs?: number[]
  char_count?: number
  cjk_count?: number
  [key: string]: unknown
}

export interface Article {
  id: number
  title: string
  topic: string | null
  keywords: string[]
  content_md: string
  source_item_ids: number[]
  status: string
  model: string | null
  meta?: ArticleMeta
  created_at: string
}

export interface JobRun {
  id: string
  kind: string
  status: string
  params: Record<string, unknown>
  result: Record<string, unknown>
  log: string
  started_at: string | null
  finished_at: string | null
  created_at: string | null
}

export interface LLMSettings {
  enabled: boolean
  base_url: string
  model: string
  api_key_masked: string
  protocol: string
  timeout_seconds: number
  max_concurrency: number
  translate_enabled: boolean
}

export interface PushChannel {
  id: number
  name: string
  kind: string
  config: Record<string, unknown>
  enabled: boolean
  created_at: string
}

export interface PushProvider {
  kind: string
  label: string
}

export interface Schedule {
  id: string
  name: string
  keywords: string[]
  exclude_keywords: string[]
  source_ids: number[]
  scopes: string[]
  github_keywords: string[]
  github_mode: string
  backfill: string
  lookback_hours: number
  min_score: number
  interval_minutes: number
  enabled: boolean
  created_at: string | null
  last_run_at: string | null
  last_job_id: string | null
  next_run_at: string | null
  last_skip: { at: string; reason: string } | null
}

export interface PushLog {
  id: number
  channel_id: number | null
  digest_id: number | null
  target_kind: string | null
  target_id: number | null
  status: string
  error: string | null
  created_at: string | null
}

export interface Stats {
  items_total: number
  items_today: number
  digests_total: number
  sources_total: number
  sources_active: number
  jobs_running: number
  by_content_type: Record<string, number>
}
