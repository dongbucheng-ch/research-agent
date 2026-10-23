import { DeleteOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Button,
  Card,
  Empty,
  Popconfirm,
  Space,
  Spin,
  Tooltip,
  TreeSelect,
  Typography,
  message,
} from 'antd'
import dayjs from 'dayjs'
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { api } from '../../api/client'
import type { Digest, Item, Page } from '../../api/types'
import { digestBatch, formatTime } from '../../utils'
import DigestGenerateModal from '../DigestGenerateModal'
import ItemDetailDrawer from '../ItemDetailDrawer'
import PushSection from '../PushSection'
import OutputViewer, { OutputToolbar, useOutputMode } from './OutputViewer'
import OutputRail, { citationByUrl, type RailCitation } from './outputRail'

/** 树形选择器默认展开的最近日期数;更早的日期收起,避免下拉一屏放不下 */
const TREE_RECENT_DAYS = 7

interface Props {
  focusId?: number | null
  /** 选择变更回写 URL:刷新、分享、后退都能回到同一条 */
  onSelect?: (id: number | null, options?: { replace?: boolean }) => void
}

/** 日期文案:最近用相对时间,更早用日期,跨年补全年份 */
function groupLabel(date: string): string {
  const day = dayjs(date)
  const today = dayjs().startOf('day')
  if (day.isSame(today, 'day')) return '今天'
  if (day.isSame(today.subtract(1, 'day'), 'day')) return '昨天'
  return day.year() === today.year() ? day.format('MM-DD') : day.format('YYYY-MM-DD')
}

function isTopic(digest: Digest): boolean {
  return digest.meta?.scope === 'topic'
}

/** 批次元信息:第 N 批 · 时间 · 条数(+ GitHub) */
/** 树节点里的批次元信息:去掉 GitHub,给标题留出宽度 */
function treeLeafMeta(digest: Digest, index: number): string {
  const count = digest.meta?.news_count ?? digest.item_count
  return `第 ${index} 批 · ${formatTime(digest.created_at).slice(11)} · ${count} 条`
}

interface BatchInfo {
  date: string
  index: number
}

