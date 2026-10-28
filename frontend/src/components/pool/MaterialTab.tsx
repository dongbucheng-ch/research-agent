import { CopyOutlined, FileTextOutlined, FilterOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import {
  Button,
  Empty,
  Input,
  Pagination,
  Popover,
  Segmented,
  Select,
  Skeleton,
  Spin,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import dayjs from 'dayjs'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, toQuery } from '../../api/client'
import type { Item, Page, Source, Stats } from '../../api/types'
import { CONTENT_TYPE_META, dayLabel, formatRelative } from '../../utils'
import ItemDetailDrawer from '../ItemDetailDrawer'

const PAGE_SIZE = 20
/** 卡片流一次给几张骨架,和首屏列数对齐(宽屏两列、手机一列) */
const SKELETON_CARDS = 4

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

/** 默认排序:最新高分——最新的收录日在前,同一天里综合分高的在前 */
const DEFAULT_SORT = 'smart'

const SORT_OPTIONS = [
  { value: 'smart', label: '最新高分' },
  { value: 'score', label: '按综合分' },
  { value: 'recent', label: '按收录时间' },
  { value: 'published', label: '按发布时间' },
]

/** ≤3 天视为「新」,用一处品牌蓝把时效突出,而不是让所有元信息一样灰 */
const FRESH_HOURS = 72

/** 低分才在卡片上常驻警示;<65 是真正的例外(全库约 11%),高分交给排序与悬停 */
const LOW_SCORE = 65

const SCORE_FIELDS = [
  { key: 'relevance', label: '相关' },
  { key: 'heat', label: '热度' },
  { key: 'freshness', label: '时效' },
] as const

const num = (value: unknown) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

const fmtScore = (value: unknown, digits = 1) => {
  const parsed = num(value)
  return parsed === null ? '-' : parsed.toFixed(digits)
}

/** 复制到剪贴板:优先 clipboard API,非安全上下文/无焦点时退回 execCommand */
async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    /* 继续走兜底 */
  }
  try {
    const area = document.createElement('textarea')
    area.value = text
    area.setAttribute('readonly', '')
    area.style.position = 'fixed'
    area.style.top = '-1000px'
    document.body.appendChild(area)
    area.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(area)
    return ok
  } catch {
    return false
  }
}

function isFresh(item: Item) {
  const raw = item.published_at ?? item.first_seen_at
  if (!raw) return false
  const diff = Date.now() - new Date(raw).getTime()
  return diff >= 0 && diff <= FRESH_HOURS * 3600 * 1000
}

