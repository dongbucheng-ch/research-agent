import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Select, Space, Table, Tag, Typography, message } from 'antd'
import type { Key } from 'react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { JobRun, Page } from '../api/types'
import DigestGenerateModal from '../components/DigestGenerateModal'
import JobDetail from '../components/JobDetail'
import SchedulesCard from '../components/SchedulesCard'
import { JOB_KIND_LABEL, JOB_STATUS_META, formatTime } from '../utils'

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
  return `${seconds.toFixed(1)}s`
}

export default function JobsPage() {
  const queryClient = useQueryClient()
  const [digestOpen, setDigestOpen] = useState(false)
  const [kind, setKind] = useState<string | undefined>()
  const [status, setStatus] = useState<string | undefined>()
  const [expandedKeys, setExpandedKeys] = useState<Key[]>([])

  const { data, isLoading } = useQuery({
    queryKey: ['jobs', kind, status],
    queryFn: () => {
      const params = new URLSearchParams({ page_size: '50' })
      if (kind) params.set('kind', kind)
      if (status) params.set('status', status)
      return api.get<Page<JobRun>>(`/jobs?${params.toString()}`)
    },
    refetchInterval: (query) =>
      query.state.data?.items?.some((job) => job.status === 'running' || job.status === 'pending')
        ? 3000
        : false,
  })

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

  return (
    <div>
      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          任务中心
        </Typography.Title>
        <Space>
          <Select
            allowClear
            placeholder="任务类型"
            style={{ width: 130 }}
            value={kind}
            onChange={setKind}
            options={Object.entries(JOB_KIND_LABEL).map(([value, label]) => ({ value, label }))}
          />
          <Select
            allowClear
            placeholder="状态"
            style={{ width: 120 }}
            value={status}
            onChange={setStatus}
            options={[
              { value: 'running', label: '进行中' },
              { value: 'succeeded', label: '成功' },
              { value: 'failed', label: '失败' },
            ]}
          />
          <Link to="/collect">
            <Button>去采集工作台</Button>
          </Link>
          <Button type="primary" onClick={() => setDigestOpen(true)}>
            生成日报
          </Button>
        </Space>
      </Space>

      <SchedulesCard
        onOpenJob={(jobId) => {
          setKind(undefined)
          setStatus(undefined)
          setExpandedKeys([jobId])
        }}
      />

      <Table<JobRun>
        rowKey="id"
        loading={isLoading}
        style={{ marginTop: 16 }}
        dataSource={data?.items}
        pagination={false}
        expandable={{
          expandedRowKeys: expandedKeys,
          onExpandedRowsChange: (keys) => setExpandedKeys([...keys]),
          expandedRowRender: (record) => <JobDetail job={record} />,
        }}
        columns={[
          { title: '类型', dataIndex: 'kind', width: 110, render: (value) => JOB_KIND_LABEL[value] ?? value },
          {
            title: '状态',
            dataIndex: 'status',
            width: 110,
            render: (value: string) => <Tag color={JOB_STATUS_META[value]?.color}>{JOB_STATUS_META[value]?.label ?? value}</Tag>,
          },
          {
            title: '采集配置',
            render: (_, record) => (
              <Typography.Text style={{ fontSize: 12 }} ellipsis={{ tooltip: configSummary(record) }}>
                {configSummary(record)}
              </Typography.Text>
            ),
          },
          { title: '创建时间', dataIndex: 'created_at', width: 170, render: (value) => formatTime(value) },
          {
            title: '耗时',
            width: 100,
            render: (_, record) => duration(record),
          },
          {
            title: '操作',
            width: 110,
            render: (_, record) => (
              <Button
                size="small"
                loading={rerun.isPending && rerun.variables?.id === record.id}
                onClick={() => rerun.mutate(record)}
              >
                重跑
              </Button>
            ),
          },
          {
            title: '任务 ID',
            dataIndex: 'id',
            width: 110,
            render: (value) => (
              <Typography.Text copyable style={{ fontSize: 12 }}>
                {value.slice(0, 8)}
              </Typography.Text>
            ),
          },
        ]}
      />

      <DigestGenerateModal open={digestOpen} onClose={() => setDigestOpen(false)} />
    </div>
  )
}
