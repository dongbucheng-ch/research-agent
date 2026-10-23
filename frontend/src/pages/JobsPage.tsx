import { ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Input, Pagination, Segmented, Select, Space, Table, Tooltip, Typography, message } from 'antd'
import type { Key } from 'react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, toQuery } from '../api/client'
import type { JobRun, Page } from '../api/types'
import DigestGenerateModal from '../components/DigestGenerateModal'
import JobDetail from '../components/JobDetail'
import SchedulesCard from '../components/SchedulesCard'
import { renderTableExpander } from '../components/TableExpander'
import { JOB_KIND_LABEL, JOB_STATUS_META, formatTime } from '../utils'

const STATUS_OPTIONS = [
  { value: 'running', label: '进行中' },
  { value: 'succeeded', label: '成功' },
  { value: 'failed', label: '失败' },
]

/** 时间窗 → 小时数(URL 存语义值,便于分享与阅读) */
const SINCE_OPTIONS = [
  { value: 'all', label: '全部' },
  { value: '24h', label: '近 24 小时' },
  { value: '7d', label: '近 7 天' },
]
const sinceHours = (value: string) => (value === '24h' ? 24 : value === '7d' ? 168 : undefined)

function configSummary(job: JobRun): string {
  const params = job.params ?? {}
  const keywords = Array.isArray(params.keywords) ? (params.keywords as string[]) : []
  if (job.kind === 'fetch') {
    const scopes = Array.isArray(params.scopes) ? (params.scopes as string[]) : ['info', 'github']
    const scopeText =
      scopes.includes('info') && scopes.includes('github')
        ? '资讯+GitHub'
        : scopes.includes('github')
          ? 'GitHub'
          : '资讯'
    const githubMode = params.github_mode === 'strict' ? ' · GitHub 严格' : ''
    return `${String(params.name ?? '临时采集')} · ${keywords.length} 词 · ${scopeText}${githubMode} · ${String(params.lookback_hours ?? 24)}h · 门槛 ${String(params.min_score ?? 75)}`
  }
  if (job.kind === 'digest') {
    const scope = params.scope === 'topic' ? `定向「${String(params.topic ?? '-')}」` : '全局'
    return `${scope} · ${keywords.length} 词 · ${String(params.period_hours ?? 24)}h · 资讯 ${String(params.max_items ?? 10)} + GitHub ${String(params.github_count ?? 5)}`
  }
  if (job.kind === 'article') {
    return `${String(params.topic ?? '未命名')} · ${keywords.length} 词 · 素材上限 ${String(params.max_sources ?? 12)} · 目标 ${String(params.target_words ?? 1800)} 字`
  }
  if (job.kind === 'push') {
    const target = params.target_kind === 'article' ? '文章' : '日报'
    return `${target} #${String(params.target_id ?? params.digest_id ?? '-')} → 渠道 #${String(params.channel_id ?? '-')}`
  }
  return '-'
}

function duration(job: JobRun): string {
  if (!job.started_at || !job.finished_at) return '-'
  const seconds = (new Date(job.finished_at).getTime() - new Date(job.started_at).getTime()) / 1000
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const minutes = Math.floor(seconds / 60)
  return `${minutes}m${Math.round(seconds - minutes * 60)}s`
}

