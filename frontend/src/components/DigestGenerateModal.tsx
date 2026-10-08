import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Form, Input, InputNumber, Modal, Radio, Select, Space, Typography, message } from 'antd'
import { api } from '../api/client'

export interface DigestGenerateValues {
  scope: 'global' | 'topic'
  topic?: string
  keywords?: string[]
  period_hours: number
  max_items: number
  github_count: number
  min_score: number
}

const DEFAULTS: DigestGenerateValues = {
  scope: 'global',
  period_hours: 24,
  max_items: 10,
  github_count: 5,
  min_score: 60,
}

interface Props {
  open: boolean
  onClose: () => void
  defaults?: Partial<DigestGenerateValues>
  onCreated?: () => void
}

export default function DigestGenerateModal({ open, onClose, defaults, onCreated }: Props) {
  const queryClient = useQueryClient()
  const [form] = Form.useForm<DigestGenerateValues>()
  const scope = Form.useWatch('scope', form) ?? defaults?.scope ?? 'global'

  const mutation = useMutation({
    mutationFn: (values: DigestGenerateValues) => {
      const keywords = (values.keywords ?? []).map((word) => word.trim()).filter(Boolean)
      const payload: Record<string, unknown> = {
        scope: values.scope,
        period_hours: values.period_hours,
        max_items: values.max_items,
        github_count: values.github_count,
        min_score: values.min_score,
      }
      if (values.scope === 'topic') {
        if (values.topic?.trim()) payload.topic = values.topic.trim()
        payload.keywords = keywords
      }
      return api.post('/digests/generate', payload)
    },
    onSuccess: () => {
      message.success('日报任务已创建,完成后到「日报 / 素材池」查看')
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
      onClose()
      onCreated?.()
    },
    onError: (error: Error) => message.error(error.message),
  })

  return (
    <Modal
      title="生成日报"
      open={open}
      onCancel={onClose}
      onOk={() => form.submit()}
      confirmLoading={mutation.isPending}
      destroyOnClose
      width={520}
    >
      <Form
        form={form}
        layout="vertical"
        style={{ marginTop: 8 }}
        initialValues={{ ...DEFAULTS, ...defaults }}
        onFinish={(values) => mutation.mutate(values)}
      >
        <Form.Item name="scope" label="日报范围">
          <Radio.Group>
            <Radio.Button value="global">全局最新最热</Radio.Button>
            <Radio.Button value="topic">按方向 / 关键词</Radio.Button>
          </Radio.Group>
        </Form.Item>
        {scope === 'topic' && (
          <>
            <Form.Item name="topic" label="研究方向">
              <Input placeholder="例如:LLM Agent / 具身智能" allowClear maxLength={50} />
            </Form.Item>
            <Form.Item
              name="keywords"
              label="关键词(输入后回车)"
              rules={[{ required: true, message: '至少填写一个关键词' }]}
            >
              <Select
                mode="tags"
                open={false}
                tokenSeparators={[',', '、', ' ', ';']}
                placeholder="例如:agent / 大模型 / 具身智能"
              />
            </Form.Item>
          </>
        )}
        <Space size="large" wrap>
          <Form.Item name="period_hours" label="回看窗口(小时)">
            <InputNumber min={6} max={720} style={{ width: 130 }} />
          </Form.Item>
          <Form.Item name="max_items" label="资讯条数">
            <InputNumber min={3} max={20} style={{ width: 110 }} />
          </Form.Item>
          <Form.Item name="github_count" label="GitHub 条数">
            <InputNumber min={3} max={5} style={{ width: 110 }} />
          </Form.Item>
        </Space>
        <Form.Item name="min_score" label="入库门槛" tooltip="素材三维总分低于该值不进入候选池">
          <InputNumber min={0} max={100} style={{ width: 130 }} />
        </Form.Item>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          GitHub 板块实时抓取「今日推荐」;全局按热度 0.6 + 时效 0.4 排序,定向按相关度 0.5 + 热度
          0.3 + 时效 0.2 排序。
        </Typography.Text>
      </Form>
    </Modal>
  )
}
