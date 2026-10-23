import { LinkOutlined, RightOutlined, UnorderedListOutlined, UpOutlined } from '@ant-design/icons'
import { Button, List, Tooltip } from 'antd'
import dayjs from 'dayjs'
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import type { Item } from '../../api/types'
import { scoreColor } from '../../utils'

/** 信息栏每个分档默认展示条数(控制在右卡首屏内,其余靠「展开」按钮展开) */
export const RAIL_TIER_PREVIEW = { focus: 3, normal: 3 } as const

/** 分档阈值:≥80 为主看对象,其余归入常规范例 */
export const RAIL_FOCUS_SCORE = 80

/** 素材在正文里的引用情况:出现次数 + 首个被引小节 + 引用序号 */
export interface RailCitation {
  count: number
  section: string | null
  /** 文章正文用 [n] 编号引用:徽标上标出同一序号,顺着正文能对上 */
  ref?: number
}

type RailRow =
  | { kind: 'group'; key: 'focus' | 'normal'; label: string; count: number }
  | { kind: 'item'; key: string; tier: 'focus' | 'normal'; item: Item }

/** 信息栏素材副信息:来源 · 月日(优先发布时间,缺省回落到首次采集时间) */
export function materialMeta(item: Item): string {
  const source = item.source_name ?? item.channel
  const date = item.published_at ?? item.first_seen_at
  return date ? `${source} · ${dayjs(date).format('M月D日')}` : source
}

export function materialTitle(item: Item): string {
  return item.translated_title || item.title
}

/**
 * 日报:素材以 `[标题](url)` 出现在正文里,所以按 url 计数;
 * 小节名取自该 url 之前最后一个 `## ` / `### ` 标题,用于徽标点击回跳正文。
 */
export function citationByUrl(markdown: string, url?: string | null): RailCitation {
  if (!markdown || !url) return { count: 0, section: null }
  const first = markdown.indexOf(url)
  if (first < 0) return { count: 0, section: null }
  let count = 0
  let from = 0
  for (;;) {
    const at = markdown.indexOf(url, from)
    if (at < 0) break
    count += 1
    from = at + url.length
  }
  return { count, section: sectionBefore(markdown, first) }
}

/**
 * 文章:正文用 `[n]` 编号引用(n = 素材在 source_item_ids 里的顺序,与参考文献列表一致),
 * 所以按编号计数;`(?!\d)` 保证 [1] 不会误配到 [10] 的前半段。
 */
export function citationByRef(markdown: string, ref: number): RailCitation {
  if (!markdown) return { count: 0, section: null, ref }
  const pattern = new RegExp(`\\[${ref}\\](?!\\d)`, 'g')
  const matches = [...markdown.matchAll(pattern)]
  if (matches.length === 0) return { count: 0, section: null, ref }
  const first = matches[0].index ?? 0
  return { count: matches.length, section: sectionBefore(markdown, first), ref }
}

