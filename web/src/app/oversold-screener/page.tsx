"use client";

import { useCallback, useMemo, useState } from "react";
import {
  App,
  Button,
  Card,
  Checkbox,
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
import { getOversoldScreener, getStockKline, addWatchItem } from "@/lib/api";

const { Title, Text } = Typography;

// ─── 预设策略 ─────────────────────────────────────────────────────────────────
const PRESETS = [
  {
    key: "large_cap",
    label: "大盘稳健",
    desc: "市值≥100亿，流动性强，回撤≥25%，适合低风险偏好",
    params: { minDrawdown: 25, lookbackDays: 60, minMarketCap: 100, minAvgAmount: 2, excludeSt: true },
    color: "#1677ff",
  },
  {
    key: "standard",
    label: "标准超跌",
    desc: "市值≥20亿，回撤≥30%，最常用的均衡策略",
    params: { minDrawdown: 30, lookbackDays: 60, minMarketCap: 20, minAvgAmount: 0.5, excludeSt: true },
    color: "#722ed1",
  },
  {
    key: "deep",
    label: "深度超跌",
    desc: "回撤≥40%，寻找极度超跌、反弹弹性大的个股",
    params: { minDrawdown: 40, lookbackDays: 90, minMarketCap: 10, minAvgAmount: 0, excludeSt: true },
    color: "#d46b08",
  },
  {
    key: "extreme",
    label: "极端超跌",
    desc: "回撤≥50%，半年内腰斩以上，高风险高弹性",
    params: { minDrawdown: 50, lookbackDays: 120, minMarketCap: 0, minAvgAmount: 0, excludeSt: true },
    color: "#cf1322",
  },
  {
    key: "wide",
    label: "宽松全量",
    desc: "回撤≥20%，不限市值，覆盖面最广，自行二次过滤",
    params: { minDrawdown: 20, lookbackDays: 60, minMarketCap: 0, minAvgAmount: 0, excludeSt: true },
    color: "#389e0d",
  },
] as const;

type PresetKey = typeof PRESETS[number]["key"];

// ─── 回撤颜色 ────────────────────────────────────────────────────────────────
function drawdownColor(pct: number): string {
  const abs = Math.abs(pct);
  if (abs >= 50) return "#a8071a";
  if (abs >= 35) return "#cf1322";
  if (abs >= 25) return "#d46b08";
  return "#ad6800";
}

// ─── K 线图（带高点参考线）──────────────────────────────────────────────────
function OversoldKlineChart({
  kline,
  highPrice,
  currentClose,
}: {
  kline: any[];
  highPrice: number;
  currentClose: number;
}) {
  const chartData = kline.map((item) => ({
    date: (item.trade_date as string)?.slice(5),
    close: Number(item.close),
    fullDate: item.trade_date as string,
  }));
  const prices = chartData.map((d) => d.close);
  const minP = Math.min(...prices, currentClose) * 0.983;
  const maxP = Math.max(...prices, highPrice) * 1.017;
  const tickInterval = Math.max(1, Math.floor(chartData.length / 10));
  const drawdownPct = ((currentClose - highPrice) / highPrice * 100).toFixed(2);

  return (
    <div>
      <Text type="secondary" style={{ fontSize: 11 }}>
        近 120 日收盘走势（红虚线：近期高点 {highPrice.toFixed(2)}，当前跌幅{" "}
        <span style={{ color: "#cf1322", fontWeight: 700 }}>{drawdownPct}%</span>）
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
          {/* 近期高点参考线 */}
          <ReferenceLine
            y={highPrice}
            stroke="#cf1322"
            strokeDasharray="4 4"
            label={{ value: `高点 ${highPrice.toFixed(2)}`, position: "right", fontSize: 10, fill: "#cf1322" }}
          />
          {/* 当前价参考线 */}
          <ReferenceLine
            y={currentClose}
            stroke="#389e0d"
            strokeDasharray="2 2"
            label={{ value: `现价 ${currentClose.toFixed(2)}`, position: "right", fontSize: 10, fill: "#389e0d" }}
          />
          <Line type="monotone" dataKey="close" stroke="#1677ff" dot={false} strokeWidth={1.5} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────
export default function OversoldScreenerPage() {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [stocks, setStocks] = useState<any[] | null>(null);
  const [rawTotal, setRawTotal] = useState(0);
  const [activePreset, setActivePreset] = useState<PresetKey | null>(null);

  // 筛选参数
  const [minDrawdown, setMinDrawdown] = useState<number>(20);
  const [lookbackDays, setLookbackDays] = useState<number>(60);
  const [minMarketCap, setMinMarketCap] = useState<number>(20);
  const [minAvgAmount, setMinAvgAmount] = useState<number>(0);
  const [excludeSt, setExcludeSt] = useState<boolean>(true);

  // K 线缓存
  const [klineCache, setKlineCache] = useState<Record<string, any[] | null>>({});
  const [adding, setAdding] = useState<Record<string, boolean>>({});
  const [watched, setWatched] = useState<Set<string>>(new Set());

  // 行业/市场过滤
  const [selectedIndustries, setSelectedIndustries] = useState<string[]>([]);
  const [selectedMarkets, setSelectedMarkets] = useState<string[]>([]);

  const industryOptions = useMemo(() => {
    if (!stocks) return [];
    const industries = Array.from(new Set(stocks.map((s) => s.industry).filter(Boolean))) as string[];
    industries.sort();
    return industries.map((i) => ({ label: i, value: i }));
  }, [stocks]);

  const marketOptions = useMemo(() => {
    if (!stocks) return [];
    const markets = Array.from(new Set(stocks.map((s) => s.market).filter(Boolean))) as string[];
    markets.sort();
    return markets.map((m) => ({ label: m, value: m }));
  }, [stocks]);

  const displayStocks = useMemo(() => {
    if (!stocks) return null;
    return stocks.filter((s) => {
      if (selectedIndustries.length > 0 && !selectedIndustries.includes(s.industry)) return false;
      if (selectedMarkets.length > 0 && !selectedMarkets.includes(s.market)) return false;
      return true;
    });
  }, [stocks, selectedIndustries, selectedMarkets]);

  const applyPreset = useCallback(
    (preset: typeof PRESETS[number]) => {
      setActivePreset(preset.key);
      setMinDrawdown(preset.params.minDrawdown);
      setLookbackDays(preset.params.lookbackDays);
      setMinMarketCap(preset.params.minMarketCap);
      setMinAvgAmount(preset.params.minAvgAmount);
      setExcludeSt(preset.params.excludeSt);
      // 重置行业/市场过滤
      setSelectedIndustries([]);
      setSelectedMarkets([]);
    },
    []
  );

  const handleSearch = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getOversoldScreener({
        min_drawdown: minDrawdown,
        lookback_days: lookbackDays,
        min_market_cap: minMarketCap,
        min_avg_amount: minAvgAmount,
        exclude_st: excludeSt,
        limit: 300,
      });
      if (res.error) message.warning(`查询部分异常: ${res.error}`);
      const items = res.items ?? [];
      setStocks(items);
      setRawTotal(res.total ?? items.length);
      message.success(`共筛出 ${items.length} 只超跌个股`);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "查询失败");
    } finally {
      setLoading(false);
    }
  }, [minDrawdown, lookbackDays, minMarketCap, minAvgAmount, excludeSt, message]);

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
          source: "oversold_screener",
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
      width: 60,
      render: (v: string) => <Text type="secondary">{v || "-"}</Text>,
    },
    {
      title: "当前收盘",
      dataIndex: "current_close",
      key: "current_close",
      width: 88,
      sorter: (a, b) => (a.current_close ?? 0) - (b.current_close ?? 0),
      render: (v: number) => (v != null ? <Text strong>{v.toFixed(2)}</Text> : "-"),
    },
    {
      title: `近期高点`,
      dataIndex: "high_price",
      key: "high_price",
      width: 88,
      sorter: (a, b) => (a.high_price ?? 0) - (b.high_price ?? 0),
      render: (v: number) => (v != null ? v.toFixed(2) : "-"),
    },
    {
      title: "回撤幅度",
      dataIndex: "drawdown_pct",
      key: "drawdown_pct",
      width: 100,
      defaultSortOrder: "ascend",
      sorter: (a, b) => (a.drawdown_pct ?? 0) - (b.drawdown_pct ?? 0),
      render: (v: number) =>
        v != null ? (
          <Text strong style={{ color: drawdownColor(v) }}>{`${v.toFixed(2)}%`}</Text>
        ) : "-",
    },
    {
      title: "日均成交(亿)",
      dataIndex: "avg_amount_20d",
      key: "avg_amount_20d",
      width: 110,
      sorter: (a, b) => (a.avg_amount_20d ?? 0) - (b.avg_amount_20d ?? 0),
      render: (v: number) => (v != null ? (v / 1e8).toFixed(2) : "-"),
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
      title: "最新交易日",
      dataIndex: "latest_trade_date",
      key: "latest_trade_date",
      width: 110,
      sorter: (a, b) => (a.latest_trade_date ?? "").localeCompare(b.latest_trade_date ?? ""),
    },
    {
      title: "操作",
      key: "action",
      width: 80,
      fixed: "right" as const,
      render: (_: any, record: any) =>
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
        ),
    },
  ];

  return (
    <div style={{ padding: "16px 24px" }}>
      <Title level={3} style={{ marginBottom: 4 }}>
        <FilterOutlined style={{ marginRight: 8 }} />
        超跌反弹股筛选
      </Title>
      <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 16 }}>
        筛选优质但近期大幅超跌的个股。回撤幅度 = (当前收盘 − 近N日最高收盘) / 近N日最高收盘 × 100%
      </Text>

      {/* ── 预设策略 ── */}
      <Card
        size="small"
        style={{ marginBottom: 12, background: "#fafafa" }}
        bodyStyle={{ padding: "10px 16px" }}
      >
        <Space wrap size={8} align="center">
          <Text type="secondary" style={{ fontSize: 12, whiteSpace: "nowrap" }}>快选策略：</Text>
          {PRESETS.map((preset) => {
            const isActive = activePreset === preset.key;
            return (
              <Tooltip key={preset.key} title={preset.desc}>
                <Button
                  size="small"
                  onClick={() => applyPreset(preset)}
                  style={{
                    borderColor: isActive ? preset.color : undefined,
                    color: isActive ? preset.color : undefined,
                    background: isActive ? `${preset.color}10` : undefined,
                    fontWeight: isActive ? 600 : undefined,
                  }}
                >
                  {preset.label}
                </Button>
              </Tooltip>
            );
          })}
        </Space>
      </Card>

      {/* ── 筛选条件 ── */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap size={12}>
          <Space size={4}>
            <Text>回撤窗口</Text>
            <InputNumber
              min={20}
              max={365}
              step={10}
              precision={0}
              value={lookbackDays}
              onChange={(v) => { v != null && setLookbackDays(v); setActivePreset(null); }}
              style={{ width: 80 }}
              addonAfter="天"
            />
          </Space>
          <Space size={4}>
            <Text>最小回撤</Text>
            <InputNumber
              min={5}
              max={80}
              step={5}
              precision={0}
              value={minDrawdown}
              onChange={(v) => { v != null && setMinDrawdown(v); setActivePreset(null); }}
              style={{ width: 80 }}
              addonAfter="%"
            />
          </Space>
          <Space size={4}>
            <Text>最小市值</Text>
            <InputNumber
              min={0}
              max={10000}
              step={10}
              precision={0}
              value={minMarketCap}
              onChange={(v) => { setMinMarketCap(v ?? 0); setActivePreset(null); }}
              style={{ width: 90 }}
              addonAfter="亿"
              placeholder="0=不限"
            />
          </Space>
          <Space size={4}>
            <Text>最小日均成交</Text>
            <InputNumber
              min={0}
              max={1000}
              step={0.5}
              precision={1}
              value={minAvgAmount}
              onChange={(v) => { setMinAvgAmount(v ?? 0); setActivePreset(null); }}
              style={{ width: 90 }}
              addonAfter="亿"
              placeholder="0=不限"
            />
          </Space>
          <Checkbox
            checked={excludeSt}
            onChange={(e) => { setExcludeSt(e.target.checked); setActivePreset(null); }}
          >
            排除ST
          </Checkbox>
          <Button type="primary" icon={<SearchOutlined />} loading={loading} onClick={handleSearch}>
            筛选
          </Button>
        </Space>

        {/* 结果后过滤 */}
        {stocks !== null && (industryOptions.length > 0 || marketOptions.length > 0) && (
          <Space wrap size={8} style={{ marginTop: 10 }}>
            {industryOptions.length > 0 && (
              <Select
                mode="multiple"
                allowClear
                placeholder="按行业过滤"
                options={industryOptions}
                value={selectedIndustries}
                onChange={setSelectedIndustries}
                style={{ minWidth: 200 }}
                maxTagCount="responsive"
              />
            )}
            {marketOptions.length > 0 && (
              <Select
                mode="multiple"
                allowClear
                placeholder="按市场过滤"
                options={marketOptions}
                value={selectedMarkets}
                onChange={setSelectedMarkets}
                style={{ minWidth: 160 }}
                maxTagCount="responsive"
              />
            )}
            <Text type="secondary" style={{ fontSize: 12 }}>
              显示 <Text strong>{displayStocks?.length ?? 0}</Text> / <Text strong>{rawTotal}</Text> 只
            </Text>
          </Space>
        )}
      </Card>

      {/* ── 结果表格 ── */}
      {displayStocks === null ? (
        <Empty
          description="设置筛选条件后点击「筛选」，系统将列出优质超跌个股"
          style={{ padding: "80px 0" }}
        />
      ) : displayStocks.length === 0 ? (
        <Empty description="无符合条件的记录，可尝试降低最小回撤幅度或减小市值要求" />
      ) : (
        <Table
          dataSource={displayStocks}
          columns={columns}
          rowKey="code"
          size="small"
          scroll={{ x: 900 }}
          pagination={{ pageSize: 50, showSizeChanger: true, showTotal: (t) => `共 ${t} 只` }}
          expandable={{
            expandedRowRender: (record) => {
              const kline = klineCache[record.code];
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
                  <div style={{ marginTop: 8, display: "flex", gap: 24, flexWrap: "wrap", fontSize: 12, marginBottom: 12 }}>
                    <div>
                      <Text type="secondary">当前收盘：</Text>
                      <Text strong>{record.current_close?.toFixed(2)}</Text>
                    </div>
                    <div>
                      <Text type="secondary">近期高点：</Text>
                      <Text strong style={{ color: "#cf1322" }}>{record.high_price?.toFixed(2)}</Text>
                    </div>
                    <div>
                      <Text type="secondary">回撤幅度：</Text>
                      <Text strong style={{ color: drawdownColor(record.drawdown_pct) }}>
                        {record.drawdown_pct?.toFixed(2)}%
                      </Text>
                    </div>
                    <div>
                      <Text type="secondary">日均成交：</Text>
                      <Text>{record.avg_amount_20d != null ? `${(record.avg_amount_20d / 1e8).toFixed(2)}亿` : "-"}</Text>
                    </div>
                    <div>
                      <Text type="secondary">上市日期：</Text>
                      <Text>{record.listed_date || "-"}</Text>
                    </div>
                    <div>
                      <Text type="secondary">最新交易日：</Text>
                      <Text>{record.latest_trade_date}</Text>
                    </div>
                  </div>
                  {/* K 线图 */}
                  {!(record.code in klineCache) || kline === null ? (
                    <Spin size="small" />
                  ) : (kline as any[]).length === 0 ? (
                    <Text type="secondary" style={{ fontSize: 12 }}>无 K 线数据</Text>
                  ) : (
                    <OversoldKlineChart
                      kline={kline}
                      highPrice={record.high_price}
                      currentClose={record.current_close}
                    />
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
