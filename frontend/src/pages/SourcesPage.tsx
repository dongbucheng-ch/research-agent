import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import { useMemo, useState } from 'react'
import { api } from '../api/client'
import type { DiscoverCandidate, DiscoverResult, RecommendedSource, Source, SourceStat } from '../api/types'
import { SOURCE_STATUS_META, formatTime } from '../utils'

const RECOMMEND_CATEGORY_META: Record<string, { label: string; color: string }> = {
  paper: { label: '论文·学术', color: 'purple' },
  lab: { label: '实验室·公司', color: 'blue' },
  blog: { label: '研究博客', color: 'cyan' },
  news: { label: '产业新闻', color: 'gold' },
  cn: { label: '中文资讯', color: 'geekblue' },
  bio: { label: '生物科技', color: 'green' },
  community: { label: '社区·榜单', color: 'default' },
  social: { label: 'X · 推文', color: 'magenta' },
  engineering: { label: '工程团队', color: 'orange' },
}

interface SourceFormValues {
  name: string
  channel: string
  collector_kind: string
  url: string
  config_text?: string
  tier: string
  enabled: boolean
  fetch_interval_minutes: number
}

export default function SourcesPage() {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<Source | null>(null)
  const [recommendOpen, setRecommendOpen] = useState(false)
  const [selectedKeys, setSelectedKeys] = useState<string[]>([])
  const [form] = Form.useForm<SourceFormValues>()
  const [discoverOpen, setDiscoverOpen] = useState(false)
  const [discoverUrl, setDiscoverUrl] = useState('')
  const [discoverResult, setDiscoverResult] = useState<DiscoverResult | null>(null)
  const [discoverSelected, setDiscoverSelected] = useState<string[]>([])
  const [discoverTier, setDiscoverTier] = useState('B')

  const { data: sources, isLoading } = useQuery({
    queryKey: ['sources'],
    queryFn: () => api.get<Source[]>('/sources'),
  })
  const [recommendCategory, setRecommendCategory] = useState<string | undefined>(undefined)
  const [sourceSearch, setSourceSearch] = useState('')
  const { data: recommended } = useQuery({
    queryKey: ['recommended-sources'],
    queryFn: () => api.get<RecommendedSource[]>('/sources/recommended'),
    enabled: recommendOpen,
  })
  const { data: sourceStats } = useQuery({
    queryKey: ['source-stats'],
    queryFn: () => api.get<SourceStat[]>('/sources/stats?days=30'),
  })
  const statById = new Map((sourceStats ?? []).map((row) => [row.source_id, row]))
  const importedNames = new Set((sources ?? []).map((source) => source.name))
  const visibleRecommended = (recommended ?? []).filter(
    (item) => !recommendCategory || item.category === recommendCategory,
  )

  const filteredSources = useMemo(() => {
    const query = sourceSearch.trim().toLowerCase()
    if (!query) return sources ?? []
    return (sources ?? []).filter((source) =>
      `${source.name} ${source.url} ${source.channel}`.toLowerCase().includes(query),
    )
  }, [sources, sourceSearch])

  const saveMutation = useMutation({
    mutationFn: (values: SourceFormValues) => {
      let config: Record<string, unknown> = {}
      if (values.config_text?.trim()) {
        try {
          config = JSON.parse(values.config_text)
        } catch {
          throw new Error('config 不是合法 JSON')
        }
      }
      const payload = { ...values, config, config_text: undefined }
      return editing ? api.put(`/sources/${editing.id}`, payload) : api.post('/sources', payload)
    },
    onSuccess: () => {
      message.success(editing ? '信源已更新' : '信源已创建')
      setOpen(false)
      queryClient.invalidateQueries({ queryKey: ['sources'] })
    },
    onError: (error: Error) => message.error(error.message),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.del(`/sources/${id}`),
    onSuccess: () => {
      message.success('已删除')
      queryClient.invalidateQueries({ queryKey: ['sources'] })
    },
  })

  const testMutation = useMutation({
    mutationFn: (id: number) => api.post<{ ok: boolean; items_found: number; sample: unknown[]; error?: string }>(`/sources/${id}/test`),
    onSuccess: (result, id) => {
      const source = sources?.find((item) => item.id === id)
      if (result.ok) {
        Modal.info({
          title: `测试通过:${source?.name} 抓到 ${result.items_found} 条`,
          width: 640,
          content: <pre style={{ maxHeight: 320, overflow: 'auto', fontSize: 12 }}>{JSON.stringify(result.sample, null, 2)}</pre>,
        })
      } else {
        Modal.error({ title: '测试失败', content: result.error ?? '未知错误' })
      }
    },
    onError: (error: Error) => message.error(error.message),
  })

  const importMutation = useMutation({
    mutationFn: () =>
      api.post<Source[]>('/sources/import-recommended', { keys: selectedKeys }),
    onSuccess: (created) => {
      message.success(`已导入 ${created.length} 个信源`)
      setRecommendOpen(false)
      setSelectedKeys([])
      queryClient.invalidateQueries({ queryKey: ['sources'] })
    },
    onError: (error: Error) => message.error(error.message),
  })

  const discoverMutation = useMutation({
    mutationFn: (url: string) => api.post<DiscoverResult>('/sources/discover', { url }),
    onSuccess: (result) => {
      setDiscoverResult(result)
      setDiscoverSelected(
        result.candidates.filter((item) => item.ok && !item.already_exists).map((item) => item.url),
      )
      if (result.candidates.length === 0) {
        message.info('未发现候选 Feed,可尝试 GitHub 仓库 / OPML 链接 / 博客首页 URL')
      }
    },
    onError: (error: Error) => message.error(error.message),
  })

  const importCandidatesMutation = useMutation({
    mutationFn: () =>
      api.post<Source[]>('/sources/import-candidates', {
        items: (discoverResult?.candidates ?? [])
          .filter((item) => discoverSelected.includes(item.url))
          .map((item) => ({ name: item.name, url: item.url, channel: 'rss', tier: discoverTier })),
      }),
    onSuccess: (created) => {
      message.success(`已导入 ${created.length} 个信源`)
      setDiscoverOpen(false)
      setDiscoverResult(null)
      setDiscoverSelected([])
      queryClient.invalidateQueries({ queryKey: ['sources'] })
    },
    onError: (error: Error) => message.error(error.message),
  })

  const openEditor = (source?: Source) => {
    setEditing(source ?? null)
    form.setFieldsValue(
      source
        ? {
            ...source,
            config_text: JSON.stringify(source.config ?? {}, null, 2),
          }
        : {
            name: '',
            url: '',
            channel: 'rss',
            collector_kind: 'stream',
            tier: 'B',
            enabled: true,
            fetch_interval_minutes: 60,
            config_text: undefined,
          },
    )
    setOpen(true)
  }

  return (
    <div>
      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          信源池
        </Typography.Title>
        <Space>
          <Input.Search
            allowClear
            placeholder="搜索名称 / URL / 渠道"
            style={{ width: 240 }}
            onChange={(event) => setSourceSearch(event.target.value)}
          />
          <Button
            onClick={() => {
              setDiscoverOpen(true)
              setDiscoverResult(null)
              setDiscoverSelected([])
            }}
          >
            信源发现
          </Button>
          <Button onClick={() => setRecommendOpen(true)}>推荐信源库</Button>
          <Button type="primary" onClick={() => openEditor()}>
            新建信源
          </Button>
        </Space>
      </Space>

      <Table<Source>
        rowKey="id"
        loading={isLoading}
        style={{ marginTop: 16 }}
        dataSource={filteredSources}
        pagination={false}
        columns={[
          {
            title: '名称',
            dataIndex: 'name',
            render: (value: string, record) => {
              const isNew = record.created_at && Date.now() - new Date(record.created_at).getTime() <= 7 * 24 * 3600 * 1000
              return (
                <Space size={6}>
                  <span>{value}</span>
                  {isNew && <Tag color="green">新增</Tag>}
                </Space>
              )
            },
          },
          {
            title: '渠道',
            dataIndex: 'channel',
            render: (value, record) => (
              <Space size={4}>
                <Tag>{value}</Tag>
                {record.engine ? <Tag color="blue">{record.engine}</Tag> : null}
                {record.object_type ? <Tag color="geekblue">{record.object_type}</Tag> : null}
              </Space>
            ),
          },
          { title: 'Tier', dataIndex: 'tier' },
          {
            title: '状态',
            dataIndex: 'status',
            render: (value: string, record) => (
              <Space size={4}>
                <Tag color={SOURCE_STATUS_META[value]?.color}>{SOURCE_STATUS_META[value]?.label ?? value}</Tag>
                {!record.enabled && <Tag>停用</Tag>}
                {record.consecutive_failures > 0 && <Tag color="error">连续失败 {record.consecutive_failures}</Tag>}
              </Space>
            ),
          },
          { title: '最近成功', dataIndex: 'last_success_at', render: (value) => formatTime(value) },
          {
            title: '近 30 天',
            width: 220,
            render: (_, record) => {
              const stat = statById.get(record.id)
              if (!stat) return <Typography.Text type="secondary" style={{ fontSize: 12 }}>暂无数据</Typography.Text>
              const lowYield = stat.candidates >= 20 && stat.ingested === 0
              return (
                <Space size={4} wrap>
                  <Typography.Text style={{ fontSize: 12 }}>
                    候选 {stat.candidates} · 入库 {stat.ingested}
                    {stat.avg_score !== null ? ` · 均分 ${stat.avg_score}` : ''}
                  </Typography.Text>
                  {lowYield && <Tag color="warning">低产</Tag>}
                  {stat.ingested > 0 && (
                    <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                      最近 {formatTime(stat.last_item_at)}
                    </Typography.Text>
                  )}
                </Space>
              )
            },
          },
          {
            title: '操作',
            render: (_, record) => (
              <Space>
                <Button size="small" loading={testMutation.isPending && testMutation.variables === record.id} onClick={() => testMutation.mutate(record.id)}>
                  测试
                </Button>
                <Button size="small" onClick={() => openEditor(record)}>编辑</Button>
                <Button size="small" danger onClick={() => Modal.confirm({ title: `删除信源「${record.name}」?`, onOk: () => deleteMutation.mutate(record.id) })}>
                  删除
                </Button>
              </Space>
            ),
          },
        ]}
        expandable={{
          expandedRowRender: (record) => (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {record.url}
              {record.last_error ? ` · 最近错误:${record.last_error}` : ''}
            </Typography.Text>
          ),
        }}
      />

      <Modal
        title={editing ? `编辑信源:${editing.name}` : '新建信源'}
        open={open}
        width={640}
        onCancel={() => setOpen(false)}
        onOk={() => form.submit()}
        confirmLoading={saveMutation.isPending}
      >
        <Form form={form} layout="vertical" onFinish={(values) => saveMutation.mutate(values)}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Space size={16} wrap>
            <Form.Item name="channel" label="渠道" rules={[{ required: true }]}>
              <Select
                style={{ width: 160 }}
                options={[
                  { value: 'rss', label: 'RSS / Atom' },
                  { value: 'arxiv', label: 'arXiv' },
                  { value: 'google_news', label: 'Google News 检索' },
                  { value: 'bing_news', label: 'Bing News 检索' },
                  { value: 'hackernews', label: 'Hacker News' },
                  { value: 'repo', label: 'GitHub 仓库检索' },
                  { value: 'skill', label: 'GitHub Skill 检索' },
                  { value: 'model', label: 'HuggingFace 模型' },
                  { value: 'github', label: 'GitHub Trending' },
                ]}
              />
            </Form.Item>
            <Form.Item name="collector_kind" label="采集类型" rules={[{ required: true }]}>
              <Select
                style={{ width: 160 }}
                options={[
                  { value: 'stream', label: 'stream 持续流' },
                  { value: 'trend', label: 'trend 榜单' },
                  { value: 'search', label: 'search 关键词检索' },
                ]}
              />
            </Form.Item>
            <Form.Item name="tier" label="Tier">
              <Select style={{ width: 100 }} options={['S', 'A', 'B', 'C'].map((value) => ({ value, label: value }))} />
            </Form.Item>
          </Space>
          <Form.Item name="url" label="URL" rules={[{ required: true }]}>
            <Input placeholder="https://..." />
          </Form.Item>
          <Form.Item name="config_text" label="高级配置(JSON)">
            <Input.TextArea rows={4} placeholder='例如 arXiv: {"categories": ["cs.AI", "cs.CL"]}' />
          </Form.Item>
          <Space size={16} wrap>
            <Form.Item name="fetch_interval_minutes" label="抓取频率(分钟)" rules={[{ required: true }]}>
              <InputNumber min={5} max={1440} />
            </Form.Item>
            <Form.Item name="enabled" label="启用" valuePropName="checked">
              <Switch />
            </Form.Item>
          </Space>
        </Form>
      </Modal>

      <Modal
        title="推荐信源库"
        open={recommendOpen}
        width={880}
        onCancel={() => setRecommendOpen(false)}
        onOk={() => importMutation.mutate()}
        okText={`导入所选(${selectedKeys.length})`}
        confirmLoading={importMutation.isPending}
        okButtonProps={{ disabled: selectedKeys.length === 0 }}
      >
        <Space wrap style={{ marginBottom: 8 }}>
          <Select
            allowClear
            placeholder="全部类别"
            style={{ width: 160 }}
            value={recommendCategory}
            onChange={setRecommendCategory}
            options={Object.entries(RECOMMEND_CATEGORY_META).map(([value, meta]) => ({
              value,
              label: meta.label,
            }))}
          />
          <Button size="small" onClick={() => setSelectedKeys(visibleRecommended.filter((item) => !importedNames.has(item.name)).map((item) => item.key))}>
            全选本类
          </Button>
          <Button size="small" onClick={() => setSelectedKeys(visibleRecommended.filter((item) => item.tier === 'A' && !importedNames.has(item.name)).map((item) => item.key))}>
            仅选本类 A 级
          </Button>
          <Button size="small" onClick={() => setSelectedKeys([])}>
            清空
          </Button>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            已导入的信源自动跳过;建议先导入 A 级,再按「测试」确认可得性
          </Typography.Text>
        </Space>
        <Table<RecommendedSource>
          rowKey="key"
          size="small"
          dataSource={visibleRecommended}
          pagination={false}
          scroll={{ y: 420 }}
          rowSelection={{
            selectedRowKeys: selectedKeys,
            onChange: (keys) => setSelectedKeys(keys as string[]),
            getCheckboxProps: (record) => ({ disabled: importedNames.has(record.name) }),
          }}
          columns={[
            { title: '名称', dataIndex: 'name', render: (value, record) => (
              <Space size={4} wrap>
                <span>{value}</span>
                {importedNames.has(record.name) && <Tag>已导入</Tag>}
              </Space>
            ) },
            {
              title: '类别',
              dataIndex: 'category',
              width: 104,
              render: (value: string) => (
                <Tag color={RECOMMEND_CATEGORY_META[value]?.color}>
                  {RECOMMEND_CATEGORY_META[value]?.label ?? value ?? '其他'}
                </Tag>
              ),
            },
            { title: '渠道', dataIndex: 'channel', width: 84 },
            { title: 'Tier', dataIndex: 'tier', width: 56 },
            { title: '说明', dataIndex: 'description', render: (value) => <span style={{ fontSize: 12, color: '#888' }}>{value}</span> },
          ]}
        />
      </Modal>
      <Modal
        title="信源发现"
        open={discoverOpen}
        width={920}
        onCancel={() => setDiscoverOpen(false)}
        onOk={() => importCandidatesMutation.mutate()}
        okText={`导入所选(${discoverSelected.length})`}
        confirmLoading={importCandidatesMutation.isPending}
        okButtonProps={{ disabled: discoverSelected.length === 0 }}
      >
        <Space.Compact style={{ width: '100%' }}>
          <Input
            value={discoverUrl}
            onChange={(event) => setDiscoverUrl(event.target.value)}
            onPressEnter={() => {
              if (discoverUrl.trim()) discoverMutation.mutate(discoverUrl.trim())
            }}
            placeholder="GitHub 仓库地址 / OPML 链接 / 博客或站点首页,如 https://github.com/example/awesome-feeds"
          />
          <Button
            type="primary"
            loading={discoverMutation.isPending}
            onClick={() => {
              if (discoverUrl.trim()) discoverMutation.mutate(discoverUrl.trim())
            }}
          >
            探测
          </Button>
        </Space.Compact>
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 8, marginBottom: 8 }}>
          支持 GitHub 仓库(自动找 OPML / feeds 清单并解析 README)、OPML 文件、页面声明的 RSS/Atom。探测通过且未存在的条目默认勾选,导入渠道为 rss。
        </Typography.Paragraph>
        {discoverResult && (
          <Space wrap style={{ marginBottom: 8 }}>
            <Tag color="green">可达 {discoverResult.ok_count}</Tag>
            <Tag>共 {discoverResult.candidates.length}</Tag>
            <Select
              style={{ width: 120 }}
              value={discoverTier}
              onChange={setDiscoverTier}
              options={['S', 'A', 'B', 'C'].map((value) => ({ value, label: `Tier ${value}` }))}
            />
            <Button
              size="small"
              onClick={() =>
                setDiscoverSelected(
                  discoverResult.candidates
                    .filter((item) => item.ok && !item.already_exists)
                    .map((item) => item.url),
                )
              }
            >
              全选可达
            </Button>
            <Button size="small" onClick={() => setDiscoverSelected([])}>
              清空
            </Button>
          </Space>
        )}
        {discoverResult && (
          <Table<DiscoverCandidate>
            rowKey="url"
            size="small"
            dataSource={discoverResult.candidates}
            pagination={false}
            scroll={{ y: 360 }}
            rowSelection={{
              selectedRowKeys: discoverSelected,
              onChange: (keys) => setDiscoverSelected(keys as string[]),
              getCheckboxProps: (record) => ({ disabled: !record.ok || record.already_exists }),
            }}
            columns={[
              {
                title: '名称',
                dataIndex: 'name',
                render: (value: string, record) => (
                  <div>
                    <div>{value}</div>
                    {record.title && record.title !== value && (
                      <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                        {record.title}
                      </Typography.Text>
                    )}
                  </div>
                ),
              },
              {
                title: 'URL',
                dataIndex: 'url',
                render: (value: string) => (
                  <Typography.Text style={{ fontSize: 12 }} ellipsis={{ tooltip: value }}>
                    {value}
                  </Typography.Text>
                ),
              },
              {
                title: '探测',
                width: 220,
                render: (_, record) =>
                  record.ok ? (
                    <Space size={4}>
                      <Tag color="green">{record.entries} 条</Tag>
                      <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                        最新 {formatTime(record.latest)}
                      </Typography.Text>
                    </Space>
                  ) : (
                    <Typography.Text type="danger" style={{ fontSize: 12 }}>
                      {record.error ?? '不可达'}
                    </Typography.Text>
                  ),
              },
              {
                title: '状态',
                width: 76,
                render: (_, record) => (record.already_exists ? <Tag>已存在</Tag> : null),
              },
            ]}
          />
        )}
      </Modal>
    </div>
  )
}