/** 取偏移量之前最后一个二/三级标题:### 是具体条目,比只认 ## 更精确 */
function sectionBefore(markdown: string, index: number): string | null {
  const heads = [...markdown.slice(0, index).matchAll(/^#{2,3}\s+(.+)$/gm)]
  return heads.length > 0 ? heads[heads.length - 1][1].trim() : null
}

/** 素材分档:重点(≥阈值)在前、常规在后,档内按分数降序,避免 11 条同权重流水 */
export function groupByTier(items: Item[]): { key: 'focus' | 'normal'; items: Item[] }[] {
  const focus: Item[] = []
  const normal: Item[] = []
  for (const item of items) {
    if ((item.score?.total ?? 0) >= RAIL_FOCUS_SCORE) focus.push(item)
    else normal.push(item)
  }
  const byScore = (a: Item, b: Item) => (b.score?.total ?? 0) - (a.score?.total ?? 0)
  focus.sort(byScore)
  normal.sort(byScore)
  return [
    { key: 'focus' as const, items: focus },
    { key: 'normal' as const, items: normal },
  ].filter((tier) => tier.items.length > 0)
}

/** 引用徽标:先切回预览,再把对应小节滚进卡片视口(吸顶头靠 scroll-margin 让位) */
function jumpToSection(section: string) {
  const find = () => {
    const heads = document.querySelectorAll<HTMLElement>(
      '.output-card .output-preview h2, .output-card .output-preview h3',
    )
    const target = [...heads].find((el) => (el.textContent ?? '').trim() === section)
    target?.scrollIntoView({ block: 'start', behavior: 'smooth' })
  }
  // 切模式后正文要重渲染,等两帧再找标题
  window.requestAnimationFrame(() => window.requestAnimationFrame(find))
}

interface Props {
  items: Item[]
  /** 每条素材的引用信息(按素材 id 索引);缺省或 count=0 时不渲染徽标 */
  citations?: Map<number, RailCitation>
  /** 切换产出物时把「展开全部」收回折叠态 */
  resetKey?: number | string | null
  /** 抽屉打开的那条:行保持淡蓝高亮,长列表里不丢位置 */
  activeItemId?: number | null
  onOpenItem: (id: number) => void
  /** 徽标回跳前把视图切回预览(源码/JSON 模式下正文不在 DOM 里) */
  onEnsurePreview?: () => void
  /** 素材列表上方的模块:推送记录、关键词等 */
  top?: ReactNode
  emptyText?: string
}

/**
 * 产出物右侧信息栏:推送/元信息 + 素材来源(分档、引用徽标、折叠展开)。
 * 日报与文章共用同一套版式,只在数据来源上不同。
 */
export default function OutputRail({
  items,
  citations,
  resetKey,
  activeItemId,
  onOpenItem,
  onEnsurePreview,
  top,
  emptyText = '这条产出物没有关联到素材记录',
}: Props) {
  const [railExpanded, setRailExpanded] = useState(false)

  // 切换产出物后回到「只列前 N 条」
  useEffect(() => {
    setRailExpanded(false)
  }, [resetKey])

  const tiers = useMemo(() => groupByTier(items), [items])
  const total = items.length
  /** 折叠态实际展示条数(按各档真实条数取 min,避免档内不足时高估) */
  const shownTotal = tiers.reduce(
    (sum, tier) => sum + Math.min(tier.items.length, RAIL_TIER_PREVIEW[tier.key]),
    0,
  )
  const hidden = total - shownTotal
  const rows = useMemo(() => {
    const result: RailRow[] = []
    for (const tier of tiers) {
      result.push({
        kind: 'group',
        key: tier.key,
        label: tier.key === 'focus' ? `重点 ≥${RAIL_FOCUS_SCORE}` : `常规 <${RAIL_FOCUS_SCORE}`,
        count: tier.items.length,
      })
      const shown = railExpanded ? tier.items : tier.items.slice(0, RAIL_TIER_PREVIEW[tier.key])
      for (const item of shown) {
        result.push({ kind: 'item', key: `item-${item.id}`, tier: tier.key, item })
      }
    }
    return result
  }, [tiers, railExpanded])

  const jump = useCallback(
    (citation: RailCitation) => {
      if (!citation.section) return
      onEnsurePreview?.()
      jumpToSection(citation.section)
    },
    [onEnsurePreview],
  )

  return (
    <aside className="output-detail-rail">
      <section className="output-rail-section">
        {top}
        <div className="output-rail-divider" />
        <div className="output-rail-title">
          素材来源
          <span className="output-rail-count">({total} 条)</span>
        </div>
        <div className="output-rail-list">
          <List
            size="small"
            split={false}
            dataSource={rows}
            locale={{ emptyText }}
            renderItem={(row) => {
              if (row.kind === 'group') {
                return (
                  <List.Item key={row.key} className="output-rail-group-head">
                    <span className={`output-rail-group-dot is-${row.key}`} />
                    <span className="output-rail-group-label">{row.label}</span>
                    <span className="output-rail-group-count">
                      {railExpanded
                        ? `共 ${row.count} 条`
                        : `已显示 ${Math.min(row.count, RAIL_TIER_PREVIEW[row.key])}/${row.count}`}
                    </span>
                  </List.Item>
                )
              }
              const cite = citations?.get(row.item.id)
              return (
                <List.Item
                  key={row.key}
                  className={`output-rail-item is-${row.tier}${
                    activeItemId === row.item.id ? ' is-active' : ''
                  }`}
                  onClick={() => onOpenItem(row.item.id)}
                >
                  <div className="output-rail-item-body">
                    <div className="output-rail-item-head">
                      <Tooltip title={materialTitle(row.item)} mouseEnterDelay={0.4}>
                        <span className="output-rail-item-title">{materialTitle(row.item)}</span>
                      </Tooltip>
                      {cite && cite.count > 0 ? (
                        <button
                          type="button"
                          className="rail-cite"
                          disabled={!cite.section}
                          title={
                            cite.section
                              ? `跳到「${cite.section}」`
                              : cite.ref
                                ? `正文引用了来源 [${cite.ref}]`
                                : '正文已引用'
                          }
                          onClick={(event) => {
                            event.stopPropagation()
                            jump(cite)
                          }}
                        >
                          <LinkOutlined />
                          {cite.ref ? `[${cite.ref}]×${cite.count}` : `×${cite.count}`}
                        </button>
                      ) : null}
                      <RightOutlined className="output-rail-item-arrow" />
                    </div>
                    <div className="output-rail-item-meta">
                      <span
                        className={`output-rail-item-score is-${scoreColor(row.item.score?.total)}`}
                      >
                        {row.item.score?.total ?? '-'}
                      </span>
                      <span className="output-rail-item-source">{materialMeta(row.item)}</span>
                    </div>
                  </div>
                </List.Item>
              )
            }}
          />
        </div>
        {hidden > 0 || railExpanded ? (
          <Button
            type="text"
            block
            className="rail-more-btn"
            onClick={() => setRailExpanded((value) => !value)}
          >
            <span className="rail-more-inner">
              <UnorderedListOutlined />
              <span className="rail-more-text">
                {railExpanded ? '收起' : `还有 ${hidden} 条 · 展开`}
              </span>
              {railExpanded ? <UpOutlined /> : <RightOutlined />}
            </span>
          </Button>
        ) : null}
      </section>
    </aside>
  )
}
