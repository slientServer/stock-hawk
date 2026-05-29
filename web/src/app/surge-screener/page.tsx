"use client";

import { useCallback, useMemo, useState } from "react";
import {
  App,
  Button,
  Card,
  DatePicker,
  Empty,
  InputNumber,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  Spin,
} from "antd";
import { CheckOutlined, EyeOutlined, FilterOutlined, SearchOutlined } from "@ant-design/icons";
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
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { getSurgeScreener, getStockKline, addWatchItem } from "@/lib/api";

const { Title, Text } = Typography;

// ─── K 线图（标记所有涨幅日）────────────────────────────────────────────────
function SurgeKlineChart({ kline, surgeDates }: { kline: any[]; surgeDates: string[] }) {
  const surgeSet = new Set(surgeDates);
  const chartData = kline.map((item) => ({
    date: (item.trade_date as string)?.slice(5),
    close: Number(item.close),
    fullDate: item.trade_date as string,
  }));
  const prices = chartData.map((d) => d.close);
  const minP = Math.min(...prices) * 0.985;
  const maxP = Math.max(...prices) * 1.015;
  const tickInterval = Math.max(1, Math.floor(chartData.length / 10));

  return (
    <div>
      <Text type="secondary" style={{ fontSize: 11 }}>
        近 120 日收盘走势（红线标记每次大涨日）
      </Text>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={chartData} margin={{ top: 8, right: 20, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="date" tick={{ fontSize: 10 }} interval={tickInterval} />
          <YAxis
            domain={[minP, maxP]}
            tick={{ fontSize: 10 }}
            width={56}
            tickFormatter={(v) => v.toFixed(2)}
          />
          <RechartTooltip
            formatter={(v: any) => [`¥${Number(v).toFixed(2)}`, "收盘价"]}
            labelFormatter={(l) => String(l)}
          />
          {chartData
            .filter((d) => surgeSet.has(d.fullDate))
            .map((d) => (
              <ReferenceLine
                key={d.fullDate}
                x={d.date}
                stroke="#cf1322"
                strokeDasharray="4 4"
                label={{ value: "↑", position: "top", fontSize: 10, fill: "#cf1322" }}
              />
            ))}
          <Line type="monotone" dataKey="close" stroke="#1677ff" dot={false} strokeWidth={1.5} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// ─── 日级明细表 ──────────────────────────────────────────────────────────────
function DayDetailTable({ days }: { days: any[] }) {
  const cols: ColumnsType<any> = [
    {
      title: "交易日",
      dataIndex: "trade_date",
      key: "td",
      width: 100,
      sorter: (a, b) => a.trade_date.localeCompare(b.trade_date),
      defaultSortOrder: "descend",
    },
    {
      title: "涨幅",
      dataIndex: "change_pct",
      key: "cp",
      width: 80,
      sorter: (a, b) => (a.change_pct ?? 0) - (b.change_pct ?? 0),
      render: (v: number) =>
        v != null ? (
          <Text strong style={{ color: "#cf1322" }}>{`+${v.toFixed(2)}%`}</Text>
        ) : "-",
    },
    {
      title: "前收",
      dataIndex: "prev_close",
      key: "pc",
      width: 70,
      render: (v: number) => (v != null ? v.toFixed(2) : "-"),
    },
    {
      title: "开盘",
      dataIndex: "open",
      key: "op",
      width: 70,
      render: (v: number) => (v != null ? v.toFixed(2) : "-"),
    },
    {
      title: "最高",
      dataIndex: "high",
      key: "hi",
      width: 70,
      render: (v: number) => (v != null ? v.toFixed(2) : "-"),
    },
    {
      title: "最低",
      dataIndex: "low",
      key: "lo",
      width: 70,
      render: (v: number) => (v != null ? v.toFixed(2) : "-"),
    },
    {
      title: "收盘",
      dataIndex: "close",
      key: "cl",
      width: 70,
      render: (v: number) => (v != null ? v.toFixed(2) : "-"),
    },
    {
      title: "成交额(亿)",
      dataIndex: "amount",
      key: "am",
      width: 90,
      render: (v: number) => (v != null ? (v / 1e8).toFixed(2) : "-"),
    },
    {
      title: "换手率",
      dataIndex: "turnover_rate",
      key: "tr",
      width: 72,
      render: (v: number) => (v != null ? `${v.toFixed(2)}%` : "-"),
    },
  ];

  return (
    <Table
      dataSource={days}
      columns={cols}
      rowKey={(r) => r.trade_date}
      size="small"
      pagination={false}
      style={{ marginBottom: 12 }}
    />
  );
}

// ─── 聚合（个股维度） ─────────────────────────────────────────────────────────
function aggregateByStock(items: any[]): any[] {
  const map = new Map<string, any>();
  for (const item of items) {
    if (!map.has(item.code)) {
      map.set(item.code, {
        code: item.code,
        name: item.name,
        industry: item.industry,
        market: item.market,
        market_cap: item.market_cap,
        listed_date: item.listed_date ?? null,
        days: [],
        surge_count: 0,
        total_pct: 0,
        max_pct: -Infinity,
        latest_date: "",
      });
    }
    const s = map.get(item.code)!;
    s.days.push(item);
    s.surge_count += 1;
    s.total_pct += item.change_pct ?? 0;
    if ((item.change_pct ?? 0) > s.max_pct) s.max_pct = item.change_pct;
    if (item.trade_date > s.latest_date) s.latest_date = item.trade_date;
  }
  return Array.from(map.values()).map((s) => ({
    ...s,
    avg_pct: s.total_pct / s.surge_count,
  }));
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────
export default function SurgeScreenerPage() {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [stocks, setStocks] = useState<any[] | null>(null);
  const [rawTotal, setRawTotal] = useState(0);
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs]>([
    dayjs().subtract(30, "day"),
    dayjs(),
  ]);
  const [minPct, setMinPct] = useState<number>(5);
  const [klineCache, setKlineCache] = useState<Record<string, any[] | null>>({});
  const [adding, setAdding] = useState<Record<string, boolean>>({});
  const [watched, setWatched] = useState<Set<string>>(new Set());
  const [selectedMarkets, setSelectedMarkets] = useState<string[]>([]);

  // 从已加载数据中提取所有市场选项
  const marketOptions = useMemo(() => {
    if (!stocks) return [];
    const markets = Array.from(new Set(stocks.map((s) => s.market).filter(Boolean))) as string[];
    markets.sort();
    return markets.map((m) => ({ label: m, value: m }));
  }, [stocks]);

  // 应用市场过滤
  const displayStocks = useMemo(() => {
    if (!stocks) return null;
    if (selectedMarkets.length === 0) return stocks;
    return stocks.filter((s) => selectedMarkets.includes(s.market));
  }, [stocks, selectedMarkets]);

  const handleSearch = useCallback(async () => {
    const [start, end] = dateRange;
    setLoading(true);
    try {
      const res = await getSurgeScreener({
        start_date: start.format("YYYY-MM-DD"),
        end_date: end.format("YYYY-MM-DD"),
        min_pct: minPct,
        limit: 500,
      });
      if (res.error) message.warning(`查询部分异常: ${res.error}`);
      const agg = aggregateByStock(res.items ?? []);
      // 默认按次数降序
      agg.sort((a, b) => b.surge_count - a.surge_count || b.avg_pct - a.avg_pct);
      setStocks(agg);
      setRawTotal(res.total ?? 0);
      message.success(`共 ${agg.length} 只个股，${res.total} 条大涨记录`);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "查询失败");
    } finally {
      setLoading(false);
    }
  }, [dateRange, minPct, message]);

  const loadKline = useCallback(
    async (code: string) => {
      if (code in klineCache) return;
      setKlineCache((prev) => ({ ...prev, [code]: null }));
      try {
        const kline = await getStockKline(code, 120);
        setKlineCache((prev) => ({ ...prev, [code]: kline }));
      } catch {
        setKlineCache((prev) => ({ ...prev, [code]: [] }));
      }
    },
    [klineCache]
  );

  const handleAddWatch = useCallback(
    async (record: any) => {
      setAdding((prev) => ({ ...prev, [record.code]: true }));
      try {
        await addWatchItem({
          code: record.code,
          name: record.name || record.code,
          industry: record.industry,
          source: "surge_screener",
        });
        setWatched((prev) => new Set(prev).add(record.code));
        message.success(`${record.name || record.code} 已加入关注列表`);
      } catch (e: any) {
        const msg = e?.message || "";
        if (msg.includes("duplicate") || msg.includes("already") || msg.includes("unique")) {
          setWatched((prev) => new Set(prev).add(record.code));
          message.info(`${record.name || record.code} 已在关注列表中`);
        } else {
          message.error(`添加失败: ${msg}`);
        }
      } finally {
        setAdding((prev) => ({ ...prev, [record.code]: false }));
      }
    },
    [message]
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
      render: (v: string) => v || "-",
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
      width: 70,
      render: (v: string) => <Text type="secondary">{v || "-"}</Text>,
    },
    {
      title: "大涨次数",
      dataIndex: "surge_count",
      key: "surge_count",
      width: 88,
      sorter: (a, b) => a.surge_count - b.surge_count,
      defaultSortOrder: "descend",
      render: (v: number) => (
        <Tag color={v >= 3 ? "red" : v >= 2 ? "orange" : "blue"}>{v} 次</Tag>
      ),
    },
    {
      title: "平均涨幅",
      dataIndex: "avg_pct",
      key: "avg_pct",
      width: 90,
      sorter: (a, b) => a.avg_pct - b.avg_pct,
      render: (v: number) => (
        <Text strong style={{ color: "#cf1322" }}>{`+${v.toFixed(2)}%`}</Text>
      ),
    },
    {
      title: "最大单日涨幅",
      dataIndex: "max_pct",
      key: "max_pct",
      width: 110,
      sorter: (a, b) => a.max_pct - b.max_pct,
      render: (v: number) => (
        <Text style={{ color: "#cf1322" }}>{`+${v.toFixed(2)}%`}</Text>
      ),
    },
    {
      title: "最近触发日",
      dataIndex: "latest_date",
      key: "latest_date",
      width: 110,
      sorter: (a, b) => a.latest_date.localeCompare(b.latest_date),
    },
    {
      title: "上市日期",
      dataIndex: "listed_date",
      key: "listed_date",
      width: 100,
      sorter: (a, b) => (a.listed_date ?? "").localeCompare(b.listed_date ?? ""),
      render: (v: string) => <Text type="secondary">{v || "-"}</Text>,
    },
    {
      title: "市值(亿)",
      dataIndex: "market_cap",
      key: "market_cap",
      width: 80,
      sorter: (a, b) => (a.market_cap ?? 0) - (b.market_cap ?? 0),
      render: (v: number) => (v != null ? (v / 1e8).toFixed(1) : "-"),
    },
    {
      title: "操作",
      key: "action",
      width: 80,
      fixed: "right" as const,
      render: (_: any, record: any) => (
        watched.has(record.code) ? (
          <Tooltip title="已在关注列表">
            <Button size="small" type="text" icon={<CheckOutlined />} style={{ color: "#52c41a" }} disabled />
          </Tooltip>
        ) : (
          <Tooltip title="加入关注列表">
            <Button
              size="small"
              type="link"
              icon={<EyeOutlined />}
              loading={adding[record.code]}
              onClick={() => handleAddWatch(record)}
            >
              关注
            </Button>
          </Tooltip>
        )
      ),
    },
  ];

  return (
    <div style={{ padding: "16px 24px" }}>
      <Title level={3} style={{ marginBottom: 16 }}>
        <FilterOutlined style={{ marginRight: 8 }} />
        A股单日涨幅筛选
      </Title>

      {/* ── 筛选条件 ── */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap size={12}>
          <DatePicker.RangePicker
            value={dateRange}
            onChange={(dates) => {
              if (dates && dates[0] && dates[1]) {
                setDateRange([dates[0], dates[1]]);
              }
            }}
            format="YYYY-MM-DD"
            allowClear={false}
            presets={[
              { label: "近7天", value: [dayjs().subtract(7, "day"), dayjs()] },
              { label: "近30天", value: [dayjs().subtract(30, "day"), dayjs()] },
              { label: "近90天", value: [dayjs().subtract(90, "day"), dayjs()] },
              { label: "近半年", value: [dayjs().subtract(180, "day"), dayjs()] },
              { label: "近一年", value: [dayjs().subtract(365, "day"), dayjs()] },
            ]}
          />
          <Space size={4}>
            <Text>单日最小涨幅</Text>
            <InputNumber
              min={0.1}
              max={50}
              step={0.5}
              precision={1}
              value={minPct}
              onChange={(v) => v != null && setMinPct(v)}
              style={{ width: 90 }}
              addonAfter="%"
            />
          </Space>
          <Button type="primary" icon={<SearchOutlined />} loading={loading} onClick={handleSearch}>
            筛选
          </Button>
          {stocks !== null && marketOptions.length > 0 && (
            <Select
              mode="multiple"
              allowClear
              placeholder="按市场筛选"
              options={marketOptions}
              value={selectedMarkets}
              onChange={setSelectedMarkets}
              style={{ minWidth: 200 }}
              maxTagCount="responsive"
            />
          )}
          {stocks !== null && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              共 <Text strong>{displayStocks?.length ?? 0}</Text> 只个股，
              <Text strong>{rawTotal}</Text> 条大涨记录
            </Text>
          )}
        </Space>
      </Card>

      {/* ── 个股聚合表格 ── */}
      {displayStocks === null ? (
        <Empty description="设置日期范围和最小涨幅后点击「筛选」" style={{ padding: "80px 0" }} />
      ) : displayStocks.length === 0 ? (
        <Empty description="无符合条件的记录" />
      ) : (
        <Table
          dataSource={displayStocks}
          columns={columns}
          rowKey="code"
          size="small"
          scroll={{ x: 860 }}
          pagination={{ pageSize: 50, showSizeChanger: true, showTotal: (t) => `共 ${t} 只` }}
          expandable={{
            expandedRowRender: (record) => {
              const kline = klineCache[record.code];
              const surgeDates: string[] = record.days.map((d: any) => d.trade_date);
              return (
                <div style={{ padding: "8px 16px" }}>
                  <Text strong style={{ fontSize: 13 }}>
                    {record.code} {record.name}
                    {record.industry ? (
                      <Tag style={{ marginLeft: 8, fontSize: 10 }}>{record.industry}</Tag>
                    ) : null}
                    {record.market_cap != null && (
                      <Text type="secondary" style={{ fontSize: 11, marginLeft: 8 }}>
                        市值 {(record.market_cap / 1e8).toFixed(1)}亿
                      </Text>
                    )}
                  </Text>
                  {/* 日级明细 */}
                  <div style={{ marginTop: 10, marginBottom: 8 }}>
                    <DayDetailTable days={record.days} />
                  </div>
                  {/* K 线图 */}
                  {!(record.code in klineCache) || kline === null ? (
                    <Spin size="small" />
                  ) : (kline as any[]).length === 0 ? (
                    <Text type="secondary" style={{ fontSize: 12 }}>无 K 线数据</Text>
                  ) : (
                    <SurgeKlineChart kline={kline} surgeDates={surgeDates} />
                  )}
                </div>
              );
            },
            onExpand: (expanded, record) => {
              if (expanded) loadKline(record.code);
            },
          }}
        />
      )}
    </div>
  );
}
