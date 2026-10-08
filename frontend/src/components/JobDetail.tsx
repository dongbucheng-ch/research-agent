import { Alert, Descriptions, Space, Table, Tabs, Tag, Typography } from 'antd'
import type { ReactNode } from 'react'

import type { JobRun } from '../api/types'
import JobLogViewer from './JobLogViewer'
import StageTable, { readStagesFromJob, StageSummaryText } from './StageTable'
import { formatTokens } from '../utils'

const PARAM_LABELS: Record<string, string> = {
  name: '研究方向',
  keywords: '关键词',
  exclude_keywords: '排除词',
  source_ids: '指定信源',
  source_id: '单个信源',
  lookback_hours: '回看窗口(小时)',
  min_score: '入库门槛',
  scopes: '采集类型',
  github_keywords: 'GitHub 关键词',
  github_mode: 'GitHub 策略',
  backfill: '补量策略',
  score_weights: '打分权重',
  scope: '模式',
  topic: '方向',
  period_hours: '时间窗(小时)',
  max_items: '资讯条数',
  github_count: 'GitHub 条数',
  github_language: 'GitHub 语言',
  push_channel_id: '推送渠道',
  max_sources: '素材上限',
  target_words: '目标字数',
  digest_id: '日报 ID',
  channel_id: '渠道 ID',
  target_kind: '推送目标类型(digest/article)',
  target_id: '推送目标 ID',
  title: '推送标题',
  source: '推送来源',
  author: '推送作者',
  tags: '推送标签',
}

const SCOPE_LABELS: Record<string, string> = { info: '资讯·论文', github: 'GitHub' }
const GITHUB_MODE_LABELS: Record<string, string> = {
  trending_fallback: '关键词优先+热榜兜底',
  strict: '严格关键词',
}
const BACKFILL_LABELS: Record<string, string> = { auto: '自动补量一轮', off: '仅提示' }
const SKIP_REASONS: Record<string, string> = {
  llm_unavailable: 'LLM 未配置',
  no_expanded_keywords: '未生成辐射词',
  all_sources_failed: '信源全部失败',
}

function renderValue(key: string, value: unknown): ReactNode {
  if (Array.isArray(value)) {
    if (!value.length) return '—'
    return value.map((row) => {
      const text = String(row)
      const label =
        key === 'scopes'
          ? (SCOPE_LABELS[text] ?? text)
          : key === 'github_mode'
            ? (GITHUB_MODE_LABELS[text] ?? text)
            : key === 'backfill'
              ? (BACKFILL_LABELS[text] ?? text)
              : text
      return <Tag key={text}>{label}</Tag>
    })
  }
  if (value && typeof value === 'object') {
    return (
      <Typography.Text style={{ fontSize: 12 }} code>
        {JSON.stringify(value)}
      </Typography.Text>
    )
  }
  if (value === null || value === undefined || value === '') return '—'
  const text = String(value)
  if (key === 'scopes') return SCOPE_LABELS[text] ?? text
  if (key === 'github_mode') return GITHUB_MODE_LABELS[text] ?? text
  if (key === 'backfill') return BACKFILL_LABELS[text] ?? text
  if (key === 'scope') return text === 'topic' ? '定向' : '全局'
  return text
}

function asRecords(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((row): row is Record<string, unknown> => !!row && typeof row === 'object')
    : []
}

function numberOf(value: unknown): number {
  return typeof value === 'number' ? value : Number(value ?? 0) || 0
}

