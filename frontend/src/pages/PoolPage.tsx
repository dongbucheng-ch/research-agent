import { Tabs, Typography } from 'antd'
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

  return (
    <div>
      <Typography.Title level={4} style={{ margin: 0 }}>
        素材池
      </Typography.Title>
      <Typography.Text type="secondary" style={{ fontSize: 13 }}>
        采集入库的原始素材(资讯 / 论文 / GitHub)与由素材生成的产出物(日报 / 完整文章),素材可反查引用它的产出物。
      </Typography.Text>
      <Tabs
        style={{ marginTop: 8 }}
        activeKey={tab}
        onChange={(key) => {
          const next = new URLSearchParams(params)
          next.set('tab', key)
          next.delete('kind')
          next.delete('id')
          setParams(next, { replace: true })
        }}
        items={[
          { key: 'material', label: '素材', children: <MaterialTab /> },
          {
            key: 'digest',
            label: '日报',
            children: <DigestPanel focusId={tab === 'digest' ? focusId : null} />,
          },
          {
            key: 'article',
            label: '文章',
            children: <ArticlePanel focusId={tab === 'article' ? focusId : null} />,
          },
        ]}
      />
    </div>
  )
}
