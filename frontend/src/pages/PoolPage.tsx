import { useSearchParams } from 'react-router-dom'
import ArticlePanel from '../components/pool/ArticlePanel'
import DigestPanel from '../components/pool/DigestPanel'
import MaterialTab from '../components/pool/MaterialTab'

const TAB_KEYS = ['material', 'digest', 'article'] as const
type TabKey = (typeof TAB_KEYS)[number]

/** 旧深链 `/pool?tab=outputs&kind=digest|article` 映射到新 tab(保持兼容)。 */
function resolveTab(params: URLSearchParams): TabKey {
  const tab = params.get('tab')
  if (tab === 'outputs') return params.get('kind') === 'article' ? 'article' : 'digest'
  return (TAB_KEYS as readonly string[]).includes(tab ?? '') ? (tab as TabKey) : 'material'
}

export default function PoolPage() {
  const [params, setParams] = useSearchParams()
  const tab = resolveTab(params)
  const focusId = Number(params.get('id')) || null

  /**
   * 子页签内选择回写 URL:刷新/分享/后退都能回到同一条。
   * replace=true 用于键盘预览(不新增历史项),点击与回车走历史项。
   */
  const selectOutput = (id: number | null, options?: { replace?: boolean }) => {
    const next = new URLSearchParams(params)
    next.set('tab', tab)
    next.delete('kind')
    if (id === null) next.delete('id')
    else next.set('id', String(id))
    if (next.toString() === params.toString()) return
    setParams(next, { replace: options?.replace ?? false })
  }

  // 页签切换由左侧栏二级菜单驱动(路由 + ?tab=),这里只按参数渲染对应面板
  return (
    <div className="pool-page">
      {/* 素材页自己读写 URL 里的筛选参数(含 source_id 深链),这里不再中转 */}
      {tab === 'material' ? <MaterialTab /> : null}
      {tab === 'digest' ? <DigestPanel focusId={focusId} onSelect={selectOutput} /> : null}
      {tab === 'article' ? <ArticlePanel focusId={focusId} onSelect={selectOutput} /> : null}
    </div>
  )
}
