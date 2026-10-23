import {
  DeleteOutlined,
  EditOutlined,
  ThunderboltOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Segmented,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { renderTableExpander } from '../components/TableExpander'
import type {
  DiscoverCandidate,
  DiscoverResult,
  RecommendedSource,
  Source,
  SourceStat,
} from '../api/types'
import { formatRelative, formatTime, scoreColor } from '../utils'

const RECOMMEND_CATEGORY_META: Record<string, { label: string; color: string }> = {
  paper: { label: '论文·学术', color: 'purple' },
  lab: { label: '实验室·公司', color: 'blue' },
  blog: { label: '研究博客', color: 'cyan' },
  news: { label: '产业新闻', color: 'gold' },
  cn: { label: '中文资讯', color: 'geekblue' },
  bio: { label: '生物科技', color: 'green' },
  community: { label: '社区·榜单', color: 'default' },
  social: { label: 'X · 推文', color: 'magenta' },
  engineering: { label: '工程团队', color: 'orange' },
}

const CHANNEL_LABEL: Record<string, string> = {
  rss: 'RSS',
  feed: 'RSS',
  arxiv: 'arXiv',
  google_news: 'Google News',
  bing_news: 'Bing News',
  hackernews: 'Hacker News',
  hn: 'Hacker News',
  repo: 'GitHub 仓库',
  skill: 'GitHub Skill',
  model: 'HuggingFace',
  github: 'GitHub Trending',
  hf_papers: 'HF Papers',
}

/** 超过该天数没有成功采集,视作「长时间无成功」(与状态徽标的判定一致) */
const STALE_DAYS = 7

/** 信源健康度:失败 > 长时间无成功 > 近 30 天无产出 > 停用 > 正常;rank 同时作为默认排序权重 */
type HealthKey = 'failed' | 'stale' | 'idle' | 'paused' | 'ok'

const HEALTH_META: Record<HealthKey, { label: string; rank: number }> = {
  failed: { label: '连续失败', rank: 0 },
  stale: { label: '长时间无成功', rank: 1 },
  idle: { label: '近 30 天无产出', rank: 2 },
  paused: { label: '已停用', rank: 3 },
  ok: { label: '正常', rank: 4 },
}

type HealthFilter = 'all' | 'attention' | 'ok' | 'paused'

interface SourceRow {
  source: Source
  stat?: SourceStat
  health: HealthKey
}

interface SourceFormValues {
  name: string
  channel: string
  collector_kind: string
  url: string
  config_text?: string
  tier: string
  enabled: boolean
  fetch_interval_minutes: number
}

function hostOf(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, '')
  } catch {
    return url
  }
}

function intervalLabel(minutes: number): string {
  if (minutes >= 1440) return `每 ${Math.round(minutes / 1440)} 天`
  if (minutes >= 60) return `每 ${Math.round(minutes / 60)} 小时`
  return `每 ${minutes} 分钟`
}

/** 单行健康度:失败优先,其次长期无成功,再次近 30 天零产出 */
function healthOf(source: Source, stat: SourceStat | undefined): HealthKey {
  const staleDays = source.last_success_at
    ? dayjs().diff(dayjs(source.last_success_at), 'day')
    : null
  if (source.consecutive_failures > 0 || source.status === 'degraded') return 'failed'
  if (!source.enabled) return 'paused'
  if (staleDays === null || staleDays >= STALE_DAYS) return 'stale'
  if (!stat || stat.ingested === 0) return 'idle'
  return 'ok'
}

