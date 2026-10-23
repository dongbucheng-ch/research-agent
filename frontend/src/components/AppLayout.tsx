import {
  ApiOutlined,
  InboxOutlined,
  PlayCircleOutlined,
  SettingOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { Badge, Breadcrumb, Layout, Menu } from 'antd'
import type { MenuProps } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, Outlet, useLocation } from 'react-router-dom'
import { version as appVersion } from '../../package.json'
import { api } from '../api/client'
import type { Stats } from '../api/types'
import BrandMark from './BrandMark'

const SIDER_WIDTH = 216
const SIDER_COLLAPSED_WIDTH = 64
const COLLAPSE_QUERY = '(max-width: 1199px)'
const STATS_REFETCH_MS = 30_000

interface NavEntry {
  path: string
  label: string
  icon: ReactNode
  /** 角标语义：info=进行中/待处理（数量型角标已移除，避免菜单栏噪声） */
  badge?: 'info'
  /** 二级导航（页签级），path 带查询串以便直接定位到某个页签 */
  children?: NavChild[]
}

interface NavChild {
  path: string
  label: string
}

const BADGE_META = {
  info: { color: '#1677ff', className: 'app-nav-badge-info' },
} as const

interface NavGroup {
  key: string
  label: string
  entries: NavEntry[]
}

const NAV_GROUPS: NavGroup[] = [
  {
    key: 'workbench',
    label: '工作台',
    entries: [
      { path: '/collect', label: '采集工作台', icon: <PlayCircleOutlined /> },
      {
        path: '/pool',
        label: '素材池',
        icon: <InboxOutlined />,
        children: [
          { path: '/pool?tab=material', label: '素材' },
          { path: '/pool?tab=digest', label: '日报' },
          { path: '/pool?tab=article', label: '文章' },
        ],
      },
      { path: '/sources', label: '信源池', icon: <ApiOutlined /> },
    ],
  },
  {
    key: 'ops',
    label: '运维',
    entries: [
      { path: '/jobs', label: '任务中心', icon: <ThunderboltOutlined />, badge: 'info' },
      { path: '/settings', label: '设置', icon: <SettingOutlined /> },
    ],
  },
]

/** 导航角标只表达「需要行动的信息」：运行中任务（素材池的当日新增数量不再上菜单）。 */
function badgeCount(path: string, stats?: Stats): number {
  if (!stats) return 0
  if (path === '/jobs') return stats.jobs_running
  return 0
}

/** 从二级项 path 里取 tab 参数,用于和当前 URL 比对 */
function tabOf(path: string): string | null {
  return new URLSearchParams(path.split('?')[1] ?? '').get('tab')
}

/**
 * 当前选中项:带二级的入口按「路径 + tab」匹配(忽略 id 等其它参数),
 * tab 缺失或为旧值(outputs)时按 PoolPage.resolveTab 的语义回退。
 */
function resolveSelection(pathname: string, search: string) {
  const params = new URLSearchParams(search)
  const raw = params.get('tab')
  const tab = raw === 'outputs' ? (params.get('kind') ?? 'digest') : raw
  for (const group of NAV_GROUPS) {
    for (const entry of group.entries) {
      if (!pathname.startsWith(entry.path)) continue
      if (!entry.children) return { entry, group, child: undefined }
      const child = entry.children.find((item) => tabOf(item.path) === tab) ?? entry.children[0]
      return { entry, group, child }
    }
  }
  return { entry: undefined, group: undefined, child: undefined }
}

function useCollapsedByViewport(): boolean {
  const [collapsed, setCollapsed] = useState(() => window.matchMedia(COLLAPSE_QUERY).matches)
  useEffect(() => {
    const query = window.matchMedia(COLLAPSE_QUERY)
    const onChange = (event: MediaQueryListEvent) => setCollapsed(event.matches)
    setCollapsed(query.matches)
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])
  return collapsed
}

