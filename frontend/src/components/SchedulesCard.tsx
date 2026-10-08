import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Card, Empty, Popconfirm, Space, Switch, Table, Tag, Tooltip, Typography, message } from 'antd'
import { api } from '../api/client'
import type { JobRun, Schedule } from '../api/types'
import { formatRelative, formatTime } from '../utils'

interface Props {
  onOpenJob?: (jobId: string) => void
}

function scopeText(schedule: Schedule): string {
  const hasInfo = schedule.scopes.includes('info')
  const hasGithub = schedule.scopes.includes('github')
  if (hasInfo && hasGithub) return '资讯+GitHub'
  return hasGithub ? 'GitHub' : '资讯'
}

function intervalText(minutes: number): string {
  if (minutes % 1440 === 0) return `每 ${minutes / 1440} 天`
  if (minutes % 60 === 0) return `每 ${minutes / 60} 小时`
  return `每 ${minutes} 分钟`
}

export default function SchedulesCard({ onOpenJob }: Props) {
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['schedules'],
    queryFn: () => api.get<Schedule[]>('/schedules'),
    refetchInterval: 30000,
  })

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['schedules'] })
    queryClient.invalidateQueries({ queryKey: ['jobs'] })
  }

  const toggle = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      api.put(`/schedules/${id}`, { enabled }),
    onSuccess: refresh,
    onError: (error: Error) => message.error(error.message),
  })

  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/schedules/${id}`),
    onSuccess: () => {
      message.success('已删除定时配置')
      refresh()
    },
    onError: (error: Error) => message.error(error.message),
  })

  const runNow = useMutation({
    mutationFn: (id: string) => api.post<JobRun>(`/schedules/${id}/run`),
    onSuccess: (job) => {
      message.success('已立即触发一次采集')
      refresh()
      onOpenJob?.(job.id)
    },
    onError: (error: Error) => message.error(error.message),
  })

  return (
    <Card
      size="small"
      title="定时采集"
      style={{ marginTop: 16 }}
      styles={{ body: { padding: data?.length ? 0 : 24 } }}
    >
      {isLoading ? null : !data || data.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="还没有定时配置:到「采集工作台」填好配置后勾选「保存为定时任务」"
        />
      ) : (
        <Table<Schedule>
          rowKey="id"
          size="small"
          dataSource={data}
          pagination={false}
          columns={[
            {
              title: '名称 / 关键词',
              render: (_, record) => (
                <Space direction="vertical" size={0}>
                  <Typography.Text strong style={{ fontSize: 13 }}>
                    {record.name}
                  </Typography.Text>
                  <Space size={4} wrap>
                    {record.keywords.slice(0, 4).map((word) => (
                      <Tag key={word} style={{ marginInlineEnd: 0 }}>
                        {word}
                      </Tag>
                    ))}
                    {record.keywords.length > 4 && <Tag>+{record.keywords.length - 4}</Tag>}
                  </Space>
                </Space>
              ),
            },
            {
              title: '采集配置',
              render: (_, record) => (
                <Typography.Text style={{ fontSize: 12 }}>
                  {scopeText(record)} · {record.lookback_hours}h · 门槛 {record.min_score}
                  {record.github_mode === 'strict' ? ' · GitHub 严格' : ''}
                </Typography.Text>
              ),
            },
            {
              title: '间隔',
              width: 100,
              render: (_, record) => intervalText(record.interval_minutes),
            },
            {
              title: '启用',
              width: 80,
              render: (_, record) => (
                <Switch
                  size="small"
                  checked={record.enabled}
                  loading={toggle.isPending && toggle.variables?.id === record.id}
                  onChange={(enabled) => toggle.mutate({ id: record.id, enabled })}
                />
              ),
            },
            {
              title: '下次运行',
              width: 170,
              render: (_, record) => (
                <Space direction="vertical" size={0}>
                  <Typography.Text style={{ fontSize: 12 }}>
                    {record.enabled ? formatTime(record.next_run_at) : '已停用'}
                  </Typography.Text>
                  {record.last_skip && (
                    <Tooltip title={record.last_skip.reason}>
                      <Typography.Text type="warning" style={{ fontSize: 11 }}>
                        上次跳过:{formatRelative(record.last_skip.at)}
                      </Typography.Text>
                    </Tooltip>
                  )}
                </Space>
              ),
            },
            {
              title: '最近任务',
              width: 150,
              render: (_, record) =>
                record.last_job_id ? (
                  <Space direction="vertical" size={0}>
                    <Button
                      type="link"
                      size="small"
                      style={{ padding: 0 }}
                      onClick={() => onOpenJob?.(record.last_job_id as string)}
                    >
                      {record.last_job_id.slice(0, 8)}
                    </Button>
                    <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                      {formatRelative(record.last_run_at)}
                    </Typography.Text>
                  </Space>
                ) : (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    未运行
                  </Typography.Text>
                ),
            },
            {
              title: '操作',
              width: 150,
              render: (_, record) => (
                <Space size={4}>
                  <Button
                    size="small"
                    loading={runNow.isPending && runNow.variables === record.id}
                    onClick={() => runNow.mutate(record.id)}
                  >
                    立即执行
                  </Button>
                  <Popconfirm title="删除该定时配置?" onConfirm={() => remove.mutate(record.id)}>
                    <Button size="small" danger>
                      删除
                    </Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      )}
    </Card>
  )
}
