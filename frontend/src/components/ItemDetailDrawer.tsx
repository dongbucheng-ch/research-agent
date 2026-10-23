import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ExportOutlined, MoreOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Button,
  Descriptions,
  Divider,
  Drawer,
  Dropdown,
  Modal,
  Space,
  Spin,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import { api } from '../api/client'
import type { ItemDetail } from '../api/types'
import { CONTENT_TYPE_META, formatRelative, formatTime, scoreHex } from '../utils'

interface Props {
  itemId: number | null
  onClose: () => void
}

/**
 * 速读卡片的两套字段只是历史遗留的数据形状,对用户不构成"版本":
 * 渲染时按卡片实际携带的字段取标签,布局、字号、颜色完全一致,界面上不做任何区分。
 * - 新形状:what / why / how(是什么 / 为什么重要 / 怎么用)
 * - 旧形状:background / method / result / insight(背景 / 方法 / 结果 / 启示)
 */
const CARD_FIELDS: Array<[string, string]> = [
  ['what', '是什么'],
  ['why', '为什么重要'],
  ['how', '怎么用'],
  ['background', '背景'],
  ['method', '方法'],
  ['result', '结果'],
  ['insight', '启示'],
]

function cardFields(card: Record<string, unknown>): Array<[string, string]> {
  const filled = CARD_FIELDS.filter(([key]) => String(card[key] ?? '').trim())
  return filled.length ? filled : CARD_FIELDS.slice(0, 3)
}

const SCORE_FIELDS: Array<{ key: 'relevance' | 'heat' | 'freshness'; label: string; weight: number }> = [
  { key: 'relevance', label: '相关', weight: 0.45 },
  { key: 'heat', label: '热度', weight: 0.35 },
  { key: 'freshness', label: '时效', weight: 0.2 },
]

const clampPercent = (value: unknown) => Math.max(0, Math.min(100, Number(value ?? 0) || 0))
/** 分值统一到一位小数:同一列里混着 100 / 98 / 93.24 三种精度会让眼睛反复校准 */
const fmtScore = (value: unknown) => (Number(value ?? 0) || 0).toFixed(1)

/**
 * 摘要与速读卡片是否同源:把中文切成二元组、英文按词,算摘要片段落在卡片里的比例。
 * 实测 60 条真实数据中位数 0.56,≥0.70 的约两成——这些摘要基本是卡片的复述,折叠掉避免读两遍。
 */
const SUMMARY_FOLD_THRESHOLD = 0.7

function tokensOf(text: string): string[] {
  const lower = text.toLowerCase()
  const latin = lower.match(/[a-z0-9][a-z0-9.+-]*/g) ?? []
  const cjk = (lower.match(/[\u4e00-\u9fa5]/g) ?? []).join('')
  const grams: string[] = []
  for (let i = 0; i + 1 < cjk.length; i += 1) grams.push(cjk.slice(i, i + 2))
  return [...latin, ...grams]
}

function overlapRatio(summary: string, cardText: string): number {
  const source = tokensOf(summary)
  if (!source.length) return 0
  const target = new Set(tokensOf(cardText))
  return source.filter((token) => target.has(token)).length / source.length
}

