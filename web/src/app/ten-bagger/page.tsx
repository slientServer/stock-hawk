"use client";

import { useState, useCallback, useEffect } from "react";
import {
  Button,
  Card,
  Col,
  Descriptions,
  Divider,
  Empty,
  Row,
  Segmented,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
  App,
} from "antd";
import { RiseOutlined, ThunderboltOutlined, RobotOutlined, EyeOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip as RechartTooltip,
  XAxis,
  YAxis,
} from "recharts";
import { runRisingScreener, getKline, analyzeStockRising, addWatchItem } from "@/lib/api";

const { Title, Text } = Typography;

function pctColor(v: number | null | undefined) {
  if (v == null) return undefined;
  if (v >= 30) return "#cf1322";
  if (v >= 10) return "#d46b08";
  if (v < 0) return "#389e0d";
  return "#1677ff";
}

function fmt(v: number | null | undefined, digits = 1) {
  if (v == null) return "-";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

// ─── 日 K 图（懒加载，行展开时挂载） ──────────────────────────────────────────
function StockKlineChart({ code, startClose }: { code: string; startClose?: number }) {
  const [kline, setKline] = useState<any[] | null>(null);

  useEffect(() => {
    getKline(code, 180)
      .then(setKline)
      .catch(() => setKline([]));
  }, [code]);

  if (kline === null) {
    return (
      <div style={{ height: 200, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <Spin />
      </div>
    );
  }
  if (!kline.length) return <Text type="secondary">无 K 线数据</Text>;

  const chartData = kline.map((item) => ({
    date: (item.trade_date as string)?.slice(5),
    close: Number(item.close),
  }));

  const prices = chartData.map((d) => d.close);
  const minP = Math.min(...prices) * 0.985;
  const maxP = Math.max(...prices) * 1.015;
  const tickInterval = Math.max(1, Math.floor(chartData.length / 10));

  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={chartData} margin={{ top: 8, right: 20, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
        <XAxis dataKey="date" tick={{ fontSize: 10 }} interval={tickInterval} />
        <YAxis
          domain={[minP, maxP]}
          tick={{ fontSize: 10 }}
          width={60}
          tickFormatter={(v) => v.toFixed(2)}
        />
        <RechartTooltip
          formatter={(v) => [`¥${Number(v).toFixed(2)}`, "收盘价"]}
          labelFormatter={(l) => `${l}`}
        />
        {startClose != null && (
          <ReferenceLine
            y={startClose}
            stroke="#faad14"
            strokeDasharray="4 4"
            label={{ value: "起点", position: "insideTopRight", fontSize: 10, fill: "#faad14" }}
          />
        )}
        <Line type="monotone" dataKey="close" stroke="#1677ff" dot={false} strokeWidth={1.5} />
      </LineChart>
    </ResponsiveContainer>
  );
}

// ─── 筛选周期配置 ─────────────────────────────────────────────────────────────
const PERIOD_OPTIONS = [
  { label: "6个月", value: "6m" },
  { label: "5个月", value: "5m" },
  { label: "4个月", value: "4m" },
  { label: "3个月", value: "3m" },
  { label: "2个月", value: "2m" },
  { label: "1月≥80%天", value: "1m_day" },
];

// ─── 主页面 ───────────────────────────────────────────────────────────────────
export default function RisingStockPage() {
  const { message } = App.useApp();
  const [running, setRunning] = useState(false);
  const [data, setData] = useState<any>(null);
  const [filterMode, setFilterMode] = useState("4m");
  const [analyses, setAnalyses] = useState<Record<string, any>>({});
  const [analyzing, setAnalyzing] = useState<Record<string, boolean>>({});

  const handleRun = useCallback(async (mode?: string) => {
    const targetMode = mode ?? filterMode;
    setRunning(true);
    try {
      const result = await runRisingScreener(targetMode);
      setData(result);
      message.success(`筛选完成，共 ${result.total_count} 只股票`);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "筛选失败");
    } finally {
      setRunning(false);
    }
  }, [filterMode, message]);

  // 页面挂载时自动以默认周期运行一次，展示最新数据
  useEffect(() => {
    handleRun(filterMode);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleFilterChange = useCallback((mode: string) => {
    setFilterMode(mode);
    handleRun(mode);
  }, [handleRun]);

  const handleAnalyze = useCallback(async (record: any) => {
    setAnalyzing((prev) => ({ ...prev, [record.code]: true }));
    try {
      const result = await analyzeStockRising({
        code: record.code,
        name: record.name,
        industry: record.industry,
        market_cap_yi: record.market_cap_yi,
        return_6m_pct: record.return_6m_pct,
        return_3m_pct: record.return_3m_pct,
        return_1m_pct: record.return_1m_pct,
        up_months: record.up_months,
        total_months: record.total_months,
        latest_close: record.latest_close,
        start_close: record.start_close,
        worst_month_pct: record.worst_month_pct,
        best_month_pct: record.best_month_pct,
      });
      setAnalyses((prev) => ({ ...prev, [record.code]: result }));
    } catch (e) {
      message.error(e instanceof Error ? e.message : "AI 分析失败");
    } finally {
      setAnalyzing((prev) => ({ ...prev, [record.code]: false }));
    }
  }, [message]);

  const allResults: any[] = data?.results ?? [];
  const results = allResults;

  const columns: ColumnsType<any> = [
    {
      title: "#",
      key: "rank",
      width: 48,
      render: (_: any, __: any, idx: number) => (
        <Text type="secondary" style={{ fontSize: 12 }}>{idx + 1}</Text>
      ),
    },
    {
      title: "代码",
      dataIndex: "code",
      key: "code",
      width: 80,
      render: (v: string) => <Text strong>{v}</Text>,
    },
    {
      title: "名称",
      dataIndex: "name",
      key: "name",
      width: 95,
    },
    {
      title: "行业",
      dataIndex: "industry",
      key: "industry",
      width: 100,
      render: (v: string) => <Text type="secondary">{v || "-"}</Text>,
    },
    {
      title: "市值(亿)",
      dataIndex: "market_cap_yi",
      key: "market_cap_yi",
      width: 90,
      sorter: (a: any, b: any) => (a.market_cap_yi ?? 0) - (b.market_cap_yi ?? 0),
      render: (v: number) => (v != null ? v.toFixed(1) : "-"),
    },
    {
      title: (
        <Tooltip title="从 ~6 个月前第一个交易日到最新收盘的整体涨幅">
          6月涨幅
        </Tooltip>
      ),
      dataIndex: "return_6m_pct",
      key: "return_6m_pct",
      width: 90,
      sorter: (a: any, b: any) => (a.return_6m_pct ?? 0) - (b.return_6m_pct ?? 0),
      defaultSortOrder: "descend",
      render: (v: number) => (
        <Text strong style={{ color: pctColor(v) }}>{fmt(v)}</Text>
      ),
    },
    {
      title: "3月涨幅",
      dataIndex: "return_3m_pct",
      key: "return_3m_pct",
      width: 80,
      sorter: (a: any, b: any) => (a.return_3m_pct ?? 0) - (b.return_3m_pct ?? 0),
      render: (v: number) => <Text style={{ color: pctColor(v) }}>{fmt(v)}</Text>,
    },
    {
      title: "1月涨幅",
      dataIndex: "return_1m_pct",
      key: "return_1m_pct",
      width: 80,
      sorter: (a: any, b: any) => (a.return_1m_pct ?? 0) - (b.return_1m_pct ?? 0),
      render: (v: number) => <Text style={{ color: pctColor(v) }}>{fmt(v)}</Text>,
    },
    {
      title: (
        <Tooltip title="近 6 个月中环比上月收涨的月数 / 统计月数">
          上涨月数
        </Tooltip>
      ),
      key: "up_months",
      width: 90,
      sorter: (a: any, b: any) => (a.up_months ?? 0) - (b.up_months ?? 0),
      render: (_: any, r: any) => {
        const ratio = r.up_months / (r.total_months || 5);
        return (
          <Tag color={ratio >= 0.8 ? "red" : ratio >= 0.6 ? "orange" : "blue"}>
            {r.up_months}/{r.total_months}
          </Tag>
        );
      },
    },
    {
      title: (
        <Tooltip title="统计区间内最差月的环比涨幅（绿色=跌幅小）">
          最差月
        </Tooltip>
      ),
      dataIndex: "worst_month_pct",
      key: "worst_month_pct",
      width: 80,
      sorter: (a: any, b: any) => (a.worst_month_pct ?? -999) - (b.worst_month_pct ?? -999),
      render: (v: number) => (
        <Text style={{ color: v != null && v < 0 ? "#389e0d" : "#cf1322" }}>{fmt(v)}</Text>
      ),
    },
    {
      title: "最强月",
      dataIndex: "best_month_pct",
      key: "best_month_pct",
      width: 80,
      sorter: (a: any, b: any) => (a.best_month_pct ?? 0) - (b.best_month_pct ?? 0),
      render: (v: number) => <Text style={{ color: pctColor(v) }}>{fmt(v)}</Text>,
    },
    {
      title: "最新价",
      dataIndex: "latest_close",
      key: "latest_close",
      width: 80,
      sorter: (a: any, b: any) => (a.latest_close ?? 0) - (b.latest_close ?? 0),
      render: (v: number) => (v != null ? `¥${v.toFixed(2)}` : "-"),
    },
    {
      title: "操作",
      key: "action",
      width: 65,
      fixed: "right" as const,
      render: (_: any, r: any) => (
        <Button size="small" icon={<EyeOutlined />}
          onClick={() => addWatchItem({ code: r.code, name: r.name, industry: r.industry, source: "ten_bagger" }).then(() => {}).catch(() => {})}
        >关注</Button>
      ),
    },
  ];

  return (
    <div>
      {/* 标题栏 */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          marginBottom: 16,
          flexWrap: "wrap",
          gap: 8,
        }}
      >
        <div>
          <Title level={3} style={{ margin: 0 }}>
            <RiseOutlined style={{ marginRight: 8, color: "#52c41a" }} />
            持续上涨选股
          </Title>
          <Text type="secondary">
            筛选最近 6 个月月月环比上涨（至少 4/5 个月为正）且整体收益为正的 A 股，展示日 K 走势
          </Text>
        </div>
        <Button
          type="primary"
          size="large"
          icon={<ThunderboltOutlined />}
          loading={running}
          onClick={() => handleRun()}
        >
          {running ? "筛选中..." : "开始筛选"}
        </Button>
      </div>

      {/* 空状态（首次加载完成后若无数据才显示） */}
      {!data && !running && (
        <Card>
          <Empty
            description={
              <span>
                点击「开始筛选」，从日 K 线数据中筛选最近 6 个月持续上涨的 A 股
                <br />
                <Text type="secondary">展开任意行可查看近 180 天日 K 走势图</Text>
              </span>
            }
          />
        </Card>
      )}

      {/* 结果区域 */}
      {data && (
        <>
          {/* 统计卡片 */}
          <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
            <Col xs={12} sm={8} md={4}>
              <Card size="small">
                <Statistic
                  title="筛选结果"
                  value={results.length}
                  suffix="只"
                  valueStyle={{ color: "#52c41a" }}
                />
              </Card>
            </Col>
            <Col xs={12} sm={8} md={4}>
              <Card size="small">
                <Statistic
                  title="平均6月涨幅"
                  value={data.avg_return_6m_pct ?? "-"}
                  precision={data.avg_return_6m_pct != null ? 1 : 0}
                  suffix={data.avg_return_6m_pct != null ? "%" : ""}
                  valueStyle={{ color: "#1677ff" }}
                />
              </Card>
            </Col>
            <Col xs={12} sm={8} md={4}>
              <Card size="small">
                <Statistic
                  title="≥4月上涨"
                  value={data.up4_count}
                  suffix="只"
                  valueStyle={{ color: "#d46b08" }}
                />
              </Card>
            </Col>
            <Col xs={12} sm={8} md={4}>
              <Card size="small">
                <Statistic
                  title="5月全涨"
                  value={data.up5_count}
                  suffix="只"
                  valueStyle={{ color: "#cf1322" }}
                />
              </Card>
            </Col>
            <Col xs={12} sm={8} md={4}>
              <Card size="small">
                <Statistic title="筛选日期" value={data.run_date} valueStyle={{ fontSize: 13 }} />
              </Card>
            </Col>
          </Row>

          {/* 周期筛选器 */}
          <Card size="small" style={{ marginBottom: 12 }}>
            <Space wrap align="center">
              <Text style={{ fontSize: 13, fontWeight: 500 }}>上涨周期：</Text>
              <Segmented
                options={PERIOD_OPTIONS}
                value={filterMode}
                onChange={(v) => handleFilterChange(v as string)}
              />
              <Text type="secondary" style={{ fontSize: 12 }}>
                {filterMode === "1m_day"
                  ? "近30个交易日中，收盘价上涨天数 ≥ 80%"
                  : `最近 ${filterMode.replace("m", "")} 个月中，至少 ${Number(filterMode.replace("m", "")) - 1} 个月环比上涨`}
              </Text>
            </Space>
          </Card>

          {/* 结果表格 */}
          <Card>
            <Space style={{ marginBottom: 8 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                展开行可查看近 180 天日 K 图（黄虚线 = 6M 起点价）及 AI 分析
              </Text>
            </Space>
            <Table
              dataSource={results}
              columns={columns}
              rowKey="code"
              size="small"
              scroll={{ x: 1000 }}
              pagination={{ pageSize: 50, showSizeChanger: true, showTotal: (t) => `共 ${t} 只` }}
              locale={{ emptyText: <Empty description="暂无符合条件的股票" /> }}
              expandable={{
                expandedRowRender: (record) => {
                  const ai = analyses[record.code];
                  const isAnalyzing = analyzing[record.code];
                  const recColor =
                    ai?.buy_recommendation === "建议买入"
                      ? "#52c41a"
                      : ai?.buy_recommendation === "谨慎买入"
                        ? "#d46b08"
                        : "#cf1322";
                  return (
                    <Row gutter={16} style={{ padding: "12px 0 8px 36px" }}>
                      {/* 基本信息 */}
                      <Col xs={24} md={6}>
                        <Descriptions size="small" column={1}>
                          <Descriptions.Item label="代码">{record.code}</Descriptions.Item>
                          <Descriptions.Item label="名称">{record.name}</Descriptions.Item>
                          <Descriptions.Item label="行业">{record.industry || "-"}</Descriptions.Item>
                          <Descriptions.Item label="市场">{record.market || "-"}</Descriptions.Item>
                          <Descriptions.Item label="市值">
                            {record.market_cap_yi != null
                              ? `${record.market_cap_yi.toFixed(2)} 亿`
                              : "-"}
                          </Descriptions.Item>
                          <Descriptions.Item label="上市日期">
                            {record.listed_date || "-"}
                          </Descriptions.Item>
                          <Descriptions.Item label="最新收盘">
                            {record.latest_close != null ? `¥${record.latest_close.toFixed(2)}` : "-"}
                            <Text type="secondary" style={{ fontSize: 11, marginLeft: 4 }}>
                              {record.latest_date}
                            </Text>
                          </Descriptions.Item>
                          <Descriptions.Item label="6M 起点价">
                            {record.start_close != null ? `¥${record.start_close.toFixed(2)}` : "-"}
                            <Text type="secondary" style={{ fontSize: 11, marginLeft: 4 }}>
                              {record.start_date}
                            </Text>
                          </Descriptions.Item>
                          <Descriptions.Item label="6M 涨幅">
                            <Text strong style={{ color: pctColor(record.return_6m_pct) }}>
                              {fmt(record.return_6m_pct)}
                            </Text>
                          </Descriptions.Item>
                          <Descriptions.Item label="上涨月数">
                            <Tag
                              color={
                                record.up_months / (record.total_months || 5) >= 0.8
                                  ? "red"
                                  : "orange"
                              }
                            >
                              {record.up_months}/{record.total_months} 个月
                            </Tag>
                          </Descriptions.Item>
                        </Descriptions>
                      </Col>
                      {/* K 线图 */}
                      <Col xs={24} md={12}>
                        <Text
                          type="secondary"
                          style={{ fontSize: 12, marginBottom: 4, display: "block" }}
                        >
                          日 K 收盘价走势（近 180 天）— 黄虚线为 6M 起点价
                        </Text>
                        <StockKlineChart
                          code={record.code}
                          startClose={record.start_close}
                        />
                      </Col>
                      {/* AI 分析 */}
                      <Col xs={24} md={6}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                          <Text strong style={{ fontSize: 13 }}>
                            <RobotOutlined style={{ marginRight: 4, color: "#722ed1" }} />
                            AI 分析
                          </Text>
                          {!ai && (
                            <Button
                              size="small"
                              type="primary"
                              ghost
                              icon={<RobotOutlined />}
                              loading={isAnalyzing}
                              onClick={() => handleAnalyze(record)}
                            >
                              {isAnalyzing ? "分析中..." : "生成分析"}
                            </Button>
                          )}
                          {ai && !ai.error && (
                            <Button
                              size="small"
                              icon={<RobotOutlined />}
                              loading={isAnalyzing}
                              onClick={() => handleAnalyze(record)}
                            >
                              重新分析
                            </Button>
                          )}
                        </div>
                        {isAnalyzing && (
                          <div style={{ textAlign: "center", padding: "20px 0" }}>
                            <Spin size="small" />
                            <Text type="secondary" style={{ display: "block", fontSize: 11, marginTop: 6 }}>
                              AI 分析中，请稍候...
                            </Text>
                          </div>
                        )}
                        {ai?.error && (
                          <Text type="danger" style={{ fontSize: 12 }}>{ai.error}</Text>
                        )}
                        {ai && !ai.error && !isAnalyzing && (
                          <div style={{ fontSize: 12 }}>
                            {ai.summary && (
                              <div style={{ marginBottom: 8, padding: "6px 8px", background: "#f6ffed", borderRadius: 4, borderLeft: "3px solid #52c41a" }}>
                                <Text style={{ fontSize: 12 }}>{ai.summary}</Text>
                              </div>
                            )}
                            <div style={{ marginBottom: 6 }}>
                              <Text type="secondary">是否建议买入：</Text>
                              <Tag color={recColor} style={{ marginLeft: 4 }}>
                                {ai.buy_recommendation || "-"}
                              </Tag>
                            </div>
                            {ai.buy_price && (
                              <div style={{ marginBottom: 6 }}>
                                <Text type="secondary">建议买入价：</Text>
                                <Text strong style={{ marginLeft: 4, color: "#1677ff" }}>{ai.buy_price}</Text>
                              </div>
                            )}
                            {Array.isArray(ai.pros) && ai.pros.length > 0 && (
                              <>
                                <Divider style={{ margin: "6px 0" }} />
                                <Text type="secondary" style={{ fontSize: 11 }}>优势</Text>
                                <ul style={{ margin: "4px 0 0 0", paddingLeft: 16 }}>
                                  {ai.pros.map((p: string, i: number) => (
                                    <li key={i} style={{ color: "#52c41a", fontSize: 12, marginBottom: 2 }}>{p}</li>
                                  ))}
                                </ul>
                              </>
                            )}
                            {Array.isArray(ai.cons) && ai.cons.length > 0 && (
                              <>
                                <Divider style={{ margin: "6px 0" }} />
                                <Text type="secondary" style={{ fontSize: 11 }}>劣势</Text>
                                <ul style={{ margin: "4px 0 0 0", paddingLeft: 16 }}>
                                  {ai.cons.map((c: string, i: number) => (
                                    <li key={i} style={{ color: "#d46b08", fontSize: 12, marginBottom: 2 }}>{c}</li>
                                  ))}
                                </ul>
                              </>
                            )}
                            {Array.isArray(ai.risks) && ai.risks.length > 0 && (
                              <>
                                <Divider style={{ margin: "6px 0" }} />
                                <Text type="secondary" style={{ fontSize: 11 }}>风险</Text>
                                <ul style={{ margin: "4px 0 0 0", paddingLeft: 16 }}>
                                  {ai.risks.map((r: string, i: number) => (
                                    <li key={i} style={{ color: "#cf1322", fontSize: 12, marginBottom: 2 }}>{r}</li>
                                  ))}
                                </ul>
                              </>
                            )}
                          </div>
                        )}
                      </Col>
                    </Row>
                  );
                },
              }}
            />
          </Card>
        </>
      )}
    </div>
  );
}
