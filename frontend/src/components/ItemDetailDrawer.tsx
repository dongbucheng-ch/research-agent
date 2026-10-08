import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ExportOutlined, MoreOutlined } from '@ant-design/icons'
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
import { CONTENT_TYPE_META, formatRelative, formatTime } from '../utils'

interface Props {
  itemId: number | null
  onClose: () => void
}

/** 速读卡片:what / why / how;旧数据(background/method/result/insight)按原字段渲染。 */
const CARD_FIELDS: Array<[string, string]> = [
  ['what', '是什么'],
  ['why', '为什么重要'],
  ['how', '怎么用'],
]

const LEGACY_CARD_FIELDS: Array<[string, string]> = [
  ['background', '背景'],
  ['method', '方法'],
  ['result', '结果'],
  ['insight', '启示'],
]

function cardFields(card: Record<string, unknown>): Array<[string, string]> {
  const hasNew = CARD_FIELDS.some(([key]) => String(card[key] ?? '').trim())
  return hasNew ? CARD_FIELDS : LEGACY_CARD_FIELDS
}

const SCORE_FIELDS: Array<{ key: 'relevance' | 'heat' | 'freshness'; label: string; weight: string }> = [
  { key: 'relevance', label: '相关', weight: '0.45' },
  { key: 'heat', label: '热度', weight: '0.35' },
  { key: 'freshness', label: '时效', weight: '0.20' },
]

/** 分数 → 内联文字/进度条颜色(与 utils.scoreColor 的分档一致)。 */
function scoreHex(total: number | null | undefined): string {
  const value = total ?? 0
  if (value >= 80) return '#cf1322'
  if (value >= 65) return '#d46b08'
  if (value >= 50) return '#1677ff'
  return '#8c8c8c'
}

const clampPercent = (value: unknown) => Math.max(0, Math.min(100, Number(value ?? 0) || 0))

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
  const references = data?.references ?? []
  const shownRefs = showAllRefs ? references : references.slice(0, 3)
  const cardRows = card ? cardFields(card) : []
  const isLegacyCard = !!card && !CARD_FIELDS.some(([key]) => String(card[key] ?? '').trim())

  return (
    <>
      <Drawer
      width={720}
      open={itemId !== null}
      onClose={onClose}
      title={
        data ? (
          <div className="item-drawer-heading">
            <div className="item-drawer-title">{data.translated_title || data.title}</div>
            {data.translated_title && data.translated_title !== data.title && (
              <div className="item-drawer-subtitle">{data.title}</div>
            )}
          </div>
        ) : (
          '条目详情'
        )
      }
      extra={
        data ? (
          <Space size={8}>
            <Button
              type="primary"
              onClick={() => enrichMutation.mutate()}
              loading={enrichMutation.isPending}
            >
              {card ? '重新生成速读卡片' : '生成速读卡片'}
            </Button>
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
          <div className="item-drawer-meta">
            <Space wrap size={4}>
              {meta && <Tag color={meta.color}>{meta.label}</Tag>}
              <Tag>{data.source_name ?? data.channel}</Tag>
              {data.author && <Tag>{data.author}</Tag>}
              {data.lang && <Tag>{data.lang}</Tag>}
              {data.tags?.slice(0, 6).map((tag) => <Tag key={tag}>{tag}</Tag>)}
            </Space>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              发布 {formatTime(data.published_at)} · 收录 {formatRelative(data.first_seen_at)}
            </Typography.Text>
          </div>

          {data.score && (
            <div className="item-score-bar">
              <div className="item-score-total" style={{ color: scoreHex(data.score.total) }}>
                {data.score.total}
                <span className="item-score-total-label">总分</span>
              </div>
              <div className="item-score-metrics">
                {SCORE_FIELDS.map(({ key, label, weight }) => {
                  const value = Number(data.score?.[key] ?? 0)
                  return (
                    <div className="item-score-metric" key={key}>
                      <span className="item-score-metric-label">
                        {label}
                        <em>{weight}</em>
                      </span>
                      <span className="item-score-track">
                        <i
                          style={{
                            width: `${clampPercent(value)}%`,
                            background: scoreHex(value),
                          }}
                        />
                      </span>
                      <span className="item-score-metric-value">{value}</span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          <Divider style={{ margin: '12px 0' }} />

          {data.summary && <Typography.Paragraph className="item-drawer-summary">{data.summary}</Typography.Paragraph>}

          <Typography.Title level={5} className="item-section-title">
            速读卡片
            {isLegacyCard && (
              <Tag color="gold" style={{ marginInlineStart: 8, fontWeight: 400 }}>
                旧版
              </Tag>
            )}
          </Typography.Title>
          {isLegacyCard && (
            <Typography.Text
              type="secondary"
              style={{ fontSize: 12, display: 'block', marginBottom: 8 }}
            >
              旧版卡片,点右上角「重新生成速读卡片」可升级为「是什么 / 为什么重要 / 怎么用」。
            </Typography.Text>
          )}
          {card ? (
            <>
              <div className="item-card-grid">
                {cardRows.map(([key, label]) => (
                  <div className="item-card-field" key={key}>
                    <div className="item-card-label">{label}</div>
                    <div className="item-card-text">{String(card[key] ?? '') || '-'}</div>
                  </div>
                ))}
              </div>
              {(card.keywords as string[] | undefined)?.length ? (
                <Space wrap size={4} style={{ marginTop: 10 }}>
                  {(card.keywords as string[]).map((keyword) => (
                    <Tag key={keyword}>{keyword}</Tag>
                  ))}
                </Space>
              ) : null}
            </>
          ) : (
            <div className="item-card-empty">
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                还没有速读卡片;生成后可获得「是什么 / 为什么重要 / 怎么用」三段摘要。
              </Typography.Text>
              <Button
                type="primary"
                size="small"
                onClick={() => enrichMutation.mutate()}
                loading={enrichMutation.isPending}
              >
                生成速读卡片
              </Button>
            </div>
          )}

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
          <Descriptions column={2} size="small">
            <Descriptions.Item label="采集来源" span={2}>
              {data.collect_name || data.origin || data.keyword_hits.length > 0 ? (
                <Space wrap size={4}>
                  {data.collect_name && <Tag color="geekblue">{data.collect_name}</Tag>}
                  {(data.collect_keywords.length ? data.collect_keywords : data.keyword_hits)
                    .slice(0, 4)
                    .map((word) => (
                      <Tag key={word}>{word}</Tag>
                    ))}
                  {data.collect_keywords.length > 0 && data.keyword_hits.length > 0 && (
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      命中 {data.keyword_hits.slice(0, 3).join(' / ')}
                    </Typography.Text>
                  )}
                  {data.origin === 'backfill' && <Tag color="gold">辐射词补采</Tag>}
                </Space>
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
