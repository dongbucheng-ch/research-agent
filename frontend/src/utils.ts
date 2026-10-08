import dayjs from 'dayjs'

import type { Digest } from './api/types'

export interface DigestBatch {
  date: string
  index: number
}

/** 日报批次:优先用后端写入的 meta.batch;历史数据按当日已加载列表回推序号。 */
export function digestBatch(digest: Digest, all: Digest[]): DigestBatch {
  const stored = digest.meta?.batch
  if (stored && typeof stored.index === 'number' && stored.date) return stored
  const date = dayjs(digest.created_at).format('YYYY-MM-DD')
  const group = all
    .filter((row) => dayjs(row.created_at).format('YYYY-MM-DD') === date)
    .sort((a, b) =>
      a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : a.id - b.id,
    )
  const index = group.findIndex((row) => row.id === digest.id)
  return { date, index: index >= 0 ? index + 1 : 1 }
}

export function scoreColor(total: number | null | undefined): string {
  const value = total ?? 0
  if (value >= 80) return 'red'
  if (value >= 65) return 'orange'
  if (value >= 50) return 'blue'
  return 'default'
}

export function formatTime(value?: string | null): string {
  return value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '-'
}

export function formatRelative(value?: string | null): string {
  if (!value) return '-'
  const diffMinutes = dayjs().diff(dayjs(value), 'minute')
  if (diffMinutes < 1) return '刚刚'
  if (diffMinutes < 60) return `${diffMinutes} 分钟前`
  const hours = Math.floor(diffMinutes / 60)
  if (hours < 24) return `${hours} 小时前`
  return `${Math.floor(hours / 24)} 天前`
}

export const CONTENT_TYPE_META: Record<string, { label: string; color: string }> = {
  paper: { label: '论文', color: 'purple' },
  tech: { label: '技术', color: 'blue' },
  industry: { label: '产业', color: 'gold' },
  community: { label: '社区', color: 'green' },
  repo: { label: '仓库', color: 'geekblue' },
  skill: { label: 'Skill', color: 'cyan' },
  model: { label: '模型', color: 'magenta' },
}

export const JOB_STATUS_META: Record<string, { label: string; color: string }> = {
  pending: { label: '排队中', color: 'default' },
  running: { label: '运行中', color: 'processing' },
  succeeded: { label: '成功', color: 'success' },
  failed: { label: '失败', color: 'error' },
  cancelled: { label: '已取消', color: 'warning' },
}

export const JOB_KIND_LABEL: Record<string, string> = {
  fetch: '采集',
  digest: '日报生成',
  article: '文章生成',
  push: '推送',
}

export const SOURCE_STATUS_META: Record<string, { label: string; color: string }> = {
  active: { label: '正常', color: 'success' },
  degraded: { label: '降级', color: 'warning' },
  paused: { label: '暂停', color: 'default' },
  archived: { label: '归档', color: 'default' },
}

/** Token 数量显示:<1 万显示原值,1 万-100 万显示 k,再往上显示 M。 */
export function formatTokens(value: unknown): string {
  const count = typeof value === 'number' ? value : Number(value ?? 0) || 0
  if (count <= 0) return '0'
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(2)}M`
  if (count >= 10_000) return `${(count / 1000).toFixed(1)}k`
  return count.toLocaleString()
}
