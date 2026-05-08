"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Alert, App, Button, Card, Descriptions, Form, Input, Select,
  Space, Spin, Table, Tag, Typography,
} from "antd";
import { CheckCircleOutlined, CloseCircleOutlined, SaveOutlined, SyncOutlined } from "@ant-design/icons";
import {
  getAdvisorOverview,
  getChainDiscoveryStatus,
  getSchedulerInfo,
  getSettings,
  testLlmSettings,
  updateSettings,
} from "@/lib/api";

const { Title, Text, Paragraph } = Typography;

type ConfigStatus = "ready" | "missing" | "blocked" | "optional";

function StatusTag({ status }: { status: ConfigStatus }) {
  const meta = {
    ready: { color: "success", text: "已配置", icon: <CheckCircleOutlined /> },
    missing: { color: "error", text: "缺失", icon: <CloseCircleOutlined /> },
    blocked: { color: "error", text: "异常", icon: <CloseCircleOutlined /> },
    optional: { color: "default", text: "可选", icon: null },
  }[status];
  return <Tag color={meta.color} icon={meta.icon}>{meta.text}</Tag>;
}

function LevelTag({ level }: { level: string }) {
  const color = level === "必填" ? "red" : level === "完整能力必填" ? "orange" : "default";
  return <Tag color={color}>{level}</Tag>;
}

function ConfiguredTag({ configured }: { configured: boolean }) {
  return configured ? <Tag color="success">已配置</Tag> : <Tag color="error">未配置</Tag>;
}

