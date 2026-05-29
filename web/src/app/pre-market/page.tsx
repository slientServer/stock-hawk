"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Collapse,
  Descriptions,
  Divider,
  Empty,
  Progress,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import {
  RadarChartOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
  AppstoreOutlined,
  EyeOutlined,
} from "@ant-design/icons";
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
import {
  addWatchItem,
  getKline,
  getPreMarketByDate,
  getPreMarketCatalysts,
  getPreMarketHistory,
  getPreMarketLatest,
  getPreMarketPerformance,
  getPreMarketTask,
  triggerPreMarket,
} from "@/lib/api";

const { Title, Text, Paragraph } = Typography;

const STRENGTH_COLOR: Record<number, string> = { 5: "red", 4: "orange", 3: "gold", 2: "blue", 1: "default" };
const EXIT_COLOR: Record<string, string> = { take_profit: "green", stop_loss: "red", max_hold: "blue", pending: "default" };
const EXIT_LABEL: Record<string, string> = { take_profit: "止盈", stop_loss: "止损", max_hold: "到期", pending: "待结" };

function fmtPct(v: number | null | undefined, decimals = 2) {
  if (v == null) return "-";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(decimals)}%`;
}
function fmtPrice(v: number | null | undefined, decimals = 2) {
  if (v == null) return "-";
  return v.toFixed(decimals);
}
function fmtWan(v: number | null | undefined) {
  if (v == null) return "-";
  const wan = v / 10000;
  if (Math.abs(wan) >= 10000) return `${(wan / 10000).toFixed(1)}亿`;
  return `${wan.toFixed(0)}万`;
}

// ─── 日K线图组件 ──────────────────────────────────────────────────────────────
function StockKlineChart({
  code,
  targetPrice,
  stopLossPrice,
  height = 180,
}: {
  code: string;
  targetPrice?: number;
  stopLossPrice?: number;
  height?: number;
}) {
  const [kline, setKline] = useState<any[] | null>(null);

  useEffect(() => {
    setKline(null);
    getKline(code, 60).then(setKline).catch(() => setKline([]));
  }, [code]);

  if (kline === null) {
    return (
      <div style={{ height, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <Spin size="small" />
      </div>
    );
  }
  if (!kline.length) {
    return <Text type="secondary" style={{ fontSize: 12 }}>暂无K线数据</Text>;
  }

  const chartData = kline.map((d) => ({
    date: (d.trade_date as string)?.slice(5),
    close: Number(d.close),
  }));

  const prices = chartData.map((d) => d.close);
  const allRef = [
    ...prices,
    ...(targetPrice ? [targetPrice] : []),
    ...(stopLossPrice ? [stopLossPrice] : []),
  ];
  const minP = Math.min(...allRef) * 0.985;
  const maxP = Math.max(...allRef) * 1.015;
  const tickInterval = Math.max(1, Math.floor(chartData.length / 7));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={chartData} margin={{ top: 4, right: 12, left: -8, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
        <XAxis dataKey="date" tick={{ fontSize: 9 }} interval={tickInterval} />
        <YAxis
          domain={[minP, maxP]}
          tick={{ fontSize: 9 }}
          width={52}
          tickFormatter={(v) => v.toFixed(2)}
        />
        <RechartTooltip
          formatter={(v) => [`¥${Number(v).toFixed(3)}`, "收盘价"]}
          labelFormatter={(l) => `${l}`}
        />
        {targetPrice != null && (
          <ReferenceLine
            y={targetPrice}
            stroke="#cf1322"
            strokeDasharray="4 4"
            label={{ value: "目标", position: "insideTopRight", fontSize: 9, fill: "#cf1322" }}
          />
        )}
        {stopLossPrice != null && (
          <ReferenceLine
            y={stopLossPrice}
            stroke="#389e0d"
            strokeDasharray="4 4"
            label={{ value: "止损", position: "insideBottomRight", fontSize: 9, fill: "#389e0d" }}
          />
        )}
        <Line type="monotone" dataKey="close" stroke="#1677ff" dot={false} strokeWidth={1.5} />
      </LineChart>
    </ResponsiveContainer>
  );
}

// ─── 选中依据生成器 ───────────────────────────────────────────────────────────
function buildRationale(item: any): string[] {
  const rtype: string = item.result_type ?? "aggressive";
  const bullets: string[] = [];

  if (["aggressive", "aggressive_main", "aggressive_backup"].includes(rtype)) {
    // 催化信息
    if (item.catalyst_sector && item.catalyst_sector !== "纯技术面") {
      const stars = (item.catalyst_strength ?? 0) > 0 ? `，强度 ${item.catalyst_strength}★` : "";
      bullets.push(`催化板块「${item.catalyst_sector}」匹配${stars}`);
    } else {
      bullets.push("无明确催化，纯技术面动量筛选入围");
    }
    // 近5日动量
    const chg5 = item.change_pct_5d ?? 0;
    if (Math.abs(chg5) >= 0.1) {
      const desc = chg5 >= 8 ? "动量强劲" : chg5 >= 3 ? "动量良好" : "小幅上涨";
      bullets.push(`近5日涨幅 ${chg5 >= 0 ? "+" : ""}${chg5.toFixed(1)}%，${desc}`);
    }
    // 量比
    const vr = item.volume_ratio;
    if (vr != null) {
      if (vr >= 2) bullets.push(`量比 ${vr.toFixed(2)}，成交显著放量，市场关注度高`);
      else if (vr >= 1.3) bullets.push(`量比 ${vr.toFixed(2)}，温和放量，买盘积极`);
      else bullets.push(`量比 ${vr.toFixed(2)}，成交平稳`);
    }
    // 主力资金
    const net3d = item.main_net_3d ?? 0;
    const net1d = item.main_net_1d ?? 0;
    if (net3d > 0) {
      bullets.push(`主力3日累计净流入 ${fmtWan(net3d)}${net1d > 0 ? "，最新一日持续净买入" : ""}`);
    } else if (net3d < 0) {
      bullets.push(`主力3日净流出 ${fmtWan(Math.abs(net3d))}，需关注资金持续性`);
    }
  } else if (rtype === "stable") {
    // 近3日动量
    const chg3 = item.change_pct_3d ?? 0;
    if (Math.abs(chg3) >= 0.01) {
      const desc = chg3 >= 2 ? "趋势向上" : chg3 >= 0 ? "温和上涨" : "小幅回调";
      bullets.push(`近3日涨幅 ${chg3 >= 0 ? "+" : ""}${chg3.toFixed(2)}%，${desc}`);
    }
    // 振幅
    const amp = item.avg_amplitude;
    if (amp != null) {
      const ampDesc = amp <= 1.5 ? "波动极低，持仓舒适度高" : amp <= 2.5 ? "低波动，风险可控" : "波动适中";
      bullets.push(`日均振幅 ${amp.toFixed(1)}%，${ampDesc}`);
    }
    // 量比
    const vr = item.volume_ratio;
    if (vr != null) {
      bullets.push(`量比 ${vr.toFixed(2)}，${vr >= 1.2 ? "资金有所涌入" : "缩量整理，筹码稳定"}`);
    }
    // 主力资金
    const net3d = item.main_net_3d ?? 0;
    if (net3d > 0) bullets.push(`主力3日净流入 ${fmtWan(net3d)}，机构资金持续布局`);
    else if (net3d < 0) bullets.push(`主力3日净流出 ${fmtWan(Math.abs(net3d))}`);
  } else if (rtype === "stable_stock") {
    // 近5日动量
    const chg5 = item.change_pct_5d ?? 0;
    if (Math.abs(chg5) >= 0.1) {
      const desc = chg5 >= 5 ? "稳步上涨" : chg5 >= 2 ? "温和向上" : "小幅上涨";
      bullets.push(`近5日涨幅 ${chg5 >= 0 ? "+" : ""}${chg5.toFixed(1)}%，${desc}，无大幅跳涨`);
    }
    // 振幅
    const amp = item.avg_amplitude;
    if (amp != null) {
      const ampDesc = amp <= 2 ? "低波动优选，适合稳健持仓" : "波动适中";
      bullets.push(`日均振幅 ${amp.toFixed(1)}%，${ampDesc}`);
    }
    // 量比
    const vr = item.volume_ratio;
    if (vr != null) {
      bullets.push(`量比 ${vr.toFixed(2)}，${vr <= 2.5 ? "成交健康，无炒作迹象" : "成交偏活跃"}`);
    }
    // 主力资金
    const net3d = item.main_net_3d ?? 0;
    const net1d = item.main_net_1d ?? 0;
    if (net3d > 0) {
      bullets.push(`主力3日持续净流入 ${fmtWan(net3d)}${net1d > 0 ? "，昨日持续净买入" : ""}`);
    } else if (net3d < 0) {
      bullets.push(`主力3日净流出 ${fmtWan(Math.abs(net3d))}`);
    }
  }

  return bullets;
}

// ─── 工作台股票详情卡 ──────────────────────────────────────────────────────────
function StockWorkbenchCard({ item }: { item: any }) {
  const rtype: string = item.result_type ?? "aggressive";
  const isEtf = rtype === "stable";
  const decimals = isEtf ? 4 : 2;

  let typeLabel = "激进标";
  let typeColor = "red";
  if (rtype === "aggressive_main") { typeLabel = "主推"; typeColor = "orange"; }
  else if (rtype === "aggressive_backup") { typeLabel = "备用"; typeColor = "default"; }
  else if (rtype === "stable") { typeLabel = "稳健ETF"; typeColor = "blue"; }
  else if (rtype === "stable_stock") { typeLabel = "稳健个股"; typeColor = "green"; }

  const changeVal = rtype === "stable"
    ? item.change_pct_3d
    : item.change_pct_5d;
  const changeLabel = rtype === "stable" ? "近3日" : "近5日";

  const borderColor: Record<string, string> = {
    aggressive: "#cf1322", aggressive_main: "#d46b08", aggressive_backup: "#999",
    stable: "#1677ff", stable_stock: "#52c41a",
  };

  const rationale = buildRationale(item);
  const rationaleColor = ["stable", "stable_stock"].includes(rtype) ? "#52c41a" : "#d46b08";
  const rationaleBg = ["stable", "stable_stock"].includes(rtype) ? "#f6ffed" : "#fffbe6";

  return (
    <Card
      size="small"
      style={{ height: "100%", borderTop: `3px solid ${borderColor[rtype] ?? "#999"}` }}
      title={
        <Space wrap size={4}>
          <Text strong style={{ fontSize: 15 }}>{item.code}</Text>
          <Text type="secondary" style={{ fontSize: 13 }}>{item.name}</Text>
          <Tag color={typeColor} style={{ marginLeft: 2 }}>{typeLabel}</Tag>
          <Tag color={item.score >= 70 ? "red" : item.score >= 50 ? "orange" : "default"}>
            {item.score?.toFixed(1)}分
          </Tag>
          {item.rank && <Tag>#{item.rank}</Tag>}
        </Space>
      }
    >
      {/* 价格三要素 */}
      <Row gutter={[8, 4]} style={{ marginBottom: 8, textAlign: "center" }}>
        <Col span={8}>
          <div style={{ fontSize: 11, color: "#aaa" }}>参考价</div>
          <div style={{ fontWeight: 600, fontSize: 14 }}>{item.close_price?.toFixed(decimals)}</div>
        </Col>
        <Col span={8}>
          <div style={{ fontSize: 11, color: "#aaa" }}>目标价</div>
          <div style={{ fontWeight: 600, fontSize: 14, color: "#cf1322" }}>{item.target_price?.toFixed(decimals)}</div>
        </Col>
        <Col span={8}>
          <div style={{ fontSize: 11, color: "#aaa" }}>止损价</div>
          <div style={{ fontWeight: 600, fontSize: 14, color: "#389e0d" }}>{item.stop_loss_price?.toFixed(decimals)}</div>
        </Col>
      </Row>

      <Divider style={{ margin: "6px 0" }} />

      {/* 关键指标 */}
      <Row gutter={[4, 4]} style={{ marginBottom: 8, fontSize: 12 }}>
        <Col span={12}>
          <Text type="secondary">{changeLabel}: </Text>
          <Text style={{ color: (changeVal ?? 0) >= 0 ? "#cf1322" : "#389e0d" }}>
            {fmtPct(changeVal, 1)}
          </Text>
        </Col>
        <Col span={12}>
          <Text type="secondary">换手率: </Text>
          <Text>{item.turnover_rate != null ? `${item.turnover_rate?.toFixed(1)}%` : "-"}</Text>
        </Col>
        <Col span={12}>
          <Text type="secondary">主力1日: </Text>
          <Text style={{ color: (item.main_net_1d ?? 0) > 0 ? "#cf1322" : "#389e0d" }}>
            {fmtWan(item.main_net_1d)}
          </Text>
        </Col>
        <Col span={12}>
          <Text type="secondary">主力3日: </Text>
          <Text style={{ color: (item.main_net_3d ?? 0) > 0 ? "#cf1322" : "#389e0d" }}>
            {fmtWan(item.main_net_3d)}
          </Text>
        </Col>
        {item.volume_ratio != null && (
          <Col span={12}>
            <Text type="secondary">量比: </Text>
            <Text>{item.volume_ratio?.toFixed(2)}</Text>
          </Col>
        )}
        {item.avg_amplitude != null && (
          <Col span={12}>
            <Text type="secondary">日均振幅: </Text>
            <Text>{fmtPct(item.avg_amplitude, 1)}</Text>
          </Col>
        )}
        {item.catalyst_sector && (
          <Col span={24}>
            <Text type="secondary">催化: </Text>
            <Tag color={STRENGTH_COLOR[item.catalyst_strength] ?? "default"} style={{ fontSize: 11 }}>
              {item.catalyst_sector}{item.catalyst_strength > 0 ? ` ${item.catalyst_strength}★` : ""}
            </Tag>
          </Col>
        )}
      </Row>

      <Divider style={{ margin: "6px 0" }} />

      {/* 选中依据（默认折叠） */}
      {rationale.length > 0 && (
        <Collapse
          size="small"
          ghost
          style={{ marginBottom: 8 }}
          items={[{
            key: "rationale",
            label: <span style={{ fontSize: 12, color: rationaleColor, fontWeight: 600 }}>推荐理由</span>,
            children: (
              <div style={{
                fontSize: 12,
                padding: "4px 8px",
                background: rationaleBg,
                borderRadius: 4,
                borderLeft: `3px solid ${rationaleColor}`,
                lineHeight: 1.8,
              }}>
                {rationale.map((line, i) => (
                  <div key={i} style={{ color: "#555" }}>• {line}</div>
                ))}
              </div>
            ),
          }]}
        />
      )}

      {/* 操作建议 */}
      <div style={{
        fontSize: 12,
        padding: "8px 10px",
        background: ["aggressive", "aggressive_main", "aggressive_backup"].includes(rtype) ? "#fff7e6" : "#f0f5ff",
        borderRadius: 4,
        borderLeft: `3px solid ${borderColor[rtype] ?? "#999"}`,
        marginBottom: 8,
        lineHeight: 1.7,
        color: "#333",
      }}>
        {item.suggestion ?? "暂无建议"}
      </div>

      {/* 日K线 */}
      <div style={{ fontSize: 11, color: "#aaa", marginBottom: 2 }}>
        日K收盘走势（近60日）｜<span style={{ color: "#cf1322" }}>红虚=目标价</span>
        {" "}｜<span style={{ color: "#389e0d" }}>绿虚=止损价</span>
      </div>
      <StockKlineChart
        code={item.code}
        targetPrice={item.target_price}
        stopLossPrice={item.stop_loss_price}
        height={160}
      />
    </Card>
  );
}

// ─── 表格展开行：建议 + K线 ───────────────────────────────────────────────────
function ExpandedRow({ record, isEtf = false }: { record: any; isEtf?: boolean }) {
  const rationale = buildRationale(record);
  const rtype: string = record.result_type ?? "aggressive";
  const rationaleColor = ["stable", "stable_stock"].includes(rtype) ? "#52c41a" : "#d46b08";
  const rationaleBg = ["stable", "stable_stock"].includes(rtype) ? "#f6ffed" : "#fffbe6";

  return (
    <Row gutter={[16, 8]} style={{ padding: "8px 16px 12px" }}>
      <Col xs={24} md={8}>
        <Descriptions size="small" column={1} style={{ fontSize: 12 }}>
          <Descriptions.Item label="操作建议">
            <Paragraph style={{ margin: 0, fontSize: 12, lineHeight: 1.7 }}>
              {record.suggestion ?? "-"}
            </Paragraph>
          </Descriptions.Item>
          {record.catalyst_sector && (
            <Descriptions.Item label="催化板块">
              <Tag color={STRENGTH_COLOR[record.catalyst_strength] ?? "default"}>
                {record.catalyst_sector}{record.catalyst_strength > 0 ? ` ${record.catalyst_strength}★` : ""}
              </Tag>
            </Descriptions.Item>
          )}
          <Descriptions.Item label="主力3日">{fmtWan(record.main_net_3d)}</Descriptions.Item>
          {record.avg_amplitude != null && (
            <Descriptions.Item label="日均振幅">{fmtPct(record.avg_amplitude, 1)}</Descriptions.Item>
          )}
        </Descriptions>
        {rationale.length > 0 && (
          <Collapse
            size="small"
            ghost
            style={{ marginTop: 8 }}
            items={[{
              key: "r",
              label: <span style={{ fontSize: 12, color: rationaleColor, fontWeight: 600 }}>推荐理由</span>,
              children: (
                <div style={{
                  fontSize: 12,
                  padding: "4px 8px",
                  background: rationaleBg,
                  borderRadius: 4,
                  borderLeft: `3px solid ${rationaleColor}`,
                  lineHeight: 1.8,
                }}>
                  {rationale.map((line, i) => (
                    <div key={i} style={{ color: "#555" }}>• {line}</div>
                  ))}
                </div>
              ),
            }]}
          />
        )}
      </Col>
      <Col xs={24} md={16}>
        <div style={{ fontSize: 11, color: "#aaa", marginBottom: 2 }}>
          日K收盘走势（近60日）｜红虚=目标价 绿虚=止损价
        </div>
        <StockKlineChart
          code={record.code}
          targetPrice={record.target_price}
          stopLossPrice={record.stop_loss_price}
          height={180}
        />
      </Col>
    </Row>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────
export default function PreMarketPage() {
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [progressStep, setProgressStep] = useState("");
  const [tradeDate, setTradeDate] = useState<string | null>(null);
  const [aggressive, setAggressive] = useState<any[]>([]);
  const [fallbackMain, setFallbackMain] = useState<any[]>([]);
  const [fallbackBackup, setFallbackBackup] = useState<any[]>([]);
  const [stable, setStable] = useState<any[]>([]);
  const [catalysts, setCatalysts] = useState<any[]>([]);
  const [performance, setPerformance] = useState<any>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadDate = useCallback(async (dateStr: string) => {
    setLoading(true);
    try {
      const [data, cats] = await Promise.all([
        getPreMarketByDate(dateStr),
        getPreMarketCatalysts(dateStr),
      ]);
      setTradeDate(data.trade_date);
      setAggressive(data.aggressive ?? []);
      setFallbackMain(data.fallback_main ?? []);
      setFallbackBackup(data.fallback_backup ?? []);
      setStable(data.stable ?? []);
      setCatalysts(cats ?? []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    Promise.all([
      getPreMarketLatest().catch(() => null),
      getPreMarketHistory(30).catch(() => []),
      getPreMarketPerformance(30).catch(() => null),
    ]).then(([latest, hist, perf]) => {
      setHistory(hist ?? []);
      setPerformance(perf);
      if (latest?.trade_date) {
        setTradeDate(latest.trade_date);
        setAggressive(latest.aggressive ?? []);
        setFallbackMain(latest.fallback_main ?? []);
        setFallbackBackup(latest.fallback_backup ?? []);
        setStable(latest.stable ?? []);
        setSelectedDate(latest.trade_date);
        getPreMarketCatalysts(latest.trade_date).then(setCatalysts).catch(() => {});
      }
      setLoading(false);
    });
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  const pollTask = useCallback((tid: string) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const task = await getPreMarketTask(tid);
        setProgress(task.progress ?? 0);
        setProgressStep(task.step ?? "");
        if (task.status === "completed" || task.status === "failed") {
          clearInterval(pollRef.current!);
          setRunning(false);
          if (task.status === "completed" && task.trade_date) {
            await loadDate(task.trade_date);
            setSelectedDate(task.trade_date);
            const [hist, perf] = await Promise.all([
              getPreMarketHistory(30).catch(() => []),
              getPreMarketPerformance(30).catch(() => null),
            ]);
            setHistory(hist ?? []);
            setPerformance(perf);
          }
        }
      } catch {
        clearInterval(pollRef.current!);
        setRunning(false);
      }
    }, 2000);
  }, [loadDate]);

  const handleRun = async () => {
    setRunning(true);
    setProgress(0);
    setProgressStep("触发中...");
    try {
      const res = await triggerPreMarket(selectedDate ?? undefined);
      if (res.task_id) {
        pollTask(res.task_id);
      } else {
        setRunning(false);
      }
    } catch {
      setRunning(false);
    }
  };

  const handleDateChange = async (dateStr: string) => {
    setSelectedDate(dateStr);
    await loadDate(dateStr);
  };

  // ─── 表格列定义 ───────────────────────────────────────────────────────────

  const aggColumns = [
    { title: "排名", dataIndex: "rank", width: 55 },
    {
      title: "代码/名称", key: "code", width: 100,
      render: (_: any, r: any) => (
        <Space direction="vertical" size={0}>
          <Text strong>{r.code}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>{r.name}</Text>
        </Space>
      ),
    },
    {
      title: "评分", dataIndex: "score", width: 65,
      render: (v: number) => (
        <Text strong style={{ color: v >= 70 ? "#cf1322" : v >= 50 ? "#d46b08" : undefined }}>{v?.toFixed(1)}</Text>
      ),
    },
    {
      title: "催化板块", key: "catalyst", width: 130,
      render: (_: any, r: any) => r.catalyst_sector
        ? <Tag color={STRENGTH_COLOR[r.catalyst_strength] ?? "default"}>
            {r.catalyst_sector}{r.catalyst_strength > 0 ? ` ${r.catalyst_strength}★` : ""}
          </Tag>
        : "-",
    },
    { title: "近5日", dataIndex: "change_pct_5d", width: 75, render: (v: number) => <Text style={{ color: v >= 0 ? "#cf1322" : "#389e0d" }}>{fmtPct(v)}</Text> },
    { title: "前1日", dataIndex: "change_pct_1d", width: 75, render: (v: number) => <Text style={{ color: v >= 0 ? "#cf1322" : "#389e0d" }}>{fmtPct(v)}</Text> },
    { title: "换手率", dataIndex: "turnover_rate", width: 75, render: (v: number) => `${v?.toFixed(1)}%` },
    { title: "量比", dataIndex: "volume_ratio", width: 65, render: (v: number) => v?.toFixed(2) },
    { title: "主力1日", dataIndex: "main_net_1d", width: 80, render: fmtWan },
    { title: "参考价", dataIndex: "close_price", width: 75, render: (v: number) => fmtPrice(v) },
    { title: "目标价", dataIndex: "target_price", width: 75, render: (v: number) => <Text style={{ color: "#cf1322" }}>{fmtPrice(v)}</Text> },
    { title: "止损价", dataIndex: "stop_loss_price", width: 75, render: (v: number) => <Text style={{ color: "#389e0d" }}>{fmtPrice(v)}</Text> },
    {
      title: "结果", dataIndex: "exit_type", width: 75,
      render: (v: string, r: any) => v && v !== "pending"
        ? <Tooltip title={`实际收益 ${fmtPct(r.actual_return_pct)}`}><Tag color={EXIT_COLOR[v]}>{EXIT_LABEL[v] ?? v}</Tag></Tooltip>
        : <Tag color="default">待结</Tag>,
    },
    {
      title: "操作", key: "action", width: 65, fixed: "right" as const,
      render: (_: any, r: any) => (
        <Button size="small" icon={<EyeOutlined />}
          onClick={() => addWatchItem({ code: r.code, name: r.name, source: "pre_market" }).then(() => {}).catch(() => {})}
        >关注</Button>
      ),
    },
  ];

  const fallbackAggColumns = [
    {
      title: "类别", key: "role", width: 65,
      render: (_: any, r: any) => r.rank === 1
        ? <Tag color="orange">主推</Tag>
        : <Tag color="default">备用</Tag>,
    },
    ...aggColumns,
  ];

  const stableColumns = [
    { title: "排名", dataIndex: "rank", width: 55 },
    {
      title: "代码/名称", key: "code", width: 120,
      render: (_: any, r: any) => (
        <Space direction="vertical" size={0}>
          <Text strong>{r.code}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>{r.name}</Text>
        </Space>
      ),
    },
    {
      title: "类型", key: "result_type", width: 70,
      render: (_: any, r: any) => r.result_type === "stable_stock"
        ? <Tag color="green">个股</Tag>
        : <Tag color="blue">ETF</Tag>,
    },
    {
      title: "评分", dataIndex: "score", width: 65,
      render: (v: number) => (
        <Text strong style={{ color: v >= 70 ? "#cf1322" : v >= 50 ? "#d46b08" : undefined }}>{v?.toFixed(1)}</Text>
      ),
    },
    {
      title: "近3日/5日", key: "change", width: 90,
      render: (_: any, r: any) => {
        const v = r.result_type === "stable_stock" ? r.change_pct_5d : r.change_pct_3d;
        return <Text style={{ color: v >= 0 ? "#cf1322" : "#389e0d" }}>{fmtPct(v)}</Text>;
      },
    },
    { title: "MA5方向", dataIndex: "ma5_direction", width: 80, render: (v: string) => <Tag color={v === "up" ? "green" : v === "down" ? "red" : "default"}>{v ?? "-"}</Tag> },
    { title: "MA5偏离", dataIndex: "ma5_deviation", width: 80, render: (v: number) => fmtPct(v) },
    {
      title: "额/量比", dataIndex: "amount_ratio", width: 80,
      render: (v: number, r: any) => (
        <Tooltip title={(r.score_detail?.liquidity_ratio_source || r.amount_ratio_source) === "volume" ? "使用成交量/20日均量" : "成交额/20日均额"}>
          <Text>{v?.toFixed(2)}</Text>
        </Tooltip>
      ),
    },
    { title: "日均振幅", dataIndex: "avg_amplitude", width: 80, render: (v: number) => fmtPct(v) },
    { title: "参考价", dataIndex: "close_price", width: 80, render: (v: number, r: any) => fmtPrice(v, r.result_type === "stable_stock" ? 2 : 4) },
    { title: "目标价", dataIndex: "target_price", width: 80, render: (v: number, r: any) => <Text style={{ color: "#cf1322" }}>{fmtPrice(v, r.result_type === "stable_stock" ? 2 : 4)}</Text> },
    { title: "止损价", dataIndex: "stop_loss_price", width: 80, render: (v: number, r: any) => <Text style={{ color: "#389e0d" }}>{fmtPrice(v, r.result_type === "stable_stock" ? 2 : 4)}</Text> },
    {
      title: "结果", dataIndex: "exit_type", width: 75,
      render: (v: string, r: any) => v && v !== "pending"
        ? <Tooltip title={`实际收益 ${fmtPct(r.actual_return_pct)}`}><Tag color={EXIT_COLOR[v]}>{EXIT_LABEL[v] ?? v}</Tag></Tooltip>
        : <Tag color="default">待结</Tag>,
    },
    {
      title: "操作", key: "action", width: 65, fixed: "right" as const,
      render: (_: any, r: any) => (
        <Button size="small" icon={<EyeOutlined />}
          onClick={() => addWatchItem({ code: r.code, name: r.name, source: "pre_market" }).then(() => {}).catch(() => {})}
        >关注</Button>
      ),
    },
  ];

  // ─── 衍生状态 ─────────────────────────────────────────────────────────────
  const topCatalyst = catalysts[0];
  const perfAgg = performance?.aggressive;
  const perfStable = performance?.stable;
  const hasFallback = fallbackMain.length > 0 || fallbackBackup.length > 0;
  const fallbackItems = [...fallbackMain, ...fallbackBackup];
  const aggTabCount = aggressive.length || fallbackItems.length;
  const workbenchAggItems = aggressive.length ? aggressive : fallbackItems;

  return (
    <div>
      {/* 标题栏 */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, marginBottom: 16 }}>
        <div>
          <Title level={3} style={{ marginBottom: 4 }}>
            <RadarChartOutlined style={{ marginRight: 8 }} />盘前选股
          </Title>
          <Text type="secondary">每日 7:00 AM 自动输出激进标（个股 +5%/-3%）+ 稳健标（ETF/个股 +2%/-1.5%）</Text>
        </div>
        <Space wrap>
          <Select
            placeholder="选择历史日期"
            style={{ width: 140 }}
            options={history.map(h => ({ value: h.trade_date, label: h.trade_date }))}
            value={selectedDate}
            onChange={handleDateChange}
            allowClear
          />
          <Button
            type="primary"
            icon={running ? <Spin size="small" /> : <ThunderboltOutlined />}
            onClick={handleRun}
            disabled={running}
          >
            {running ? "运行中..." : "手动触发"}
          </Button>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => selectedDate ? loadDate(selectedDate) : getPreMarketLatest().then(d => {
              if (d?.trade_date) loadDate(d.trade_date);
            })}
          >刷新</Button>
        </Space>
      </div>

      {running && (
        <Card style={{ marginBottom: 16 }}>
          <Progress percent={progress} status={progress >= 100 ? "success" : "active"} />
          <Text type="secondary">{progressStep}</Text>
        </Card>
      )}

      {/* 统计卡片 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} md={6}>
          <Card>
            <Statistic
              title={hasFallback && !aggressive.length ? "激进标（降级）" : "激进标"}
              value={aggTabCount}
              suffix="只"
              valueStyle={{ color: hasFallback && !aggressive.length ? "#d46b08" : "#cf1322" }}
            />
            <Text type="secondary">目标 +5% | 止损 -3%</Text>
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic title="稳健标" value={stable.length} suffix="只" valueStyle={{ color: "#1677ff" }} />
            <Text type="secondary">目标 +2% | 止损 -1.5%</Text>
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic title="最强催化" value={topCatalyst?.sector_name ?? "-"} valueStyle={{ fontSize: 18 }} />
            {topCatalyst && <Tag color={STRENGTH_COLOR[topCatalyst.catalyst_strength]}>强度 {topCatalyst.catalyst_strength}</Tag>}
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic
              title="激进/稳健胜率(近30日)"
              value={perfAgg?.win_rate != null
                ? `${(perfAgg.win_rate * 100).toFixed(0)}% / ${perfStable?.win_rate != null ? (perfStable.win_rate * 100).toFixed(0) + "%" : "-"}`
                : "-"}
              valueStyle={{ fontSize: 18 }}
            />
            <Text type="secondary">已结仓 {(perfAgg?.count ?? 0) + (perfStable?.count ?? 0)} 笔</Text>
          </Card>
        </Col>
      </Row>

      {loading ? (
        <Spin size="large" style={{ display: "block", margin: "60px auto" }} />
      ) : (
        <Tabs
          defaultActiveKey="workbench"
          items={[
            // ── 工作台 ──────────────────────────────────────────────────────
            {
              key: "workbench",
              label: (
                <span>
                  <AppstoreOutlined style={{ marginRight: 4 }} />工作台
                </span>
              ),
              children: (() => {
                const hasAny = workbenchAggItems.length > 0 || stable.length > 0;
                // 有数据但激进标全被过滤（低分）且无降级结果
                const noAggressiveSignal = tradeDate && aggressive.length === 0 && !hasFallback;
                if (!hasAny && !noAggressiveSignal) return <Empty description="暂无推荐标的，请先手动触发选股" />;
                return (
                  <div>
                    {/* 激进标无信号提示 */}
                    {noAggressiveSignal && (
                      <Alert
                        type="warning"
                        showIcon
                        message="🚫 今日激进标无有效信号，建议空仓休息"
                        description="所有候选标的评分均低于 65 分，催化或技术形态不足，建议仅操作稳健标或今日不操作。"
                        style={{ marginBottom: 16 }}
                      />
                    )}
                    {/* 激进标区 */}
                    {workbenchAggItems.length > 0 && (
                      <div style={{ marginBottom: 28 }}>
                        <div style={{ marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
                          <Text strong style={{ fontSize: 15 }}>🔥 激进标</Text>
                          {!aggressive.length && hasFallback && (
                            <Tag color="warning">降级·纯技术面</Tag>
                          )}
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            {tradeDate} | 目标+5% 止损-3%
                          </Text>
                        </div>
                        <Row gutter={[16, 16]}>
                          {workbenchAggItems.map((item) => (
                            <Col key={item.id ?? item.code} xs={24} lg={12} xxl={8}>
                              <StockWorkbenchCard item={item} />
                            </Col>
                          ))}
                        </Row>
                      </div>
                    )}

                    {/* 稳健标区 */}
                    {stable.length > 0 && (
                      <div>
                        <div style={{ marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
                          <Text strong style={{ fontSize: 15 }}>🛡️ 稳健标</Text>
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            {tradeDate} | 目标+2% 止损-1.5%
                          </Text>
                        </div>
                        <Row gutter={[16, 16]}>
                          {stable.map((item) => (
                            <Col key={item.id ?? item.code} xs={24} lg={12} xxl={8}>
                              <StockWorkbenchCard item={item} />
                            </Col>
                          ))}
                        </Row>
                      </div>
                    )}
                  </div>
                );
              })(),
            },

            // ── 激进标 Tab ────────────────────────────────────────────────
            {
              key: "aggressive",
              label: <Badge count={aggTabCount} offset={[8, 0]}><span>激进标（个股）</span></Badge>,
              children: aggressive.length ? (
                <Table
                  dataSource={aggressive}
                  columns={aggColumns}
                  rowKey="id"
                  size="small"
                  scroll={{ x: 900 }}
                  pagination={false}
                  expandable={{
                    expandedRowRender: (r: any) => <ExpandedRow record={r} />,
                  }}
                />
              ) : hasFallback ? (
                <>
                  <Alert
                    type="warning"
                    showIcon
                    message="⚡ 激进标降级·纯技术面"
                    description="催化数据不足，已切换为纯技术面全市场筛选。主推1只 + 备用2只，仅供参考。"
                    style={{ marginBottom: 12 }}
                  />
                  <Table
                    dataSource={fallbackItems}
                    columns={fallbackAggColumns}
                    rowKey="id"
                    size="small"
                    scroll={{ x: 980 }}
                    pagination={false}
                    rowClassName={(r: any) => r.rank === 1 ? "ant-table-row-selected" : ""}
                    expandable={{
                      expandedRowRender: (r: any) => <ExpandedRow record={r} />,
                    }}
                  />
                </>
              ) : (
                <Empty description={`${tradeDate ?? "今日"} 暂无激进标，尝试手动触发选股`} />
              ),
            },

            // ── 稳健标 Tab ────────────────────────────────────────────────
            {
              key: "stable",
              label: <Badge count={stable.length} offset={[8, 0]}><span>稳健标（ETF+个股）</span></Badge>,
              children: stable.length ? (
                <Table
                  dataSource={stable}
                  columns={stableColumns}
                  rowKey="id"
                  size="small"
                  scroll={{ x: 980 }}
                  pagination={false}
                  expandable={{
                    expandedRowRender: (r: any) => <ExpandedRow record={r} isEtf={r.result_type === "stable"} />,
                  }}
                />
              ) : <Empty description={`${tradeDate ?? "今日"} 暂无稳健标`} />,
            },

            // ── 催化板块 Tab ───────────────────────────────────────────────
            {
              key: "catalysts",
              label: <Badge count={catalysts.length} offset={[8, 0]}><span>催化板块</span></Badge>,
              children: catalysts.length ? (
                <Row gutter={[12, 12]}>
                  {catalysts.map((c, i) => (
                    <Col key={i} xs={24} sm={12} md={8} lg={6}>
                      <Card size="small">
                        <Space direction="vertical" size={4} style={{ width: "100%" }}>
                          <Space>
                            <Text strong>{c.sector_name}</Text>
                            <Tag color={STRENGTH_COLOR[c.catalyst_strength]}>强度 {c.catalyst_strength}</Tag>
                            <Tag>{c.catalyst_type}</Tag>
                          </Space>
                          <Text type="secondary" style={{ fontSize: 12 }}>{c.summary}</Text>
                          {c.related_codes?.length > 0 && (
                            <Space wrap size={4}>
                              {c.related_codes.map((code: string) => <Tag key={code}>{code}</Tag>)}
                            </Space>
                          )}
                          {c.llm_used && <Tag color="blue" style={{ fontSize: 11 }}>LLM</Tag>}
                        </Space>
                      </Card>
                    </Col>
                  ))}
                </Row>
              ) : <Empty description="暂无催化板块数据" />,
            },

            // ── 绩效统计 Tab ───────────────────────────────────────────────
            {
              key: "performance",
              label: "绩效统计",
              children: performance ? (
                <Space direction="vertical" size={16} style={{ width: "100%" }}>
                  <Row gutter={[16, 16]}>
                    {[
                      { label: "激进标（个股）", data: performance.aggressive },
                      { label: "稳健标（ETF）", data: performance.stable },
                      { label: "综合", data: performance.combined },
                    ].map(({ label, data }) => (
                      <Col key={label} xs={24} md={8}>
                        <Card title={label} size="small">
                          {data?.count > 0 ? (
                            <Space direction="vertical" size={8} style={{ width: "100%" }}>
                              <Statistic title="总笔数" value={data.count} />
                              <Statistic title="胜率" value={data.win_rate != null ? `${(data.win_rate * 100).toFixed(1)}%` : "-"} />
                              <Statistic
                                title="平均收益"
                                value={data.avg_return != null ? fmtPct(data.avg_return) : "-"}
                                valueStyle={{ color: (data.avg_return ?? 0) >= 0 ? "#cf1322" : "#389e0d" }}
                              />
                              <Statistic title="盈亏比" value={data.profit_loss_ratio != null ? data.profit_loss_ratio.toFixed(2) : "-"} />
                            </Space>
                          ) : <Empty description="暂无已结仓记录" />}
                        </Card>
                      </Col>
                    ))}
                  </Row>
                  {performance.details?.length > 0 && (
                    <Card title="明细记录" size="small">
                      <Table
                        size="small"
                        rowKey={(r: any) => `${r.code}-${r.trade_date}-${r.result_type}`}
                        dataSource={performance.details}
                        pagination={{ pageSize: 20, showSizeChanger: false }}
                        columns={[
                          {
                            title: "名称/代码",
                            key: "name",
                            width: 120,
                            render: (_: any, r: any) => (
                              <div>
                                <div style={{ fontWeight: 600, fontSize: 13 }}>{r.name || r.code}</div>
                                <div style={{ fontSize: 11, color: "#8c8c8c" }}>{r.code}</div>
                              </div>
                            ),
                          },
                          {
                            title: "类型",
                            dataIndex: "result_type",
                            width: 80,
                            render: (v: string) => {
                              const map: Record<string, [string, string]> = {
                                aggressive_main: ["激进主", "orange"],
                                aggressive_backup: ["激进备", "gold"],
                                aggressive: ["激进", "orange"],
                                stable: ["稳健", "blue"],
                                stable_stock: ["稳健股", "geekblue"],
                              };
                              const [label, color] = map[v] ?? [v, "default"];
                              return <Tag color={color}>{label}</Tag>;
                            },
                          },
                          {
                            title: "推荐日",
                            dataIndex: "trade_date",
                            width: 95,
                            sorter: (a: any, b: any) => (a.trade_date || "").localeCompare(b.trade_date || ""),
                          },
                          {
                            title: "买入价",
                            dataIndex: "entry_price",
                            width: 75,
                            render: (v: number) => v != null ? v.toFixed(2) : "-",
                          },
                          {
                            title: "目标价",
                            dataIndex: "target_price",
                            width: 75,
                            render: (v: number) => v != null ? v.toFixed(2) : "-",
                          },
                          {
                            title: "止损价",
                            dataIndex: "stop_loss_price",
                            width: 75,
                            render: (v: number) => v != null ? v.toFixed(2) : "-",
                          },
                          {
                            title: "卖出日",
                            dataIndex: "exit_date",
                            width: 95,
                            render: (v: string) => v || "-",
                          },
                          {
                            title: "卖出价",
                            dataIndex: "exit_price",
                            width: 75,
                            render: (v: number) => v != null ? v.toFixed(2) : "-",
                          },
                          {
                            title: "持仓天数",
                            dataIndex: "holding_days",
                            width: 80,
                            sorter: (a: any, b: any) => (a.holding_days ?? 0) - (b.holding_days ?? 0),
                            render: (_: any, r: any) => {
                              if (r.exit_date) return `${r.holding_days}天`;
                              return <Tag color="processing">持仓中 {r.holding_days}天</Tag>;
                            },
                          },
                          {
                            title: "状态",
                            dataIndex: "exit_type",
                            width: 110,
                            render: (v: string, r: any) => {
                              if (v === "take_profit") return <Tag color="success">止盈</Tag>;
                              if (v === "stop_loss") return <Tag color="error">止损</Tag>;
                              if (v === "max_hold") return <Tag color="warning">到期平仓</Tag>;
                              // 进行中
                              if (r.deadline_passed) return <Tag color="default">待回填</Tag>;
                              return <Tag color="processing">尚未到截止日</Tag>;
                            },
                          },
                          {
                            title: "收益率",
                            dataIndex: "return_pct",
                            width: 90,
                            sorter: (a: any, b: any) => (a.return_pct ?? -999) - (b.return_pct ?? -999),
                            render: (v: number) => v != null ? (
                              <span style={{ color: v >= 0 ? "#cf1322" : "#389e0d", fontWeight: 600 }}>
                                {fmtPct(v)}
                              </span>
                            ) : "-",
                          },
                        ]}
                      />
                    </Card>
                  )}
                </Space>
              ) : <Empty description="暂无绩效数据" />,
            },
          ]}
        />
      )}
    </div>
  );
}