/** 失败原因:优先取 result.error,其次取日志最后一行(异常类型 + 消息),让失败不用展开就能读懂 */
function failReason(job: JobRun): string | null {
  if (job.status !== 'failed') return null
  const error = job.result?.error
  if (typeof error === 'string' && error.trim()) return error.trim()
  const lines = (job.log ?? '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
  return lines.length ? lines[lines.length - 1] : '未记录错误信息,展开可查看完整日志'
}

/** 状态用「圆点 + 文字」低饱和徽标:红色专供给需要动手的失败行,成功保持安静 */
function JobStatusBadge({ status }: { status: string }) {
  return (
    <span className={`jobs-badge is-${status}`}>
      <i />
      {JOB_STATUS_META[status]?.label ?? status}
    </span>
  )
}

export default function JobsPage() {
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()
  const surfaceRef = useRef<HTMLDivElement>(null)
  const [digestOpen, setDigestOpen] = useState(false)
  const [expandedKeys, setExpandedKeys] = useState<Key[]>([])

  // 筛选与分页全部落在 URL 上:刷新、分享、后退都能回到同一屏(与素材池/信源池一致)
  const kind = params.get('kind') ?? ''
  const status = params.get('status') ?? ''
  const q = params.get('q') ?? ''
  const since = params.get('since') ?? 'all'
  const page = Number(params.get('page')) || 1
  const pageSize = Number(params.get('size')) || 20

  const patchParams = useCallback(
    (patch: Record<string, string | number | undefined>) => {
      const next = new URLSearchParams(params)
      for (const [key, value] of Object.entries(patch)) {
        if (value === undefined || value === '') next.delete(key)
        else next.set(key, String(value))
      }
      if (next.toString() !== params.toString()) setParams(next, { replace: true })
    },
    [params, setParams],
  )

  /** 关键词输入:本地立即可见,300ms 后才落到 URL 与请求 */
  const [searchInput, setSearchInput] = useState(q)
  useEffect(() => {
    setSearchInput(q)
  }, [q])
  useEffect(() => {
    const handle = window.setTimeout(() => {
      if (searchInput.trim() === q) return
      patchParams({ q: searchInput.trim() || undefined, page: undefined })
    }, 300)
    return () => window.clearTimeout(handle)
  }, [searchInput, q, patchParams])

  const { data, isLoading, isFetching, dataUpdatedAt } = useQuery({
    queryKey: ['jobs', kind, status, q, since, page, pageSize],
    queryFn: () =>
      api.get<Page<JobRun>>(
        `/jobs${toQuery({
          kind: kind || undefined,
          status: status || undefined,
          q: q || undefined,
          since_hours: sinceHours(since),
          page,
          page_size: pageSize,
        })}`,
      ),
    /* 保留上一批行:翻页/改筛选时表格不整块消失,只做一次轻微降透明度,避免闪烁 */
    placeholderData: keepPreviousData,
    refetchInterval: (query) =>
      query.state.data?.items?.some((job) => job.status === 'running' || job.status === 'pending')
        ? 3000
        : false,
  })

  /** 换页/换筛选后把表体滚回顶部:保留旧数据意味着表格不再重新挂载,滚动位置得手动复位 */
  useEffect(() => {
    surfaceRef.current?.querySelector('.ant-table-content')?.scrollTo({ top: 0 })
  }, [kind, status, q, since, page, pageSize])

  /** 心跳:有排队/运行中的任务时才真轮询,「x 秒前刷新」每秒自走一格 */
  const polling = Boolean(
    data?.items?.some((job) => job.status === 'running' || job.status === 'pending'),
  )
  const [, setTick] = useState(0)
  useEffect(() => {
    const handle = window.setInterval(() => setTick((value) => value + 1), 1000)
    return () => window.clearInterval(handle)
  }, [])
  const refreshedAgo = dataUpdatedAt ? Math.max(0, Math.round((Date.now() - dataUpdatedAt) / 1000)) : null

  const rerun = useMutation({
    mutationFn: (job: JobRun) => {
      if (job.kind === 'digest') return api.post<JobRun>('/digests/generate', job.params)
      if (job.kind === 'article') return api.post<JobRun>('/articles/generate', job.params)
      if (job.kind === 'push') return api.post<JobRun>('/jobs/push', job.params)
      return api.post<JobRun>('/jobs/fetch', job.params)
    },
    onSuccess: () => {
      message.success('已按同样配置重新提交')
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
    },
    onError: (error: Error) => message.error(error.message),
  })

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const failedOnly = status === 'failed'

  /** 「查看日志」= 展开该行(详情与日志就在展开行里),并把滚动的行带进视野 */
  const openJobDetail = (job: JobRun) => {
    setExpandedKeys([job.id])
    window.requestAnimationFrame(() => {
      document
        .querySelector(`[data-row-key="${job.id}"]`)
        ?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    })
  }

  return (
    <div className="jobs-page">
      <div className="jobs-toolbar">
        <div className="jobs-toolbar-main">
          <Select
            allowClear
            placeholder="任务类型"
            style={{ width: 118 }}
            value={kind || undefined}
            onChange={(value) => patchParams({ kind: value, page: undefined })}
            options={Object.entries(JOB_KIND_LABEL).map(([value, label]) => ({ value, label }))}
          />
          <Select
            allowClear
            placeholder="状态"
            style={{ width: 104 }}
            value={status || undefined}
            onChange={(value) => patchParams({ status: value, page: undefined })}
            options={STATUS_OPTIONS}
          />
          <Input
            allowClear
            className="jobs-search"
            placeholder="搜索任务 ID / 配置关键词"
            prefix={<SearchOutlined />}
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
          />
          <Segmented
            value={since}
            onChange={(value) => patchParams({ since: value === 'all' ? undefined : value, page: undefined })}
            options={SINCE_OPTIONS}
          />
          <Button
            size="small"
            className={failedOnly ? 'jobs-only-failed is-on' : 'jobs-only-failed'}
            aria-pressed={failedOnly}
            onClick={() => patchParams({ status: failedOnly ? undefined : 'failed', page: undefined })}
          >
            仅看失败
          </Button>
        </div>
        <Space>
          <Link to="/collect">
            <Button>去采集工作台</Button>
          </Link>
          <Button type="primary" onClick={() => setDigestOpen(true)}>
            生成日报
          </Button>
        </Space>
      </div>

      <SchedulesCard
        onOpenJob={(jobId) => {
          patchParams({ kind: undefined, status: undefined, page: undefined })
          setExpandedKeys([jobId])
        }}
      />

      <div
        ref={surfaceRef}
        className={isFetching && !isLoading ? 'jobs-surface is-updating' : 'jobs-surface'}
      >
        <div className="jobs-surface-head">
          <div className="jobs-surface-title">
            执行记录
            {!isLoading && <span className="jobs-surface-count">{total} 条</span>}
          </div>
          <span className={polling ? 'jobs-live is-on' : 'jobs-live'}>
            <i />
            {polling
              ? refreshedAgo === null
                ? '实时刷新中'
                : `实时 · ${refreshedAgo}s 前刷新`
              : refreshedAgo === null
                ? ''
                : `${refreshedAgo}s 前刷新`}
          </span>
        </div>
        {/* 数据齐才渲染:先占住高度,避免「空表 → 满表」时表头/行整体跳一下 */}
        {isLoading ? (
          <div className="jobs-blank" />
        ) : (
          <Table<JobRun>
            rowKey="id"
            dataSource={items}
            pagination={false}
            /* 固定布局 + 内部滚动:表头常驻,列宽不随数据到达重排（与信源池同一套约定） */
            tableLayout="fixed"
            scroll={{ x: 1000 }}
            expandable={{
              columnWidth: 32,
              expandIcon: renderTableExpander,
              expandedRowKeys: expandedKeys,
              onExpandedRowsChange: (keys) => setExpandedKeys([...keys]),
              expandedRowRender: (record) => <JobDetail job={record} />,
            }}
            columns={[
              { title: '类型', dataIndex: 'kind', width: 96, render: (value) => JOB_KIND_LABEL[value] ?? value },
              {
                title: '状态',
                dataIndex: 'status',
                width: 108,
                render: (value: string) => <JobStatusBadge status={value} />,
              },
              {
                title: '采集配置',
                render: (_, record) => {
                  const reason = failReason(record)
                  return (
                    <div className="jobs-config">
                      <Typography.Text
                        className="jobs-config-line"
                        ellipsis={{ tooltip: configSummary(record) }}
                      >
                        {configSummary(record)}
                      </Typography.Text>
                      {reason && (
                        <Typography.Text className="jobs-error-line" ellipsis={{ tooltip: reason }}>
                          失败原因:{reason}
                        </Typography.Text>
                      )}
                    </div>
                  )
                },
              },
              {
                title: '创建时间',
                dataIndex: 'created_at',
                width: 168,
                render: (value) => <span className="jobs-time">{formatTime(value)}</span>,
              },
              {
                title: '耗时',
                width: 88,
                render: (_, record) => <span className="jobs-duration">{duration(record)}</span>,
              },
              {
                title: '操作',
                width: 176,
                render: (_, record) => {
                  const rerunning = rerun.isPending && rerun.variables?.id === record.id
                  /* 失败行给「原因 → 动作」的完整路径;成功行只留一个安静的图标,不抢注意力 */
                  if (record.status === 'failed') {
                    return (
                      <Space size={6}>
                        <Button size="small" loading={rerunning} onClick={() => rerun.mutate(record)}>
                          重跑
                        </Button>
                        <Button size="small" type="text" onClick={() => openJobDetail(record)}>
                          查看日志
                        </Button>
                      </Space>
                    )
                  }
                  return (
                    <Tooltip title="按同样配置重跑">
                      <Button
                        size="small"
                        type="text"
                        className="jobs-icon-btn"
                        aria-label="重跑"
                        icon={<ReloadOutlined />}
                        loading={rerunning}
                        onClick={() => rerun.mutate(record)}
                      />
                    </Tooltip>
                  )
                },
              },
              {
                title: '任务 ID',
                dataIndex: 'id',
                width: 104,
                render: (value: string) => (
                  <Typography.Text className="jobs-id" copyable={{ text: value, tooltips: ['复制任务 ID', '已复制'] }}>
                    {value.slice(0, 8)}
                  </Typography.Text>
                ),
              },
            ]}
          />
        )}
        <div className="jobs-surface-foot">
          <Pagination
            current={page}
            pageSize={pageSize}
            total={total}
            disabled={isFetching}
            showSizeChanger
            pageSizeOptions={['20', '50', '100']}
            showTotal={(count, range) => `${range[0]}-${range[1]} / 共 ${count} 条`}
            onChange={(nextPage, nextSize) => {
              if (nextSize !== pageSize) patchParams({ size: nextSize, page: undefined })
              else patchParams({ page: nextPage })
            }}
          />
        </div>
      </div>

      <DigestGenerateModal open={digestOpen} onClose={() => setDigestOpen(false)} />
    </div>
  )
}
