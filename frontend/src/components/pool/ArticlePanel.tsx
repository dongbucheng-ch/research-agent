import { DeleteOutlined, FileAddOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Button,
  Card,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Skeleton,
  Space,
  Spin,
  Tooltip,
  TreeSelect,
  Typography,
  message,
} from 'antd'
import dayjs from 'dayjs'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, toQuery } from '../../api/client'
import type { Article, Item, Page, PushChannel } from '../../api/types'
import { dayLabel, formatTime } from '../../utils'
import ItemDetailDrawer from '../ItemDetailDrawer'
import PushSection from '../PushSection'
import OutputViewer, { OutputToolbar, useOutputMode } from './OutputViewer'
import OutputRail, { citationByRef, type RailCitation } from './outputRail'

/** 树形选择器默认展开的最近日期数;更早的日期收起,避免下拉一屏放不下 */
const TREE_RECENT_DAYS = 7

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
  /** 选择变更回写 URL:刷新、分享、后退都能回到同一条 */
  onSelect?: (id: number | null) => void
}

export default function ArticlePanel({ focusId, onSelect }: Props) {
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [open, setOpen] = useState(false)
  const [watching, setWatching] = useState(false)
  const [materialItemId, setMaterialItemId] = useState<number | null>(null)
  const [searchValue, setSearchValue] = useState('')
  /** null=用默认展开集合(最近 N 天);用户展开/收起后以其为准 */
  const [expandedKeys, setExpandedKeys] = useState<string[] | null>(null)
  /** 预览/源码/JSON 由卡片头持有,正文只消费当前模式 */
  const [outputMode, setOutputMode] = useOutputMode()
  const [form] = Form.useForm<GenerateValues>()

  const { data, isLoading } = useQuery({
    queryKey: ['articles'],
    queryFn: () => api.get<Page<Article>>('/articles?page_size=30'),
    refetchInterval: watching ? 15000 : false,
  })
  const articles = data?.items ?? []
  const current = articles.find((article) => article.id === selectedId) ?? articles[0]
  const currentId = current?.id

  const select = useCallback(
    (id: number | null) => {
      setSelectedId(id)
      onSelect?.(id)
    },
    [onSelect],
  )

  // 日期 → 文章 两级;组内保持后端的按时间倒序
  const groups = useMemo(() => {
    const list: { date: string; items: Article[] }[] = []
    for (const article of articles) {
      const date = dayjs(article.created_at).format('YYYY-MM-DD')
      const last = list[list.length - 1]
      if (last && last.date === date) last.items.push(article)
      else list.push({ date, items: [article] })
    }
    return list
  }, [articles])

  const keywordsOf = useCallback(
    (article: Article) =>
      [article.title, article.topic, ...(article.keywords ?? [])]
        .filter(Boolean)
        .join(' ')
        .toLowerCase(),
    [],
  )

  const treeData = useMemo(
    () =>
      groups.map((group) => ({
        value: `date:${group.date}`,
        selectable: false,
        title: (
          <span className="output-tree-date">
            <span>{dayLabel(group.date)}</span>
            <span className="output-tree-date-meta">{group.items.length} 篇</span>
          </span>
        ),
        children: group.items.map((article) => ({
          value: article.id,
          label: article.title,
          title: (
            <span className="output-tree-leaf">
              <span className="output-tree-leaf-title" title={article.title}>
                {article.title}
              </span>
              <span className="output-tree-leaf-meta">
                <span className="output-tree-leaf-time measured">
                  {formatTime(article.created_at).slice(11)}
                </span>
                {article.meta?.char_count ? (
                  <span className="output-tree-leaf-count measured">
                    {`${article.meta.char_count} 字`}
                  </span>
                ) : null}
                <span className="output-tree-leaf-count measured">
                  {`素材 ${article.meta?.kept ?? article.source_item_ids.length}`}
                </span>
              </span>
            </span>
          ),
          keywords: keywordsOf(article),
        })),
      })),
    [groups, keywordsOf],
  )

  const defaultExpandedKeys = useMemo(() => {
    const cutoff = dayjs().startOf('day').subtract(TREE_RECENT_DAYS - 1, 'day')
    const keys = groups
      .filter((group) => !dayjs(group.date).isBefore(cutoff, 'day'))
      .map((group) => `date:${group.date}`)
    const currentDate = current?.created_at
      ? dayjs(current.created_at).format('YYYY-MM-DD')
      : undefined
    if (currentDate && !keys.includes(`date:${currentDate}`)) keys.push(`date:${currentDate}`)
    return keys
  }, [groups, current?.created_at])

  const searching = searchValue.trim().length > 0
  const matchedKeys = useMemo(() => {
    if (!searching) return []
    const needle = searchValue.trim().toLowerCase()
    return groups
      .filter((group) => group.items.some((article) => keywordsOf(article).includes(needle)))
      .map((group) => `date:${group.date}`)
  }, [searching, searchValue, groups, keywordsOf])

  // 搜索时只展开命中的日期;否则用用户手动展开结果 / 默认(最近 N 天)
  const treeExpandedKeys = searching ? matchedKeys : (expandedKeys ?? defaultExpandedKeys)

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

  /** 每条素材在正文里的引用编号与次数:编号 = source_item_ids 顺序 = 参考文献列表顺序 */
  const citations = useMemo(() => {
    const markdown = current?.content_md ?? ''
    const map = new Map<number, RailCitation>()
    ;(materials ?? []).forEach((item, index) => map.set(item.id, citationByRef(markdown, index + 1)))
    return map
  }, [materials, current?.content_md])

  /** 引用徽标点击:源码/JSON 下正文不在 DOM,先切回预览 */
  const ensurePreview = useCallback(() => {
    if (outputMode !== 'preview') setOutputMode('preview')
  }, [outputMode, setOutputMode])

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
      select(null)
      queryClient.invalidateQueries({ queryKey: ['articles'] })
    },
  })

  /** 右栏顶部元信息:关键词 + 体量,回答「这篇写了什么、多长」 */
  const railMeta = useMemo(() => {
    if (!current) return null
    const keywords = current.keywords ?? current.meta?.keywords ?? []
    const stats = [
      current.meta?.char_count ? `${current.meta.char_count} 字` : null,
      `${materials?.length ?? current.source_item_ids.length} 条素材`,
      current.meta?.sections?.length ? `${current.meta.sections.length} 节` : null,
      current.model,
    ].filter(Boolean)
    return { keywords, stats: stats.join(' · ') }
  }, [current, materials])

  return (
    <div className="output-screen article-screen">
      {isLoading ? (
        /* 加载态按「即将出现的形状」给骨架:左边卡是封面 + 正文,右边是素材来源 */
        <div className="output-detail" aria-busy="true" aria-label="文章加载中">
          <Card size="small" className="output-card output-skeleton-card">
            <div className="output-skeleton-head">
              <Skeleton.Input active size="small" block />
            </div>
            <div className="output-skeleton-body">
              <Skeleton active title={{ width: '38%' }} paragraph={{ rows: 4 }} />
            </div>
          </Card>
          <aside className="output-detail-rail">
            <section className="output-rail-section">
              <Skeleton active title={{ width: '46%' }} paragraph={{ rows: 5 }} />
            </section>
          </aside>
        </div>
      ) : articles.length === 0 ? (
        <Card size="small" className="output-card">
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <div className="output-empty-copy">
                <div className="output-empty-title">{watching ? '文章生成中' : '还没有文章'}</div>
                <div className="output-empty-hint">
                  {watching
                    ? '约需 2-5 分钟,完成后会自动出现在这里。'
                    : '选好方向与时间窗口后,生成任务完成时会出现在这里。'}
                </div>
              </div>
            }
          >
            {watching ? (
              <Spin />
            ) : (
              <Button type="primary" onClick={() => setOpen(true)}>
                生成文章
              </Button>
            )}
          </Empty>
        </Card>
      ) : current ? (
        /* 两张平级卡片:左=文章内容(内容列居中),右=元信息 + 推送 + 素材来源 */
        <div className="output-detail">
          <Card
            size="small"
            className="output-card"
            /* 源码/JSON 要「满宽满高」,正文内边距必须为 0,否则面板四周会留出白边 */
            styles={{ body: { padding: outputMode === 'preview' ? 24 : 0 } }}
            title={
              /* 卡片头一行:左侧日期/文章选择器,右侧预览/源码/JSON + 复制/生成/删除图标按钮 */
              <div className="output-card-head-row">
                <TreeSelect
                  className="output-tree-select"
                  value={currentId ?? undefined}
                  onChange={(value) => select(Number(value))}
                  treeData={treeData}
                  treeExpandedKeys={treeExpandedKeys}
                  onTreeExpand={(keys) => setExpandedKeys(keys as string[])}
                  showSearch
                  searchValue={searchValue}
                  onSearch={setSearchValue}
                  filterTreeNode={(input, node) => {
                    const needle = input.trim().toLowerCase()
                    if (!needle) return true
                    const keywords = String((node as { keywords?: string }).keywords ?? '')
                    return keywords.toLowerCase().includes(needle)
                  }}
                  placeholder="选择日期 / 文章"
                  treeNodeLabelProp="label"
                  // 数据量小(≤30 条),关虚拟滚动可保证深链时日期分组头一起渲染
                  virtual={false}
                  popupMatchSelectWidth={600}
                  popupClassName="output-tree-popup output-tree-stacked"
                />
                <div className="output-card-head-actions">
                  <OutputToolbar
                    mode={outputMode}
                    onModeChange={setOutputMode}
                    contentMd={current.content_md}
                    payload={jsonPayload}
                    loading={materialsLoading}
                    copyAsIcon
                    modeControl="switch"
                  />
                  <Tooltip title="生成文章">
                    <Button
                      className="icon-btn"
                      icon={<FileAddOutlined />}
                      aria-label="生成文章"
                      onClick={() => setOpen(true)}
                    />
                  </Tooltip>
                  {/* 危险操作降级为图标,误触由二次确认兜底 */}
                  <Popconfirm
                    title="删除这篇文章？"
                    description="删除后不可恢复,采集到的素材不受影响。"
                    okText="删除"
                    cancelText="取消"
                    okButtonProps={{ danger: true, loading: deleteMutation.isPending }}
                    onConfirm={() => deleteMutation.mutate(current.id)}
                  >
                    <Tooltip title="删除文章">
                      <Button
                        className="icon-btn is-danger"
                        icon={<DeleteOutlined />}
                        aria-label="删除文章"
                        disabled={deleteMutation.isPending}
                      />
                    </Tooltip>
                  </Popconfirm>
                </div>
              </div>
            }
          >
            {/* 预览=限宽居中留白;源码/JSON=满宽满高的深色面板,两种版式刻意区分 */}
            <div
              className={
                outputMode === 'preview' ? 'output-content' : 'output-content output-content-raw'
              }
            >
              <OutputViewer
                contentMd={current.content_md}
                payload={jsonPayload}
                loading={materialsLoading}
                mode={outputMode}
                showToolbar={false}
              />
            </div>
          </Card>
          <OutputRail
            items={materials ?? []}
            citations={citations}
            resetKey={currentId}
            loading={materialsLoading}
            variant="trail"
            activeItemId={materialItemId}
            onOpenItem={setMaterialItemId}
            onEnsurePreview={ensurePreview}
            emptyText="这条文章没有关联到素材记录"
            top={
              <>
                {railMeta && (railMeta.keywords.length > 0 || railMeta.stats) ? (
                  <div className="output-rail-meta">
                    {railMeta.keywords.length > 0 ? (
                      <div className="output-rail-meta-tags">
                        {railMeta.keywords.slice(0, 4).map((word) => (
                          <span key={word} className="output-rail-tag">
                            {word}
                          </span>
                        ))}
                        {railMeta.keywords.length > 4 ? (
                          <span className="output-rail-tag is-more">
                            +{railMeta.keywords.length - 4}
                          </span>
                        ) : null}
                      </div>
                    ) : null}
                    {railMeta.stats ? (
                      <div className="output-rail-meta-line" title={railMeta.stats}>
                        {railMeta.stats}
                      </div>
                    ) : null}
                  </div>
                ) : null}
                <div className="output-rail-divider" />
                <PushSection targetKind="article" targetId={current.id} vertical />
              </>
            }
          />
        </div>
      ) : null}

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
