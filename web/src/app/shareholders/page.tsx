"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Empty,
  Input,
  InputNumber,
  Radio,
  Space,
  Spin,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  MinusOutlined,
  SearchOutlined,
  SyncOutlined,
  TeamOutlined,
} from "@ant-design/icons";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as RechartTooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ColumnsType } from "antd/es/table";
import { getShareholdersOverview, getStockShareholders, getStockKline, triggerStocksCollect, getStocksCollectStatus } from "@/lib/api";

const { Title, Text } = Typography;

// ─── 趋势图标 ─────────────────────────────────────────────────────────────────
function TrendIcon({ change }: { change: number | null }) {
  if (change == null) return <MinusOutlined style={{ color: "#bfbfbf" }} />;
  if (change < -5) return <ArrowDownOutlined style={{ color: "#389e0d", fontWeight: 700 }} />;
  if (change < 0) return <ArrowDownOutlined style={{ color: "#52c41a" }} />;
  if (change > 5) return <ArrowUpOutlined style={{ color: "#a8071a", fontWeight: 700 }} />;
  if (change > 0) return <ArrowUpOutlined style={{ color: "#cf1322" }} />;
  return <MinusOutlined style={{ color: "#8c8c8c" }} />;
}

function changeColor(change: number | null): string {
  if (change == null) return "#8c8c8c";
  if (change < 0) return "#389e0d";   // 减少=利好，绿色
  if (change > 0) return "#cf1322";   // 增加=利空，红色
  return "#8c8c8c";
}

