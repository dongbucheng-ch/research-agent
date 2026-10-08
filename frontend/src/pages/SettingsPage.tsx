import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Card,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import dayjs from "dayjs";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type {
  LLMSettings,
  PushChannel,
  PushLog,
  PushProvider,
} from "../api/types";

const GENERAL_DEFAULTS: Record<string, number> = {
  fetch_max_concurrency: 8,
  fetch_lookback_hours: 24,
  enrich_max_items: 100,
  enrich_batch_size: 6,
};

function validateTemplate(text: string): string | null {
  const raw = text.trim();
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return "payload_template 需为 JSON 对象";
    }
    return null;
  } catch {
    return "JSON 解析失败,请检查括号与引号是否成对";
  }
}

function channelTarget(channel: PushChannel): string {
  const config = (channel.config ?? {}) as { url?: string; source?: string };
  const parts: string[] = [];
  if (config.url) {
    try {
      parts.push(new URL(config.url).host);
    } catch {
      parts.push(config.url);
    }
  }
  if (config.source) parts.push(`source=${config.source}`);
  return parts.join(" · ");
}

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const [llmForm] = Form.useForm();
  const [generalForm] = Form.useForm();
  const [channelForm] = Form.useForm();
  const [channelEditForm] = Form.useForm();
  const [channelOpen, setChannelOpen] = useState(false);
  const [channelKind, setChannelKind] = useState("webhook");
  const [llmDirty, setLlmDirty] = useState(false);
  const [generalDirty, setGeneralDirty] = useState(false);
  const [editingChannel, setEditingChannel] = useState<PushChannel | null>(null);
  const [templateText, setTemplateText] = useState("");
  const [templateError, setTemplateError] = useState<string | null>(null);

  const { data: llm } = useQuery({
    queryKey: ["llm-settings"],
    queryFn: () => api.get<LLMSettings>("/settings/llm"),
  });
  const { data: general } = useQuery({
    queryKey: ["general-settings"],
    queryFn: () => api.get<Record<string, unknown>>("/settings/general"),
  });
  const { data: providers } = useQuery({
    queryKey: ["push-providers"],
    queryFn: () => api.get<PushProvider[]>("/settings/providers"),
  });
  const { data: channels } = useQuery({
    queryKey: ["push-channels"],
    queryFn: () => api.get<PushChannel[]>("/settings/push-channels"),
  });
  const { data: pushLogs } = useQuery({
    queryKey: ["push-logs", "recent"],
    queryFn: () => api.get<PushLog[]>("/settings/push-logs?limit=100"),
  });

  const latestByChannel = useMemo(() => {
    const map = new Map<number, PushLog>();
    for (const log of pushLogs ?? []) {
      if (log.channel_id !== null && !map.has(log.channel_id)) {
        map.set(log.channel_id, log);
      }
    }
    return map;
  }, [pushLogs]);

  useEffect(() => {
    if (llm) {
      llmForm.setFieldsValue({ ...llm, api_key: "" });
    }
  }, [llm, llmForm]);

  useEffect(() => {
    if (general) generalForm.setFieldsValue(general);
  }, [general, generalForm]);

  const saveLlmMutation = useMutation({
    mutationFn: (values: Record<string, unknown>) =>
      api.put("/settings/llm", {
        ...values,
        api_key: (values.api_key as string)?.trim()
          ? values.api_key
          : undefined,
      }),
    onSuccess: () => {
      setLlmDirty(false);
      message.success("LLM 配置已保存");
      queryClient.invalidateQueries({ queryKey: ["llm-settings"] });
    },
    onError: (error: Error) => message.error(error.message),
  });

  const testLlmMutation = useMutation({
    mutationFn: (values: Record<string, unknown>) =>
      api.post<{ ok: boolean; message: string; latency_ms?: number }>(
        "/settings/llm/test",
        {
          base_url: values.base_url || undefined,
          model: values.model || undefined,
          api_key: (values.api_key as string)?.trim() || undefined,
        },
      ),
    onSuccess: (result) => {
      if (result.ok)
        message.success(
          `${result.message}${result.latency_ms ? `(${result.latency_ms}ms)` : ""}`,
        );
      else message.error(result.message);
    },
    onError: (error: Error) => message.error(error.message),
  });

  const saveGeneralMutation = useMutation({
    mutationFn: (values: Record<string, unknown>) =>
      api.put("/settings/general", values),
    onSuccess: () => {
      setGeneralDirty(false);
      message.success("通用设置已保存");
      queryClient.invalidateQueries({ queryKey: ["general-settings"] });
    },
  });

  const createChannelMutation = useMutation({
    mutationFn: (values: {
      name: string;
      kind: string;
      url?: string;
      token?: string;
    }) =>
      api.post("/settings/push-channels", {
        name: values.name,
        kind: values.kind,
        config:
          values.kind === "webhook"
            ? { url: values.url, token: values.token || undefined }
            : {},
        enabled: true,
      }),
    onSuccess: () => {
      message.success("推送渠道已创建");
      setChannelOpen(false);
      queryClient.invalidateQueries({ queryKey: ["push-channels"] });
    },
    onError: (error: Error) => message.error(error.message),
  });

  const deleteChannelMutation = useMutation({
    mutationFn: (id: number) => api.del(`/settings/push-channels/${id}`),
    onSuccess: () => {
      message.success("已删除");
      queryClient.invalidateQueries({ queryKey: ["push-channels"] });
    },
  });

  const testChannelMutation = useMutation({
    mutationFn: (id: number) =>
      api.post<{ ok: boolean; message?: string }>(
        `/settings/push-channels/${id}/test`,
      ),
    onSuccess: (result) => {
      if (result.ok) message.success(result.message ?? "推送成功");
      else message.error(result.message ?? "推送失败");
    },
  });

  const toggleChannelMutation = useMutation({
    mutationFn: (input: { id: number; enabled: boolean }) =>
      api.put(`/settings/push-channels/${input.id}`, {
        enabled: input.enabled,
      }),
    onSuccess: (_result, input) => {
      message.success(input.enabled ? "渠道已启用" : "渠道已停用");
      queryClient.invalidateQueries({ queryKey: ["push-channels"] });
    },
    onError: (error: Error) => message.error(error.message),
  });

  const updateChannelMutation = useMutation({
    mutationFn: (input: { id: number; values: Record<string, unknown> }) =>
      api.put(`/settings/push-channels/${input.id}`, input.values),
    onSuccess: () => {
      message.success("渠道已更新");
      setEditingChannel(null);
      queryClient.invalidateQueries({ queryKey: ["push-channels"] });
    },
    onError: (error: Error) => message.error(error.message),
  });

  const openChannelEditor = (channel: PushChannel) => {
    const config = (channel.config ?? {}) as Record<string, unknown>;
    channelEditForm.setFieldsValue({
      name: channel.name,
      url: config.url ?? "",
      token: "",
      source: config.source ?? "",
      author: config.author ?? "",
      enabled: channel.enabled,
    });
    const template = config.payload_template;
    setTemplateText(template ? JSON.stringify(template, null, 2) : "");
    setTemplateError(null);
    setEditingChannel(channel);
  };

  const handleChannelSave = async () => {
    if (!editingChannel) return;
    let values: Record<string, unknown>;
    try {
      values = await channelEditForm.validateFields();
    } catch {
      return;
    }
    const error = validateTemplate(templateText);
    if (error) {
      setTemplateError(error);
      return;
    }
    const config = {
      ...((editingChannel.config ?? {}) as Record<string, unknown>),
    };
    if (editingChannel.kind === "webhook") {
      config.url = String(values.url ?? "").trim();
      const token = String(values.token ?? "").trim();
      if (token) config.token = token;
    }
    const source = String(values.source ?? "").trim();
    const author = String(values.author ?? "").trim();
    if (source) config.source = source;
    else delete config.source;
    if (author) config.author = author;
    else delete config.author;
    if (templateText.trim()) {
      config.payload_template = JSON.parse(templateText);
    } else {
      delete config.payload_template;
    }
    updateChannelMutation.mutate({
      id: editingChannel.id,
      values: {
        name: String(values.name ?? "").trim(),
        enabled: Boolean(values.enabled),
        config,
      },
    });
  };

  const resetGeneralField = (name: string) => {
    generalForm.setFieldsValue({ [name]: GENERAL_DEFAULTS[name] });
    setGeneralDirty(true);
  };

  const generalExtra = (name: string, hint: string) => (
    <>
      {hint} ·{" "}
      <Typography.Link onClick={() => resetGeneralField(name)}>
        恢复默认
      </Typography.Link>
    </>
  );

  const cardActions = (dirty: boolean, saving: boolean, onSave: () => void) => (
    <Space align="center" size={8}>
      {dirty ? (
        <Tag color="gold" style={{ marginInlineEnd: 0 }}>
          未保存修改
        </Tag>
      ) : (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          已同步
        </Typography.Text>
      )}
      <Button
        type="primary"
        size="small"
        loading={saving}
        disabled={!dirty}
        onClick={onSave}
      >
        保存
      </Button>
    </Space>
  );

  return (
    <div>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        设置
      </Typography.Title>

      <Card
        title="LLM 配置"
        size="small"
        style={{ marginBottom: 24 }}
        extra={cardActions(llmDirty, saveLlmMutation.isPending, () =>
          llmForm.submit(),
        )}
      >
        <Form
          form={llmForm}
          layout="vertical"
          onValuesChange={() => setLlmDirty(true)}
          onFinish={(values) => saveLlmMutation.mutate(values)}
        >
          <Space
            size={16}
            wrap
            align="start"
            style={{ display: "flex", marginBottom: 16 }}
          >
            <Form.Item
              name="base_url"
              label="Base URL"
              style={{ width: 320 }}
              tooltip="OpenAI 兼容端点,例如 https://api.deepseek.com/v1"
            >
              <Input placeholder="https://api.example.com/v1" />
            </Form.Item>
            <Form.Item name="model" label="Model" style={{ width: 220 }}>
              <Input placeholder="deepseek-chat / gpt-4o-mini ..." />
            </Form.Item>
            <Form.Item
              name="api_key"
              label="API Key"
              style={{ width: 320 }}
              extra={
                llm?.api_key_masked
                  ? `已保存 ${llm.api_key_masked} · 留空则保留`
                  : "尚未配置"
              }
            >
              <Input.Password placeholder="sk-..." autoComplete="new-password" />
            </Form.Item>
            <Form.Item label={"\u00A0"}>
              <Button
                onClick={() => testLlmMutation.mutate(llmForm.getFieldsValue())}
                loading={testLlmMutation.isPending}
              >
                测试连接
              </Button>
            </Form.Item>
          </Space>
          <Space size={16} wrap align="start" style={{ display: "flex" }}>
            <Form.Item
              name="timeout_seconds"
              label="超时"
              extra="10–600 秒"
              rules={[
                { type: "number", min: 10, max: 600, message: "范围 10–600" },
              ]}
            >
              <InputNumber
                min={10}
                max={600}
                addonAfter="秒"
                style={{ width: 150 }}
              />
            </Form.Item>
            <Form.Item
              name="max_concurrency"
              label="并发数"
              extra="1–16,建议 3"
              rules={[{ type: "number", min: 1, max: 16, message: "范围 1–16" }]}
            >
              <InputNumber min={1} max={16} style={{ width: 120 }} />
            </Form.Item>
            <Form.Item
              name="enabled"
              label="启用"
              valuePropName="checked"
              tooltip="关闭后采集/日报/文章不再调用 LLM(富化与生成会走降级模板)"
            >
              <Switch checkedChildren="开" unCheckedChildren="关" />
            </Form.Item>
            <Form.Item
              name="translate_enabled"
              label="翻译 / 摘要"
              valuePropName="checked"
              tooltip="关闭后富化步骤不做中文翻译与摘要"
            >
              <Switch checkedChildren="开" unCheckedChildren="关" />
            </Form.Item>
          </Space>
        </Form>
      </Card>

      <Card
        title="通用设置"
        size="small"
        style={{ marginBottom: 24 }}
        extra={cardActions(generalDirty, saveGeneralMutation.isPending, () =>
          generalForm.submit(),
        )}
      >
        <Form
          form={generalForm}
          layout="vertical"
          onValuesChange={() => setGeneralDirty(true)}
          onFinish={(values) => saveGeneralMutation.mutate(values)}
        >
          <Space size={16} wrap align="start">
            <Form.Item
              name="fetch_max_concurrency"
              label="信源抓取并发"
              extra={generalExtra("fetch_max_concurrency", "1–32,默认 8")}
              rules={[{ type: "number", min: 1, max: 32, message: "范围 1–32" }]}
            >
              <InputNumber min={1} max={32} style={{ width: 140 }} />
            </Form.Item>
            <Form.Item
              name="fetch_lookback_hours"
              label="默认回看窗口"
              extra={generalExtra("fetch_lookback_hours", "最长 48 小时,默认 24")}
              rules={[{ type: "number", min: 1, max: 48, message: "范围 1–48" }]}
            >
              <InputNumber
                min={1}
                max={48}
                addonAfter="小时"
                style={{ width: 160 }}
              />
            </Form.Item>
            <Form.Item
              name="enrich_max_items"
              label="候选/富化上限"
              tooltip="超过上限的候选按「关键词命中 / 信源等级 / 时效」预排序,仅对 Top-N 调用 LLM 富化,其余零成本降级入库"
              extra={generalExtra("enrich_max_items", "推荐 100,上限 500")}
              rules={[{ type: "number", min: 1, max: 500, message: "范围 1–500" }]}
            >
              <InputNumber
                min={1}
                max={500}
                addonAfter="条"
                style={{ width: 170 }}
              />
            </Form.Item>
            <Form.Item
              name="enrich_batch_size"
              label="批量富化"
              tooltip="单次 LLM 请求处理几条,过大可能触发响应截断"
              extra={generalExtra("enrich_batch_size", "单次请求条数,建议 6")}
              rules={[{ type: "number", min: 1, max: 20, message: "范围 1–20" }]}
            >
              <InputNumber
                min={1}
                max={20}
                addonAfter="条/次"
                style={{ width: 160 }}
              />
            </Form.Item>
          </Space>
          <div style={{ marginTop: 4 }}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              「恢复默认」只改表单,点右上角保存后才生效
            </Typography.Text>
          </div>
        </Form>
      </Card>

      <Card
        title="推送渠道"
        size="small"
        style={{ marginBottom: 24 }}
        extra={
          <Button size="small" onClick={() => setChannelOpen(true)}>
            新建渠道
          </Button>
        }
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          推送采用可插拔的 PushProvider:当前内置「通用 Webhook」与「导出」。飞书
          / Discord / 邮件等平台后续仅需新增一个 provider 文件,无需改动核心。
        </Typography.Paragraph>
        <Table<PushChannel>
          rowKey="id"
          size="small"
          dataSource={channels}
          pagination={false}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="还没有推送渠道"
              >
                <Button
                  type="primary"
                  size="small"
                  onClick={() => setChannelOpen(true)}
                >
                  新建渠道
                </Button>
              </Empty>
            ),
          }}
          columns={[
            {
              title: "名称",
              dataIndex: "name",
              render: (_: string, record: PushChannel) => {
                const last = latestByChannel.get(record.id);
                return (
                  <Space direction="vertical" size={0}>
                    <Typography.Text strong>{record.name}</Typography.Text>
                    <Space size={6} wrap>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {channelTarget(record) || "未配置地址"}
                      </Typography.Text>
                      {last ? (
                        <Typography.Text
                          type={last.status === "success" ? "success" : "danger"}
                          style={{ fontSize: 12 }}
                        >
                          最近推送{" "}
                          {last.created_at
                            ? dayjs(last.created_at).format("MM-DD HH:mm")
                            : ""}{" "}
                          · {last.status === "success" ? "成功" : "失败"}
                        </Typography.Text>
                      ) : (
                        <Typography.Text
                          type="secondary"
                          style={{ fontSize: 12 }}
                        >
                          尚未推送
                        </Typography.Text>
                      )}
                    </Space>
                  </Space>
                );
              },
            },
            {
              title: "类型",
              dataIndex: "kind",
              width: 140,
              render: (value: string) => (
                <Tag>
                  {providers?.find((p) => p.kind === value)?.label ?? value}
                </Tag>
              ),
            },
            {
              title: "启用",
              dataIndex: "enabled",
              width: 90,
              render: (value: boolean, record: PushChannel) => (
                <Switch
                  size="small"
                  checked={value}
                  loading={
                    toggleChannelMutation.isPending &&
                    toggleChannelMutation.variables?.id === record.id
                  }
                  onChange={(checked) =>
                    toggleChannelMutation.mutate({
                      id: record.id,
                      enabled: checked,
                    })
                  }
                />
              ),
            },
            {
              title: "操作",
              width: 220,
              render: (_: unknown, record: PushChannel) => (
                <Space>
                  <Button
                    size="small"
                    onClick={() => testChannelMutation.mutate(record.id)}
                    loading={
                      testChannelMutation.isPending &&
                      testChannelMutation.variables === record.id
                    }
                  >
                    测试
                  </Button>
                  <Button size="small" onClick={() => openChannelEditor(record)}>
                    编辑
                  </Button>
                  <Popconfirm
                    title="删除该渠道?"
                    description="渠道配置不可恢复,历史推送日志会保留。"
                    okText="删除"
                    cancelText="取消"
                    okButtonProps={{ danger: true }}
                    onConfirm={() => deleteChannelMutation.mutate(record.id)}
                  >
                    <Button size="small" danger>
                      删除
                    </Button>
                  </Popconfirm>
                </Space>
              ),
            },
          ]}
        />
      </Card>

      <Card title="关于" size="small">
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          research-agent · 关键词驱动的研究与资讯采集(论文 / 技术 / 产业 /
          社区),支持三维打分、日报聚合与素材池检索。内部使用。
        </Typography.Paragraph>
      </Card>

      <Modal
        title="新建推送渠道"
        open={channelOpen}
        onCancel={() => setChannelOpen(false)}
        onOk={() => channelForm.submit()}
        confirmLoading={createChannelMutation.isPending}
      >
        <Form
          form={channelForm}
          layout="vertical"
          initialValues={{ kind: "webhook" }}
          onFinish={(values) => createChannelMutation.mutate(values)}
          onValuesChange={(changed) =>
            changed.kind && setChannelKind(changed.kind)
          }
        >
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input placeholder="例如:团队群机器人" />
          </Form.Item>
          <Form.Item name="kind" label="类型" rules={[{ required: true }]}>
            <Select
              options={providers?.map((provider) => ({
                value: provider.kind,
                label: provider.label,
              }))}
            />
          </Form.Item>
          {channelKind === "webhook" && (
            <>
              <Form.Item
                name="url"
                label="Webhook URL"
                rules={[{ required: true }]}
              >
                <Input placeholder="https://..." />
              </Form.Item>
              <Form.Item name="token" label="Token(可选,作为 Bearer 头)">
                <Input.Password autoComplete="new-password" />
              </Form.Item>
            </>
          )}
        </Form>
      </Modal>

      <Drawer
        title="编辑渠道"
        width={520}
        open={editingChannel !== null}
        onClose={() => setEditingChannel(null)}
        destroyOnClose
        footer={
          <Space style={{ display: "flex", justifyContent: "flex-end" }}>
            <Button onClick={() => setEditingChannel(null)}>取消</Button>
            <Button
              type="primary"
              loading={updateChannelMutation.isPending}
              onClick={handleChannelSave}
            >
              保存
            </Button>
          </Space>
        }
      >
        <Form form={channelEditForm} layout="vertical">
          <Form.Item
            name="name"
            label="名称"
            rules={[{ required: true, message: "请输入渠道名称" }]}
          >
            <Input placeholder="例如:深数社区" />
          </Form.Item>
          <Form.Item label="类型">
            <Typography.Text>
              {providers?.find((p) => p.kind === editingChannel?.kind)?.label ??
                editingChannel?.kind}
            </Typography.Text>
          </Form.Item>
          {editingChannel?.kind === "webhook" && (
            <>
              <Form.Item
                name="url"
                label="Webhook URL"
                rules={[{ required: true, message: "请输入 Webhook URL" }]}
              >
                <Input placeholder="https://..." />
              </Form.Item>
              <Form.Item
                name="token"
                label="Token"
                extra="留空表示保留现有 Token"
              >
                <Input.Password
                  placeholder="留空则不变"
                  autoComplete="new-password"
                />
              </Form.Item>
            </>
          )}
          <Form.Item
            name="source"
            label="默认来源 source"
            extra="推送模板里的 $source 取这里;留空则用产出物默认"
          >
            <Input placeholder="例如 sribd_forum_ai" />
          </Form.Item>
          <Form.Item
            name="author"
            label="默认作者 author"
            extra="部分平台(如深数社区)没有该字段,仅记录在推送日志"
          >
            <Input placeholder="例如 研讯编辑部" />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch checkedChildren="开" unCheckedChildren="关" />
          </Form.Item>
          <Form.Item
            label="payload_template(JSON)"
            validateStatus={templateError ? "error" : undefined}
            help={
              templateError ??
              "占位符:$title / $lead / $content / $highlights / $tags / $source / $author;留空表示不套模板"
            }
          >
            <Input.TextArea
              rows={8}
              value={templateText}
              onChange={(event) => {
                const next = event.target.value;
                setTemplateText(next);
                setTemplateError(validateTemplate(next));
              }}
              placeholder={
                '{\n  "sourceId": "$title",\n  "title": "$title",\n  "tags": "$tags"\n}'
              }
              style={{ fontFamily: "Menlo, monospace", fontSize: 12 }}
            />
          </Form.Item>
        </Form>
      </Drawer>
    </div>
  );
}