export default function JobDetail({ job }: { job: JobRun }) {
  const result = (job.result ?? {}) as Record<string, unknown>
  const params = job.params ?? {}
  const spec = (result.spec ?? null) as Record<string, unknown> | null
  const stages = readStagesFromJob(job)
  const sources = asRecords(result.sources_detail)
  const items = asRecords(result.items)
  const backfill = (result.backfill ?? null) as Record<string, unknown> | null
  const shortfall = (result.shortfall ?? null) as Record<string, unknown> | null
  const usage = (result.llm_usage ?? {}) as Record<string, unknown>

  const overview = (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      {job.status === 'failed' && (
        <Alert type="error" showIcon message="任务失败" description={String(result.error ?? '')} />
      )}
      {shortfall && (
        <Alert
          type="warning"
          showIcon
          message="素材不足"
          description={
            <span>
              {Object.entries(shortfall).map(([key, value]) => {
                const row = value as { expected?: number; actual?: number }
                const label =
                  key === 'news' ? '资讯' : key === 'github' ? 'GitHub' : key === 'materials' ? '素材' : '字数'
                return (
                  <div key={key}>
                    {label}:期望 {row.expected} / 实际 {row.actual}
                  </div>
                )
              })}
            </span>
          }
        />
      )}
      {backfill && (
        <Alert
          type="info"
          showIcon
          message={
            backfill.skipped
              ? `未执行补量(${SKIP_REASONS[String(backfill.skipped)] ?? String(backfill.skipped)})`
              : '已自动补量一轮'
          }
          description={
            Array.isArray(backfill.keywords) && backfill.keywords.length
              ? `辐射词:${(backfill.keywords as string[]).join(' / ')};补采抓取 ${numberOf(
                  backfill.fetched,
                )} 条、新增 ${numberOf(backfill.new_items)} 条`
              : undefined
          }
        />
      )}
      <StageTable stages={stages} />
      <Descriptions size="small" column={4} bordered>
        <Descriptions.Item label="抓取">{numberOf(result.fetched)}</Descriptions.Item>
        <Descriptions.Item label="新入库">{numberOf(result.new_items)}</Descriptions.Item>
        <Descriptions.Item label="去重">{numberOf(result.duplicates)}</Descriptions.Item>
        <Descriptions.Item label="过滤">{numberOf(result.filtered)}</Descriptions.Item>
        <Descriptions.Item label="低于门槛">{numberOf(result.low_score)}</Descriptions.Item>
        <Descriptions.Item label="失败信源">{numberOf(result.failed_sources)}</Descriptions.Item>
        <Descriptions.Item label="LLM 错误">{numberOf(result.llm_errors)}</Descriptions.Item>
        <Descriptions.Item label="LLM Token">
          {numberOf(usage.total_tokens)
            ? `${formatTokens(usage.total_tokens)}（入 ${formatTokens(usage.prompt_tokens)} / 出 ${formatTokens(usage.completion_tokens)}）`
            : '—'}
        </Descriptions.Item>
        <Descriptions.Item label="富化降级">{numberOf(result.llm_degraded)}</Descriptions.Item>
        <Descriptions.Item label="总耗时">
          {result.elapsed_seconds ? `${numberOf(result.elapsed_seconds).toFixed(1)}s` : '—'}
        </Descriptions.Item>
      </Descriptions>
      {stages.length > 0 && <StageSummaryText stages={stages} />}
    </Space>
  )

  const configTab = (
    <Space direction="vertical" size="small" style={{ width: '100%' }}>
      <Descriptions size="small" column={2} bordered>
        {Object.entries(params).map(([key, value]) => (
          <Descriptions.Item key={key} label={PARAM_LABELS[key] ?? key}>
            {renderValue(key, value)}
          </Descriptions.Item>
        ))}
        {!Object.keys(params).length && (
          <Descriptions.Item label="参数">—</Descriptions.Item>
        )}
      </Descriptions>
      {spec && (
        <>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            实际生效配置(含关键词翻译结果)
          </Typography.Text>
          <Descriptions size="small" column={2} bordered>
            {Object.entries(spec).map(([key, value]) => (
              <Descriptions.Item key={key} label={PARAM_LABELS[key] ?? key}>
                {renderValue(key, value)}
              </Descriptions.Item>
            ))}
          </Descriptions>
        </>
      )}
    </Space>
  )

  const resultTab = (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      {sources.length > 0 ? (
        <Table
          size="small"
          rowKey={(row) => `${row.source_id}-${row.round ?? 'main'}`}
          pagination={false}
          dataSource={sources}
          columns={[
            {
              title: '信源',
              dataIndex: 'name',
              ellipsis: true,
              render: (value: string, row) => (
                <span>
                  {value}
                  {row.round === 'backfill' && (
                    <Tag color="gold" style={{ marginInlineStart: 6 }}>
                      补量
                    </Tag>
                  )}
                </span>
              ),
            },
            { title: '引擎', dataIndex: 'engine', width: 90 },
            {
              title: '耗时',
              dataIndex: 'seconds',
              width: 90,
              render: (value: number) => `${numberOf(value).toFixed(2)}s`,
            },
            { title: '抓取', dataIndex: 'fetched', width: 70 },
            { title: '过滤', dataIndex: 'filtered', width: 70 },
            { title: '去重', dataIndex: 'duplicates', width: 70 },
            { title: '低分', dataIndex: 'low_score', width: 70 },
            { title: '入库', dataIndex: 'ingested', width: 70 },
            {
              title: '状态',
              dataIndex: 'error',
              width: 90,
              render: (error: string | null) =>
                error ? <Tag color="error">失败</Tag> : <Tag color="success">正常</Tag>,
            },
          ]}
        />
      ) : (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          该任务没有信源明细(日报 / 文章 / 推送任务无此结构)。
        </Typography.Text>
      )}
      {items.length > 0 && (
        <Table
          size="small"
          rowKey={(row) => String(row.id ?? row.title)}
          pagination={{ pageSize: 10, hideOnSinglePage: true }}
          dataSource={items}
          columns={[
            { title: '类型', dataIndex: 'type', width: 90 },
            {
              title: '标题',
              dataIndex: 'title',
              ellipsis: true,
              render: (value: string, row) =>
                row.url ? (
                  <a href={String(row.url)} target="_blank" rel="noreferrer">
                    {value}
                  </a>
                ) : (
                  value
                ),
            },
            { title: '相关', dataIndex: 'relevance', width: 70 },
            { title: '热度', dataIndex: 'heat', width: 70 },
            { title: '时效', dataIndex: 'freshness', width: 70 },
            { title: '总分', dataIndex: 'total', width: 70 },
          ]}
        />
      )}
      {Object.keys(result).length > 0 && (
        <details>
          <summary style={{ cursor: 'pointer', fontSize: 12, color: '#666' }}>原始 JSON</summary>
          <pre className="job-log" style={{ marginTop: 8 }}>{JSON.stringify(result, null, 2)}</pre>
        </details>
      )}
    </Space>
  )

  return (
    <Tabs
      size="small"
      items={[
        { key: 'overview', label: '概览', children: overview },
        { key: 'config', label: '配置', children: configTab },
        { key: 'result', label: '结果', children: resultTab },
        {
          key: 'log',
          label: '日志',
          children: <JobLogViewer log={job.log} />,
        },
      ]}
    />
  )
}
