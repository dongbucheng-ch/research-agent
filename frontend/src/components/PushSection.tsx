import { ReloadOutlined, SendOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Form, Input, Modal, Select, Space, Spin, Tag, Tooltip, Typography, message } from 'antd'
import { useEffect, useState } from 'react'
import { api, toQuery } from '../api/client'
import type { PushChannel, PushLog } from '../api/types'
import { formatRelative } from '../utils'

interface Props {
  targetKind: 'digest' | 'article'
  targetId: number | null
  /** 日报右侧信息栏:窄栏内本身就是纵向排布,这里仅用于标记容器来源 */
  vertical?: boolean
}

interface PushOverrides {
  title?: string
  source?: string
  author?: string
  tags?: string[]
}

/** 推送成功后的高亮窗口:含 1.5s 日志刷新的等待时间,保证新记录出现时仍显示「刚刚」 */
const JUST_PUSHED_MS = 4000

export default function PushSection({ targetKind, targetId, vertical = false }: Props) {
  const queryClient = useQueryClient()
  const [channelId, setChannelId] = useState<number | undefined>(undefined)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [settingsForm] = Form.useForm<PushOverrides>()
  /** 历史记录默认折叠:主行只留最近一次结果,避免右栏被日志挤满 */
  const [logsExpanded, setLogsExpanded] = useState(false)
  const [detailLog, setDetailLog] = useState<PushLog | null>(null)
  /** 刚推送成功的时间戳:窗口期内主行显示「刚刚」并高亮 */
  const [justPushedAt, setJustPushedAt] = useState<number | null>(null)

  const { data: channels } = useQuery({
    queryKey: ['push-channels', 'enabled'],
    queryFn: () => api.get<PushChannel[]>('/settings/push-channels'),
  })
  const enabledChannels = (channels ?? []).filter((channel) => channel.enabled)

  const { data: target } = useQuery({
    queryKey: ['push-target', targetKind, targetId],
    queryFn: () =>
      api.get<{ title: string }>(
        targetKind === 'digest' ? `/digests/${targetId}` : `/articles/${targetId}`,
      ),
    enabled: targetId !== null,
  })

  useEffect(() => {
    if (channelId === undefined && enabledChannels.length > 0) setChannelId(enabledChannels[0].id)
  }, [channelId, enabledChannels])

  useEffect(() => {
    if (justPushedAt === null) return
    const timer = setTimeout(() => setJustPushedAt(null), JUST_PUSHED_MS)
    return () => clearTimeout(timer)
  }, [justPushedAt])

  const logsQueryKey = ['push-logs', targetKind, targetId]
  const { data: logs } = useQuery({
    queryKey: logsQueryKey,
    queryFn: () =>
      api.get<PushLog[]>(
        `/settings/push-logs${toQuery({ target_kind: targetKind, target_id: targetId, limit: 10 })}`,
      ),
    enabled: targetId !== null,
  })

  /** 重试要按「那条记录自己的渠道」发,所以渠道 id 作为变量传入,而不是读 state */
  const pushMutation = useMutation({
    mutationFn: (params: { channelId?: number | null; overrides?: PushOverrides }) =>
      api.post('/jobs/push', {
        target_kind: targetKind,
        target_id: targetId,
        channel_id: params.channelId ?? channelId,
        ...(params.overrides ?? {}),
      }),
    onSuccess: () => {
      message.success('推送任务已提交')
      setSettingsOpen(false)
      setJustPushedAt(Date.now())
      setTimeout(() => queryClient.invalidateQueries({ queryKey: logsQueryKey }), 1500)
    },
    onError: (error: Error) => message.error(error.message),
  })

  const retry = (log: PushLog) => pushMutation.mutate({ channelId: log.channel_id })

  const selectedChannel = (channels ?? []).find((channel) => channel.id === channelId)
  const channelConfig = (selectedChannel?.config ?? {}) as Record<string, unknown>
  const configText = (key: string) => {
    const value = channelConfig[key]
    return typeof value === 'string' && value.trim() ? value : undefined
  }

  const openSettings = () => {
    settingsForm.resetFields()
    setSettingsOpen(true)
  }

  const submitPush = () => {
    const values = settingsForm.getFieldsValue()
    const overrides: PushOverrides = {}
    if (values.title?.trim()) overrides.title = values.title.trim()
    if (values.source?.trim()) overrides.source = values.source.trim()
    if (values.author?.trim()) overrides.author = values.author.trim()
    const tags = (values.tags ?? []).map((tag) => tag.trim()).filter(Boolean)
    if (tags.length > 0) overrides.tags = tags
    pushMutation.mutate({ overrides })
  }

  const channelName = (id: number | null) =>
    (channels ?? []).find((channel) => channel.id === id)?.name ?? '渠道已删除'

  /** 状态点 + 渠道 + 时间三段式;失败才展开第二行错误,并提供重试 */
  const renderLog = (log: PushLog, primary = false) => {
    const failed = log.status !== 'success'
    const justNow = primary && justPushedAt !== null
    return (
      <div
        key={log.id}
        className={`push-log${primary ? ' is-primary' : ''}${failed ? ' is-failed' : ''}${justNow ? ' is-just-pushed' : ''}`}
      >
        <span className="push-log-dot" aria-hidden />
        <div className="push-log-body">
          <div className="push-log-top">
            <span className="push-log-status">{failed ? '失败' : '成功'}</span>
            <span className="push-log-channel">{channelName(log.channel_id)}</span>
            <span className="push-log-time">
              {justNow ? '刚刚' : formatRelative(log.created_at)}
            </span>
          </div>
          {failed && log.error && (
            <div className="push-log-error">
              {log.error}
              <button type="button" className="push-log-detail" onClick={() => setDetailLog(log)}>
                详情
              </button>
            </div>
          )}
        </div>
        {primary && (
          <Tooltip title={failed ? '重新推送' : '再推一次'}>
            <Button
              type="text"
              size="small"
              className="push-log-retry"
              icon={<ReloadOutlined />}
              aria-label="重新推送"
              disabled={pushMutation.isPending}
              onClick={() => retry(log)}
            />
          </Tooltip>
        )}
      </div>
    )
  }

  const latestLog = logs?.[0]
  const historyLogs = (logs ?? []).slice(1)

  return (
    <div className={vertical ? 'push-section push-section-vertical' : 'push-section'}>
      <div className="push-head">
        <span className="push-title">推送</span>
        {logs && logs.length > 1 && (
          <button
            type="button"
            className="push-more"
            onClick={() => setLogsExpanded((expanded) => !expanded)}
          >
            {logsExpanded ? '收起' : `查看全部(${logs.length})`}
          </button>
        )}
      </div>

      {/* 主行:最近一次结果 / 推送中 / 空态 */}
      {pushMutation.isPending ? (
        <div className="push-log is-primary is-running">
          <Spin size="small" />
          <span className="push-log-status">推送中…</span>
        </div>
      ) : latestLog ? (
        renderLog(latestLog, true)
      ) : targetId !== null && logs ? (
        <div className="push-empty">还没有推送记录,选好渠道后点「推送」即可发送</div>
      ) : null}

      {logsExpanded && historyLogs.length > 0 && (
        <div className="push-history">{historyLogs.map((log) => renderLog(log))}</div>
      )}

      {/* 操作行:渠道与推送同高同圆角,按钮不再独占一整条色块 */}
      <div className="push-actions">
        <Select
          className="push-channel-select"
          placeholder="选择推送渠道"
          value={channelId}
          onChange={setChannelId}
          options={enabledChannels.map((channel) => ({
            value: channel.id,
            label: `${channel.name}(${channel.kind})`,
          }))}
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          aria-label="推送到该渠道"
          disabled={targetId === null || channelId === undefined}
          onClick={openSettings}
        >
          推送
        </Button>
      </div>

      {enabledChannels.length === 0 && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          还没有启用的推送渠道,先到「设置 → 推送渠道」添加(webhook / 导出)
        </Typography.Text>
      )}

      <Modal
        title="推送详情"
        open={detailLog !== null}
        onCancel={() => setDetailLog(null)}
        footer={
          <Space>
            <Button onClick={() => setDetailLog(null)}>关闭</Button>
            <Button
              type="primary"
              icon={<ReloadOutlined />}
              onClick={() => {
                if (detailLog) retry(detailLog)
                setDetailLog(null)
              }}
            >
              重新推送
            </Button>
          </Space>
        }
      >
        {detailLog && (
          <Space direction="vertical" size={10} style={{ width: '100%' }}>
            <Space size={8} wrap>
              <Tag color="error">失败</Tag>
              <Typography.Text>{channelName(detailLog.channel_id)}</Typography.Text>
              <Typography.Text type="secondary">
                {formatRelative(detailLog.created_at)}
              </Typography.Text>
            </Space>
            <Typography.Paragraph
              copyable
              style={{ margin: 0, maxHeight: 240, overflow: 'auto', whiteSpace: 'pre-wrap' }}
            >
              {detailLog.error ?? '(无错误信息)'}
            </Typography.Paragraph>
          </Space>
        )}
      </Modal>

      <Modal
        title="推送设置"
        open={settingsOpen}
        onCancel={() => setSettingsOpen(false)}
        onOk={submitPush}
        okText="推送"
        confirmLoading={pushMutation.isPending}
        destroyOnClose
      >
        <Form form={settingsForm} layout="vertical">
          <Form.Item name="title" label="标题" tooltip="留空则使用产出物原标题">
            <Input
              maxLength={255}
              placeholder={target?.title ? `默认:${target.title}` : '留空则使用原标题'}
            />
          </Form.Item>
          <Form.Item name="source" label="来源" tooltip="留空则使用渠道配置里的默认来源">
            <Input
              maxLength={128}
              placeholder={configText('source') ? `默认:${configText('source')}` : '留空则用渠道默认'}
            />
          </Form.Item>
          <Form.Item name="author" label="作者" tooltip="留空则使用渠道配置里的默认作者">
            <Input
              maxLength={128}
              placeholder={configText('author') ? `默认:${configText('author')}` : '留空则用渠道默认'}
            />
          </Form.Item>
          <Form.Item
            name="tags"
            label="标签"
            tooltip="留空则按素材自动汇总(最多 9 个);输入后回车添加"
          >
            <Select
              mode="tags"
              tokenSeparators={[',', ';', '、']}
              placeholder="留空则自动:按素材标签汇总"
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
