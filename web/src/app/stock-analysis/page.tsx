"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  App,
  AutoComplete,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Input,
  Row,
  Space,
  Spin,
  Progress,
  Statistic,
  Switch,
  Table,
  Tag,
  Typography,
} from "antd";
import {
  BarChartOutlined,
  HistoryOutlined,
  ReloadOutlined,
  SaveOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import { useRouter, useSearchParams } from "next/navigation";
import type { ColumnsType } from "antd/es/table";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  createStockAnalysisTask,
  getLatestStockAnalysis,
  getStocks,
  getStockAnalysisHistory,
  getStockAnalysisTasks,
} from "@/lib/api";

const { Title, Text, Paragraph } = Typography;

function money(value?: number | null) {
  if (value == null) return "-";
  const sign = value > 0 ? "+" : "";
  if (Math.abs(value) >= 100000000) return `${sign}${(value / 100000000).toFixed(2)}亿`;
  if (Math.abs(value) >= 10000) return `${sign}${(value / 10000).toFixed(2)}万`;
  return `${sign}${Number(value).toFixed(2)}`;
}

function price(value?: number | null) {
  return value == null ? "-" : Number(value).toFixed(2);
}

function shortTime(value?: string | null) {
  if (!value) return "-";
  return value.length > 10 ? value.slice(5, 16).replace("T", " ") : value;
}

function actionTag(action?: string, label?: string) {
  const colors: Record<string, string> = {
    buy: "red",
    add: "volcano",
    hold: "blue",
    watch: "default",
    reduce: "green",
    avoid: "orange",
  };
  return <Tag color={colors[action || ""] || "default"}>{label || action || "-"}</Tag>;
}

function confidenceTag(value?: string) {
  const color = value === "high" ? "green" : value === "medium" ? "blue" : "orange";
  return <Tag color={color}>{value || "-"}</Tag>;
}