// ─── 股东户数历史图 ────────────────────────────────────────────────────────────
function HolderHistoryChart({ data }: { data: any[] }) {
  if (!data.length) return <Text type="secondary">暂无历史数据</Text>;

  const chartData = data.map((d) => ({
    date: d.end_date?.slice(0, 7),
    holder_count: d.holder_count,
    change: d.holder_count_change != null ? Number(d.holder_count_change) : null,
  }));

  return (
    <ResponsiveContainer width="100%" height={220}>
      <ComposedChart data={chartData} margin={{ top: 8, right: 40, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
        <XAxis dataKey="date" tick={{ fontSize: 10 }} />
        <YAxis
          yAxisId="left"
          tick={{ fontSize: 10 }}
          width={72}
          tickFormatter={(v) =>
            v >= 10000 ? `${(v / 10000).toFixed(1)}万` : String(v)
          }
        />
        <YAxis
          yAxisId="right"
          orientation="right"
          tick={{ fontSize: 10 }}
          width={48}
          tickFormatter={(v) => `${v}%`}
        />
        <RechartTooltip
          formatter={(value: any, name: any) => {
            if (name === "holder_count")
              return [
                value >= 10000
                  ? `${(value / 10000).toFixed(2)}万户`
                  : `${value}户`,
                "股东人数",
              ];
            if (name === "change") return [`${Number(value).toFixed(2)}%`, "变动幅度"];
            return [value, name];
          }}
        />
        <Legend
          formatter={(v) => (v === "holder_count" ? "股东人数" : "变动幅度(%)")}
          wrapperStyle={{ fontSize: 11 }}
        />
        <Bar
          yAxisId="left"
          dataKey="holder_count"
          fill="#1677ff"
          opacity={0.7}
          maxBarSize={40}
        />
        <Line
          yAxisId="right"
          type="monotone"
          dataKey="change"
          stroke="#cf1322"
          dot={{ r: 3 }}
          strokeWidth={1.5}
          connectNulls
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

// ─── 股价走势图（带涨停标记）─────────────────────────────────────────────────
function getLimitThreshold(code: string): number {
  if (code.startsWith("688") || code.startsWith("689")) return 0.185; // 科创板 ±20%
  if (code.startsWith("300") || code.startsWith("301")) return 0.185; // 创业板 ±20%
  if (code.startsWith("8") || code.startsWith("4")) return 0.285;    // 北交所 ±30%
  return 0.095; // 主板 ±10%
}

function PriceChart({ kline, code }: { kline: any[]; code: string }) {
  if (!kline.length) return <Text type="secondary" style={{ fontSize: 12 }}>暂无 K 线数据</Text>;

  const threshold = getLimitThreshold(code);
  const chartData = kline.map((item, i) => {
    const close = Number(item.close);
    const prevClose = i > 0 ? Number(kline[i - 1].close) : null;
    const changePct = prevClose != null ? (close - prevClose) / prevClose : null;
    const isLimitUp = changePct != null && changePct >= threshold;
    return {
      date: (item.trade_date as string)?.slice(5),
      close,
      isLimitUp,
      changePct: changePct != null ? (changePct * 100).toFixed(2) : null,
    };
  });

  const prices = chartData.map((d) => d.close);
  const minP = Math.min(...prices) * 0.992;
  const maxP = Math.max(...prices) * 1.008;
  const limitUpCount = chartData.filter((d) => d.isLimitUp).length;
  const tickInterval = Math.max(1, Math.floor(chartData.length / 10));

  const renderDot = (props: any) => {
    const { cx, cy, payload } = props;
    if (!payload.isLimitUp) return <circle key={`d-${payload.date}`} cx={cx} cy={cy} r={0} />;
    return (
      <circle
        key={`d-${payload.date}`}
        cx={cx} cy={cy} r={5}
        fill="#cf1322" stroke="#fff" strokeWidth={1.5}
      />
    );
  };

  return (
    <div>
      <Text type="secondary" style={{ fontSize: 11 }}>
        近 180 日收盘价走势
        {limitUpCount > 0 && (
          <span style={{ marginLeft: 8, color: "#cf1322", fontWeight: 600 }}>
            ● 涨停 {limitUpCount} 次
          </span>
        )}
        {limitUpCount === 0 && (
          <span style={{ marginLeft: 8, color: "#8c8c8c" }}>（期间无涨停）</span>
        )}
      </Text>
      <ResponsiveContainer width="100%" height={190}>
        <LineChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="date" tick={{ fontSize: 10 }} interval={tickInterval} />
          <YAxis
            domain={[minP, maxP]}
            tick={{ fontSize: 10 }}
            width={58}
            tickFormatter={(v) => v.toFixed(2)}
          />
          <RechartTooltip
            formatter={(v: any, _: any, props: any) => {
              const extra = props.payload?.isLimitUp ? "  🔴 涨停" : "";
              const chg = props.payload?.changePct;
              const chgStr = chg != null ? `  (${Number(chg) > 0 ? "+" : ""}${chg}%)` : "";
              return [`¥${Number(v).toFixed(2)}${chgStr}${extra}`, "收盘价"];
            }}
          />
          <Line
            type="monotone"
            dataKey="close"
            stroke="#fa8c16"
            dot={renderDot}
            activeDot={{ r: 4 }}
            strokeWidth={1.5}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────
export default function ShareholdersPage() {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [stocks, setStocks] = useState<any[] | null>(null);

  // 筛选参数
  const [keyword, setKeyword] = useState("");
  const [trend, setTrend] = useState<"all" | "decreasing" | "increasing">("all");
  const [minMarketCap, setMinMarketCap] = useState<number>(0);
  const [excludeSt, setExcludeSt] = useState(true);
  const [minLimitUp, setMinLimitUp] = useState<number>(0);

  // 展开行的历史数据缓存
  const [historyCache, setHistoryCache] = useState<Record<string, any[] | null>>({});
  const [klineCache, setKlineCache] = useState<Record<string, any[] | null>>({});

  // 采集状态
  const [collecting, setCollecting] = useState(false);
  const [collectProgress, setCollectProgress] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPoll = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }, []);

  const startPoll = useCallback(() => {
    stopPoll();
    pollRef.current = setInterval(async () => {
      try {
        const s = await getStocksCollectStatus();
        if (!s.running) {
          stopPoll();
          setCollecting(false);
          setCollectProgress(null);
          message.success("全量股东数据采集完成，请重新查询");
        } else {
          setCollectProgress(s.progress ?? "采集中...");
        }
      } catch { stopPoll(); setCollecting(false); }
    }, 3000);
  }, [stopPoll, message]);

  useEffect(() => () => stopPoll(), [stopPoll]);

  const handleCollectAll = useCallback(async () => {
    try {
      const res = await triggerStocksCollect("shareholders_all");
      if (res.status === "already_running") {
        message.warning("已有采集任务在运行，请稍候");
        return;
      }
      setCollecting(true);
      setCollectProgress("启动中...");
      message.info("全量股东数采集已启动，约需 1~3 分钟，完成后请重新查询");
      startPoll();
    } catch (e) {
      message.error(e instanceof Error ? e.message : "启动失败");
    }
  }, [message, startPoll]);

  // 行业过滤
  const [selectedIndustries, setSelectedIndustries] = useState<string[]>([]);

  const industryOptions = useMemo(() => {
    if (!stocks) return [];
    const set = Array.from(new Set(stocks.map((s) => s.industry).filter(Boolean))) as string[];
    set.sort();
    return set.map((i) => ({ label: i, value: i }));
  }, [stocks]);

  const displayStocks = useMemo(() => {
    if (!stocks) return null;
    if (!selectedIndustries.length) return stocks;
    return stocks.filter((s) => selectedIndustries.includes(s.industry));
  }, [stocks, selectedIndustries]);

  // 统计
  const stats = useMemo(() => {
    if (!displayStocks) return null;
    const dec = displayStocks.filter((s) => (s.latest_change ?? 0) < 0).length;
    const inc = displayStocks.filter((s) => (s.latest_change ?? 0) > 0).length;
    return { total: displayStocks.length, dec, inc };
  }, [displayStocks]);

  const handleSearch = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getShareholdersOverview({
        trend: trend === "all" ? undefined : trend,
        keyword: keyword.trim() || undefined,
        min_market_cap: minMarketCap,
        exclude_st: excludeSt,
        min_limit_up: minLimitUp > 0 ? minLimitUp : undefined,
        limit: 6000,
      });
      if (res.error) message.warning(`查询部分异常: ${res.error}`);
      setStocks(res.items ?? []);
      setSelectedIndustries([]);
      message.success(`共 ${res.total ?? res.items?.length ?? 0} 只股票有股东数据`);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "查询失败");
    } finally {
      setLoading(false);
    }
  }, [trend, keyword, minMarketCap, excludeSt, minLimitUp, message]);

  const loadHistory = useCallback(
    async (code: string) => {
      if (code in historyCache) return;
      setHistoryCache((prev) => ({ ...prev, [code]: null }));
      setKlineCache((prev) => ({ ...prev, [code]: null }));
      const [holderRes, klineRes] = await Promise.allSettled([
        getStockShareholders(code, 12),
        getStockKline(code, 180),
      ]);
      setHistoryCache((prev) => ({
        ...prev,
        [code]: holderRes.status === "fulfilled" ? (holderRes.value.items ?? []) : [],
      }));
      setKlineCache((prev) => ({
        ...prev,
        [code]: klineRes.status === "fulfilled" ? (Array.isArray(klineRes.value) ? klineRes.value : []) : [],
      }));
    },
    [historyCache]
  );

  const columns: ColumnsType<any> = [
    {
      title: "#",
      key: "rank",
      width: 44,
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
      width: 90,
    },
    {
      title: "行业",
      dataIndex: "industry",
      key: "industry",
      width: 110,
      render: (v: string) =>
        v ? <Tag style={{ fontSize: 10 }}>{v}</Tag> : <Text type="secondary">-</Text>,
    },
    {
      title: "市场",
      dataIndex: "market",
      key: "market",
      width: 55,
      render: (v: string) => <Text type="secondary">{v || "-"}</Text>,
    },
    {
      title: "市值(亿)",
      dataIndex: "market_cap",
      key: "market_cap",
      width: 80,
      sorter: (a, b) => (a.market_cap ?? 0) - (b.market_cap ?? 0),
      render: (v: number) => (v != null ? v.toFixed(1) : "-"),
    },
    {
      title: "报告期",
      dataIndex: "latest_date",
      key: "latest_date",
      width: 100,
      sorter: (a, b) => (a.latest_date ?? "").localeCompare(b.latest_date ?? ""),
      render: (v: string) => <Text type="secondary">{v}</Text>,
    },
    {
      title: "股东人数",
      dataIndex: "latest_count",
      key: "latest_count",
      width: 100,
      sorter: (a, b) => (a.latest_count ?? 0) - (b.latest_count ?? 0),
      render: (v: number) =>
        v != null ? (
          <Text>{v >= 10000 ? `${(v / 10000).toFixed(2)}万` : v}</Text>
        ) : (
          "-"
        ),
    },
    {
      title: "变动幅度",
      dataIndex: "latest_change",
      key: "latest_change",
      width: 110,
      defaultSortOrder: "ascend",
      sorter: (a, b) => (a.latest_change ?? 0) - (b.latest_change ?? 0),
      render: (v: number) => (
        <Space size={4}>
          <TrendIcon change={v} />
          {v != null ? (
            <Text strong style={{ color: changeColor(v) }}>
              {v > 0 ? "+" : ""}{v.toFixed(2)}%
            </Text>
          ) : (
            <Text type="secondary">-</Text>
          )}
        </Space>
      ),
    },
    {
      title: "户均持股数",
      dataIndex: "avg_holding",
      key: "avg_holding",
      width: 100,
      sorter: (a, b) => (a.avg_holding ?? 0) - (b.avg_holding ?? 0),
      render: (v: number) =>
        v != null ? (
          <Text>{v >= 10000 ? `${(v / 10000).toFixed(2)}万` : v.toFixed(0)}</Text>
        ) : (
          "-"
        ),
    },
    {
      title: "近180日涨停",
      dataIndex: "limit_up_count",
      key: "limit_up_count",
      width: 100,
      sorter: (a, b) => (a.limit_up_count ?? 0) - (b.limit_up_count ?? 0),
      render: (v: number) =>
        v > 0 ? (
          <Text strong style={{ color: "#cf1322" }}>
            {v} 次
          </Text>
        ) : (
          <Text type="secondary">0</Text>
        ),
    },
  ];

  return (
    <div style={{ padding: "16px 24px" }}>
      <Title level={3} style={{ marginBottom: 4 }}>
        <TeamOutlined style={{ marginRight: 8 }} />
        股东数变化
      </Title>
      <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 16 }}>
        基于季报披露数据，股东人数<span style={{ color: "#389e0d", fontWeight: 600 }}>减少</span>意味筹码集中（利好），
        <span style={{ color: "#cf1322", fontWeight: 600 }}>增加</span>意味筹码分散（需关注）。
      </Text>

      {/* ── 数据采集入口 ── */}
      {collecting ? (
        <Alert
          type="info"
          showIcon
          icon={<SyncOutlined spin />}
          message={`正在采集全量股东数据... ${collectProgress ?? ""}`}
          description="数据来自中登公司，需逐季度拉取，预计 1~3 分钟完成"
          style={{ marginBottom: 16 }}
        />
      ) : (
        stocks === null && (
          <Alert
            type="warning"
            showIcon
            message="股东数数据覆盖不足"
            description={
              <span>
                首次使用需采集全量数据（约 1~3 分钟）。
                <Button
                  type="link"
                  size="small"
                  style={{ padding: "0 4px" }}
                  onClick={handleCollectAll}
                >
                  立即采集全市场股东数
                </Button>
              </span>
            }
            style={{ marginBottom: 16 }}
          />
        )
      )}

      {/* ── 筛选区 ── */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap size={12} align="center">
          <Input
            placeholder="代码 / 名称"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onPressEnter={handleSearch}
            style={{ width: 140 }}
            allowClear
          />
          <Radio.Group
            value={trend}
            onChange={(e) => setTrend(e.target.value)}
            optionType="button"
            buttonStyle="solid"
            size="small"
          >
            <Radio.Button value="all">全部</Radio.Button>
            <Radio.Button value="decreasing">
              <ArrowDownOutlined style={{ color: "#389e0d" }} /> 减少中
            </Radio.Button>
            <Radio.Button value="increasing">
              <ArrowUpOutlined style={{ color: "#cf1322" }} /> 增加中
            </Radio.Button>
          </Radio.Group>
          <Space size={4}>
            <Text>最小市值</Text>
            <InputNumber
              min={0}
              max={10000}
              step={10}
              precision={0}
              value={minMarketCap}
              onChange={(v) => setMinMarketCap(v ?? 0)}
              style={{ width: 90 }}
              addonAfter="亿"
              placeholder="0=不限"
            />
          </Space>
          <Space size={4}>
            <Text>近180日涨停</Text>
            <InputNumber
              min={0}
              max={100}
              step={1}
              precision={0}
              value={minLimitUp}
              onChange={(v) => setMinLimitUp(v ?? 0)}
              style={{ width: 80 }}
              addonAfter="次↑"
              placeholder="0=不限"
            />
          </Space>
          <Checkbox checked={excludeSt} onChange={(e) => setExcludeSt(e.target.checked)}>
            排除ST
          </Checkbox>
          <Button type="primary" icon={<SearchOutlined />} loading={loading} onClick={handleSearch}>
            查询
          </Button>
          <Tooltip title="重新采集全市场股东数数据（约1~3分钟）">
            <Button
              icon={<SyncOutlined />}
              loading={collecting}
              onClick={handleCollectAll}
              disabled={collecting}
            >
              采集全量数据
            </Button>
          </Tooltip>
        </Space>

        {/* 行业过滤 + 统计 */}
        {stocks !== null && (
          <Space wrap size={8} style={{ marginTop: 10 }} align="center">
            {industryOptions.length > 0 && (
              <select
                multiple
                value={selectedIndustries}
                onChange={() => {}}
                style={{ display: "none" }}
              />
            )}
            {stats && (
              <>
                <Tag color="default">共 {stats.total} 只</Tag>
                <Tag color="green" icon={<ArrowDownOutlined />}>
                  减少 {stats.dec} 只
                </Tag>
                <Tag color="red" icon={<ArrowUpOutlined />}>
                  增加 {stats.inc} 只
                </Tag>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  减少占比 {stats.total ? ((stats.dec / stats.total) * 100).toFixed(1) : 0}%
                </Text>
              </>
            )}
          </Space>
        )}
      </Card>

      {/* ── 结果表格 ── */}
      {displayStocks === null ? (
        <Empty
          description="点击「查询」加载股东数变化数据"
          style={{ padding: "80px 0" }}
        />
      ) : displayStocks.length === 0 ? (
        <Empty description="暂无符合条件的股东数数据，请先确认数据已采集" />
      ) : (
        <Table
          dataSource={displayStocks}
          columns={columns}
          rowKey="code"
          size="small"
          scroll={{ x: 960 }}
          pagination={{ pageSize: 50, showSizeChanger: true, showTotal: (t) => `共 ${t} 只` }}
          rowClassName={(record) => {
            const c = record.latest_change;
            if (c == null) return "";
            if (c < -10) return "row-strong-decrease";
            if (c > 10) return "row-strong-increase";
            return "";
          }}
          expandable={{
            expandedRowRender: (record) => {
              const hist = historyCache[record.code];
              const kline = klineCache[record.code];
              const isLoading = !(record.code in historyCache) || hist === null;
              return (
                <div style={{ padding: "8px 16px" }}>
                  <Space style={{ marginBottom: 8 }}>
                    <Text strong style={{ fontSize: 13 }}>
                      {record.code} {record.name}
                    </Text>
                    {record.industry && (
                      <Tag style={{ fontSize: 10 }}>{record.industry}</Tag>
                    )}
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      最新报告期：{record.latest_date}
                      {record.latest_count != null && (
                        <>
                          &nbsp;｜ 股东人数：
                          <Text strong>
                            {record.latest_count >= 10000
                              ? `${(record.latest_count / 10000).toFixed(2)}万户`
                              : `${record.latest_count}户`}
                          </Text>
                        </>
                      )}
                      {record.latest_change != null && (
                        <>
                          &nbsp;｜ 较上期：
                          <Text strong style={{ color: changeColor(record.latest_change) }}>
                            {record.latest_change > 0 ? "+" : ""}{record.latest_change.toFixed(2)}%
                          </Text>
                        </>
                      )}
                    </Text>
                  </Space>
                  {isLoading ? (
                    <div style={{ textAlign: "center", padding: 20 }}>
                      <Spin size="small" />
                    </div>
                  ) : (
                    <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
                      <div style={{ flex: "1 1 360px", minWidth: 300 }}>
                        <Text type="secondary" style={{ fontSize: 11, display: "block", marginBottom: 4 }}>
                          股东人数变化（季度）
                        </Text>
                        <HolderHistoryChart data={hist ?? []} />
                      </div>
                      <div style={{ flex: "1 1 360px", minWidth: 300 }}>
                        <PriceChart kline={kline ?? []} code={record.code} />
                      </div>
                    </div>
                  )}
                </div>
              );
            },
            onExpand: (expanded, record) => {
              if (expanded) loadHistory(record.code);
            },
          }}
        />
      )}

      <style>{`
        .row-strong-decrease td { background: #f6ffed !important; }
        .row-strong-increase td { background: #fff1f0 !important; }
      `}</style>
    </div>
  );
}
