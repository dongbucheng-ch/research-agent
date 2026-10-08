import {
  ApiOutlined,
  InboxOutlined,
  PlayCircleOutlined,
  SettingOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { Layout, Menu } from 'antd'
import { Link, Outlet, useLocation } from 'react-router-dom'

const SIDER_WIDTH = 216

const items = [
  { key: '/collect', icon: <PlayCircleOutlined />, label: <Link to="/collect">采集工作台</Link> },
  { key: '/pool', icon: <InboxOutlined />, label: <Link to="/pool">素材池</Link> },
  { key: '/sources', icon: <ApiOutlined />, label: <Link to="/sources">信源池</Link> },
  { key: '/jobs', icon: <ThunderboltOutlined />, label: <Link to="/jobs">任务中心</Link> },
  { key: '/settings', icon: <SettingOutlined />, label: <Link to="/settings">设置</Link> },
]

export default function AppLayout() {
  const location = useLocation()
  const selected =
    items.find((item) => location.pathname.startsWith(item.key))?.key ?? '/collect'
  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Sider
        theme="light"
        width={SIDER_WIDTH}
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
        <div className="app-brand">🛰️ research-agent</div>
        <Menu mode="inline" selectedKeys={[selected]} items={items} style={{ borderInlineEnd: 0 }} />
      </Layout.Sider>
      <Layout style={{ marginInlineStart: SIDER_WIDTH, minHeight: '100vh' }}>
        <Layout.Content>
          <div className="page-body">
            <Outlet />
          </div>
        </Layout.Content>
      </Layout>
    </Layout>
  )
}