export default function AppLayout() {
  const location = useLocation()
  const collapsed = useCollapsedByViewport()
  const { data: stats } = useQuery({
    queryKey: ['stats'],
    queryFn: () => api.get<Stats>('/stats/overview'),
    refetchInterval: STATS_REFETCH_MS,
  })

  const { entry: currentEntry, group: currentGroup, child: currentChild } = useMemo(
    () => resolveSelection(location.pathname, location.search),
    [location.pathname, location.search],
  )
  const selectedKey = currentChild?.path ?? currentEntry?.path ?? '/collect'
  const parentKey = currentEntry?.children ? currentEntry.path : undefined
  const [openKeys, setOpenKeys] = useState<string[]>(parentKey ? [parentKey] : [])
  // 进入二级页时自动展开所属分组;用户手动收起后不再强制打开
  useEffect(() => {
    if (parentKey) setOpenKeys((keys) => (keys.includes(parentKey) ? keys : [...keys, parentKey]))
  }, [parentKey])
  const crumbItems = [
    ...(currentGroup ? [{ title: currentGroup.label }] : []),
    ...(currentEntry ? [{ title: currentEntry.label }] : []),
    ...(currentChild ? [{ title: currentChild.label }] : []),
  ]

  const items: MenuProps['items'] = useMemo(
    () =>
      NAV_GROUPS.map((group) => ({
        type: 'group' as const,
        key: group.key,
        label: group.label,
        children: group.entries.map((entry) => {
          const count = badgeCount(entry.path, stats)
          const badge = entry.badge ? BADGE_META[entry.badge] : undefined
          const showBadge = count > 0 && badge !== undefined
          const base = {
            key: entry.path,
            icon: entry.icon,
            // 折叠态下 label 被隐藏，用角标语义类渲染「信息点」
            className: showBadge ? badge.className : undefined,
            // 折叠态由 AntD 渲染 tooltip；展开态传 undefined 以避免冗余提示
            title: collapsed ? entry.label : undefined,
          }
          const badgeNode = showBadge ? (
            <Badge count={count} size="small" color={badge.color} />
          ) : null
          if (!entry.children) {
            return {
              ...base,
              label: (
                <Link to={entry.path} className="app-nav-link">
                  <span className="app-nav-label">{entry.label}</span>
                  {badgeNode}
                </Link>
              ),
            }
          }
          return {
            ...base,
            // 有二级时父项只负责展开/收起,不发跳转,避免「点一下既跳转又展开」
            label: (
              <span className="app-nav-link">
                <span className="app-nav-label">{entry.label}</span>
                {badgeNode}
              </span>
            ),
            children: entry.children.map((child) => ({
              key: child.path,
              label: (
                <Link to={child.path} className="app-nav-link">
                  <span className="app-nav-label">{child.label}</span>
                </Link>
              ),
            })),
          }
        }),
      })),
    [collapsed, stats],
  )

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Sider
        theme="light"
        width={SIDER_WIDTH}
        collapsedWidth={SIDER_COLLAPSED_WIDTH}
        collapsed={collapsed}
        trigger={null}
        className="app-sider"
        style={{
          position: 'fixed',
          insetInlineStart: 0,
          top: 0,
          bottom: 0,
          height: '100vh',
          overflow: 'auto',
        }}
      >
        <div className="app-brand">
          <BrandMark className="app-brand-mark" />
          <span className="app-brand-text">research-agent</span>
          <span className="app-brand-version">v{appVersion}</span>
        </div>
        <Menu
          mode="inline"
          theme="light"
          inlineCollapsed={collapsed}
          selectedKeys={[selectedKey]}
          // 折叠态下 AntD 自行管理（弹出面板），受控 openKeys 只在展开态生效
          {...(collapsed ? {} : { openKeys, onOpenChange: (keys: string[]) => setOpenKeys(keys) })}
          items={items}
          style={{ borderInlineEnd: 0 }}
        />
      </Layout.Sider>
      <Layout
        style={{
          marginInlineStart: collapsed ? SIDER_COLLAPSED_WIDTH : SIDER_WIDTH,
          minHeight: '100vh',
        }}
      >
        <Layout.Content>
          {crumbItems.length > 0 && (
            <Breadcrumb className="app-crumb-bar" separator="/" items={crumbItems} />
          )}
          <div className="page-body">
            <Outlet />
          </div>
        </Layout.Content>
      </Layout>
    </Layout>
  )
}