export default function MaterialTab() {
  const [params, setParams] = useSearchParams()
  const [activeItemId, setActiveItemId] = useState<number | null>(null)

  // 筛选状态全部落在 URL 上:刷新、分享、后退都能回到同一屏(与信源池深链一致)
  const engine = params.get('engine') ?? ''
  const contentType = params.get('type') ?? undefined
  const sourceId = Number(params.get('source_id')) || undefined
  const minScoreRaw = params.get('min_score')
  const minScore = minScoreRaw ? Number(minScoreRaw) : undefined
  const sort = params.get('sort') ?? DEFAULT_SORT
  const search = params.get('q') ?? ''
  const page = Number(params.get('page')) || 1

  const patchParams = useCallback(
    (patch: Record<string, string | number | undefined>) => {
      const next = new URLSearchParams(params)
      for (const [key, value] of Object.entries(patch)) {
        if (value === undefined || value === '') next.delete(key)
        else next.set(key, String(value))
      }
      if (next.toString() !== params.toString()) setParams(next, { replace: true })
    },
    [params, setParams],
  )

  /** 关键词输入:本地立即可见,300ms 后才落到 URL 与请求 */
  const [searchInput, setSearchInput] = useState(search)
  useEffect(() => {
    setSearchInput(search)
  }, [search])
  useEffect(() => {
    const handle = window.setTimeout(() => {
      if (searchInput.trim() === search) return
      patchParams({ q: searchInput.trim() || undefined, page: undefined })
    }, 300)
    return () => window.clearTimeout(handle)
  }, [searchInput, search, patchParams])

  /** 换筛选或翻页后回到列表顶部,避免停在上一条信息的中段 */
  const bodyRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    bodyRef.current?.scrollTo({ top: 0 })
  }, [contentType, engine, sourceId, minScore, search, sort, page])

  const { data: stats } = useQuery({
    queryKey: ['stats'],
    queryFn: () => api.get<Stats>('/stats/overview'),
  })
  const { data: sources } = useQuery({
    queryKey: ['sources'],
    queryFn: () => api.get<Source[]>('/sources'),
  })
  const { data, isPending, isFetching } = useQuery({
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

  const sourceOptions = useMemo(
    () =>
      (sources ?? [])
        .filter((source) => !engine || (ENGINE_CHANNELS[engine] ?? []).includes(source.channel))
        .map((source) => ({ value: source.id, label: `${source.name}(${source.channel})` })),
    [sources, engine],
  )
  const sourceLabel = sourceOptions.find((option) => option.value === sourceId)?.label

  /** 已选条件:一行 chip,可单删也可一键清空(替代 6 个控件的来回找) */
  const chips = [
    contentType
      ? {
          key: 'type',
          label: `类型:${CONTENT_TYPE_META[contentType]?.label ?? contentType}`,
          clear: () => patchParams({ type: undefined, page: undefined }),
        }
      : null,
    sourceId
      ? {
          key: 'source',
          label: `信源:${sourceLabel ?? sourceId}`,
          clear: () => patchParams({ source_id: undefined, page: undefined }),
        }
      : null,
    minScore
      ? {
          key: 'score',
          label: `≥ ${minScore} 分`,
          clear: () => patchParams({ min_score: undefined, page: undefined }),
        }
      : null,
    search
      ? {
          key: 'q',
          label: `关键词:${search}`,
          clear: () => {
            setSearchInput('')
            patchParams({ q: undefined, page: undefined })
          },
        }
      : null,
  ].filter((chip): chip is { key: string; label: string; clear: () => void } => chip !== null)

  const clearAll = () => {
    setSearchInput('')
    patchParams({
      engine: undefined,
      type: undefined,
      source_id: undefined,
      min_score: undefined,
      sort: undefined,
      q: undefined,
      page: undefined,
    })
  }

  const items = data?.items ?? []
  const filterCount = chips.length

  /** 日期分组只跟「按日期排」的两种排序走:按综合分 / 按发布时间时同一日期散落在列表各处,
     十几条重复的日期头只会变成噪音,也说明不了顺序。 */
  const dateOrdered = sort === 'smart' || sort === 'recent'

  /** 按「收录日」分组:与默认排序(最新收录日在前、同日按分)同一把尺子,列表自己解释得通 */
  const dayGroups = useMemo(() => {
    const groups: { date: string; items: Item[] }[] = []
    for (const item of items) {
      const date = dayjs(item.first_seen_at).format('YYYY-MM-DD')
      const last = groups[groups.length - 1]
      if (last && last.date === date) last.items.push(item)
      else groups.push({ date, items: [item] })
    }
    return groups
  }, [items])

  const copyLink = async (item: Item) => {
    if (await copyText(item.url)) message.success('链接已复制')
    else message.warning('复制失败,请手动打开原文')
  }

  const openOriginal = (item: Item) => {
    window.open(item.url, '_blank', 'noopener,noreferrer')
  }

  /** 单张素材卡:点卡片去原文;右上角两个图标进详情、复制链接 */
  const renderCard = (item: Item) => {
    const total = num(item.score?.total)
    const fresh = isFresh(item)
    const lowScore = total !== null && total < LOW_SCORE
    const scoreText = `综合分 ${fmtScore(total, 1)} · ${SCORE_FIELDS.map(
      ({ key, label }) => `${label} ${fmtScore(item.score?.[key], 0)}`,
    ).join(' · ')}`
    const keywordSource = item.collect_keywords.length ? item.collect_keywords : item.keyword_hits
    const keywords = keywordSource.slice(0, 2)
    const folded = [
      ...keywordSource.slice(2),
      ...item.keyword_hits
        .filter((word) => !item.collect_keywords.includes(word))
        .map((word) => `命中 ${word}`),
      ...(item.origin === 'backfill' ? ['辐射词补采'] : []),
    ]
    return (
      <article
        key={item.id}
        className="mat-card"
        role="button"
        tabIndex={0}
        aria-label={item.translated_title || item.title}
        onClick={() => openOriginal(item)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            openOriginal(item)
          }
        }}
      >
        <div className="mat-main">
          <div className="mat-head">
            <div className="mat-title">{item.translated_title || item.title}</div>
            <div className="mat-actions">
              <Tooltip title="查看详情">
                <Button
                  type="text"
                  size="small"
                  className="mat-icon-btn"
                  aria-label="查看详情"
                  icon={<FileTextOutlined />}
                  onClick={(event) => {
                    event.stopPropagation()
                    setActiveItemId(item.id)
                  }}
                />
              </Tooltip>
              <Tooltip title="复制链接">
                <Button
                  type="text"
                  size="small"
                  className="mat-icon-btn"
                  aria-label="复制链接"
                  icon={<CopyOutlined />}
                  onClick={(event) => {
                    event.stopPropagation()
                    void copyLink(item)
                  }}
                />
              </Tooltip>
            </div>
          </div>
          {item.translated_title && item.translated_title !== item.title && (
            <div className="mat-orig" title={item.title}>
              {item.title}
            </div>
          )}
          {/* 元信息两格:左边是人读得懂的「类型 / 来源 / 作者」,右边是排序用的两个数(分数、时间),右对齐成一列 */}
          <div className="mat-meta">
            <span className="mat-meta-facts">
              <span>{CONTENT_TYPE_META[item.content_type]?.label ?? item.content_type}</span>
              <span className="mat-source">{item.source_name ?? item.channel}</span>
              {item.author && <span className="mat-author">{item.author}</span>}
            </span>
            <span className="mat-meta-right">
              {total !== null && (
                <Tooltip title={scoreText}>
                  <span className={lowScore ? 'mat-score is-low' : 'mat-score'}>
                    {fmtScore(total, 1)}
                  </span>
                </Tooltip>
              )}
              <span className={fresh ? 'mat-time is-fresh' : 'mat-time'}>
                {formatRelative(item.published_at ?? item.first_seen_at)}
              </span>
            </span>
          </div>
          {(item.collect_name || keywords.length > 0) && (
            <div className="mat-tags">
              {item.collect_name && <Tag color="geekblue">{item.collect_name}</Tag>}
              {keywords.map((word, index) => (
                <Tag key={`${word}-${index}`}>{word}</Tag>
              ))}
              {folded.length > 0 && (
                <Tooltip title={folded.join(' · ')}>
                  <Tag className="mat-tag-more">+{folded.length}</Tag>
                </Tooltip>
              )}
            </div>
          )}
          {item.summary && <p className="mat-summary">{item.summary}</p>}
        </div>
      </article>
    )
  }

  const filterPanel = (
    <div className="mat-filter-form">
      <label>
        <span>内容类型</span>
        <Select
          allowClear
          placeholder="不限"
          value={contentType}
          onChange={(value) => patchParams({ type: value, page: undefined })}
          options={Object.entries(CONTENT_TYPE_META).map(([value, meta]) => ({
            value,
            label: meta.label,
          }))}
        />
      </label>
      <label>
        <span>具体信源</span>
        <Select
          allowClear
          showSearch
          optionFilterProp="label"
          placeholder="不限"
          value={sourceId}
          onChange={(value) => patchParams({ source_id: value, page: undefined })}
          options={sourceOptions}
        />
      </label>
      <label>
        <span>最低分</span>
        <Select
          allowClear
          placeholder="不限"
          value={minScore}
          onChange={(value) => patchParams({ min_score: value, page: undefined })}
          options={[50, 60, 70, 80].map((value) => ({ value, label: `≥ ${value} 分` }))}
        />
      </label>
    </div>
  )

  return (
    <div className="mat-page">
      <div className="mat-toolbar">
        <div className="mat-toolbar-row">
          <Segmented
            className="mat-engine"
            value={engine}
            onChange={(value) => patchParams({ engine: String(value) || undefined, source_id: undefined, page: undefined })}
            options={ENGINE_OPTIONS}
          />
          <Input.Search
            className="mat-search"
            allowClear
            placeholder="搜索标题 / 摘要"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
          />
          <span className="mat-toolbar-gap" />
          {/* 排序常驻工具条:默认「最新高分」,一眼看得出这屏是按什么排的 */}
          <Tooltip title="最新的收录日在前,同一天里按综合分从高到低">
            <span className="mat-sort">
              <span className="mat-sort-label">排序</span>
              <Select
                className="mat-sort-select"
                value={sort}
                onChange={(value) => patchParams({ sort: value, page: undefined })}
                options={SORT_OPTIONS}
                popupMatchSelectWidth={150}
              />
            </span>
          </Tooltip>
          <Popover trigger="click" placement="bottomRight" content={filterPanel} arrow={false}>
            <Button icon={<FilterOutlined />} className={filterCount ? 'mat-filter-on' : undefined}>
              筛选{filterCount ? ` · ${filterCount}` : ''}
            </Button>
          </Popover>
          {/* 两份数据到齐才显示,宽度固定:数字出现时不会把「排序」「筛选」推来推去 */}
          <Typography.Text className="mat-count">
            {data && stats ? (
              <span className="mat-count-cells">
                <span>
                  匹配 <b>{data.total}</b> / 全库 {stats.items_total}
                </span>
                <span>
                  今日 <b>+{stats.items_today}</b>
                </span>
              </span>
            ) : (
              '\u00A0'
            )}
          </Typography.Text>
        </div>
        {/* 常驻一行:有筛选时放 chip,没有时留白,避免工具条高度变化带动卡片位移 */}
        <div className="mat-chips">
          {chips.map((chip) => (
            <Tag key={chip.key} closable onClose={chip.clear} className="mat-chip">
              {chip.label}
            </Tag>
          ))}
          {filterCount > 0 && (
            <Button type="link" size="small" onClick={clearAll}>
              清空全部
            </Button>
          )}
        </div>
      </div>

      <div className="mat-body" ref={bodyRef}>
        <Spin spinning={isFetching}>
          {isPending ? (
            /* 加载态按「即将出现的形状」给骨架:几张和真实卡片同形的占位 */
            <div className="mat-grid" aria-busy="true" aria-label="素材加载中">
              {Array.from({ length: SKELETON_CARDS }, (_, index) => (
                <div className="mat-card mat-skeleton-card" key={index}>
                  <Skeleton active title={{ width: '58%' }} paragraph={{ rows: 3 }} />
                </div>
              ))}
            </div>
          ) : items.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={
                <div className="mat-empty-copy">
                  <div className="mat-empty-title">没有符合条件的素材</div>
                  <div className="mat-empty-hint">
                    {filterCount > 0
                      ? '删掉一两个筛选条件,或清空全部再看。'
                      : '去采集工作台采一次,素材会出现在这里。'}
                  </div>
                </div>
              }
            />
          ) : (
            <div className="mat-grid">
              {/* 分组头与卡片拍平成同一层、每个子节点都带 key:换排序或翻页时 React 才能收掉上一批节点 */}
              {dayGroups.flatMap((group, index) => {
                const cards = group.items.map((item) => renderCard(item))
                if (!dateOrdered) return cards
                return [
                  /* 分组头:今天 / 昨天 / 日期,与产出物选择器同一套说法 */
                  <div className="mat-day" key={`day-${index}-${group.date}`}>
                    {dayLabel(group.date)}
                  </div>,
                  ...cards,
                ]
              })}
            </div>
          )}
        </Spin>
      </div>

      <div className="mat-footer">
        <Pagination
          current={page}
          total={data?.total ?? 0}
          pageSize={PAGE_SIZE}
          showSizeChanger={false}
          onChange={(nextPage) => patchParams({ page: nextPage > 1 ? nextPage : undefined })}
        />
      </div>

      <ItemDetailDrawer itemId={activeItemId} onClose={() => setActiveItemId(null)} />
    </div>
  )
}