export default function SourcesPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<Source | null>(null)
  const [recommendOpen, setRecommendOpen] = useState(false)
  const [selectedKeys, setSelectedKeys] = useState<string[]>([])
  const [form] = Form.useForm<SourceFormValues>()
  const [discoverOpen, setDiscoverOpen] = useState(false)
  const [discoverUrl, setDiscoverUrl] = useState('')
  const [discoverResult, setDiscoverResult] = useState<DiscoverResult | null>(null)
  const [discoverSelected, setDiscoverSelected] = useState<string[]>([])
  const [discoverTier, setDiscoverTier] = useState('B')
  const [recommendCategory, setRecommendCategory] = useState<string | undefined>(undefined)
  const [sourceSearch, setSourceSearch] = useState('')
  const [healthFilter, setHealthFilter] = useState<HealthFilter>('all')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)

  const { data: sources, isPending: sourcesPending } = useQuery({
    queryKey: ['sources'],
    queryFn: () => api.get<Source[]>('/sources'),
  })
  const { data: recommended } = useQuery({
    queryKey: ['recommended-sources'],
    queryFn: () => api.get<RecommendedSource[]>('/sources/recommended'),
    enabled: recommendOpen,
  })
  const { data: sourceStats, isPending: statsPending } = useQuery({
    queryKey: ['source-stats'],
    queryFn: () => api.get<SourceStat[]>('/sources/stats?days=30'),
  })

  /* 行高、列宽、排序权重都同时依赖「信源」和「30 天统计」两份数据。
     若只等信源就先画一帧,统计到达后会以另一套行高/顺序重画一遍,
     表现为刷新时整表抖动(实测行高 65 → 67.5、列宽 267 → 275、部分行换位)。
     两份数据到齐前只渲染空表 + loading,保证首帧即为最终形态。 */
  const tableLoading = sourcesPending || statsPending

  const statById = useMemo(
    () => new Map((sourceStats ?? []).map((row) => [row.source_id, row])),
    [sourceStats],
  )
  const importedNames = new Set((sources ?? []).map((source) => source.name))
  const visibleRecommended = (recommended ?? []).filter(
    (item) => !recommendCategory || item.category === recommendCategory,
  )

  /** 每行的「结论」:健康度 + 近 30 天产出,表格只负责把它排到前面 */
  const rows = useMemo<SourceRow[]>(
    () =>
      tableLoading
        ? []
        : (sources ?? []).map((source) => {
            const stat = statById.get(source.id)
            return { source, stat, health: healthOf(source, stat) }
          }),
    [sources, statById, tableLoading],
  )

  const counts = useMemo(() => {
    const acc = { all: rows.length, attention: 0, ok: 0, paused: 0 }
    for (const row of rows) {
      if (row.health === 'ok') acc.ok += 1
      else if (row.health === 'paused') acc.paused += 1
      else acc.attention += 1
    }
    return acc
  }, [rows])

  /** 默认「需处理优先」:失败 → 长期无成功 → 无产出 → 停用 → 正常,同级按名称 */
  const visibleSources = useMemo(() => {
    const needle = sourceSearch.trim().toLowerCase()
    return rows
      .filter((row) => {
        if (healthFilter === 'attention') return row.health !== 'ok' && row.health !== 'paused'
        if (healthFilter === 'ok') return row.health === 'ok'
        if (healthFilter === 'paused') return row.health === 'paused'
        return true
      })
      .filter((row) => {
        if (!needle) return true
        const haystack = [
          row.source.name,
          row.source.url,
          row.source.channel,
          row.source.engine ?? '',
          CHANNEL_LABEL[row.source.channel] ?? '',
        ]
          .join(' ')
          .toLowerCase()
        return haystack.includes(needle)
      })
      .sort(
        (a, b) =>
          HEALTH_META[a.health].rank - HEALTH_META[b.health].rank ||
          b.source.consecutive_failures - a.source.consecutive_failures ||
          a.source.name.localeCompare(b.source.name),
      )
  }, [rows, healthFilter, sourceSearch])

  /** 概览条:给「这一行算好还是坏」提供锚点(入库/候选、均分、最近采集) */
  const summary = useMemo(() => {
    const failed = rows.filter((row) => row.health === 'failed').length
    const stale = rows.filter((row) => row.health === 'stale').length
    const idle = rows.filter((row) => row.health === 'idle').length
    const stats = tableLoading ? [] : sourceStats ?? []
    const ingested = stats.reduce((sum, row) => sum + row.ingested, 0)
    const candidates = stats.reduce((sum, row) => sum + row.candidates, 0)
    const scored = stats.filter((row) => row.avg_score !== null)
    const avg =
      scored.length > 0
        ? (scored.reduce((sum, row) => sum + (row.avg_score ?? 0), 0) / scored.length).toFixed(1)
        : '-'
    const lastFetch = (tableLoading ? [] : sources ?? []).reduce<string | null>(
      (latest, source) =>
        source.last_fetch_at && (!latest || source.last_fetch_at > latest)
          ? source.last_fetch_at
          : latest,
      null,
    )
    return { total: rows.length, failed, stale, idle, ingested, candidates, avg, lastFetch }
  }, [rows, sources, sourceStats, tableLoading])

  const filterOptions = useMemo(
    () => [
      { value: 'all', label: `全部 ${counts.all}` },
      { value: 'attention', label: `需处理 ${counts.attention}` },
      { value: 'ok', label: `正常 ${counts.ok}` },
      ...(counts.paused > 0 ? [{ value: 'paused', label: `停用 ${counts.paused}` }] : []),
    ],
    [counts],
  )

  const saveMutation = useMutation({
    mutationFn: (values: SourceFormValues) => {
      let config: Record<string, unknown> = {}
      if (values.config_text?.trim()) {
        try {
          config = JSON.parse(values.config_text)
        } catch {
          throw new Error('config 不是合法 JSON')
        }
      }
      const payload = { ...values, config, config_text: undefined }
      return editing ? api.put(`/sources/${editing.id}`, payload) : api.post('/sources', payload)
    },
    onSuccess: () => {
      message.success(editing ? '信源已更新' : '信源已创建')
      setOpen(false)
      queryClient.invalidateQueries({ queryKey: ['sources'] })
    },
    onError: (error: Error) => message.error(error.message),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.del(`/sources/${id}`),
    onSuccess: () => {
      message.success('已删除')
      queryClient.invalidateQueries({ queryKey: ['sources'] })
    },
  })

  const testMutation = useMutation({
    mutationFn: (id: number) =>
      api.post<{ ok: boolean; items_found: number; sample: unknown[]; error?: string }>(
        `/sources/${id}/test`,
      ),
    onSuccess: (result, id) => {
      const source = sources?.find((item) => item.id === id)
      if (result.ok) {
        Modal.info({
          title: `测试通过:${source?.name} 抓到 ${result.items_found} 条`,
          width: 640,
          content: (
            <pre style={{ maxHeight: 320, overflow: 'auto', fontSize: 12 }}>
              {JSON.stringify(result.sample, null, 2)}
            </pre>
          ),
        })
      } else {
        Modal.error({ title: '测试失败', content: result.error ?? '未知错误' })
      }
    },
    onError: (error: Error) => message.error(error.message),
  })

  const importMutation = useMutation({
    mutationFn: () => api.post<Source[]>('/sources/import-recommended', { keys: selectedKeys }),
    onSuccess: (created) => {
      message.success(`已导入 ${created.length} 个信源`)
      setRecommendOpen(false)
      setSelectedKeys([])
      queryClient.invalidateQueries({ queryKey: ['sources'] })
    },
    onError: (error: Error) => message.error(error.message),
  })

  const discoverMutation = useMutation({
    mutationFn: (url: string) => api.post<DiscoverResult>('/sources/discover', { url }),
    onSuccess: (result) => {
      setDiscoverResult(result)
      setDiscoverSelected(
        result.candidates.filter((item) => item.ok && !item.already_exists).map((item) => item.url),
      )
      if (result.candidates.length === 0) {
        message.info('未发现候选 Feed,可尝试 GitHub 仓库 / OPML 链接 / 博客首页 URL')
      }
    },
    onError: (error: Error) => message.error(error.message),
  })

  const importCandidatesMutation = useMutation({
    mutationFn: () =>
      api.post<Source[]>('/sources/import-candidates', {
        items: (discoverResult?.candidates ?? [])
          .filter((item) => discoverSelected.includes(item.url))
          .map((item) => ({ name: item.name, url: item.url, channel: 'rss', tier: discoverTier })),
      }),
    onSuccess: (created) => {
      message.success(`已导入 ${created.length} 个信源`)
      setDiscoverOpen(false)
      setDiscoverResult(null)
      setDiscoverSelected([])
      queryClient.invalidateQueries({ queryKey: ['sources'] })
    },
    onError: (error: Error) => message.error(error.message),
  })

  const openEditor = (source?: Source) => {
    setEditing(source ?? null)
    form.setFieldsValue(
      source
        ? {
            ...source,
            config_text: JSON.stringify(source.config ?? {}, null, 2),
          }
        : {
            name: '',
            url: '',
            channel: 'rss',
            collector_kind: 'stream',
            tier: 'B',
            enabled: true,
            fetch_interval_minutes: 60,
            config_text: undefined,
          },
    )
    setOpen(true)
  }

  const columns: ColumnsType<SourceRow> = [
    {
      title: '信源',
      key: 'name',
      sorter: (a, b) => a.source.name.localeCompare(b.source.name),
      render: (_, row) => (
        <div className="src-name">
          <div className="src-name-title">{row.source.name}</div>
          <div className="src-name-meta">
            {hostOf(row.source.url)} · {intervalLabel(row.source.fetch_interval_minutes)}
          </div>
        </div>
      ),
    },
    {
      title: '渠道',
      key: 'channel',
      width: 160,
      render: (_, row) => (
        <div className="src-channel">
          <span className="src-chip">{CHANNEL_LABEL[row.source.channel] ?? row.source.channel}</span>
          <span className="src-name-meta">
            {[row.source.engine, row.source.object_type].filter(Boolean).join(' · ') ||
              row.source.collector_kind}
          </span>
        </div>
      ),
    },
    {
      title: 'Tier',
      key: 'tier',
      /* 84 = 文字 26 + 排序图标 20 + 左右内边距 32;fixed 布局下不会像 auto 那样自动撑开 */
      width: 84,
      sorter: (a, b) => a.source.tier.localeCompare(b.source.tier),
      render: (_, row) => <span className={`src-tier is-${row.source.tier.toLowerCase()}`}>{row.source.tier}</span>,
    },
    {
      title: '状态',
      key: 'health',
      width: 160,
      render: (_, row) => {
        const meta = HEALTH_META[row.health]
        const text =
          row.health === 'failed'
            ? `${meta.label} ${row.source.consecutive_failures}`
            : meta.label
        const badge = (
          <span className={`src-badge is-${row.health}`}>
            <i />
            {text}
          </span>
        )
        return row.source.last_error ? (
          <Tooltip title={row.source.last_error} mouseEnterDelay={0.3}>
            {badge}
          </Tooltip>
        ) : (
          badge
        )
      },
    },
    {
      title: '近 30 天产出',
      key: 'stat',
      width: 236,
      sorter: (a, b) => (a.stat?.ingested ?? -1) - (b.stat?.ingested ?? -1),
      render: (_, row) => {
        const stat = row.stat
        if (!stat) return <span className="src-muted">近 30 天无采集</span>
        const ratio = stat.candidates > 0 ? Math.min(1, stat.ingested / stat.candidates) : 0
        return (
          <div className="src-health">
            <div className="src-health-top">
              <span className="src-bar">
                <i
                  className={ratio === 0 ? 'is-zero' : ''}
                  style={{ width: `${Math.max(3, Math.round(ratio * 100))}%` }}
                />
              </span>
              <span className="src-health-num">
                入库 {stat.ingested}
                <span className="src-muted"> / 候选 {stat.candidates}</span>
              </span>
            </div>
            <div className="src-health-bottom">
              <span className={`src-score is-${scoreColor(stat.avg_score)}`}>
                {stat.avg_score ?? '-'}
              </span>
              <span className="src-muted">
                {stat.last_item_at ? `最近产出 ${dayjs(stat.last_item_at).format('M月D日')}` : '暂无产出'}
              </span>
            </div>
          </div>
        )
      },
    },
    {
      title: '最近成功',
      key: 'last_success_at',
      width: 112,
      sorter: (a, b) => (a.source.last_success_at ?? '').localeCompare(b.source.last_success_at ?? ''),
      render: (_, row) => {
        const days = row.source.last_success_at
          ? dayjs().diff(dayjs(row.source.last_success_at), 'day')
          : null
        return (
          <Tooltip title={formatTime(row.source.last_success_at)} mouseEnterDelay={0.3}>
            <span className={days === null || days >= STALE_DAYS ? 'src-stale' : ''}>
              {formatRelative(row.source.last_success_at)}
            </span>
          </Tooltip>
        )
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 176,
      align: 'right',
      render: (_, row) => (
        <div className="src-actions">
          <Tooltip title={row.stat ? `查看素材(近 30 天入库 ${row.stat.ingested} 条)` : '查看该信源的素材'}>
            <Button
              className="src-icon-btn"
              icon={<UnorderedListOutlined />}
              aria-label="查看素材"
              onClick={() => navigate(`/pool?tab=material&source_id=${row.source.id}`)}
            />
          </Tooltip>
          {/* 低频与危险操作 hover 才显形:行内只留一个常驻入口,误触由二次确认兜底 */}
          <div className="src-actions-more">
            <Tooltip title="测试抓取">
              <Button
                className="src-icon-btn"
                icon={<ThunderboltOutlined />}
                aria-label="测试抓取"
                loading={testMutation.isPending && testMutation.variables === row.source.id}
                onClick={() => testMutation.mutate(row.source.id)}
              />
            </Tooltip>
            <Tooltip title="编辑信源">
              <Button
                className="src-icon-btn"
                icon={<EditOutlined />}
                aria-label="编辑信源"
                onClick={() => openEditor(row.source)}
              />
            </Tooltip>
            <Popconfirm
              title={`删除信源「${row.source.name}」?`}
              description="删除后不可恢复,已采集的素材不受影响。"
              okText="删除"
              cancelText="取消"
              okButtonProps={{ danger: true, loading: deleteMutation.isPending }}
              onConfirm={() => deleteMutation.mutate(row.source.id)}
            >
              <Tooltip title="删除信源">
                <Button
                  className="src-icon-btn is-danger"
                  icon={<DeleteOutlined />}
                  aria-label="删除信源"
                  disabled={deleteMutation.isPending}
                />
              </Tooltip>
            </Popconfirm>
          </div>
        </div>
      ),
    },
  ]

  return (
    <div className="sources-page">
      {/* 工具区:筛选收敛在一行,统计条给下面每一行的判断提供锚点 */}
      <div className="src-surface src-toolbar">
        <div className="src-toolbar-row">
          <Space size={8} wrap>
            <Input.Search
              allowClear
              placeholder="搜索名称 / URL / 渠道"
              style={{ width: 260 }}
              value={sourceSearch}
              onChange={(event) => {
                setSourceSearch(event.target.value)
                setPage(1)
              }}
            />
            <Segmented
              value={healthFilter}
              onChange={(value) => {
                setHealthFilter(value as HealthFilter)
                setPage(1)
              }}
              options={filterOptions}
            />
          </Space>
          <Space size={8}>
            <Button
              onClick={() => {
                setDiscoverOpen(true)
                setDiscoverResult(null)
                setDiscoverSelected([])
              }}
            >
              信源发现
            </Button>
            <Button onClick={() => setRecommendOpen(true)}>推荐信源库</Button>
            <Button type="primary" onClick={() => openEditor()}>
              新建信源
            </Button>
          </Space>
        </div>
        <div className="src-stats">
          <span className="src-stat">
            共 <b>{summary.total}</b> 个信源
          </span>
          <span className="src-stat is-alert">
            连续失败 <b>{summary.failed}</b>
          </span>
          {summary.stale > 0 ? (
            <span className="src-stat is-warn">
              长时间无成功 <b>{summary.stale}</b>
            </span>
          ) : null}
          <span className="src-stat is-warn">
            近 30 天无产出 <b>{summary.idle}</b>
          </span>
          <span className="src-stat">
            30 天入库 <b>{summary.ingested}</b>
            <span className="src-muted"> / 候选 {summary.candidates}</span>
          </span>
          <span className="src-stat">
            平均均分 <b>{summary.avg}</b>
          </span>
          <span className="src-stat">
            最近采集 <b>{formatRelative(summary.lastFetch)}</b>
          </span>
        </div>
      </div>

      <div className="src-surface src-table">
        <Table<SourceRow>
          rowKey={(row) => row.source.id}
          loading={tableLoading}
          dataSource={tableLoading ? [] : visibleSources}
          columns={columns}
          rowClassName={(row) => `src-row is-${row.health}`}
          /* 固定布局 + 最小宽度:窄屏横向滚动,而不是把每列压到竖排换行。
             必须 fixed:auto 布局会按内容算列宽,数据一到列宽整体重排 → 横向抖动 */
          tableLayout="fixed"
          scroll={{ x: 1200 }}
          pagination={{
            current: page,
            pageSize,
            showSizeChanger: true,
            pageSizeOptions: ['20', '50', '100'],
            showTotal: (total, range) => `${range[0]}-${range[1]} / 共 ${total} 个`,
            onChange: (nextPage, nextSize) => {
              if (nextSize !== pageSize) {
                setPageSize(nextSize)
                setPage(1)
              } else {
                setPage(nextPage)
              }
            },
          }}
          expandable={{
            /* 展开指示符用 chevron 而不是带框「＋」:方框加号在行内会被读成「添加」,
               chevron（收起 → 展开旋转 90°）才是表格展开的通用约定,也不需要 22px 的方框 */
            columnWidth: 32,
            expandIcon: renderTableExpander,
            expandedRowClassName: () => 'src-row-expanded',
            expandedRowRender: (row) => (
              <div className="src-expand">
                <div>{row.source.url}</div>
                {row.source.last_error ? (
                  <div className="src-expand-error">最近错误:{row.source.last_error}</div>
                ) : null}
                <div className="src-muted">
                  创建 {formatTime(row.source.created_at)} · 上次抓取{' '}
                  {formatRelative(row.source.last_fetch_at)} · 采集类型 {row.source.collector_kind}
                </div>
              </div>
            ),
          }}
        />
      </div>

      <Modal
        title={editing ? `编辑信源:${editing.name}` : '新建信源'}
        open={open}
        width={640}
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
        confirmLoading={saveMutation.isPending}
      >
        <Form form={form} layout="vertical" onFinish={(values) => saveMutation.mutate(values)}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Space size={16} wrap>
            <Form.Item name="channel" label="渠道" rules={[{ required: true }]}>
              <Select
                style={{ width: 160 }}
                options={[
                  { value: 'rss', label: 'RSS / Atom' },
                  { value: 'arxiv', label: 'arXiv' },
                  { value: 'google_news', label: 'Google News 检索' },
                  { value: 'bing_news', label: 'Bing News 检索' },
                  { value: 'hackernews', label: 'Hacker News' },
                  { value: 'repo', label: 'GitHub 仓库检索' },
                  { value: 'skill', label: 'GitHub Skill 检索' },
                  { value: 'model', label: 'HuggingFace 模型' },
                  { value: 'github', label: 'GitHub Trending' },
                ]}
              />
            </Form.Item>
            <Form.Item name="collector_kind" label="采集类型" rules={[{ required: true }]}>
              <Select
                style={{ width: 160 }}
                options={[
                  { value: 'stream', label: 'stream 持续流' },
                  { value: 'trend', label: 'trend 榜单' },
                  { value: 'search', label: 'search 关键词检索' },
                ]}
              />
            </Form.Item>
            <Form.Item name="tier" label="Tier">
              <Select
                style={{ width: 100 }}
                options={['S', 'A', 'B', 'C'].map((value) => ({ value, label: value }))}
              />
            </Form.Item>
          </Space>
          <Form.Item name="url" label="URL" rules={[{ required: true }]}>
            <Input placeholder="https://..." />
          </Form.Item>
          <Form.Item name="config_text" label="高级配置(JSON)">
            <Input.TextArea rows={4} placeholder='例如 arXiv: {"categories": ["cs.AI", "cs.CL"]}' />
          </Form.Item>
          <Space size={16} wrap>
            <Form.Item name="fetch_interval_minutes" label="抓取频率(分钟)" rules={[{ required: true }]}>
              <InputNumber min={5} max={1440} />
            </Form.Item>
            <Form.Item name="enabled" label="启用" valuePropName="checked">
              <Switch />
            </Form.Item>
          </Space>
        </Form>
      </Modal>

      <Modal
        title="推荐信源库"
        open={recommendOpen}
        width={880}
        onCancel={() => setRecommendOpen(false)}
        onOk={() => importMutation.mutate()}
        okText={`导入所选(${selectedKeys.length})`}
        confirmLoading={importMutation.isPending}
        okButtonProps={{ disabled: selectedKeys.length === 0 }}
      >
        <Space wrap style={{ marginBottom: 8 }}>
          <Select
            allowClear
            placeholder="全部类别"
            style={{ width: 160 }}
            value={recommendCategory}
            onChange={setRecommendCategory}
            options={Object.entries(RECOMMEND_CATEGORY_META).map(([value, meta]) => ({
              value,
              label: meta.label,
            }))}
          />
          <Button
            size="small"
            onClick={() =>
              setSelectedKeys(
                visibleRecommended
                  .filter((item) => !importedNames.has(item.name))
                  .map((item) => item.key),
              )
            }
          >
            全选本类
          </Button>
          <Button
            size="small"
            onClick={() =>
              setSelectedKeys(
                visibleRecommended
                  .filter((item) => item.tier === 'A' && !importedNames.has(item.name))
                  .map((item) => item.key),
              )
            }
          >
            仅选本类 A 级
          </Button>
          <Button size="small" onClick={() => setSelectedKeys([])}>
            清空
          </Button>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            已导入的信源自动跳过;建议先导入 A 级,再按「测试」确认可得性
          </Typography.Text>
        </Space>
        <Table<RecommendedSource>
          rowKey="key"
          size="small"
          dataSource={visibleRecommended}
          pagination={false}
          scroll={{ y: 420 }}
          rowSelection={{
            selectedRowKeys: selectedKeys,
            onChange: (keys) => setSelectedKeys(keys as string[]),
            getCheckboxProps: (record) => ({ disabled: importedNames.has(record.name) }),
          }}
          columns={[
            {
              title: '名称',
              dataIndex: 'name',
              render: (value, record) => (
                <Space size={4} wrap>
                  <span>{value}</span>
                  {importedNames.has(record.name) && <Tag>已导入</Tag>}
                </Space>
              ),
            },
            {
              title: '类别',
              dataIndex: 'category',
              width: 104,
              render: (value: string) => (
                <Tag color={RECOMMEND_CATEGORY_META[value]?.color}>
                  {RECOMMEND_CATEGORY_META[value]?.label ?? value ?? '其他'}
                </Tag>
              ),
            },
            { title: '渠道', dataIndex: 'channel', width: 84 },
            { title: 'Tier', dataIndex: 'tier', width: 56 },
            {
              title: '说明',
              dataIndex: 'description',
              render: (value) => <span style={{ fontSize: 12, color: '#888' }}>{value}</span>,
            },
          ]}
        />
      </Modal>
      <Modal
        title="信源发现"
        open={discoverOpen}
        width={920}
        onCancel={() => setDiscoverOpen(false)}
        onOk={() => importCandidatesMutation.mutate()}
        okText={`导入所选(${discoverSelected.length})`}
        confirmLoading={importCandidatesMutation.isPending}
        okButtonProps={{ disabled: discoverSelected.length === 0 }}
      >
        <Space.Compact style={{ width: '100%' }}>
          <Input
            value={discoverUrl}
            onChange={(event) => setDiscoverUrl(event.target.value)}
            onPressEnter={() => {
              if (discoverUrl.trim()) discoverMutation.mutate(discoverUrl.trim())
            }}
            placeholder="GitHub 仓库地址 / OPML 链接 / 博客或站点首页,如 https://github.com/example/awesome-feeds"
          />
          <Button
            type="primary"
            loading={discoverMutation.isPending}
            onClick={() => {
              if (discoverUrl.trim()) discoverMutation.mutate(discoverUrl.trim())
            }}
          >
            探测
          </Button>
        </Space.Compact>
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 8, marginBottom: 8 }}>
          支持 GitHub 仓库(自动找 OPML / feeds 清单并解析 README)、OPML 文件、页面声明的 RSS/Atom。探测通过且未存在的条目默认勾选,导入渠道为 rss。
        </Typography.Paragraph>
        {discoverResult && (
          <Space wrap style={{ marginBottom: 8 }}>
            <Tag color="green">可达 {discoverResult.ok_count}</Tag>
            <Tag>共 {discoverResult.candidates.length}</Tag>
            <Select
              style={{ width: 120 }}
              value={discoverTier}
              onChange={setDiscoverTier}
              options={['S', 'A', 'B', 'C'].map((value) => ({ value, label: `Tier ${value}` }))}
            />
            <Button
              size="small"
              onClick={() =>
                setDiscoverSelected(
                  discoverResult.candidates
                    .filter((item) => item.ok && !item.already_exists)
                    .map((item) => item.url),
                )
              }
            >
              全选可达
            </Button>
            <Button size="small" onClick={() => setDiscoverSelected([])}>
              清空
            </Button>
          </Space>
        )}
        {discoverResult && (
          <Table<DiscoverCandidate>
            rowKey="url"
            size="small"
            dataSource={discoverResult.candidates}
            pagination={false}
            scroll={{ y: 360 }}
            rowSelection={{
              selectedRowKeys: discoverSelected,
              onChange: (keys) => setDiscoverSelected(keys as string[]),
              getCheckboxProps: (record) => ({ disabled: !record.ok || record.already_exists }),
            }}
            columns={[
              {
                title: '名称',
                dataIndex: 'name',
                render: (value: string, record) => (
                  <div>
                    <div>{value}</div>
                    {record.title && record.title !== value && (
                      <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                        {record.title}
                      </Typography.Text>
                    )}
                  </div>
                ),
              },
              {
                title: 'URL',
                dataIndex: 'url',
                render: (value: string) => (
                  <Typography.Text style={{ fontSize: 12 }} ellipsis={{ tooltip: value }}>
                    {value}
                  </Typography.Text>
                ),
              },
              {
                title: '探测',
                width: 220,
                render: (_, record) =>
                  record.ok ? (
                    <Space size={4}>
                      <Tag color="green">{record.entries} 条</Tag>
                      <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                        最新 {formatTime(record.latest)}
                      </Typography.Text>
                    </Space>
                  ) : (
                    <Typography.Text type="danger" style={{ fontSize: 12 }}>
                      {record.error ?? '不可达'}
                    </Typography.Text>
                  ),
              },
              {
                title: '状态',
                width: 76,
                render: (_, record) => (record.already_exists ? <Tag>已存在</Tag> : null),
              },
            ]}
          />
        )}
      </Modal>
    </div>
  )
}
