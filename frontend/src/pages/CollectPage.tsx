import {
  ApiOutlined,
  DatabaseOutlined,
  FilterOutlined,
  SettingOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Descriptions,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Radio,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api } from '../api/client'
import type { JobRun, Source } from '../api/types'
import PipelineBoard from '../components/PipelineBoard'
import type { PipelineStage, StageState } from '../components/PipelineBoard'
import StageTable, { readStagesFromJob } from '../components/StageTable'
import type { StageInfo } from '../components/StageTable'
import { formatTokens } from '../utils'

const STAGE_COLORS = ['#13c2c2', '#1677ff', '#22c55e', '#f59e0b', '#a855f7']
const STAGE_SOFT = ['#e6fffb', '#e6f0ff', '#e7f8ee', '#fef3e2', '#f6ecfe']

interface CollectForm {
  name?: string
  keywords: string[]
  schedule_enabled?: boolean
  schedule_name?: string
  schedule_interval?: number
  exclude_keywords?: string[]
  source_ids?: number[]
  lookback_hours: number
  min_score: number
  scopes: Array<'info' | 'github'>
  github_keywords?: string[]
  github_mode: 'strict' | 'trending_fallback'
  backfill: 'auto' | 'off'
}

interface SourceDetail {
  source_id: number
  name: string
  engine: string
  preset: string
  kind: string
  seconds: number
  fetched: number
  filtered: number
  duplicates: number
  low_score: number
  ingested: number
  error: string | null
  round?: string
}

/** 前 5 张流水线卡片与后端 8 个阶段的映射。 */
const CARD_STAGE_KEYS: Record<string, string[]> = {
  config: ['setup'],
  collect: ['sources', 'collect'],
  normalize: ['normalize', 'dedup'],
  enrich: ['enrich', 'score'],
  store: ['store'],
}

const CARD_ORDER = ['config', 'collect', 'normalize', 'enrich', 'store'] as const

function cardState(stages: StageInfo[], keys: string[], legacy: StageState): StageState {
  if (!stages.length) return legacy
  const group = stages.filter((stage) => keys.includes(stage.key))
  if (!group.length) return 'pending'
  if (group.some((stage) => stage.status === 'error')) return 'error'
  if (group.some((stage) => stage.status === 'running')) return 'running'
  if (group.every((stage) => stage.status === 'success' || stage.status === 'skipped')) {
    return 'success'
  }
  return 'pending'
}

/** 卡片注释:真实阶段耗时(如「信源 0.0s · 采集 15.6s」)。 */
function stageNote(stages: StageInfo[], keys: string[]): string | undefined {
  const group = stages.filter((stage) => keys.includes(stage.key) && stage.status !== 'pending')
  if (!group.length) return undefined
  return group
    .map((stage) =>
      stage.status === 'skipped' ? `${stage.label} 跳过` : `${stage.label} ${(stage.seconds ?? 0).toFixed(1)}s`,
    )
    .join(' · ')
}

function sourceDetailsFromJob(job?: JobRun | null): SourceDetail[] {
  const raw = (job?.result as { sources_detail?: unknown } | undefined)?.sources_detail
  if (!Array.isArray(raw)) return []
  return raw.filter(
    (row): row is SourceDetail =>
      !!row && typeof row === 'object' && typeof (row as SourceDetail).name === 'string',
  )
}

interface IngestLine {
  type: string
  title: string
  relevance: string
  heat: string
  freshness: string
  total: string
  url?: string
}

function parseIngestedFromLog(log: string): IngestLine[] {
  const lines: IngestLine[] = []
  const pattern =
    /^(?:\[入库\]\s+(\w+)|入库\[(\w+)\])\s+(.+?)\s+\(相关\s+([\d.]+)\s+\/\s+热度\s+([\d.]+)\s+\/\s+时效\s+([\d.]+)\s+→\s+([\d.]+)\)$/gm
  for (const match of log.matchAll(pattern)) {
    lines.push({
      type: match[1] ?? match[2],
      title: match[3],
      relevance: match[4],
      heat: match[5],
      freshness: match[6],
      total: match[7],
    })
  }
  return lines
}

