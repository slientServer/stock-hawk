"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Alert, App, Button, Card, Descriptions, Form, Input, Select,
  Space, Spin, Table, Tag, Typography,
} from "antd";
import { CheckCircleOutlined, CloseCircleOutlined, SaveOutlined, SyncOutlined } from "@ant-design/icons";
import {
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
    ]).then(([s, sch]) => {
      setSettings(s);
      setScheduler(sch);
      setLoading(false);
    });
  };

  useEffect(() => { loadData(); }, []);

  const llmConfigured = Boolean(settings.llm?.custom_configured);

  const requirements = useMemo(() => [
    {
      key: "infra",
      item: "PostgreSQL / Redis",
      level: "必填",
      status: settings.database && settings.redis ? "ready" : "missing",
      usage: "系统启动、行情/资讯/分析结果存储和任务状态依赖",
      fill: "通常由 .env 和 Docker Compose 提供",
    },
    {
      key: "llm",
      item: "LLM 提供商",
      level: "必填",
      status: !llmConfigured ? "missing" : "ready",
      usage: "ETF 分析、持续上涨个股分析、资讯去重汇总",
      fill: "Custom Base URL / Token / Model",
    },
    {
      key: "tushare",
      item: "Tushare Token",
      level: "完整能力必填",
      status: settings.data_source?.tushare_configured ? "ready" : "missing",
      usage: "ETF 份额/规模等增强数据；缺失时 ETF 分析会标注数据缺口",
      fill: "TUSHARE_TOKEN",
    },
    {
      key: "feishu",
      item: "飞书 Webhook",
      level: "可选",
      status: settings.feishu?.webhook_configured ? "ready" : "optional",
      usage: "后续用于任务状态和重要结果通知",
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
          description="可以执行 ETF 分析、持续上涨分析和资讯中心汇总流程。"
        />
      )}

      <Card title="配置清单" style={{ marginTop: 16 }}>
        <Table rowKey="key" dataSource={requirements} columns={requirementColumns} pagination={false} size="small" />
      </Card>

      <Form form={form} layout="vertical" onFinish={onSave}>
        <Card title="必填：LLM 提供商" style={{ marginTop: 16 }}>
          <Paragraph type="secondary">
            ETF 分析、持续上涨个股分析和资讯中心汇总统一走 Custom Base URL 配置。
          </Paragraph>
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
            Tushare 用于补齐 ETF 份额、规模等增强数据；未配置时相关分析会标注数据缺口。
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
