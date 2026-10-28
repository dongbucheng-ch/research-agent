import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
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
  Tooltip,
  Typography,
  message,
} from "antd";
import {
  CheckCircleFilled,
  CloseCircleFilled,
  DeleteOutlined,
  EditOutlined,
  ExclamationCircleFilled,
  PlusOutlined,
  SendOutlined,
  ThunderboltOutlined,
  UndoOutlined,
} from "@ant-design/icons";
import dayjs from "dayjs";
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
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
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);

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

  const dirtyCount = (llmDirty ? 1 : 0) + (generalDirty ? 1 : 0);

  /** 改动未保存时拦截关闭/刷新,避免静默丢失 */
  useEffect(() => {
    if (!dirtyCount) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirtyCount]);

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
      setSavedAt(dayjs().format("HH:mm"));
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
    onSuccess: (result) =>
      setTestResult({
        ok: result.ok,
        message: `${result.message}${result.latency_ms ? ` · ${result.latency_ms}ms` : ""}`,
      }),
    onError: (error: Error) => setTestResult({ ok: false, message: error.message }),
  });

  const saveGeneralMutation = useMutation({
    mutationFn: (values: Record<string, unknown>) =>
      api.put("/settings/general", values),
    onSuccess: () => {
      setGeneralDirty(false);
      setSavedAt(dayjs().format("HH:mm"));
      message.success("通用设置已保存");
      queryClient.invalidateQueries({ queryKey: ["general-settings"] });
    },
    onError: (error: Error) => message.error(error.message),
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

  /** 字段说明 + 字段级「恢复默认」:图标化,避免蓝色文字链在弱化文本里抢注意力 */
  const numExtra = (name: string, hint: string) => (
    <span className="st-hint">
      <span>{hint}</span>
      <Tooltip title={`恢复默认(${GENERAL_DEFAULTS[name]})`}>
        <button
          type="button"
          className="st-reset"
          aria-label="恢复默认"
          onClick={() => resetGeneralField(name)}
        >
          <UndoOutlined />
        </button>
      </Tooltip>
    </span>
  );

  const groupHead = (label: string, extra?: ReactNode) => (
    <div className="st-group-head">
      <span className="st-group-label">{label}</span>
      {extra}
    </div>
  );

  const cardTitle = (title: string, sub: string) => (
    <span className="st-card-title">
      <span className="st-card-title-main">{title}</span>
      <span className="st-card-title-sub">{sub}</span>
    </span>
  );

  const saving = saveLlmMutation.isPending || saveGeneralMutation.isPending;

  /** 保存全部:两个表单各自校验后提交;失败时保留脏标记,不关掉保存条 */
  const saveAll = async () => {
    try {
      if (llmDirty) {
        await saveLlmMutation.mutateAsync(await llmForm.validateFields());
      }
    } catch {
      /* 校验或保存失败:表单内联错误 + message 已给出 */
    }
    try {
      if (generalDirty) {
        await saveGeneralMutation.mutateAsync(await generalForm.validateFields());
      }
    } catch {
      /* 同上 */
    }
  };

  const discardAll = () => {
    if (llm) llmForm.setFieldsValue({ ...llm, api_key: "" });
    if (general) generalForm.setFieldsValue(general);
    setLlmDirty(false);
    setGeneralDirty(false);
    setTestResult(null);
  };

  return (
    <div className="settings-page">
      <header className="st-head">
        <div>
          <h1 className="st-title">设置</h1>
          <p className="st-sub">
            模型、采集与推送的全局配置;改动保存后对新任务生效。
          </p>
        </div>
        <div className="st-head-status">
          {dirtyCount > 0 ? (
            <span className="st-status is-dirty">{dirtyCount} 处未保存</span>
          ) : (
            <span className="st-status">
              {savedAt ? `已保存 ${savedAt}` : "配置已同步"}
            </span>
          )}
        </div>
      </header>

      <div className="st-main">
        <Card
          className="st-card"
          title={cardTitle("模型与生成", "决定富化与日报的质量和延迟")}
          size="small"
        >
          <Form
            form={llmForm}
            layout="vertical"
            onValuesChange={() => {
              setLlmDirty(true);
              setTestResult(null);
            }}
            onFinish={(values) => saveLlmMutation.mutate(values)}
          >
            <div className="st-group st-connect">
              {groupHead(
                "连接",
                <Button
                  type="text"
                  size="small"
                  className="st-ghost-btn"
                  icon={<ThunderboltOutlined />}
                  loading={testLlmMutation.isPending}
                  onClick={() =>
                    testLlmMutation.mutate(llmForm.getFieldsValue())
                  }
                >
                  测试连接
                </Button>,
              )}
              {/* auto-fit 栅格:字段宽度在 260–420px 之间自适应,超宽屏也不会被拉长 */}
              <div className="st-connect-grid">
                <Form.Item
                  name="base_url"
                  label="Base URL"
                  tooltip="OpenAI 兼容端点,例如 https://api.deepseek.com/v1"
                >
                  <Input placeholder="https://api.example.com/v1" />
                </Form.Item>
                <Form.Item name="model" label="Model">
                  <Input placeholder="deepseek-chat / gpt-4o-mini ..." />
                </Form.Item>
                <Form.Item
                  name="api_key"
                  label="API Key"
                  extra={
                    llm?.api_key_masked
                      ? `已保存 ${llm.api_key_masked} · 留空则保留`
                      : "尚未配置"
                  }
                >
                  <Input.Password
                    placeholder="sk-..."
                    autoComplete="new-password"
                  />
                </Form.Item>
              </div>
              {testResult && (
                <Alert
                  className="st-test-result"
                  type={testResult.ok ? "success" : "error"}
                  showIcon
                  message={testResult.message}
                />
              )}
            </div>

            <div className="st-pair">
              <div className="st-group">
                {groupHead("运行参数")}
                <div className="st-row">
                  <Form.Item
                    name="timeout_seconds"
                    label="超时"
                    className="st-num"
                    extra="范围 10–600 秒"
                    rules={[
                      {
                        type: "number",
                        min: 10,
                        max: 600,
                        message: "范围 10–600",
                      },
                    ]}
                  >
                    <InputNumber min={10} max={600} addonAfter="秒" />
                  </Form.Item>
                  <Form.Item
                    name="max_concurrency"
                    label="并发数"
                    className="st-num"
                    extra="范围 1–16 · 建议 3"
                    rules={[
                      { type: "number", min: 1, max: 16, message: "范围 1–16" },
                    ]}
                  >
                    <InputNumber min={1} max={16} />
                  </Form.Item>
                </div>
              </div>

              <div className="st-group">
                {groupHead("行为开关")}
                <div className="st-switches">
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
                  <Form.Item
                    name="disable_thinking"
                    label="关闭深度思考"
                    valuePropName="checked"
                    tooltip="推荐开启(即「关掉思考」)。推理模型会把输出预算全烧在思维链上:实测同一日报 prompt,关闭 18.8s 返回完整 JSON,开启 47.6s 仍拿不到正文并最终请求超时;网关不支持该参数时会自动去掉重试。"
                  >
                    <Switch checkedChildren="开" unCheckedChildren="关" />
                  </Form.Item>
                </div>
              </div>
            </div>
          </Form>
        </Card>

        <Card
          className="st-card"
          title={cardTitle("采集与富化", "抓取并发、回看窗口与 LLM 富化预算")}
          size="small"
        >
          <Form
            form={generalForm}
            layout="vertical"
            onValuesChange={() => setGeneralDirty(true)}
            onFinish={(values) => saveGeneralMutation.mutate(values)}
          >
            <div className="st-pair">
              <div className="st-group">
                {groupHead("抓取")}
                <div className="st-row">
                  <Form.Item
                    name="fetch_max_concurrency"
                    label="信源抓取并发"
                    className="st-num"
                    extra={numExtra("fetch_max_concurrency", "范围 1–32 · 默认 8")}
                    rules={[
                      { type: "number", min: 1, max: 32, message: "范围 1–32" },
                    ]}
                  >
                    <InputNumber min={1} max={32} />
                  </Form.Item>
                  <Form.Item
                    name="fetch_lookback_hours"
                    label="默认回看窗口"
                    className="st-num"
                    extra={numExtra(
                      "fetch_lookback_hours",
                      "范围 1–48 小时 · 默认 24",
                    )}
                    rules={[
                      { type: "number", min: 1, max: 48, message: "范围 1–48" },
                    ]}
                  >
                    <InputNumber min={1} max={48} addonAfter="小时" />
                  </Form.Item>
                </div>
              </div>

              <div className="st-group">
                {groupHead("富化")}
                <div className="st-row">
                  <Form.Item
                    name="enrich_max_items"
                    label="候选/富化上限"
                    className="st-num"
                    tooltip="超过上限的候选按「关键词命中 / 信源等级 / 时效」预排序,仅对 Top-N 调用 LLM 富化,其余零成本降级入库"
                    extra={numExtra("enrich_max_items", "范围 1–500 · 默认 100")}
                    rules={[
                      { type: "number", min: 1, max: 500, message: "范围 1–500" },
                    ]}
                  >
                    <InputNumber min={1} max={500} addonAfter="条" />
                  </Form.Item>
                  <Form.Item
                    name="enrich_batch_size"
                    label="批量富化"
                    className="st-num"
                    tooltip="单次 LLM 请求处理几条,过大可能触发响应截断"
                    extra={numExtra("enrich_batch_size", "范围 1–20 · 默认 6")}
                    rules={[
                      { type: "number", min: 1, max: 20, message: "范围 1–20" },
                    ]}
                  >
                    <InputNumber min={1} max={20} addonAfter="条/次" />
                  </Form.Item>
                </div>
              </div>
            </div>
            <p className="st-note">
              「恢复默认」只改表单,保存后才生效;渠道改动即时生效。
            </p>
          </Form>
        </Card>

        <Card
          className="st-card"
          title={cardTitle("推送渠道", "渠道改动即时生效,不参与底部保存")}
          size="small"
          extra={
            <Button
              type="primary"
              size="small"
              icon={<PlusOutlined />}
              onClick={() => setChannelOpen(true)}
            >
              新建渠道
            </Button>
          }
        >
          <p className="st-note">
            推送采用可插拔的 PushProvider:当前内置「通用 Webhook」与「导出」;
            飞书 / Discord / 邮件等平台后续仅需新增一个 provider 文件。
          </p>
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
                width: 200,
                render: (value: string) => (
                  <Typography.Text strong>{value}</Typography.Text>
                ),
              },
              {
                title: "推送地址",
                responsive: ["lg"],
                render: (_: unknown, record: PushChannel) => (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {channelTarget(record) || "未配置地址"}
                  </Typography.Text>
                ),
              },
              {
                title: "类型",
                dataIndex: "kind",
                width: 120,
                responsive: ["sm"],
                render: (value: string) => (
                  <Tag>
                    {providers?.find((p) => p.kind === value)?.label ?? value}
                  </Tag>
                ),
              },
              {
                title: "最近推送",
                width: 172,
                responsive: ["md"],
                render: (_: unknown, record: PushChannel) => {
                  const last = latestByChannel.get(record.id);
                  if (!last) {
                    return (
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        尚未推送
                      </Typography.Text>
                    );
                  }
                  const ok = last.status === "success";
                  return (
                    <Typography.Text
                      type={ok ? "success" : "danger"}
                      style={{ fontSize: 12 }}
                    >
                      {last.created_at
                        ? dayjs(last.created_at).format("MM-DD HH:mm")
                        : ""}
                      {" · "}
                      {ok ? "成功" : "失败"}
                    </Typography.Text>
                  );
                },
              },
              {
                title: "启用",
                dataIndex: "enabled",
                width: 80,
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
                width: 128,
                render: (_: unknown, record: PushChannel) => (
                  <Space size={2} className="st-row-actions">
                    <Tooltip title="发送一条测试推送">
                      <Button
                        type="text"
                        size="small"
                        className="st-icon-btn"
                        aria-label="测试推送"
                        icon={<SendOutlined />}
                        onClick={() => testChannelMutation.mutate(record.id)}
                        loading={
                          testChannelMutation.isPending &&
                          testChannelMutation.variables === record.id
                        }
                      />
                    </Tooltip>
                    <Tooltip title="编辑渠道">
                      <Button
                        type="text"
                        size="small"
                        className="st-icon-btn"
                        aria-label="编辑渠道"
                        icon={<EditOutlined />}
                        onClick={() => openChannelEditor(record)}
                      />
                    </Tooltip>
                    <Popconfirm
                      title="删除该渠道?"
                      description="渠道配置不可恢复,历史推送日志会保留。"
                      okText="删除"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                      onConfirm={() => deleteChannelMutation.mutate(record.id)}
                    >
                      <Tooltip title="删除渠道">
                        <Button
                          type="text"
                          size="small"
                          className="st-icon-btn is-danger"
                          aria-label="删除渠道"
                          icon={<DeleteOutlined />}
                        />
                      </Tooltip>
                    </Popconfirm>
                  </Space>
                ),
              },
            ]}
          />
        </Card>

        <p className="st-footnote">
          research-agent · 关键词驱动的研究与资讯采集(论文 / 技术 / 产业 /
          社区),支持三维打分、日报聚合与素材池检索。内部使用。
        </p>

        {dirtyCount > 0 && (
          <div className="st-savebar" role="status">
            <span className="st-savebar-text">
              <ExclamationCircleFilled /> 有 {dirtyCount} 处修改尚未保存
            </span>
            <Space size={8}>
              <Button onClick={discardAll}>放弃修改</Button>
              <Button type="primary" loading={saving} onClick={saveAll}>
                保存全部
              </Button>
            </Space>
          </div>
        )}

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
            <Input placeholder="例如:研讯平台" />
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
    </div>
  );
}
