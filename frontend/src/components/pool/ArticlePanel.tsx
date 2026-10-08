import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Button,
  Card,
  Divider,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { api, toQuery } from '../../api/client'
import type { Article, Item, Page, PushChannel } from '../../api/types'
import { formatTime, scoreColor } from '../../utils'
import ItemDetailDrawer from '../ItemDetailDrawer'
import PushSection from '../PushSection'
import OutputViewer from './OutputViewer'

interface GenerateValues {
  topic?: string
  keywords: string[]
  period_hours: number
  max_sources: number
  target_words: number
  min_score: number
  push_channel_id?: number
}

interface Props {
  focusId?: number | null
}

export default function ArticlePanel({ focusId }: Props) {
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [open, setOpen] = useState(false)
  const [watching, setWatching] = useState(false)
  const [materialItemId, setMaterialItemId] = useState<number | null>(null)
  const [form] = Form.useForm<GenerateValues>()

  const { data, isLoading } = useQuery({
    queryKey: ['articles'],
    queryFn: () => api.get<Page<Article>>('/articles?page_size=30'),
    refetchInterval: watching ? 15000 : false,
  })
  const articles = data?.items ?? []
  const current = articles.find((article) => article.id === selectedId) ?? articles[0]

  const { data: channels } = useQuery({
    queryKey: ['push-channels'],
    queryFn: () => api.get<PushChannel[]>('/settings/push-channels'),
  })

  const sourceIds = (current?.source_item_ids ?? []).join(',')
  const { data: materials, isLoading: materialsLoading } = useQuery({
    queryKey: ['article-materials', sourceIds],
    queryFn: () => api.get<Item[]>(`/items/lookup${toQuery({ ids: sourceIds })}`),
    enabled: Boolean(sourceIds),
  })

  // 结构化信封:sources.ref 对应正文 [n] 引用(lookup 保持 source_item_ids 入参顺序)。
  const jsonPayload = useMemo(() => {
    if (!current) return null
    return {
      kind: 'article',
      id: current.id,
      title: current.title,
      created_at: current.created_at,
      topic: current.topic,
      keywords: current.keywords,
      model: current.model,
      meta: current.meta ?? {},
      content_md: current.content_md,
      sources: (materials ?? []).map((item, index) => ({
        ref: index + 1,
        id: item.id,
        title: item.translated_title || item.title,
        url: item.url,
        channel: item.source_name ?? item.channel,
        score: item.score?.total ?? null,
      })),
    }
  }, [current, materials])

  useEffect(() => {
    if (current && selectedId === null) setSelectedId(current.id)
  }, [current, selectedId])

  useEffect(() => {
    if (focusId && articles.some((article) => article.id === focusId)) setSelectedId(focusId)
  }, [focusId, articles])

  useEffect(() => {
    if (!watching) return
    const timer = setTimeout(() => setWatching(false), 10 * 60 * 1000)
    return () => clearTimeout(timer)
  }, [watching])

  const generateMutation = useMutation({
    mutationFn: (values: GenerateValues) =>
      api.post('/articles/generate', {
        topic: values.topic?.trim() || undefined,
        keywords: (values.keywords ?? []).map((word) => word.trim()).filter(Boolean),
        period_hours: values.period_hours,
        max_sources: values.max_sources,
        target_words: values.target_words,
        min_score: values.min_score,
        push_channel_id: values.push_channel_id,
      }),
    onSuccess: () => {
      message.success('文章生成任务已创建(约 2-5 分钟),完成后自动刷新')
      setOpen(false)
      setWatching(true)
    },
    onError: (error: Error) => message.error(error.message),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.del(`/articles/${id}`),
    onSuccess: () => {
      message.success('已删除')
      setSelectedId(null)
      queryClient.invalidateQueries({ queryKey: ['articles'] })
    },
  })

  return (
    <div>
      <Space style={{ width: '100%', justifyContent: 'flex-end', marginBottom: 12 }}>
        <Button type="primary" onClick={() => setOpen(true)}>
          生成文章
        </Button>
      </Space>

      {isLoading ? (
        <div style={{ textAlign: 'center', padding: 60 }}>
          <Spin />
        </div>
      ) : articles.length === 0 ? (
        <Empty
          description={watching ? '文章生成中,完成后自动出现在这里…' : '还没有文章,点击右上角生成'}
          style={{ padding: 60 }}
        >
          {watching && <Spin />}
        </Empty>
      ) : (
        <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
          <Card size="small" style={{ width: 320, flexShrink: 0 }} styles={{ body: { padding: 8 } }}>
            <List
              dataSource={articles}
              renderItem={(article) => (
                <List.Item
                  style={{
                    cursor: 'pointer',
                    padding: '10px 12px',
                    borderRadius: 8,
                    background: current?.id === article.id ? '#eef4ff' : undefined,
                  }}
                  onClick={() => setSelectedId(article.id)}
                >
                  <List.Item.Meta
                    title={<span style={{ fontSize: 14 }}>{article.title}</span>}
                    description={
                      <span style={{ fontSize: 12 }}>
                        {formatTime(article.created_at)}
                        {article.meta?.char_count ? ` · ${article.meta.char_count} 字` : ''}
                        {article.meta?.kept ? ` · 素材 ${article.meta.kept}` : ''}
                      </span>
                    }
                  />
                </List.Item>
              )}
            />
          </Card>
          <Card
            size="small"
            style={{ flex: 1, minWidth: 0 }}
            styles={{ body: { padding: 24 } }}
            title={
              current ? (
                <Space wrap>
                  {current.title}
                  {(current.keywords ?? []).slice(0, 3).map((word) => (
                    <Tag key={word}>{word}</Tag>
                  ))}
                </Space>
              ) : null
            }
            extra={
              current ? (
                <Button size="small" danger onClick={() => deleteMutation.mutate(current.id)}>
                  删除
                </Button>
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
                  locale={{ emptyText: '这条文章没有关联到素材记录' }}
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
                <PushSection targetKind="article" targetId={current.id} />
              </>
            ) : (
              <Empty />
            )}
          </Card>
        </div>
      )}

      <Modal
        title="生成完整文章"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
        confirmLoading={generateMutation.isPending}
        width={520}
      >
        <Form
          form={form}
          layout="vertical"
          style={{ marginTop: 8 }}
          initialValues={{
            period_hours: 168,
            max_sources: 12,
            target_words: 1800,
            min_score: 60,
            keywords: [],
          }}
          onFinish={(values) => generateMutation.mutate(values)}
        >
          <Form.Item name="topic" label="研究方向">
            <Input placeholder="例如:LLM Agent / 具身智能" allowClear maxLength={50} />
          </Form.Item>
          <Form.Item
            name="keywords"
            label="关键词(输入后回车)"
            rules={[{ required: true, message: '至少填写一个关键词' }]}
          >
            <Select
              mode="tags"
              open={false}
              tokenSeparators={[',', '、', ' ', ';']}
              placeholder="例如:agent / 大模型"
            />
          </Form.Item>
          <Space size="large" wrap>
            <Form.Item name="period_hours" label="回看窗口(小时)">
              <InputNumber min={6} max={720} style={{ width: 130 }} />
            </Form.Item>
            <Form.Item name="max_sources" label="素材上限">
              <InputNumber min={3} max={30} style={{ width: 110 }} />
            </Form.Item>
            <Form.Item name="target_words" label="目标字数">
              <InputNumber min={600} max={6000} step={100} style={{ width: 120 }} />
            </Form.Item>
          </Space>
          <Space size="large" wrap>
            <Form.Item name="min_score" label="入库门槛" tooltip="素材三维总分低于该值不进入候选">
              <InputNumber min={0} max={100} style={{ width: 130 }} />
            </Form.Item>
            <Form.Item name="push_channel_id" label="生成后推送(可选)">
              <Select
                allowClear
                placeholder="不推送"
                style={{ width: 200 }}
                options={(channels ?? [])
                  .filter((channel) => channel.enabled)
                  .map((channel) => ({
                    value: channel.id,
                    label: `${channel.name}(${channel.kind})`,
                  }))}
              />
            </Form.Item>
          </Space>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            流程:召回 → LLM 过滤去重 → 选题大纲 → 逐节写作(强制 [n] 引用)→ 合成;
            参考文献由本地按素材拼装,不依赖模型复述链接。
          </Typography.Text>
        </Form>
      </Modal>
      <ItemDetailDrawer itemId={materialItemId} onClose={() => setMaterialItemId(null)} />
    </div>
  )
}