export default function DigestPanel({ focusId, onSelect }: Props) {
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [open, setOpen] = useState(false)
  const [materialItemId, setMaterialItemId] = useState<number | null>(null)
  const [searchValue, setSearchValue] = useState('')
  /** null=用默认展开集合(最近 N 天);用户展开/收起后以其为准 */
  const [expandedKeys, setExpandedKeys] = useState<string[] | null>(null)
  /** 预览/源码/JSON 由卡片头持有,正文只消费当前模式 */
  const [outputMode, setOutputMode] = useOutputMode()

  const { data, isLoading } = useQuery({
    queryKey: ['digests'],
    queryFn: () => api.get<Page<Digest>>('/digests?page_size=30'),
  })
  const digests = data?.items ?? []
  const current = digests.find((digest) => digest.id === selectedId) ?? digests[0]
  const currentId = current?.id

  const select = useCallback(
    (id: number | null, options?: { replace?: boolean }) => {
      setSelectedId(id)
      onSelect?.(id, options)
    },
    [onSelect],
  )

  // 批次(日期 + 当日序号)只算一次,供树节点 / 搜索 / 元信息复用
  const batchById = useMemo(() => {
    const map = new Map<number, BatchInfo>()
    for (const digest of digests) map.set(digest.id, digestBatch(digest, digests))
    return map
  }, [digests])

  const batchOf = useCallback(
    (digest: Digest): BatchInfo => batchById.get(digest.id) ?? { date: '', index: 1 },
    [batchById],
  )

  // 日期 → 批次 两级;组内保持后端的按时间倒序
  const groups = useMemo(() => {
    const list: { date: string; items: Digest[] }[] = []
    for (const digest of digests) {
      const date = batchOf(digest).date
      const last = list[list.length - 1]
      if (last && last.date === date) last.items.push(digest)
      else list.push({ date, items: [digest] })
    }
    return list
  }, [digests, batchOf])

  const keywordsOf = useCallback(
    (digest: Digest) => {
      const batch = batchOf(digest)
      return [
        digest.title,
        digest.meta?.topic,
        batch.date,
        groupLabel(batch.date),
        `第${batch.index}批`,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
    },
    [batchOf],
  )

  const treeData = useMemo(
    () =>
      groups.map((group) => ({
        value: `date:${group.date}`,
        selectable: false,
        title: (
          <span className="output-tree-date">
            <span>{groupLabel(group.date)}</span>
            <span className="output-tree-date-meta">{group.items.length} 条</span>
          </span>
        ),
        children: group.items.map((digest) => {
          const batch = batchOf(digest)
          return {
            value: digest.id,
            label: `${groupLabel(group.date)} · 第 ${batch.index} 批 · ${digest.title}`,
            title: (
              <span className="output-tree-leaf">
                <span className="output-tree-leaf-title" title={digest.title}>
                  {digest.title}
                </span>
                <span className="output-tree-leaf-meta">
                  {treeLeafMeta(digest, batch.index)}
                  {isTopic(digest) ? ' · 定向' : ''}
                </span>
              </span>
            ),
            keywords: keywordsOf(digest),
          }
        }),
      })),
    [groups, batchOf, keywordsOf],
  )

  const defaultExpandedKeys = useMemo(() => {
    const cutoff = dayjs().startOf('day').subtract(TREE_RECENT_DAYS - 1, 'day')
    const keys = groups
      .filter((group) => !dayjs(group.date).isBefore(cutoff, 'day'))
      .map((group) => `date:${group.date}`)
    const currentDate = currentId ? batchById.get(currentId)?.date : undefined
    if (currentDate && !keys.includes(`date:${currentDate}`)) keys.push(`date:${currentDate}`)
    return keys
  }, [groups, currentId, batchById])

  const searching = searchValue.trim().length > 0
  const matchedKeys = useMemo(() => {
    if (!searching) return []
    const needle = searchValue.trim().toLowerCase()
    return groups
      .filter((group) => group.items.some((digest) => keywordsOf(digest).includes(needle)))
      .map((group) => `date:${group.date}`)
  }, [searching, searchValue, groups, keywordsOf])

  // 搜索时只展开命中的日期;否则用用户手动展开结果 / 默认(最近 N 天)
  const treeExpandedKeys = searching ? matchedKeys : (expandedKeys ?? defaultExpandedKeys)

  const { data: materials, isLoading: materialsLoading } = useQuery({
    queryKey: ['digest-items', current?.id],
    queryFn: () => api.get<Item[]>(`/digests/${current!.id}/items`),
    enabled: Boolean(current?.id),
  })

  /** 每条素材在正文里的引用次数与所属小节:徽标点击可回跳正文 */
  const citations = useMemo(() => {
    const markdown = current?.content_md ?? ''
    const map = new Map<number, RailCitation>()
    for (const item of materials ?? []) map.set(item.id, citationByUrl(markdown, item.url))
    return map
  }, [materials, current?.content_md])

  /** 引用徽标点击:源码/JSON 下正文不在 DOM,先切回预览 */
  const ensurePreview = useCallback(() => {
    if (outputMode !== 'preview') setOutputMode('preview')
  }, [outputMode, setOutputMode])

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
      select(null)
      queryClient.invalidateQueries({ queryKey: ['digests'] })
    },
  })

  /** 内容卡片内部:仅正文;选择器与模式切换都在卡片头常驻(卡片本身与右侧信息卡平级) */
  const renderContent = (): ReactNode => {
    if (!current) return null
    return (
      <OutputViewer
        contentMd={current.content_md}
        payload={jsonPayload}
        loading={materialsLoading}
        mode={outputMode}
        showToolbar={false}
      />
    )
  }

  return (
    <div>
      {isLoading ? (
        <div style={{ textAlign: 'center', padding: 60 }}>
          <Spin />
        </div>
      ) : digests.length === 0 ? (
        <Empty description="还没有日报" style={{ padding: 60 }}>
          <Button type="primary" onClick={() => setOpen(true)}>
            生成日报
          </Button>
        </Empty>
      ) : current ? (
        /* 两张平级卡片:左=日报内容(内容列居中),右=素材来源 + 推送 */
        <div className="output-detail">
          <Card
            size="small"
            className="output-card"
            /* 源码/JSON 要「满宽满高」,正文内边距必须为 0,否则面板四周会留出白边 */
            styles={{ body: { padding: outputMode === 'preview' ? 24 : 0 } }}
            title={
              /* 卡片头一行:左侧批选择器,右侧预览/源码/JSON + 复制/删除图标按钮;吸顶常驻 */
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
                  placeholder="选择日期 / 批次"
                  treeNodeLabelProp="label"
                  // 数据量小(≤30 条),关虚拟滚动可保证深链时日期分组头一起渲染
                  virtual={false}
                  popupMatchSelectWidth={600}
                  popupClassName="output-tree-popup"
                  style={{ width: 360 }}
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
                  {/* 危险操作降级为图标,误触由二次确认兜底 */}
                  <Popconfirm
                    title="删除这条日报？"
                    description="删除后不可恢复,采集到的素材不受影响。"
                    okText="删除"
                    cancelText="取消"
                    okButtonProps={{ danger: true, loading: deleteMutation.isPending }}
                    onConfirm={() => deleteMutation.mutate(current.id)}
                  >
                    <Tooltip title="删除日报">
                      <Button
                        className="icon-btn"
                        icon={<DeleteOutlined />}
                        aria-label="删除日报"
                        disabled={deleteMutation.isPending}
                      />
                    </Tooltip>
                  </Popconfirm>
                </div>
              </div>
            }
          >
            {/* 预览=限宽居中留白;源码/JSON=满宽满高的深色面板,两种版式刻意区分 */}
            <div className={outputMode === 'preview' ? 'output-content' : 'output-content output-content-raw'}>
              {renderContent()}
            </div>
          </Card>
          <OutputRail
            items={materials ?? []}
            citations={citations}
            resetKey={currentId}
            activeItemId={materialItemId}
            onOpenItem={setMaterialItemId}
            onEnsurePreview={ensurePreview}
            emptyText="这条日报没有关联到素材记录"
            top={<PushSection targetKind="digest" targetId={current.id} vertical />}
          />
        </div>
      ) : null}

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