export default function ItemDetailDrawer({ itemId, onClose }: Props) {
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['item', itemId],
    queryFn: () => api.get<ItemDetail>(`/items/${itemId}`),
    enabled: itemId !== null,
  })

  const enrichMutation = useMutation({
    mutationFn: () => api.post<ItemDetail>(`/items/${itemId}/enrich`),
    onSuccess: () => {
      message.success('已生成速读卡片')
      queryClient.invalidateQueries({ queryKey: ['item', itemId] })
      queryClient.invalidateQueries({ queryKey: ['items'] })
    },
    onError: (error: Error) => message.error(error.message),
  })

  const hideMutation = useMutation({
    mutationFn: () => api.patch<ItemDetail>(`/items/${itemId}`, { status: 'hidden' }),
    onSuccess: () => {
      message.success('已隐藏该条目')
      queryClient.invalidateQueries({ queryKey: ['items'] })
      onClose()
    },
    onError: (error: Error) => message.error(error.message),
  })

  const meta = data ? CONTENT_TYPE_META[data.content_type] : undefined
  const card = data?.card as Record<string, unknown> | null | undefined
  const [showAllRefs, setShowAllRefs] = useState(false)
  const [bodyOpen, setBodyOpen] = useState(false)
  const [summaryOpen, setSummaryOpen] = useState(false)
  const references = data?.references ?? []
  const shownRefs = showAllRefs ? references : references.slice(0, 3)
  const cardRows = card ? cardFields(card) : []

  /** meta 行只留 3 个话题标签,其余收进「+N」;标签密集出现会稀释真正要看的信号 */
  const topicTags = data?.tags ?? []
  const shownTopicTags = topicTags.slice(0, 3)
  const hiddenTopicTags = topicTags.slice(3)

  /** 卡片关键词与 meta 行、采集来源重复的不再重复展示 */
  const shownWords = new Set(
    [...(data?.collect_keywords ?? []), ...(data?.keyword_hits ?? []), ...topicTags].map((word) =>
      word.toLowerCase(),
    ),
  )
  const cardKeywords = ((card?.keywords as string[] | undefined) ?? []).filter(
    (keyword) => !shownWords.has(keyword.toLowerCase()),
  )

  /** 采集关键词去重:先去大小写重复(AI 与 ai),再去包含关系(agent 与 llm agent 只留更具体的那个) */
  const collectWords: string[] = []
  const seenCollect = new Set<string>()
  for (const word of (data?.collect_keywords.length ? data.collect_keywords : data?.keyword_hits) ?? []) {
    const key = word.toLowerCase()
    if (seenCollect.has(key)) continue
    seenCollect.add(key)
    collectWords.push(word)
  }
  const loweredCollect = collectWords.map((word) => word.toLowerCase())
  const shownCollectWords = collectWords.filter((word, index) => {
    const self = loweredCollect[index]
    return !loweredCollect.some(
      (other, otherIndex) => otherIndex !== index && other.length > self.length && other.includes(self),
    )
  })

  /** 摘要与卡片同源时折叠成一行灰字(可展开),避免同一段内容读两遍 */
  const summaryText = data?.summary ?? ''
  const foldSummary =
    !!card &&
    !!summaryText &&
    overlapRatio(
      summaryText,
      cardRows.map(([key]) => String(card?.[key] ?? '')).join(' '),
    ) >= SUMMARY_FOLD_THRESHOLD
  const showSummary = !!summaryText && (!foldSummary || summaryOpen)

  return (
    <>
      <Drawer
      width={720}
      rootClassName="item-drawer"
      open={itemId !== null}
      onClose={onClose}
      title={
        data ? (
          <div className="item-drawer-heading">
            <Tooltip title={data.translated_title || data.title} placement="bottomLeft">
              <div className="item-drawer-title">{data.translated_title || data.title}</div>
            </Tooltip>
            {data.translated_title && data.translated_title !== data.title && (
              <Tooltip title={data.title} placement="bottomLeft">
                <div className="item-drawer-subtitle">{data.title}</div>
              </Tooltip>
            )}
          </div>
        ) : (
          '条目详情'
        )
      }
      extra={
        data ? (
          <Space size={8}>
            {/* 生成/重生成是「速读卡片」自己的动作,挪到该区块标题行(就近原则),
                header 只留「打开原文 / 更多」,标题才能拿到完整宽度 */}
            <Tooltip title="打开原文">
              <Button icon={<ExportOutlined />} href={data.url} target="_blank" rel="noreferrer" />
            </Tooltip>
            <Dropdown
              trigger={['click']}
              menu={{
                items: [
                  ...(data.raw_text || data.translated_text
                    ? [{ key: 'body', label: '查看抓取正文' }]
                    : []),
                  { key: 'hide', label: '隐藏该条目', danger: true },
                ],
                onClick: ({ key }) => {
                  if (key === 'hide') hideMutation.mutate()
                  else setBodyOpen(true)
                },
              }}
            >
              <Button icon={<MoreOutlined />} loading={hideMutation.isPending} />
            </Dropdown>
          </Space>
        ) : null
      }
    >
      {isLoading || !data ? (
        <Spin />
      ) : (
        <>
          {/* 身份信息走一行灰字(标签只留给话题分类),一屏内的 chip 数量从 13 降到 3 */}
          <div className="item-drawer-meta">
            <div className="item-drawer-meta-line">
              {[meta?.label, data.source_name ?? data.channel, data.author].filter(Boolean).join(' · ')}
            </div>
            {shownTopicTags.length > 0 && (
              <Space wrap size={4}>
                {shownTopicTags.map((tag) => (
                  <Tag key={tag}>{tag}</Tag>
                ))}
                {hiddenTopicTags.length > 0 && (
                  <Tooltip title={hiddenTopicTags.join(' / ')}>
                    <Tag className="item-tag-more">+{hiddenTopicTags.length}</Tag>
                  </Tooltip>
                )}
              </Space>
            )}
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              发布 {formatTime(data.published_at)} · 收录 {formatRelative(data.first_seen_at)}
              {data.lang ? ` · ${data.lang}` : ''}
            </Typography.Text>
          </div>

          {showSummary && (
            <Typography.Paragraph className="item-drawer-summary">{summaryText}</Typography.Paragraph>
          )}

          <Divider style={{ margin: '12px 0' }} />

          {/* 速读卡片:一张独立的卡、单列纵向编号段落。
              旧的两列象限要左右来回扫读,长句在窄列里被切成碎行,读起来像表格而不像文章 */}
          <section className="read-card">
            <div className="read-card-head">
              <span className="read-card-title">速读卡片</span>
              <Button
                type="text"
                size="small"
                className="item-section-action"
                icon={<ThunderboltOutlined />}
                loading={enrichMutation.isPending}
                onClick={() => enrichMutation.mutate()}
              >
                {card ? '重新生成' : '生成'}
              </Button>
            </div>
            {card ? (
              <>
                <ol className="read-card-body">
                  {cardRows.map(([key, label], index) => (
                    <li className="read-card-item" key={key}>
                      <div className="read-card-item-head">
                        <span className="read-card-index">{String(index + 1).padStart(2, '0')}</span>
                        <span className="read-card-label">{label}</span>
                      </div>
                      <p className="read-card-text">{String(card[key] ?? '') || '-'}</p>
                    </li>
                  ))}
                </ol>
                {(cardKeywords.length > 0 || foldSummary) && (
                  <div className="read-card-foot">
                    {cardKeywords.length > 0 && (
                      <span className="read-card-words">{cardKeywords.join(' · ')}</span>
                    )}
                    {foldSummary && (
                      <Button
                        type="link"
                        size="small"
                        className="read-card-summary-toggle"
                        onClick={() => setSummaryOpen((value) => !value)}
                      >
                        {summaryOpen ? '收起原始摘要' : '原始摘要'}
                      </Button>
                    )}
                  </div>
                )}
                {foldSummary && summaryOpen && (
                  <div className="read-card-summary">{summaryText}</div>
                )}
              </>
            ) : (
              <div className="read-card-empty">
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  还没有速读卡片;点右上角「生成」得到结构化速读要点。
                </Typography.Text>
              </div>
            )}
          </section>

          <Divider style={{ margin: '12px 0' }} />
          {references.length > 0 ? (
            <>
              <Typography.Title level={5} className="item-section-title" style={{ marginTop: 0 }}>
                被引用({references.length})
              </Typography.Title>
              <Space direction="vertical" size={6} style={{ width: '100%', marginBottom: 8 }}>
                {shownRefs.map((ref) => (
                  <Link
                    key={`${ref.kind}-${ref.id}`}
                    to={`/pool?tab=${ref.kind}&id=${ref.id}`}
                    onClick={onClose}
                  >
                    <Tag color={ref.kind === 'digest' ? 'blue' : 'purple'}>
                      {ref.kind === 'digest' ? '日报' : '文章'}
                    </Tag>
                    {ref.title}
                    <Typography.Text type="secondary" style={{ fontSize: 12, marginInlineStart: 8 }}>
                      {formatRelative(ref.created_at)}
                    </Typography.Text>
                  </Link>
                ))}
                {references.length > 3 && (
                  <Button type="link" size="small" style={{ padding: 0 }} onClick={() => setShowAllRefs((value) => !value)}>
                    {showAllRefs ? '收起' : `查看全部 ${references.length} 条`}
                  </Button>
                )}
              </Space>
            </>
          ) : (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              暂无产出物引用
            </Typography.Text>
          )}

          <Divider style={{ margin: '12px 0' }} />
          {/* 评分块降噪后置:总分不再用大号数字与满宽灰底抢占首屏,退到「参考信息」这一档 */}
          {data.score && (
            <div className="item-score-bar">
              <div className="item-score-total" style={{ color: scoreHex(data.score.total) }}>
                {fmtScore(data.score.total)}
                <span className="item-score-total-label">总分</span>
              </div>
              <div className="item-score-metrics">
                {SCORE_FIELDS.map(({ key, label, weight }) => {
                  const value = Number(data.score?.[key] ?? 0)
                  return (
                    <div className="item-score-metric" key={key}>
                      <span className="item-score-metric-label">
                        {label}
                        <em>{Math.round(weight * 100)}%</em>
                      </span>
                      <span className="item-score-track">
                        <i style={{ width: `${clampPercent(value)}%` }} />
                      </span>
                      <span className="item-score-metric-value">{fmtScore(value)}</span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          <Descriptions column={2} size="small">
            <Descriptions.Item label="采集来源" span={2}>
              {data.collect_name || data.origin || data.keyword_hits.length > 0 ? (
                <span className="item-collect-line">
                  {[
                    data.collect_name,
                    ...(data.collect_keywords.length ? shownCollectWords : data.keyword_hits).slice(0, 4),
                    ...(data.origin === 'backfill' ? ['辐射词补采'] : []),
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </span>
              ) : (
                '(旧素材,未记录采集方向)'
              )}
            </Descriptions.Item>
            <Descriptions.Item label="发布时间">{formatTime(data.published_at)}</Descriptions.Item>
            <Descriptions.Item label="收录时间">{formatRelative(data.first_seen_at)}</Descriptions.Item>
            <Descriptions.Item label="链接" span={2}>
              <Typography.Text copyable style={{ maxWidth: 560 }} ellipsis>
                {data.url}
              </Typography.Text>
            </Descriptions.Item>
          </Descriptions>
        </>
      )}
      </Drawer>
      <Modal
        title="抓取正文"
        open={bodyOpen}
        onCancel={() => setBodyOpen(false)}
        footer={null}
        width={720}
      >
        <div className="item-body-modal">
          {data?.translated_text && (
            <>
              <Typography.Title level={5} style={{ marginTop: 0 }}>
                译文
              </Typography.Title>
              <Typography.Paragraph>{data.translated_text}</Typography.Paragraph>
            </>
          )}
          {data?.raw_text ? (
            <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
              {data.raw_text}
            </Typography.Paragraph>
          ) : (
            <Typography.Text type="secondary">
              该条目没有抓取到正文,可打开原文链接查看。
            </Typography.Text>
          )}
        </div>
      </Modal>
    </>
  )
}