/** 优先使用后端结构化结果(标题完整、带原文链接),旧任务回退到日志解析。 */
function ingestedFromJob(job?: JobRun | null): IngestLine[] {
  const raw = (job?.result as { items?: unknown } | undefined)?.items
  if (Array.isArray(raw) && raw.length) {
    return raw.map((row) => {
      const record = row as Record<string, unknown>
      return {
        type: String(record.type ?? ''),
        title: String(record.title ?? ''),
        relevance: String(record.relevance ?? '-'),
        heat: String(record.heat ?? '-'),
        freshness: String(record.freshness ?? '-'),
        total: String(record.total ?? '-'),
        url: typeof record.url === 'string' ? record.url : undefined,
      }
    })
  }
  return parseIngestedFromLog(job?.log ?? '')
}

/** 旧任务(无结构化阶段数据)的回退:按日志关键字推测已完成阶段数(0–5)。 */
function legacyStageProgress(job?: JobRun | null): number {
  if (!job) return 0
  if (job.status === 'succeeded') return 5
  const log = job.log || ''
  if (/入库\[/.test(log) || /完成: 新入库/.test(log)) return 4
  if (/标准化完成|候选均已存在|本轮无新增候选/.test(log)) return 3
  if (/抓取 \d+ 条|抓取失败/.test(log)) return 2
  if (/没有可用信源/.test(log)) return 1
  if (/未提供(采集参数|包含关键词)/.test(log)) return 0
  return 1
}

function legacyStageStates(job?: JobRun | null): StageState[] {
  const progress = legacyStageProgress(job)
  return Array.from({ length: 5 }, (_, index) => {
    if (index < progress) return 'success'
    if (index > progress) return 'pending'
    if (job?.status === 'failed') return 'error'
    if (job?.status === 'succeeded') return 'success'
    return 'running'
  })
}

function formatTime(value?: string | null): string {
  if (!value) return '—'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

export default function CollectPage() {
  const queryClient = useQueryClient()
  const [form] = Form.useForm<CollectForm>()
  const [jobId, setJobId] = useState<string | null>(null)
  const [configOpen, setConfigOpen] = useState(false)

  const { data: sources } = useQuery({
    queryKey: ['sources'],
    queryFn: () => api.get<Source[]>('/sources'),
  })

  const { data: recentJobs } = useQuery({
    queryKey: ['jobs', 'fetch', 'latest'],
    queryFn: () => api.get<{ items: JobRun[] }>('/jobs?kind=fetch&page_size=1'),
  })

  useEffect(() => {
    if (!jobId && recentJobs?.items?.length) {
      setJobId(recentJobs.items[0].id)
    }
  }, [recentJobs, jobId])

  const { data: job } = useQuery({
    queryKey: ['job', jobId],
    queryFn: () => api.get<JobRun>(`/jobs/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'pending' || status === 'running' ? 2000 : false
    },
  })

  const running = job?.status === 'pending' || job?.status === 'running'

  const { data: overview } = useQuery({
    queryKey: ['stats', 'overview'],
    queryFn: () => api.get<{ items_total: number }>('/stats/overview'),
    refetchInterval: running ? 5000 : false,
  })

  useEffect(() => {
    if (job?.status === 'succeeded') {
      queryClient.invalidateQueries({ queryKey: ['stats', 'overview'] })
    }
  }, [job?.status, queryClient])

  const startMutation = useMutation({
    mutationFn: async (values: CollectForm) => {
      const created = await api.post<JobRun>('/jobs/fetch', {
        name: values.name?.trim() || '临时采集',
        keywords: values.keywords,
        exclude_keywords: values.exclude_keywords ?? [],
        source_ids: values.source_ids ?? [],
        lookback_hours: values.lookback_hours,
        min_score: values.min_score,
        scopes: values.scopes?.length ? values.scopes : ['info', 'github'],
        github_keywords: values.github_keywords ?? [],
        github_mode: values.github_mode ?? 'trending_fallback',
        backfill: values.backfill ?? 'auto',
      })
      if (values.schedule_enabled) {
        await api.post('/schedules', {
          name: values.schedule_name?.trim() || values.name?.trim() || '定时采集',
          keywords: values.keywords,
          exclude_keywords: values.exclude_keywords ?? [],
          source_ids: values.source_ids ?? [],
          lookback_hours: values.lookback_hours,
          min_score: values.min_score,
          scopes: values.scopes?.length ? values.scopes : ['info', 'github'],
          github_keywords: values.github_keywords ?? [],
          github_mode: values.github_mode ?? 'trending_fallback',
          backfill: values.backfill ?? 'auto',
          interval_minutes: values.schedule_interval ?? 360,
          enabled: true,
          last_job_id: created.id,
        })
      }
      return { created, scheduled: Boolean(values.schedule_enabled) }
    },
    onSuccess: ({ created, scheduled }) => {
      message.success(scheduled ? '采集已提交,并已保存为定时任务' : '采集任务已提交')
      setConfigOpen(false)
      setJobId(created.id)
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      if (scheduled) queryClient.invalidateQueries({ queryKey: ['schedules'] })
    },
    onError: (error: Error) => message.error(error.message),
  })

  const digestMutation = useMutation({
    mutationFn: () => {
      const values = form.getFieldsValue()
      const keywords = (values.keywords ?? []).map((word) => word.trim()).filter(Boolean)
      const base = {
        period_hours: values.lookback_hours ?? 24,
        min_score: values.min_score ?? 60,
      }
      const payload = keywords.length
        ? {
            scope: 'topic',
            topic: values.name?.trim() || undefined,
            keywords,
            ...base,
          }
        : { scope: 'global', ...base }
      return api.post<JobRun>('/digests/generate', payload)
    },
    onSuccess: () =>
      message.success('日报任务已创建(按当前方向 / 关键词),可到「日报 / 素材池」查看'),
    onError: (error: Error) => message.error(error.message),
  })

  const formKeywords = (Form.useWatch('keywords', form) as string[] | undefined) ?? []
  const formName = Form.useWatch('name', form) as string | undefined
  const formLookbackHours = Form.useWatch('lookback_hours', form) as number | undefined
  const formMinScore = Form.useWatch('min_score', form) as number | undefined
  const formScopes = (Form.useWatch('scopes', form) as CollectForm['scopes'] | undefined) ?? ['info', 'github']
  const scheduleOn = Boolean(Form.useWatch('schedule_enabled', form))
  const formGithubMode =
    (Form.useWatch('github_mode', form) as CollectForm['github_mode'] | undefined) ??
    'trending_fallback'
  const formBackfill =
    (Form.useWatch('backfill', form) as CollectForm['backfill'] | undefined) ?? 'auto'
  const cfgLookback = formLookbackHours ?? 24
  const cfgMinScore = formMinScore ?? 75
  const stageInfos = useMemo(() => readStagesFromJob(job), [job])
  const enrichStageInfo = stageInfos.find((stage) => stage.key === 'enrich')
  const enrichCounters = (enrichStageInfo?.counters ?? {}) as Record<string, unknown>
  const sourceDetails = useMemo(() => sourceDetailsFromJob(job), [job])
  const liveStage = stageInfos.find((stage) => stage.status === 'running')
  const legacyStates = useMemo(() => legacyStageStates(job), [job])
  const states = CARD_ORDER.map((key, index) =>
    cardState(stageInfos, CARD_STAGE_KEYS[key], legacyStates[index]),
  )
  const ingested = useMemo(() => ingestedFromJob(job), [job])
  const report = useMemo(() => (job ? buildReport(job, sources ?? [], ingested) : ''), [job, sources, ingested])

  const hasResult = !!job && (job.status === 'succeeded' || job.status === 'failed')
  const result = (job?.result ?? {}) as Record<string, unknown>
  const numberOf = (value: unknown) => (typeof value === 'number' ? value : Number(value ?? 0) || 0)
  const fetched = numberOf(result.fetched)
  const duplicates = numberOf(result.duplicates)
  const filtered = numberOf(result.filtered)
  const newItems = numberOf(result.new_items)
  const failedSources = numberOf(result.failed_sources)
  const llmErrors = numberOf(result.llm_errors)
  const lowScore = numberOf(result.low_score)
  const avgScore = ingested.length
    ? (ingested.reduce((acc, row) => acc + Number(row.total || 0), 0) / ingested.length).toFixed(1)
    : '—'
  const elapsed = job?.started_at && job?.finished_at
    ? `${((new Date(job.finished_at).getTime() - new Date(job.started_at).getTime()) / 1000).toFixed(1)}s`
    : '—'
  const stageElapsed = typeof result.elapsed_seconds === 'number' ? `${Number(result.elapsed_seconds).toFixed(1)}s` : elapsed
  const emptyReason = useMemo(() => {
    if (!hasResult || job?.status !== 'succeeded' || newItems > 0) return null
    if (duplicates > 0) {
      return `本轮没有新增素材:去重跳过 ${duplicates} 条(候选均已存在于素材库),因此未触发 LLM 富化。这是正常的增量采集结果。`
    }
    if (lowScore > 0) {
      return `新候选有 ${lowScore} 条低于入库门槛(${cfgMinScore},最低 75),可在配置中调整门槛后重采。`
    }
    if (filtered > 0) {
      return `抓取到 ${fetched} 条,但关键词粗筛过滤 ${filtered} 条,没有进入富化环节。`
    }
    return '本轮没有抓到候选条目,可放宽关键词或延长回看窗口后重采。'
  }, [hasResult, job?.status, newItems, duplicates, lowScore, filtered, fetched, cfgMinScore])
  const backfillInfo = (result.backfill ?? null) as
    | { keywords?: string[]; fetched?: number; new_items?: number; skipped?: string }
    | null
  const shortfallInfo = (result.shortfall ?? null) as
    | { expected?: number; actual?: number }
    | null
  const specInfo = (result.spec ?? {}) as {
    keywords?: string[]
    keyword_translations?: Record<string, string[]>
  }
  const typedKeywords = ((job?.params?.keywords as string[]) ?? []).filter(Boolean)
  const translatedKeywords = (specInfo.keywords ?? []).filter(
    (word) => !typedKeywords.includes(word),
  )
  const expandedKeywords = backfillInfo?.keywords ?? []
  const backfillSkipReasons: Record<string, string> = {
    llm_unavailable: 'LLM 未配置',
    no_expanded_keywords: '未生成辐射词',
    all_sources_failed: '信源全部失败',
  }
  const scrollTo = (id: string) =>
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  const llmUsage = (result.llm_usage ?? {}) as {
    calls?: number
    prompt_tokens?: number
    completion_tokens?: number
    total_tokens?: number
  }
  const enrichTokens = numberOf(enrichCounters.tokens) || numberOf(llmUsage.total_tokens)
  const enrichDegraded = numberOf(result.llm_degraded) || numberOf(enrichCounters.degraded)
  const enrichNoteBase =
    stageNote(stageInfos, CARD_STAGE_KEYS.enrich) ??
    (ingested.length ? `${ingested.length} 条带三维分数` : '随采集任务自动执行')
  const enrichNoteSuffix = [
    enrichDegraded > 0 ? `降级 ${enrichDegraded} 条(超上限,未用 LLM)` : '',
    llmErrors > 0 ? `LLM 错误 ${llmErrors} 条` : '',
    enrichTokens > 0 ? `Token ${formatTokens(enrichTokens)}` : '',
  ]
    .filter(Boolean)
    .join(' · ')

  const stages: PipelineStage[] = [
    {
      key: 'config',
      title: '配置',
      desc: '研究方向 · 关键词 · 回看窗口 · 入库门槛',
      color: STAGE_COLORS[0],
      soft: STAGE_SOFT[0],
      icon: <SettingOutlined />,
      state: states[0],
      stats: [
        { label: '关键词', value: formKeywords.length },
        { label: '回看窗口', value: `${cfgLookback}h` },
        { label: '入库门槛', value: cfgMinScore },
      ],
      action: {
        label: job ? '修改配置' : '配置采集',
        onClick: () => setConfigOpen(true),
        disabled: running,
      },
      note:
        stageNote(stageInfos, CARD_STAGE_KEYS.config) ??
        (formName ? `${formName} · 即输即用,不保存预设` : '关键词即输即用,不保存预设'),
    },
    {
      key: 'collect',
      title: '采集',
      desc: '从配置的信源并发抓取原始条目',
      color: STAGE_COLORS[1],
      soft: STAGE_SOFT[1],
      icon: <ApiOutlined />,
      state: states[1],
      stats: [
        { label: '抓取', value: fetched },
        { label: '信源', value: numberOf(result.sources) },
        { label: '失败源', value: failedSources },
      ],
      action: {
        label: '查看日志',
        onClick: () => scrollTo('collect-log'),
        disabled: !job?.log,
      },
      note:
        stageNote(stageInfos, CARD_STAGE_KEYS.collect) ??
        (job?.started_at ? `${formatTime(job.started_at)} · 总耗时 ${stageElapsed}` : '尚未执行'),
    },
    {
      key: 'normalize',
      title: '标准化',
      desc: 'URL 归一化 · 指纹/SimHash 去重 · 关键词过滤',
      color: STAGE_COLORS[2],
      soft: STAGE_SOFT[2],
      icon: <FilterOutlined />,
      state: states[2],
      stats: [
        { label: '去重', value: duplicates },
        { label: '过滤', value: filtered },
        { label: '候选', value: Math.max(fetched - duplicates - filtered, 0) },
      ],
      action: { label: '查看报告', onClick: () => scrollTo('collect-report'), disabled: !report },
      note:
        stageNote(stageInfos, CARD_STAGE_KEYS.normalize) ??
        (job?.log ? '标准化明细见运行日志' : '随采集任务自动执行'),
    },
    {
      key: 'enrich',
      title: '富化打分',
      desc: 'LLM 翻译 · 摘要 · 相关/热度/时效三维打分',
      color: STAGE_COLORS[3],
      soft: STAGE_SOFT[3],
      icon: <ThunderboltOutlined />,
      state: states[3],
      stats: [
        { label: '富化', value: numberOf(enrichCounters.done) || newItems },
        { label: 'Token', value: enrichTokens > 0 ? formatTokens(enrichTokens) : '—' },
        { label: '均分', value: avgScore },
      ],
      action: {
        label: '生成日报',
        onClick: () => digestMutation.mutate(),
        loading: digestMutation.isPending,
        disabled: !hasResult || job?.status !== 'succeeded',
      },
      note: enrichNoteSuffix ? `${enrichNoteBase} · ${enrichNoteSuffix}` : enrichNoteBase,
    },
    {
      key: 'store',
      title: '入库产出',
      desc: '入库形成资讯流与日报素材池',
      color: STAGE_COLORS[4],
      soft: STAGE_SOFT[4],
      icon: <DatabaseOutlined />,
      state: states[4],
      stats: [
        { label: '本次入库', value: newItems },
        { label: '低分跳过', value: lowScore },
        { label: '资讯流累计', value: overview?.items_total ?? '—' },
      ],
      action: {
        label: '查看资讯流',
        onClick: () => window.location.assign('/feed'),
        disabled: !hasResult,
      },
      note:
        stageNote(stageInfos, CARD_STAGE_KEYS.store) ??
        (job?.finished_at ? `完成于 ${formatTime(job.finished_at)}` : '等待入库'),
    },
  ]

  return (
    <div>
      <Space style={{ width: '100%', justifyContent: 'space-between' }} align="start">
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>
            采集工作台
          </Typography.Title>
          <Typography.Text type="secondary">
            输入研究方向关键词即可采集:去重 → 翻译 → 摘要 → 相关/热度/时效打分 → 入库
          </Typography.Text>
        </div>
        <Space>
          <Link to="/feed">
            <Button>查看资讯流</Button>
          </Link>
        </Space>
      </Space>

      <div style={{ marginTop: 16 }}>
        <PipelineBoard
          title="研讯采集流水线"
          tag={<Tag color="blue">{job?.params?.name ? String(job.params.name) : '未执行'}</Tag>}
          schedule="手动触发;关键词即输即用,不保存预设"
          refreshing={running}
          onRefresh={() => {
            queryClient.invalidateQueries({ queryKey: ['job', jobId] })
            queryClient.invalidateQueries({ queryKey: ['jobs', 'fetch', 'latest'] })
          }}
          stages={stages}
        />
      </div>

      <Modal
        title="采集配置"
        open={configOpen}
        onCancel={() => setConfigOpen(false)}
        onOk={() => form.submit()}
        okText={job ? '重新采集' : '开始采集'}
        cancelText="取消"
        confirmLoading={startMutation.isPending}
        okButtonProps={{ style: { background: STAGE_COLORS[0], borderColor: STAGE_COLORS[0] } }}
        width={520}
        forceRender
      >
        <Form<CollectForm>
          form={form}
          layout="vertical"
          style={{ marginTop: 8 }}
          initialValues={{
            lookback_hours: 24,
            min_score: 75,
            keywords: [],
            scopes: ['info', 'github'],
            github_mode: 'trending_fallback',
            backfill: 'auto',
            schedule_interval: 360,
          }}
          onFinish={(values) => startMutation.mutate(values)}
        >
          <Form.Item name="name" label="研究方向">
            <Input placeholder="例如:LLM Agent / 具身智能 / 多模态" allowClear maxLength={50} />
          </Form.Item>
          <Form.Item
            name="keywords"
            label="关键词(命中任一即收录,输入后回车)"
            rules={[{ required: true, message: '至少填写一个关键词' }]}
          >
            <Select
              mode="tags"
              open={false}
              tokenSeparators={[',', '、', ' ', ';']}
              placeholder="例如:agent / 大模型 / embodied / 机器人"
            />
          </Form.Item>
          <Form.Item
            name="scopes"
            label="采集类型"
            rules={[{ required: true, message: '至少选择一种采集类型' }]}
          >
            <Checkbox.Group
              options={[
                { label: '资讯·论文(RSS / 新闻 / arXiv)', value: 'info' },
                { label: 'GitHub(热榜 / 仓库检索)', value: 'github' },
              ]}
            />
          </Form.Item>
          {formScopes.includes('github') && (
            <>
              <Form.Item
                name="github_keywords"
                label="GitHub 关键词(留空沿用上方关键词)"
                tooltip="GitHub 与资讯可以用不同的检索词,例如资讯用「生物科技」,GitHub 用「biotech agent」"
              >
                <Select
                  mode="tags"
                  open={false}
                  tokenSeparators={[',', '、', ' ', ';']}
                  placeholder="例如:agent / llm / embodied"
                />
              </Form.Item>
              <Form.Item name="github_mode" label="GitHub 采集策略">
                <Radio.Group>
                  <Radio value="trending_fallback">关键词优先 + 热榜兜底(推荐)</Radio>
                  <Radio value="strict">严格按关键词</Radio>
                </Radio.Group>
              </Form.Item>
            </>
          )}
          <Form.Item
            name="backfill"
            label="素材不足时"
            tooltip="单次新入库少于 5 条时:自动让 LLM 生成相关词再补采一轮(不会递归扩采)"
          >
            <Radio.Group>
              <Radio value="auto">自动补量一轮(推荐)</Radio>
              <Radio value="off">仅提示,不补量</Radio>
            </Radio.Group>
          </Form.Item>
          <Form.Item name="schedule_enabled" valuePropName="checked">
            <Checkbox>
              保存为定时任务
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                (本次先跑一次,之后按间隔自动采集)
              </Typography.Text>
            </Checkbox>
          </Form.Item>
          {scheduleOn && (
            <Space size="large" wrap>
              <Form.Item name="schedule_name" label="定时任务名称">
                <Input placeholder="默认沿用研究方向" allowClear maxLength={80} style={{ width: 200 }} />
              </Form.Item>
              <Form.Item name="schedule_interval" label="采集间隔">
                <Select
                  style={{ width: 150 }}
                  options={[
                    { value: 60, label: '每小时' },
                    { value: 180, label: '每 3 小时' },
                    { value: 360, label: '每 6 小时' },
                    { value: 720, label: '每 12 小时' },
                    { value: 1440, label: '每天' },
                    { value: 10080, label: '每周' },
                  ]}
                />
              </Form.Item>
            </Space>
          )}
          <Space size="large">
            <Form.Item
              name="lookback_hours"
              label="回看窗口(小时)"
              tooltip="最长 48 小时"
            >
              <InputNumber min={1} max={48} style={{ width: 140 }} />
            </Form.Item>
            <Form.Item
              name="min_score"
              label="入库门槛"
              tooltip="最低 75 分;三维总分低于此值不入库,总分 = 0.45×相关 + 0.35×热度 + 0.20×时效"
            >
              <InputNumber min={75} max={100} style={{ width: 140 }} />
            </Form.Item>
          </Space>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            关键词与方向即输即用,不保存预设;采集类型决定使用「来源池」中的哪些信源
            (资讯·论文 = rss/news,GitHub = github)。
          </Typography.Text>
        </Form>
      </Modal>

      <Card
        title="采集进度与结果"
        style={{ marginTop: 16 }}
        extra={
          <Space>
            {running && <Spin size="small" />}
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              日报可在流水线「富化打分」环节一键生成
            </Typography.Text>
          </Space>
        }
      >
        {!job ? (
          <Empty description="还没有采集记录,填写关键词后点击「开始采集」" />
        ) : (
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            <Space wrap>
              <Tag color={job.status === 'succeeded' ? 'green' : job.status === 'failed' ? 'red' : 'blue'}>
                {job.status === 'succeeded' ? '已完成' : job.status === 'failed' ? '失败' : '进行中'}
              </Tag>
              <Typography.Text type="secondary">
                任务 {job.id.slice(0, 8)} · 创建于 {job.created_at ? new Date(job.created_at).toLocaleString('zh-CN') : '-'}
              </Typography.Text>
              <Typography.Text type="secondary">
                耗时 {job.started_at && job.finished_at
                  ? `${((new Date(job.finished_at).getTime() - new Date(job.started_at).getTime()) / 1000).toFixed(1)}s`
                  : '-'}
              </Typography.Text>
            </Space>
            {job.status === 'failed' && (
              <Alert type="error" showIcon message="采集失败" description={String(job.result?.error ?? '')} />
            )}
            {running && liveStage && (
              <Space size={8} wrap className="run-status-line">
                <Spin size="small" />
                <Tag color="blue" style={{ marginInlineEnd: 0 }}>
                  {liveStage.label}({stageInfos.indexOf(liveStage) + 1}/{stageInfos.length})
                </Tag>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {liveStage.message || '执行中…'}
                </Typography.Text>
              </Space>
            )}
            {emptyReason && <Alert type="warning" showIcon message="本次没有新增素材" description={emptyReason} />}
            {(typedKeywords.length > 0 || expandedKeywords.length > 0) && (
              <Space direction="vertical" size={4} style={{ width: '100%' }}>
                <Space wrap size={4} align="center">
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    实际检索词:
                  </Typography.Text>
                  {typedKeywords.map((word) => (
                    <Tag key={word} color="blue" style={{ marginInlineEnd: 0 }}>
                      {word}
                    </Tag>
                  ))}
                  {translatedKeywords.map((word) => (
                    <Tag key={word} style={{ marginInlineEnd: 0 }}>
                      {word}
                    </Tag>
                  ))}
                  {translatedKeywords.length > 0 && (
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      (LLM 翻译)
                    </Typography.Text>
                  )}
                  {expandedKeywords.length > 0 && (
                    <>
                      <Tag color="gold" style={{ marginInlineEnd: 0 }}>
                        辐射词
                      </Tag>
                      {expandedKeywords.map((word) => (
                        <Tag key={word} style={{ marginInlineEnd: 0 }}>
                          {word}
                        </Tag>
                      ))}
                    </>
                  )}
                </Space>
                {backfillInfo && (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {backfillInfo.skipped
                      ? `未执行补量:${backfillSkipReasons[backfillInfo.skipped] ?? backfillInfo.skipped}`
                      : `已自动补量一轮:补采抓取 ${backfillInfo.fetched ?? 0} 条、新增 ${backfillInfo.new_items ?? 0} 条`}
                  </Typography.Text>
                )}
              </Space>
            )}
            {shortfallInfo && (
              <Alert
                type="warning"
                showIcon
                message={`素材不足:期望 ${shortfallInfo.expected} 条,实际 ${shortfallInfo.actual} 条`}
                description="可放宽关键词、延长回看窗口或降低入库门槛后重采;日报/文章生成时会如实标注素材不足。"
              />
            )}
            <Descriptions size="small" column={2} bordered>
              <Descriptions.Item label="方向">
                {String(job.params?.name ?? '临时采集')}
              </Descriptions.Item>
              <Descriptions.Item label="回看窗口">{String(job.params?.lookback_hours ?? '-')} 小时</Descriptions.Item>
              <Descriptions.Item label="关键词">
                {((job.params?.keywords as string[]) ?? []).map((word) => (
                  <Tag key={word}>{word}</Tag>
                ))}
              </Descriptions.Item>
              <Descriptions.Item label="排除词">
                {((job.params?.exclude_keywords as string[]) ?? []).length
                  ? ((job.params?.exclude_keywords as string[]) ?? []).map((word) => <Tag key={word}>{word}</Tag>)
                  : '-'}
              </Descriptions.Item>
            </Descriptions>
            <div className="job-log" id="collect-log">
              {job.log || '等待日志…'}
            </div>
          </Space>
        )}
      </Card>

      {hasResult && (
        <Card
          title="环节耗时与信源明细"
          style={{ marginTop: 16 }}
          extra={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              总耗时 {stageElapsed}
            </Typography.Text>
          }
        >
          <StageTable stages={stageInfos} emptyText="该任务没有阶段数据(旧任务),重新采集即可看到每个环节的耗时" />
          {sourceDetails.length > 0 && (
            <Table<SourceDetail>
              size="small"
              rowKey="source_id"
              style={{ marginTop: 16 }}
              pagination={false}
              dataSource={sourceDetails}
              columns={[
                {
                  title: '信源',
                  dataIndex: 'name',
                  ellipsis: true,
                  render: (value: string, record) => (
                    <span>
                      {value}
                      {record.round === 'backfill' && (
                        <Tag color="gold" style={{ marginInlineStart: 6 }}>
                          补量
                        </Tag>
                      )}
                    </span>
                  ),
                },
                {
                  title: '引擎',
                  dataIndex: 'engine',
                  width: 90,
                  render: (value: string, record) => (
                    <Tag color={value === 'github' ? 'purple' : value === 'news' ? 'blue' : 'cyan'}>
                      {value || record.kind}
                    </Tag>
                  ),
                },
                {
                  title: '耗时',
                  dataIndex: 'seconds',
                  width: 90,
                  render: (value: number) => `${Number(value ?? 0).toFixed(2)}s`,
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
                    error ? (
                      <Typography.Text type="danger" style={{ fontSize: 12 }} ellipsis={{ tooltip: error }}>
                        失败
                      </Typography.Text>
                    ) : (
                      <Tag color="success">正常</Tag>
                    ),
                },
              ]}
            />
          )}
        </Card>
      )}

      {hasResult && job?.status === 'succeeded' && (
        <Card
          title="采集结果(Markdown)"
          style={{ marginTop: 16 }}
          extra={
            <Button
              icon={<ThunderboltOutlined />}
              onClick={() => {
                navigator.clipboard?.writeText(report)
                message.success('已复制 Markdown')
              }}
            >
              复制 Markdown
            </Button>
          }
        >
          <div className="digest-markdown collect-report" id="collect-report">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{report}</ReactMarkdown>
          </div>
          {ingested.length > 0 && (
            <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
              共 {ingested.length} 条入库明细,完整清单见上方日志或「资讯流」。
            </Typography.Paragraph>
          )}
        </Card>
      )}
    </div>
  )
}

function buildReport(job: JobRun, sources: Source[], ingested: IngestLine[]): string {
  const params = job.params ?? {}
  const result = job.result ?? {}
  const sourceNames = ((params.source_ids as number[]) ?? [])
    .map((id) => sources.find((s) => s.id === id)?.name)
    .filter(Boolean)
  const keywords = (params.keywords as string[]) ?? []
  const exclude = (params.exclude_keywords as string[]) ?? []
  const lines: string[] = []
  lines.push(`# 采集报告:${String(params.name ?? '临时采集')}`)
  lines.push('')
  lines.push(`> 关键词:**${keywords.join(' / ') || '-'}**${exclude.length ? ` · 排除:${exclude.join(' / ')}` : ''}`)
  lines.push('')
  lines.push(
    `- 信源:${sourceNames.length ? sourceNames.join('、') : '全部启用信源'}${sourceNames.length ? `(共 ${sourceNames.length} 个)` : ''}`,
  )
  lines.push(`- 回看窗口:${String(params.lookback_hours ?? '-')} 小时`)
  lines.push(`- 任务状态:${job.status === 'succeeded' ? '已完成' : job.status}`)
  lines.push('')
  lines.push('## 结果统计')
  lines.push('')
  lines.push('| 指标 | 数量 |')
  lines.push('| --- | --- |')
  lines.push(`| 抓取 | ${result.fetched ?? 0} |`)
  lines.push(`| 关键词过滤 | ${result.filtered ?? 0} |`)
  lines.push(`| 重复跳过 | ${result.duplicates ?? 0} |`)
  lines.push(`| 低于门槛跳过 | ${result.low_score ?? 0} |`)
  lines.push(`| **新入库** | **${result.new_items ?? 0}** |`)
  lines.push(`| 失败信源 | ${result.failed_sources ?? 0} |`)
  lines.push(`| LLM 错误 | ${result.llm_errors ?? 0} |`)
  lines.push(`| 富化降级 | ${result.llm_degraded ?? 0} |`)
  const usage = (result.llm_usage ?? {}) as Record<string, unknown>
  if (Number(usage.total_tokens ?? 0) > 0) {
    lines.push(
      `| LLM Token | ${formatTokens(usage.total_tokens)}(入 ${formatTokens(usage.prompt_tokens)} / 出 ${formatTokens(usage.completion_tokens)} · ${Number(usage.calls ?? 0)} 次调用) |`,
    )
  }
  if (ingested.length) {
    lines.push('')
    lines.push('## 入库条目')
    lines.push('')
    lines.push('| 类型 | 标题 | 相关 | 热度 | 时效 | 总分 | 原文 |')
    lines.push('| --- | --- | --- | --- | --- | --- | --- |')
    for (const row of ingested.slice(0, 60)) {
      const title = row.title.replace(/\|/g, '\\|').replace(/\[/g, '\\[').replace(/\]/g, '\\]')
      lines.push(
        `| ${row.type} | ${title} | ${row.relevance} | ${row.heat} | ${row.freshness} | **${row.total}** | ${
          row.url ? `[链接](${row.url})` : '-'
        } |`,
      )
    }
    if (ingested.length > 60) {
      lines.push(`| … | 其余 ${ingested.length - 60} 条见日志 | | | | | |`)
    }
  }
  return lines.join('\n')
}
