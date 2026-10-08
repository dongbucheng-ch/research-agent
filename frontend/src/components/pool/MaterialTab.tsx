import { useQuery } from '@tanstack/react-query'
import {
  Card,
  Empty,
  Input,
  List,
  Pagination,
  Segmented,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd'
import { useState } from 'react'
import { api, toQuery } from '../../api/client'
import type { Item, Page, Source, Stats } from '../../api/types'
import { CONTENT_TYPE_META, formatRelative, scoreColor } from '../../utils'
import ItemDetailDrawer from '../ItemDetailDrawer'

const PAGE_SIZE = 20

const ENGINE_OPTIONS = [
  { label: '全部引擎', value: '' },
  { label: 'RSS', value: 'rss' },
  { label: '资讯/论文', value: 'news' },
  { label: 'GitHub', value: 'github' },
]

// 与后端 CHANNEL_ROUTES 对齐:引擎 → 渠道键。用于信源下拉联动过滤。
const ENGINE_CHANNELS: Record<string, string[]> = {
  rss: ['rss', 'feed'],
  news: ['arxiv', 'google_news', 'bing_news', 'hackernews', 'hn'],
  github: ['github', 'github_trending', 'trending', 'repo', 'skill', 'model'],
}

export default function MaterialTab() {
  const [contentType, setContentType] = useState<string | undefined>(undefined)
  const [engine, setEngine] = useState('')
  const [sourceId, setSourceId] = useState<number | undefined>(undefined)
  const [minScore, setMinScore] = useState<number | undefined>(undefined)
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState('score')
  const [page, setPage] = useState(1)
  const [activeItemId, setActiveItemId] = useState<number | null>(null)

  const { data: stats } = useQuery({
    queryKey: ['stats'],
    queryFn: () => api.get<Stats>('/stats/overview'),
  })
  const { data: sources } = useQuery({
    queryKey: ['sources'],
    queryFn: () => api.get<Source[]>('/sources'),
  })
  const { data, isLoading } = useQuery({
    queryKey: ['items', contentType, engine, sourceId, minScore, search, sort, page],
    queryFn: () =>
      api.get<Page<Item>>(
        `/items${toQuery({
          content_type: contentType || undefined,
          engine: engine || undefined,
          source_id: sourceId,
          min_score: minScore,
          q: search || undefined,
          sort,
          page,
          page_size: PAGE_SIZE,
        })}`,
      ),
  })

  const sourceOptions = (sources ?? [])
    .filter((source) => !engine || (ENGINE_CHANNELS[engine] ?? []).includes(source.channel))
    .map((source) => ({ value: source.id, label: `${source.name}(${source.channel})` }))

  const resetPage = () => setPage(1)

  return (
    <div>
      <Space style={{ width: '100%', justifyContent: 'space-between' }} align="center">
        <Space wrap className="feed-toolbar">
          <Segmented
            value={engine}
            onChange={(value) => {
              setEngine(String(value))
              setSourceId(undefined)
              resetPage()
            }}
            options={ENGINE_OPTIONS}
          />
          <Select
            allowClear
            placeholder="内容类型"
            style={{ width: 140 }}
            value={contentType}
            onChange={(value) => {
              setContentType(value)
              resetPage()
            }}
            options={Object.entries(CONTENT_TYPE_META).map(([value, meta]) => ({
              value,
              label: meta.label,
            }))}
          />
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="具体信源"
            style={{ width: 220 }}
            value={sourceId}
            onChange={(value) => {
              setSourceId(value)
              resetPage()
            }}
            options={sourceOptions}
          />
          <Select
            allowClear
            placeholder="分数不限"
            style={{ width: 120 }}
            value={minScore}
            onChange={(value) => {
              setMinScore(value)
              resetPage()
            }}
            options={[50, 60, 70, 80].map((value) => ({ value, label: `≥ ${value} 分` }))}
          />
          <Select
            style={{ width: 132 }}
            value={sort}
            onChange={setSort}
            options={[
              { value: 'score', label: '按综合分' },
              { value: 'recent', label: '按收录时间' },
              { value: 'published', label: '按发布时间' },
            ]}
          />
          <Input.Search
            allowClear
            placeholder="搜索标题 / 摘要"
            style={{ width: 220 }}
            onSearch={(value) => {
              setSearch(value.trim())
              resetPage()
            }}
          />
        </Space>
        {stats && (
          <Typography.Text type="secondary">
            共 {stats.items_total} 条 · 今日新增 {stats.items_today}
          </Typography.Text>
        )}
      </Space>

      {isLoading ? (
        <div style={{ textAlign: 'center', padding: 60 }}>
          <Spin />
        </div>
      ) : !data || data.items.length === 0 ? (
        <Empty description="没有符合条件的素材,换个筛选或去采集工作台采一次" style={{ padding: 60 }} />
      ) : (
        <>
          <List
            dataSource={data.items}
            renderItem={(item) => (
              <List.Item style={{ padding: 0, border: 'none', marginBottom: 12 }}>
                <Card
                  size="small"
                  className="item-card"
                  style={{ width: '100%' }}
                  onClick={() => setActiveItemId(item.id)}
                  styles={{ body: { padding: 16 } }}
                >
                  <div className="item-title">{item.translated_title || item.title}</div>
                  {item.translated_title && item.translated_title !== item.title && (
                    <div style={{ color: '#aaa', fontSize: 12, marginBottom: 6 }}>{item.title}</div>
                  )}
                  <div className="item-meta">
                    {CONTENT_TYPE_META[item.content_type]?.label ?? item.content_type} ·{' '}
                    {item.source_name ?? item.channel} ·{' '}
                    {formatRelative(item.published_at ?? item.first_seen_at)}
                    {item.author ? ` · ${item.author}` : ''}
                  </div>
                  {(item.collect_name || item.keyword_hits.length > 0) && (
                    <Space wrap size={4} style={{ marginBottom: 6 }}>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        采集来源:
                      </Typography.Text>
                      {item.collect_name && (
                        <Tag color="geekblue" style={{ marginInlineEnd: 0 }}>
                          {item.collect_name}
                        </Tag>
                      )}
                      {(item.collect_keywords.length ? item.collect_keywords : item.keyword_hits)
                        .slice(0, 3)
                        .map((word) => (
                          <Tag key={word} style={{ marginInlineEnd: 0 }}>
                            {word}
                          </Tag>
                        ))}
                      {item.keyword_hits.length > 0 &&
                        item.collect_keywords.length > 0 &&
                        !item.collect_keywords.some((word) => item.keyword_hits.includes(word)) && (
                          <Tag color="blue" style={{ marginInlineEnd: 0 }}>
                            命中 {item.keyword_hits.slice(0, 2).join(' / ')}
                          </Tag>
                        )}
                      {item.origin === 'backfill' && (
                        <Tag color="gold" style={{ marginInlineEnd: 0 }}>
                          辐射词补采
                        </Tag>
                      )}
                    </Space>
                  )}
                  {item.summary && (
                    <div
                      className="item-summary"
                      style={{
                        display: '-webkit-box',
                        WebkitLineClamp: 2,
                        WebkitBoxOrient: 'vertical',
                        overflow: 'hidden',
                      }}
                    >
                      {item.summary}
                    </div>
                  )}
                  <Space wrap size={4}>
                    <Tag color={scoreColor(item.score?.total)}>总分 {item.score?.total ?? '-'}</Tag>
                    <Tag>相关 {item.score?.relevance ?? '-'}</Tag>
                    <Tag>热度 {item.score?.heat ?? '-'}</Tag>
                    <Tag>时效 {item.score?.freshness ?? '-'}</Tag>
                    {item.channel === 'github' && <Tag color="geekblue">GitHub</Tag>}
                  </Space>
                </Card>
              </List.Item>
            )}
          />
          <div style={{ textAlign: 'right' }}>
            <Pagination
              current={page}
              total={data.total}
              pageSize={PAGE_SIZE}
              showSizeChanger={false}
              onChange={setPage}
            />
          </div>
        </>
      )}

      <ItemDetailDrawer itemId={activeItemId} onClose={() => setActiveItemId(null)} />
    </div>
  )
}