function displayText(value: any) {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function evidenceList(value: any) {
  if (Array.isArray(value)) return value.map(displayText).filter(Boolean);
  if (value == null) return [];
  if (typeof value === "object") {
    return Object.entries(value)
      .map(([key, item]) => `${key}: ${displayText(item)}`)
      .filter(Boolean);
  }
  return [displayText(value)].filter(Boolean);
}

function taskStatusTag(status?: string) {
  if (status === "completed") return <Tag color="green">完成</Tag>;
  if (status === "running") return <Tag color="blue">运行中</Tag>;
  if (status === "queued") return <Tag color="default">排队</Tag>;
  if (status === "failed") return <Tag color="red">失败</Tag>;
  return <Tag>{status || "-"}</Tag>;
}

export default function StockAnalysisPage() {
  return (
    <Suspense fallback={<Spin size="large" style={{ display: "block", margin: "80px auto" }} />}>
      <StockAnalysisClient />
    </Suspense>
  );
}

function StockAnalysisClient() {
  const { message } = App.useApp();
  const router = useRouter();
  const params = useSearchParams();
  const initialCode = params.get("code") || "";
  const [code, setCode] = useState(initialCode);
  const [searchText, setSearchText] = useState(initialCode);
  const [stockOptions, setStockOptions] = useState<any[]>([]);
  const [searchingStocks, setSearchingStocks] = useState(false);
  const [analysis, setAnalysis] = useState<any>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [tasks, setTasks] = useState<any[]>([]);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [useLlm, setUseLlm] = useState(true);

  const loadHistory = useCallback((targetCode?: string) => {
    setLoading(true);
    const normalized = (targetCode ?? "").trim();
    Promise.all([
      normalized ? getLatestStockAnalysis(normalized).catch(() => null) : Promise.resolve(null),
      getStockAnalysisHistory({ code: normalized || undefined, limit: 40 }).catch(() => []),
    ]).then(([latest, rows]) => {
      setAnalysis(latest);
      setHistory(rows);
      setLoading(false);
    });
  }, []);

  const applyTaskResult = useCallback((task: any) => {
    if (!task?.result) return;
    setAnalysis(task.result);
    setHistory((prev) => [task.result, ...prev.filter((item) => item.id !== task.result.id)].slice(0, 40));
    router.replace(`/stock-analysis?code=${encodeURIComponent(task.result.code || task.code)}`, { scroll: false });
  }, [router]);

  const refreshTasks = useCallback(async () => {
    const rows = await getStockAnalysisTasks(30).catch(() => []);
    setTasks(rows);
    if (!activeTaskId) return;
    const active = rows.find((item: any) => item.task_id === activeTaskId);
    if (!active) return;
    if (active.status === "completed") {
      applyTaskResult(active);
      setActiveTaskId(null);
      message.success("分析完成，结果已保存");
    }
    if (active.status === "failed") {
      setActiveTaskId(null);
      message.error(active.error_message || "分析任务失败");
    }
  }, [activeTaskId, applyTaskResult, message]);

  useEffect(() => {
    setCode(initialCode);
    setSearchText(initialCode);
    loadHistory(initialCode);
  }, [initialCode, loadHistory]);

  useEffect(() => {
    refreshTasks();
  }, [refreshTasks]);

  useEffect(() => {
    const text = searchText.trim();
    if (!text) {
      setStockOptions([]);
      return;
    }
    const timer = window.setTimeout(() => {
      setSearchingStocks(true);
      getStocks({ keyword: text, limit: 12 })
        .then((rows) => {
          setStockOptions((rows || []).map((item: any) => ({
            value: item.code,
            label: (
              <Space>
                <Text strong>{item.name || item.code}</Text>
                <Text type="secondary">{item.code}</Text>
                {item.industry && <Tag>{item.industry}</Tag>}
              </Space>
            ),
          })));
        })
        .catch(() => setStockOptions([]))
        .finally(() => setSearchingStocks(false));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [searchText]);

  useEffect(() => {
    if (!tasks.some((task) => task.status === "queued" || task.status === "running")) return;
    const timer = window.setInterval(refreshTasks, 1500);
    return () => window.clearInterval(timer);
  }, [tasks, refreshTasks]);

  const handleRun = async () => {
    const normalized = code.trim();
    if (!normalized) {
      message.warning("请输入股票代码");
      return;
    }
    setRunning(true);
    try {
      const task = await createStockAnalysisTask({ code: normalized, use_llm: useLlm, save: true, lookback_days: 180 });
      setActiveTaskId(task.task_id);
      setTasks((prev) => [task, ...prev.filter((item) => item.task_id !== task.task_id)].slice(0, 30));
      router.replace(`/stock-analysis?code=${encodeURIComponent(task.code || normalized)}`, { scroll: false });
      message.success("分析任务已发起");
    } catch (e: any) {
      message.error(e?.message || "任务创建失败");
    } finally {
      setRunning(false);
    }
  };

  const columns: ColumnsType<any> = useMemo(() => [
    {
      title: "时间",
      dataIndex: "analysis_time",
      key: "analysis_time",
      width: 135,
      render: shortTime,
    },
    {
      title: "标的",
      key: "stock",
      width: 140,
      render: (_: any, row: any) => (
        <a onClick={() => {
          setCode(row.code);
          setAnalysis(row);
          router.replace(`/stock-analysis?code=${encodeURIComponent(row.code)}`, { scroll: false });
        }}>
          <Text strong>{row.name || row.code}</Text><br />
          <Text type="secondary">{row.code}</Text>
        </a>
      ),
    },
    {
      title: "建议",
      key: "action",
      width: 90,
      render: (_: any, row: any) => actionTag(row.action, row.action_label),
    },
    {
      title: "评分",
      dataIndex: "score",
      key: "score",
      width: 90,
      render: (value: number) => value == null ? "-" : Number(value).toFixed(1),
    },
    {
      title: "置信度",
      dataIndex: "confidence",
      key: "confidence",
      width: 90,
      render: confidenceTag,
    },
    {
      title: "摘要",
      dataIndex: "summary",
      key: "summary",
      render: (value: string) => <Paragraph style={{ margin: 0 }} ellipsis={{ rows: 2 }}>{value || "-"}</Paragraph>,
    },
  ], [router]);

  const taskColumns: ColumnsType<any> = useMemo(() => [
    {
      title: "发起时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 135,
      render: shortTime,
    },
    {
      title: "标的",
      key: "stock",
      width: 150,
      render: (_: any, row: any) => (
        <Space orientation="vertical" size={0}>
          <Text strong>{row.name || row.code}</Text>
          <Text type="secondary">{row.code}</Text>
        </Space>
      ),
    },
    {
      title: "状态",
      key: "status",
      width: 110,
      render: (_: any, row: any) => taskStatusTag(row.status),
    },
    {
      title: "进度",
      key: "progress",
      width: 240,
      render: (_: any, row: any) => <Progress percent={Number(row.progress || 0)} size="small" status={row.status === "failed" ? "exception" : undefined} />,
    },
    {
      title: "当前步骤",
      dataIndex: "step",
      key: "step",
      render: (value: string, row: any) => (
        <Space orientation="vertical" size={2}>
          <Text>{value || "-"}</Text>
          {row.error_message && <Text type="danger">{row.error_message}</Text>}
        </Space>
      ),
    },
    {
      title: "结果",
      key: "result",
      width: 130,
      render: (_: any, row: any) => row.status === "completed" && row.result ? (
        <Button size="small" onClick={() => applyTaskResult(row)}>查看结果</Button>
      ) : row.action ? actionTag(row.action, row.action_label) : "-",
    },
  ], [applyTaskResult]);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, marginBottom: 16 }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>个股分析</Title>
          <Text type="secondary">价格、K线、资金、热度、资讯、公告和政策</Text>
        </div>
        <Space wrap>
          <Switch checked={useLlm} onChange={setUseLlm} checkedChildren="LLM" unCheckedChildren="规则" />
          <AutoComplete
            value={code}
            options={stockOptions}
            onChange={(value) => {
              setCode(value);
              setSearchText(value);
            }}
            onSearch={setSearchText}
            onSelect={(value) => {
              setCode(value);
              setSearchText(value);
            }}
            filterOption={false}
            notFoundContent={searchingStocks ? <Spin size="small" /> : <Empty description="无匹配股票" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
            style={{ width: 260 }}
          >
            <Input
              onPressEnter={handleRun}
              placeholder="输入代码或名称搜索"
              prefix={<SearchOutlined />}
            />
          </AutoComplete>
          <Button icon={<ReloadOutlined />} onClick={() => loadHistory(code)} loading={loading}>刷新</Button>
          <Button type="primary" icon={<SaveOutlined />} onClick={handleRun} loading={running}>发起分析任务</Button>
        </Space>
      </div>

      <Card title="任务列表" style={{ marginBottom: 16 }}>
        <Table
          dataSource={tasks}
          columns={taskColumns}
          rowKey={(row: any) => row.task_id}
          pagination={false}
          size="small"
          scroll={{ x: 900 }}
          locale={{ emptyText: <Empty description="暂无分析任务" /> }}
        />
      </Card>

      {loading ? (
        <Spin size="large" style={{ display: "block", margin: "80px auto" }} />
      ) : analysis ? (
        <AnalysisView analysis={analysis} />
      ) : (
        <Empty description="暂无分析结果" style={{ margin: "80px 0" }} />
      )}

      <Card title={<Space><HistoryOutlined />历史分析</Space>} style={{ marginTop: 16 }}>
        <Table
          dataSource={history}
          columns={columns}
          rowKey={(row: any) => row.id || `${row.code}-${row.analysis_time}`}
          pagination={{ pageSize: 10 }}
          size="small"
          scroll={{ x: 820 }}
          locale={{ emptyText: <Empty description="暂无历史记录" /> }}
        />
      </Card>
    </div>
  );
}

function AnalysisView({ analysis }: { analysis: any }) {
  const result = analysis.result || {};
  const input = analysis.input_snapshot || {};
  const quote = input.quote || {};
  const metrics = input.kline_metrics || {};
  const flow = input.stock_flow || {};
  const operation = result.operation_advice || {};
  const scores = result.scores || {};
  const sections = result.sections || {};
  const chartData = buildChartData(input);

  return (
    <>
      {(analysis.data_gaps || []).length > 0 && (
        <Alert
          type="info"
          showIcon
          title="数据缺口"
          description={(analysis.data_gaps || []).join("；")}
          style={{ marginBottom: 16 }}
        />
      )}

      <Row gutter={[16, 16]}>
        <Col xs={12} lg={6}><Card><Statistic title="当前价" value={analysis.current_price ?? quote.price ?? "-"} precision={2} /></Card></Col>
        <Col xs={12} lg={6}><Card><Statistic title="综合评分" value={analysis.score ?? result.score ?? "-"} precision={1} /></Card></Col>
        <Col xs={12} lg={6}><Card><Statistic title="近20日涨跌" value={metrics.return_20d ?? "-"} suffix={metrics.return_20d == null ? "" : "%"} precision={2} /></Card></Col>
        <Col xs={12} lg={6}><Card><Statistic title="5日主力净流入" value={money(flow.main_net_5d)} /></Card></Col>
      </Row>

      <Card style={{ marginTop: 16 }}>
        <Space orientation="vertical" size={12} style={{ width: "100%" }}>
          <Space wrap>
            <Title level={4} style={{ margin: 0 }}>{analysis.name || analysis.code} <Text type="secondary">{analysis.code}</Text></Title>
            {actionTag(analysis.action || result.action, analysis.action_label || result.action_label)}
            {confidenceTag(analysis.confidence || result.confidence)}
            <Tag>{quote.is_realtime ? "实时" : "入库"} · {shortTime(quote.quote_time || analysis.analysis_time)}</Tag>
            {analysis.llm_used && <Tag color="purple">LLM增强</Tag>}
          </Space>
          <Paragraph style={{ margin: 0 }}>{analysis.summary || result.summary}</Paragraph>
        </Space>
      </Card>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={10}>
          <Card title="操作建议" style={{ height: "100%" }}>
            <Descriptions size="small" column={1}>
              <Descriptions.Item label="执行">{operation.primary || "-"}</Descriptions.Item>
              <Descriptions.Item label="买入区间">{Array.isArray(operation.entry_zone) ? operation.entry_zone.map(price).join(" - ") : "-"}</Descriptions.Item>
              <Descriptions.Item label="目标价">{price(operation.target_price)}</Descriptions.Item>
              <Descriptions.Item label="止损价">{price(operation.stop_loss)}</Descriptions.Item>
              <Descriptions.Item label="仓位上限">{operation.max_position_pct == null ? "-" : `${operation.max_position_pct}%`}</Descriptions.Item>
              <Descriptions.Item label="周期">{operation.time_horizon || analysis.time_horizon || "-"}</Descriptions.Item>
              <Descriptions.Item label="加仓条件">{operation.add_condition || "-"}</Descriptions.Item>
              <Descriptions.Item label="减仓条件">{operation.reduce_condition || "-"}</Descriptions.Item>
              <Descriptions.Item label="证伪条件">{operation.invalidation || "-"}</Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
        <Col xs={24} lg={14}>
          <PriceFlowChart data={chartData} />
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={12} md={6}><Card><Statistic title="技术面" value={scores.technical ?? "-"} precision={1} /></Card></Col>
        <Col xs={12} md={6}><Card><Statistic title="资金面" value={scores.fund_flow ?? "-"} precision={1} /></Card></Col>
        <Col xs={12} md={6}><Card><Statistic title="市场热度" value={scores.market_heat ?? "-"} precision={1} /></Card></Col>
        <Col xs={12} md={6}><Card><Statistic title="事件面" value={scores.event ?? "-"} precision={1} /></Card></Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={12}><SectionCard title="K线结构" section={sections.price_kline} /></Col>
        <Col xs={24} lg={12}><SectionCard title="资金流动" section={sections.fund_flow} /></Col>
        <Col xs={24} lg={12}><SectionCard title="市场热情" section={sections.market_heat} /></Col>
        <Col xs={24} lg={12}><SectionCard title="资讯" section={sections.news} /></Col>
        <Col xs={24} lg={12}><SectionCard title="公告" section={sections.announcements} /></Col>
        <Col xs={24} lg={12}><SectionCard title="政策" section={sections.policy} /></Col>
      </Row>

      {(result.risks || []).length > 0 && (
        <Alert
          type="warning"
          showIcon
          title="风险条件"
          description={(result.risks || []).join("；")}
          style={{ marginTop: 16 }}
        />
      )}
    </>
  );
}

function buildChartData(input: any) {
  const flowsByDate = new Map<string, any>();
  for (const row of input?.stock_flow?.trend || []) {
    if (row.trade_date) flowsByDate.set(row.trade_date, row);
  }
  return (input?.kline || []).slice(-80).map((row: any) => {
    const flow = flowsByDate.get(row.trade_date) || {};
    return {
      date: row.trade_date,
      label: row.trade_date?.slice(5) || "-",
      close: row.close,
      main_net: flow.main_net == null ? null : Number((flow.main_net / 10000).toFixed(2)),
    };
  });
}

function PriceFlowChart({ data }: { data: any[] }) {
  return (
    <Card title={<Space><BarChartOutlined />价格与资金</Space>}>
      {data.length > 0 ? (
        <div style={{ height: 310 }}>
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" minTickGap={22} tick={{ fontSize: 12 }} />
              <YAxis yAxisId="price" width={48} tick={{ fontSize: 12 }} domain={["dataMin", "dataMax"]} />
              <YAxis yAxisId="flow" orientation="right" width={48} tick={{ fontSize: 12 }} />
              <Tooltip
                formatter={(value: any, name: any) => [
                  name === "main_net" ? `${value}万` : value,
                  name === "main_net" ? "主力净流入" : "收盘价",
                ]}
                labelFormatter={(_, items) => items?.[0]?.payload?.date || "-"}
              />
              <ReferenceLine yAxisId="flow" y={0} stroke="#999" strokeDasharray="3 3" />
              <Bar yAxisId="flow" dataKey="main_net" fill="#8c8c8c" barSize={8} />
              <Line yAxisId="price" type="monotone" dataKey="close" stroke="#1677ff" strokeWidth={2} dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <Empty description="暂无图表数据" />
      )}
    </Card>
  );
}

function SectionCard({ title, section }: { title: string; section?: any }) {
  const evidence = evidenceList(section?.evidence);
  const view = displayText(section?.view);
  return (
    <Card title={title} style={{ height: "100%" }}>
      <Paragraph style={{ marginBottom: 10 }}>{view || "-"}</Paragraph>
      <Space orientation="vertical" size={6} style={{ width: "100%" }}>
        {evidence.length > 0 ? evidence.map((item: string, index: number) => (
          <Text key={`${title}-${index}`} type="secondary" style={{ fontSize: 13, wordBreak: "break-word" }}>
            {item}
          </Text>
        )) : <Text type="secondary">-</Text>}
      </Space>
    </Card>
  );
}
