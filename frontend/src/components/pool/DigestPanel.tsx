import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Card, Divider, Empty, List, Space, Spin, Tag, Typography, message } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api/client'
import type { Digest, Item, Page } from '../../api/types'
import { digestBatch, formatTime, scoreColor } from '../../utils'
import DigestGenerateModal from '../DigestGenerateModal'
import ItemDetailDrawer from '../ItemDetailDrawer'
import PushSection from '../PushSection'
import OutputViewer from './OutputViewer'

interface Props {
  focusId?: number | null
}

export default function DigestPanel({ focusId }: Props) {
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [open, setOpen] = useState(false)
  const [materialItemId, setMaterialItemId] = useState<number | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['digests'],
    queryFn: () => api.get<Page<Digest>>('/digests?page_size=30'),
  })
  const digests = data?.items ?? []
  const current = digests.find((digest) => digest.id === selectedId) ?? digests[0]

  const { data: materials, isLoading: materialsLoading } = useQuery({
    queryKey: ['digest-items', current?.id],
    queryFn: () => api.get<Item[]>(`/digests/${current!.id}/items`),
    enabled: Boolean(current?.id),
  })

  const jsonPayload = useMemo(() => {
    if (!current) return null
    return {
      kind: 'digest',
      id: current.id,
      title: current.title,
      created_at: current.created_at,
      batch: digestBatch(current, digests),
      scope: current.meta?.scope ?? null,
      topic: current.meta?.topic ?? null,
      period: { start: current.period_start, end: current.period_end },
      model: current.model,
      lead: current.lead,
      highlights: current.highlights,
      content_md: current.content_md,
      items: (materials ?? []).map((item) => ({
        id: item.id,
        title: item.translated_title || item.title,
        url: item.url,
        channel: item.source_name ?? item.channel,
        score: item.score?.total ?? null,
      })),
    }
  }, [current, digests, materials])

  useEffect(() => {
    if (current && selectedId === null) setSelectedId(current.id)
  }, [current, selectedId])

  useEffect(() => {
    if (focusId && digests.some((digest) => digest.id === focusId)) setSelectedId(focusId)
  }, [focusId, digests])

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.del(`/digests/${id}`),
    onSuccess: () => {
      message.success('已删除')
      setSelectedId(null)
      queryClient.invalidateQueries({ queryKey: ['digests'] })
    },
  })

  const scopeTag = (digest: Digest) => {
    if (digest.meta?.scope === 'topic') return <Tag color="geekblue">定向</Tag>
    if (digest.meta?.scope === 'global') return <Tag color="blue">全局</Tag>
    return null
  }

  return (
    <div>
      <Space style={{ width: '100%', justifyContent: 'flex-end', marginBottom: 12 }}>
        <Button type="primary" onClick={() => setOpen(true)}>
          生成日报
        </Button>
      </Space>

      {isLoading ? (
        <div style={{ textAlign: 'center', padding: 60 }}>
          <Spin />
        </div>
      ) : digests.length === 0 ? (
        <Empty description="还没有日报,点击右上角生成" style={{ padding: 60 }} />
      ) : (
        <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
          <Card size="small" style={{ width: 320, flexShrink: 0 }} styles={{ body: { padding: 8 } }}>
            <List
              dataSource={digests}
              renderItem={(digest) => {
                const batch = digestBatch(digest, digests)
                return (
                  <List.Item
                    style={{
                      cursor: 'pointer',
                      padding: '10px 12px',
                      borderRadius: 8,
                      background: current?.id === digest.id ? '#eef4ff' : undefined,
                    }}
                    onClick={() => setSelectedId(digest.id)}
                  >
                    <div style={{ width: '100%' }}>
                      <Space size={6} wrap>
                        <span className="output-batch">
                          {batch.date} · 第 {batch.index} 批
                        </span>
                        {scopeTag(digest)}
                      </Space>
                      <div className="output-item-name">{digest.title}</div>
                      <div className="output-item-meta">
                        {formatTime(digest.created_at)} ·{' '}
                        {digest.meta?.news_count ?? digest.item_count} 条
                        {digest.meta?.github_count ? ` + ${digest.meta.github_count} GitHub` : ''}
                      </div>
                    </div>
                  </List.Item>
                )
              }}
            />
          </Card>
          <Card
            size="small"
            style={{ flex: 1, minWidth: 0 }}
            styles={{ body: { padding: 24 } }}
            extra={
              current ? (
                <Button size="small" danger onClick={() => deleteMutation.mutate(current.id)}>
                  删除
                </Button>
              ) : null
            }
            title={
              current ? (
                <Space>
                  {current.title}
                  {scopeTag(current)}
                  {current.meta?.topic ? (
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {String(current.meta.topic)}
                    </Typography.Text>
                  ) : null}
                </Space>
              ) : null
            }
          >
            {current ? (
              <>
                <OutputViewer
                  contentMd={current.content_md}
                  payload={jsonPayload}
                  loading={materialsLoading}
                />
                <Divider />
                <Typography.Title level={5} style={{ marginTop: 0 }}>
                  素材来源({materials?.length ?? 0} 条)
                </Typography.Title>
                <List
                  size="small"
                  dataSource={materials ?? []}
                  locale={{ emptyText: '这条日报没有关联到素材记录' }}
                  renderItem={(item) => (
                    <List.Item
                      style={{ cursor: 'pointer', padding: '6px 0' }}
                      onClick={() => setMaterialItemId(item.id)}
                    >
                      <Space size={8} wrap>
                        <Tag color={scoreColor(item.score?.total)}>{item.score?.total ?? '-'}</Tag>
                        <Typography.Text style={{ fontSize: 13 }}>
                          {item.translated_title || item.title}
                        </Typography.Text>
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          {item.source_name ?? item.channel}
                        </Typography.Text>
                      </Space>
                    </List.Item>
                  )}
                />
                <Divider />
                <PushSection targetKind="digest" targetId={current.id} />
              </>
            ) : (
              <Empty />
            )}
          </Card>
        </div>
      )}

      <DigestGenerateModal
        open={open}
        onClose={() => setOpen(false)}
        onCreated={() => {
          setTimeout(() => queryClient.invalidateQueries({ queryKey: ['digests'] }), 8000)
        }}
      />
      <ItemDetailDrawer itemId={materialItemId} onClose={() => setMaterialItemId(null)} />
    </div>
  )
}
