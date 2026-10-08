import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Empty, Form, Input, List, Modal, Select, Space, Tag, Typography, message } from 'antd'
import { useEffect, useState } from 'react'
import { api, toQuery } from '../api/client'
import type { PushChannel, PushLog } from '../api/types'
import { formatRelative } from '../utils'

interface Props {
  targetKind: 'digest' | 'article'
  targetId: number | null
}

interface PushOverrides {
  title?: string
  source?: string
  author?: string
  tags?: string[]
}

export default function PushSection({ targetKind, targetId }: Props) {
  const queryClient = useQueryClient()
  const [channelId, setChannelId] = useState<number | undefined>(undefined)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [settingsForm] = Form.useForm<PushOverrides>()

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

  const logsQueryKey = ['push-logs', targetKind, targetId]
  const { data: logs } = useQuery({
    queryKey: logsQueryKey,
    queryFn: () =>
      api.get<PushLog[]>(
        `/settings/push-logs${toQuery({ target_kind: targetKind, target_id: targetId, limit: 10 })}`,
      ),
    enabled: targetId !== null,
  })

  const pushMutation = useMutation({
    mutationFn: (overrides: PushOverrides) =>
      api.post('/jobs/push', {
        target_kind: targetKind,
        target_id: targetId,
        channel_id: channelId,
        ...overrides,
      }),
    onSuccess: () => {
      message.success('推送任务已提交')
      setSettingsOpen(false)
      setTimeout(() => queryClient.invalidateQueries({ queryKey: logsQueryKey }), 1500)
    },
    onError: (error: Error) => message.error(error.message),
  })

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
    pushMutation.mutate(overrides)
  }

  const channelName = (id: number | null) =>
    (channels ?? []).find((channel) => channel.id === id)?.name ?? '渠道已删除'

  return (
    <div className="push-section">
      <Space wrap align="center">
        <Typography.Text strong>推送</Typography.Text>
        <Select
          placeholder="选择推送渠道"
          style={{ width: 200 }}
          value={channelId}
          onChange={setChannelId}
          options={enabledChannels.map((channel) => ({
            value: channel.id,
            label: `${channel.name}(${channel.kind})`,
          }))}
        />
        <Button
          type="primary"
          size="small"
          disabled={targetId === null || channelId === undefined}
          onClick={openSettings}
        >
          推送到该渠道
        </Button>
        {enabledChannels.length === 0 && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            还没有启用的推送渠道,先到「设置 → 推送渠道」添加(webhook / 导出)
          </Typography.Text>
        )}
      </Space>
      {logs && logs.length > 0 && (
        <List
          size="small"
          style={{ marginTop: 8 }}
          dataSource={logs}
          renderItem={(log) => (
            <List.Item style={{ padding: '4px 0' }}>
              <Space size={8} wrap>
                <Tag color={log.status === 'success' ? 'success' : 'error'}>
                  {log.status === 'success' ? '成功' : '失败'}
                </Tag>
                <Typography.Text style={{ fontSize: 12 }}>{channelName(log.channel_id)}</Typography.Text>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {formatRelative(log.created_at)}
                </Typography.Text>
                {log.error && (
                  <Typography.Text type="danger" style={{ fontSize: 12 }} ellipsis>
                    {log.error}
                  </Typography.Text>
                )}
              </Space>
            </List.Item>
          )}
        />
      )}
      {targetId !== null && (!logs || logs.length === 0) && (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无推送记录" style={{ margin: '8px 0 0' }} />
      )}
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