export default function SettingsPage() {
  const { message } = App.useApp();
  const [settings, setSettings] = useState<any>({});
  const [scheduler, setScheduler] = useState<any>({ jobs: [] });
  const [advisor, setAdvisor] = useState<any>(null);
  const [discovery, setDiscovery] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testingLlm, setTestingLlm] = useState(false);
  const [llmTest, setLlmTest] = useState<any>(null);
  const [form] = Form.useForm();

  const loadData = () => {
    setLoading(true);
    Promise.all([
      getSettings().catch(() => ({})),
      getSchedulerInfo().catch(() => ({ jobs: [] })),
      getAdvisorOverview().catch(() => null),
      getChainDiscoveryStatus().catch(() => null),
    ]).then(([s, sch, overview, discoveryStatus]) => {
      setSettings(s);
      setScheduler(sch);
      setAdvisor(overview);
      setDiscovery(discoveryStatus);
      setLoading(false);
    });
  };

  useEffect(() => { loadData(); }, []);

  const llmConfigured = Boolean(settings.llm?.custom_configured);
  const discoveryStatus = discovery?.result?.status;
  const latestLlmError = discovery?.result?.error || "";
  const latestLlmErrorHint = /readtimeout|timeout/i.test(latestLlmError)
    ? "含义：Custom Base URL 可连接，但产业链发现的长上下文请求超时。需要换更快模型、提高网关/模型超时时间，或缩短产业链发现 prompt。"
    : "";
  const llmBlocked = discoveryStatus === "llm_unavailable" ||
    advisor?.capabilities?.some((item: any) => item.key === "llm" && item.status === "blocked");

  const requirements = useMemo(() => [
    {
      key: "infra",
      item: "PostgreSQL / Neo4j / Redis",
      level: "必填",
      status: settings.database && settings.neo4j && settings.redis ? "ready" : "missing",
      usage: "系统启动、行情存储、知识图谱和任务状态依赖",
      fill: "通常由 .env 和 Docker Compose 提供",
    },
    {
      key: "llm",
      item: "LLM 提供商",
      level: "必填",
      status: !llmConfigured ? "missing" : "ready",
      usage: "自动发现产业链、产业链结构化、深度归因分析",
      fill: "Custom Base URL / Token / Model",
    },
    {
      key: "tushare",
      item: "Tushare Token",
      level: "完整能力必填",
      status: settings.data_source?.tushare_configured ? "ready" : "missing",
      usage: "股票行业、财报、披露日、估值数据；缺失时部分路径降级到 AKShare",
      fill: "TUSHARE_TOKEN",
    },
    {
      key: "feishu",
      item: "飞书 Webhook",
      level: "可选",
      status: settings.feishu?.webhook_configured ? "ready" : "optional",
      usage: "后续用于预警和报告推送",
      fill: "FEISHU_WEBHOOK_URL",
    },
  ], [settings, llmConfigured]);

  const requiredIssues = requirements.filter((item) =>
    item.status !== "ready" && item.level !== "可选"
  );

  const requirementColumns = [
    { title: "配置项", dataIndex: "item", key: "item", width: 190 },
    { title: "级别", dataIndex: "level", key: "level", width: 130, render: (v: string) => <LevelTag level={v} /> },
    { title: "状态", dataIndex: "status", key: "status", width: 110, render: (v: ConfigStatus) => <StatusTag status={v} /> },
    { title: "用途", dataIndex: "usage", key: "usage" },
    { title: "需要填写", dataIndex: "fill", key: "fill", width: 260 },
  ];

  const schedulerColumns = [
    { title: "任务名", dataIndex: "name", key: "name" },
    { title: "下次执行", dataIndex: "next_run", key: "next_run", render: (v: string) => v || "-" },
  ];

  const onSave = async (values: any) => {
    const data: Record<string, any> = {};
    [
      "custom_base_url",
      "custom_api_key",
      "custom_model",
      "tushare_token",
      "feishu_webhook_url",
      "log_level",
    ].forEach((key) => {
      const value = values[key];
      if (value !== undefined && value !== null && String(value).trim() !== "") {
        data[key] = typeof value === "string" ? value.trim() : value;
      }
    });

    if (Object.keys(data).length === 0) {
      message.warning("没有需要更新的配置");
      return;
    }

    setSaving(true);
    try {
      await updateSettings(data);
      message.success("配置已保存");
      form.resetFields();
      loadData();
    } catch (e: any) {
      message.error(`保存失败: ${e.message}`);
    } finally {
      setSaving(false);
    }
  };

  const onTestLlm = async () => {
    const customBaseUrl = form.getFieldValue("custom_base_url") || settings.llm?.custom_base_url;
    setTestingLlm(true);
    setLlmTest(null);
    try {
      const result = await testLlmSettings({ custom_base_url: customBaseUrl });
      setLlmTest(result);
      if (result.ok) {
        message.success("Custom Base URL 测试通过");
      } else {
        message.error(result.message || "Custom Base URL 测试失败");
      }
    } catch (e: any) {
      setLlmTest({ ok: false, message: e.message, diagnosis: ["诊断接口调用失败"] });
      message.error(`测试失败: ${e.message}`);
    } finally {
      setTestingLlm(false);
    }
  };

  if (loading) return <Spin size="large" style={{ display: "block", margin: "100px auto" }} />;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16 }}>
        <div>
          <Title level={3} style={{ marginBottom: 4 }}>系统设置</Title>
          <Text type="secondary">补齐数据源、LLM 和通知配置，配置会写入 data/runtime_settings.json</Text>
        </div>
        <Button icon={<SyncOutlined />} onClick={loadData}>刷新状态</Button>
      </div>

      {requiredIssues.length > 0 ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginTop: 16 }}
          title="还有必填配置未就绪"
          description={requiredIssues.map((item) => `${item.item}: ${item.status === "blocked" ? "已配置但调用异常" : "未配置"}`).join("；")}
        />
      ) : (
        <Alert
          type="success"
          showIcon
          style={{ marginTop: 16 }}
          title="必填配置已就绪"
          description="可以继续执行数据采集、产业链发现和投研分析流程。"
        />
      )}

      <Card title="配置清单" style={{ marginTop: 16 }}>
        <Table rowKey="key" dataSource={requirements} columns={requirementColumns} pagination={false} size="small" />
      </Card>

      <Form form={form} layout="vertical" onFinish={onSave}>
        <Card title="必填：LLM 提供商" style={{ marginTop: 16 }}>
          <Paragraph type="secondary">
            自动发现产业链和深度归因统一走 Custom Base URL 配置，不再展示其他独立提供商配置。
          </Paragraph>
          {llmBlocked && (
            <Alert
              type="error"
              showIcon
              style={{ marginBottom: 16 }}
              title="最近一次产业链发现任务的 LLM 调用失败"
              description={
                <Space orientation="vertical" size={4}>
                  <Text>{latestLlmError || "这可能是历史任务结果；请点击下方测试按钮检查当前 Custom Base URL 是否可用。"}</Text>
                  {latestLlmErrorHint && <Text type="secondary">{latestLlmErrorHint}</Text>}
                </Space>
              }
            />
          )}
          <Space wrap style={{ marginBottom: 12 }}>
            <Text strong>当前状态</Text>
            <Tag color={settings.llm?.custom_configured ? "success" : "default"}>Custom {settings.llm?.custom_configured ? "已配置" : "未配置"}</Tag>
          </Space>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(220px, 1fr))", gap: 16 }}>
            <Form.Item name="custom_base_url" label={<span>Custom Base URL <Tag color="red">必填</Tag></span>}>
              <Input placeholder={settings.llm?.custom_base_url || "https://api.example.com/v1"} />
            </Form.Item>
            <Form.Item name="custom_api_key" label="Custom Token">
              <Input.Password placeholder="留空则不修改" />
            </Form.Item>
            <Form.Item name="custom_model" label="Custom Model">
              <Input placeholder={settings.llm?.custom_model || "gpt-4o-mini"} />
            </Form.Item>
          </div>
          <Space wrap>
            <Button onClick={onTestLlm} loading={testingLlm}>
              测试 Custom Base URL
            </Button>
            <Text type="secondary">会请求 Custom Base URL + /chat/completions，并展示 HTTP 状态和响应摘要。</Text>
          </Space>
          {llmTest && (
            <Alert
              type={llmTest.ok ? "success" : "error"}
              showIcon
              style={{ marginTop: 16 }}
              title={llmTest.message || (llmTest.ok ? "测试通过" : "测试失败")}
              description={
                <Space orientation="vertical" size={6}>
                  {(llmTest.diagnosis ?? []).map((item: string) => <Text key={item}>{item}</Text>)}
                  {llmTest.request_url && <Text type="secondary">请求地址: {llmTest.request_url}</Text>}
                  {llmTest.http_status && <Text type="secondary">HTTP 状态: {llmTest.http_status}</Text>}
                  {llmTest.model && <Text type="secondary">请求模型: {llmTest.model}</Text>}
                  {llmTest.response_preview && (
                    <Paragraph copyable style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}>
                      {llmTest.response_preview}
                    </Paragraph>
                  )}
                </Space>
              }
            />
          )}
        </Card>

        <Card title="完整能力必填：数据源" style={{ marginTop: 16 }}>
          <Paragraph type="secondary">
            Tushare 用于补齐股票行业、财报、披露日和估值。实时板块源由系统内置真实行情接口自动处理，不需要在这里配置东方财富参数。
          </Paragraph>
          <Form.Item
            name="tushare_token"
            label={<span>Tushare Token <ConfiguredTag configured={Boolean(settings.data_source?.tushare_configured)} /></span>}
          >
            <Input.Password placeholder="留空则不修改" style={{ maxWidth: 620 }} />
          </Form.Item>
        </Card>

        <Card title="可选：通知与运行参数" style={{ marginTop: 16 }}>
          <Form.Item
            name="feishu_webhook_url"
            label={<span>飞书 Webhook URL <ConfiguredTag configured={Boolean(settings.feishu?.webhook_configured)} /></span>}
          >
            <Input placeholder="留空则不修改" style={{ maxWidth: 620 }} />
          </Form.Item>
          <Form.Item name="log_level" label="日志级别">
            <Select
              placeholder={settings.log_level || "INFO"}
              allowClear
              style={{ width: 220 }}
              options={[
                { label: "DEBUG", value: "DEBUG" },
                { label: "INFO", value: "INFO" },
                { label: "WARNING", value: "WARNING" },
                { label: "ERROR", value: "ERROR" },
              ]}
            />
          </Form.Item>
          <Button type="primary" htmlType="submit" icon={<SaveOutlined />} loading={saving}>
            保存配置
          </Button>
        </Card>
      </Form>

      <Card title="基础设施（只读）" style={{ marginTop: 16 }}>
        <Descriptions column={2} bordered size="small">
          <Descriptions.Item label="PostgreSQL">
            {settings.database?.host}:{settings.database?.port}/{settings.database?.db}
          </Descriptions.Item>
          <Descriptions.Item label="PostgreSQL User">
            {settings.database?.user || "-"}
          </Descriptions.Item>
          <Descriptions.Item label="Neo4j">
            {settings.neo4j?.uri || "-"}
          </Descriptions.Item>
          <Descriptions.Item label="Redis">
            {settings.redis?.url || "-"}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="定时调度" style={{ marginTop: 16 }}>
        <Table
          dataSource={scheduler.jobs ?? []}
          columns={schedulerColumns}
          rowKey="id"
          pagination={false}
          size="small"
          locale={{ emptyText: "无调度任务" }}
        />
      </Card>
    </div>
  );
}
