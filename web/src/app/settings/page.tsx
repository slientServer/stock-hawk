"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Alert, App, Button, Card, Col, Descriptions, Form, Input, Progress, Row,
  Select, Space, Spin, Statistic, Table, Tag, Typography,
} from "antd";
import {
  CheckCircleOutlined, CloseCircleOutlined, PlayCircleOutlined,
  SaveOutlined, SyncOutlined,
} from "@ant-design/icons";
import {
  getDataCompleteness,
  getSchedulerInfo,
  getSettings,
  getStatsDetail,
  testLlmSettings,
  triggerWorkflow,
  updateSettings,
} from "@/lib/api";

const { Title, Text, Paragraph } = Typography;

type ConfigStatus = "ready" | "missing" | "blocked" | "optional";

const JOB_WORKFLOW_MAP: Record<string, string> = {
  finance_news_hourly: "finance_news",
  etf_analysis: "etf_analysis",
  pre_market_screen: "pre_market",
  pre_market_perf: "pre_market_perf",
  daily_kline_update: "daily_kline",
  main_flow_update: "main_flow",
};

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
  const [triggeringJobs, setTriggeringJobs] = useState<Record<string, boolean>>({});
  const [statsDetail, setStatsDetail] = useState<any>(null);
  const [dataCompleteness, setDataCompleteness] = useState<any>(null);

  const loadData = () => {
    setLoading(true);
    Promise.all([
      getSettings().catch(() => ({})),
      getSchedulerInfo().catch(() => ({ jobs: [] })),
      getStatsDetail().catch(() => null),
      getDataCompleteness().catch(() => null),
    ]).then(([s, sch, stats, completeness]) => {
      setSettings(s);
      setScheduler(sch);
      setStatsDetail(stats);
      setDataCompleteness(completeness);
      setLoading(false);
    });
  };

  useEffect(() => { loadData(); }, []);

  const llmConfigured = Boolean(settings.llm?.custom_configured);

  const handleTrigger = async (jobId: string) => {
    const workflowType = JOB_WORKFLOW_MAP[jobId];
    if (!workflowType) {
      message.warning("该任务暂不支持手动触发");
      return;
    }
    setTriggeringJobs((prev) => ({ ...prev, [jobId]: true }));
    try {
      const res = await triggerWorkflow(workflowType);
      if (res.error) {
        message.error(`触发失败: ${res.error}`);
      } else {
        message.success(`工作流 ${workflowType} 已触发`);
      }
    } catch (e: any) {
      message.error(`触发异常: ${e.message}`);
    } finally {
      setTriggeringJobs((prev) => ({ ...prev, [jobId]: false }));
    }
  };

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
    {
      title: "操作",
      key: "action",
      width: 130,
      render: (_: any, record: any) => {
        const canTrigger = JOB_WORKFLOW_MAP[record.id] !== undefined;
        return (
          <Button
            type="link"
            size="small"
            icon={<PlayCircleOutlined />}
            disabled={!canTrigger}
            loading={triggeringJobs[record.id] || false}
            onClick={() => handleTrigger(record.id)}
          >
            立即执行
          </Button>
        );
      },
    },
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

      <Card title="数据概览" style={{ marginTop: 16 }}>
        {dataCompleteness && (
          <div style={{ marginBottom: 24, textAlign: "center" }}>
            <Progress
              type="dashboard"
              percent={dataCompleteness.overall_score ?? 0}
              format={(pct) => `${pct}分`}
            />
            <Text type="secondary" style={{ display: "block", marginTop: 8 }}>
              数据完备性综合评分
            </Text>
          </div>
        )}

        {statsDetail && (
          <Row gutter={[16, 16]}>
            <Col span={8}>
              <Statistic title="股票总数" value={statsDetail.stocks?.total ?? 0} />
            </Col>
            <Col span={8}>
              <Statistic title="日K线记录" value={statsDetail.klines?.total ?? 0} />
              <Text type="secondary">
                覆盖 {statsDetail.klines?.stock_coverage ?? 0} 只股票
                {statsDetail.klines?.date_to && ` | 最新: ${statsDetail.klines.date_to}`}
              </Text>
            </Col>
            <Col span={8}>
              <Statistic title="资金流记录" value={statsDetail.fund_flow?.total ?? 0} />
              <Text type="secondary">
                {statsDetail.fund_flow?.date_to ? `最新: ${statsDetail.fund_flow.date_to}` : "暂无数据"}
              </Text>
            </Col>
            <Col span={8}>
              <Statistic title="财报记录" value={statsDetail.financials?.total ?? 0} />
              <Text type="secondary">
                覆盖 {statsDetail.financials?.stock_coverage ?? 0} 只股票
                {statsDetail.financials?.date_to && ` | 最新: ${statsDetail.financials.date_to}`}
              </Text>
            </Col>
            <Col span={8}>
              <Statistic title="股东户数记录" value={statsDetail.shareholders?.total ?? 0} />
              <Text type="secondary">
                覆盖 {statsDetail.shareholders?.stock_coverage ?? 0} 只股票
                {statsDetail.shareholders?.date_to && ` | 最新: ${statsDetail.shareholders.date_to}`}
              </Text>
            </Col>
          </Row>
        )}

        {!statsDetail && !dataCompleteness && (
          <Text type="secondary">暂无数据统计信息</Text>
        )}

        {dataCompleteness?.recommendations?.length > 0 && (
          <div style={{ marginTop: 24 }}>
            <Text strong>修复建议</Text>
            <Table
              dataSource={dataCompleteness.recommendations}
              rowKey={(r: any) => r.task || r.action}
              pagination={false}
              size="small"
              style={{ marginTop: 8 }}
              columns={[
                {
                  title: "优先级", dataIndex: "priority", key: "priority", width: 80,
                  render: (v: string) => <Tag color={v === "P0" ? "red" : "orange"}>{v}</Tag>,
                },
                { title: "操作", dataIndex: "action", key: "action" },
                { title: "影响", dataIndex: "impact", key: "impact" },
              ]}
            />
          </div>
        )}
      </Card>
    </div>
  );
}
