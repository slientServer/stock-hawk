"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  App,
  AutoComplete,
  Badge,
  Button,
  Card,
  Col,
  Collapse,
  Descriptions,
  Divider,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Space,
  Spin,
  Statistic,
  Switch,
  Table,
  Tag,
  Tabs,
  Tooltip,
  Typography,
} from "antd";
import {
  DashboardOutlined,
  EditOutlined,
  EyeOutlined,
  FundOutlined,
  MinusCircleOutlined,
  PlusOutlined,
  RadarChartOutlined,
  ReadOutlined,
  ReloadOutlined,
  RiseOutlined,
  SearchOutlined,
  SettingOutlined,
  SyncOutlined,
} from "@ant-design/icons";
import { useRouter } from "next/navigation";
import {
  addWatchItem,
  closePosition,
  createPosition,
  getPortfolioQuote,
  getPositions,
  getPreMarketLatest,
  getWatchlist,
  removeWatchItem,
  searchStocks,
  updatePosition,
  updateWatchItem,
} from "@/lib/api";

const { Title, Text, Paragraph } = Typography;

// ─── 工具函数 ─────────────────────────────────────────────────────────────────
function fmtMoney(v: number | null | undefined) {
  if (v == null) return "-";
  const abs = Math.abs(v);
  if (abs >= 1e8) return `${(v / 1e8).toFixed(2)}亿`;
  if (abs >= 1e4) return `${(v / 1e4).toFixed(2)}万`;
  return v.toFixed(2);
}
function fmtPct(v: number | null | undefined) {
  if (v == null) return "-";
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
}
function fmtPrice(v: number | null | undefined, d = 3) {
  if (v == null) return "-";
  return v.toFixed(d);
}

// 是否处于交易时间
function isMarketOpen() {
  const now = new Date();
  const day = now.getDay();
  if (day === 0 || day === 6) return false;
  const mins = now.getHours() * 60 + now.getMinutes();
  return (mins >= 9 * 60 + 25 && mins <= 11 * 60 + 35) ||
    (mins >= 13 * 60 - 5 && mins <= 15 * 60 + 5);
}

// ─── 价格横轴可视化 ──────────────────────────────────────────────────────────
function PriceBar({
  avgCost, currentPrice, targetPrice, stopLossPrice,
}: {
  avgCost: number;
  currentPrice: number | null;
  targetPrice: number | null;
  stopLossPrice: number | null;
}) {
  if (!avgCost || avgCost <= 0) return null;

  const stop = stopLossPrice ?? avgCost * 0.92;
  const target = targetPrice ?? avgCost * 1.08;
  // 补仓线 = 止损与成本的中点，是一个自然的逢低加仓参考位
  const addLine = (stop + avgCost) / 2;
  const cur = currentPrice ?? avgCost;

  const low = Math.min(stop, cur) * 0.988;
  const high = Math.max(target, cur) * 1.012;
  const range = high - low || 1;

  // 价格 → bar 百分比
  const px = (p: number) =>
    `${Math.max(0, Math.min(100, ((p - low) / range) * 100)).toFixed(2)}%`;
  const pw = (p1: number, p2: number) =>
    `${Math.max(0, ((Math.min(p2, high) - Math.max(p1, low)) / range) * 100).toFixed(2)}%`;

  const isProfit = cur >= avgCost;
  const isStopHit = stopLossPrice != null && cur <= stopLossPrice;
  const isTpHit = targetPrice != null && cur >= targetPrice;
  const dotColor = isTpHit ? "#52c41a" : isStopHit ? "#ff4d4f" : isProfit ? "#cf1322" : "#fa8c16";

  // 标签列表（按价格排序，奇偶交错行）
  const markers = [
    { price: stop, label: "止损", color: "#ff4d4f" },
    { price: addLine, label: "补仓", color: "#fa8c16" },
    { price: avgCost, label: "成本", color: "#1677ff" },
    { price: target, label: "目标", color: "#52c41a" },
  ].sort((a, b) => a.price - b.price);

  return (
    <div style={{ margin: "4px 0 0", userSelect: "none" }}>
      {/* ── 价格条 ── */}
      <div style={{ position: "relative", height: 10, borderRadius: 5, background: "#f0f0f0" }}>
        {/* 止损→补仓：危险红 */}
        <div style={{ position: "absolute", left: px(stop), width: pw(stop, addLine), height: "100%", background: "#ffa39e", borderRadius: "5px 0 0 5px" }} />
        {/* 补仓→成本：警告橙 */}
        <div style={{ position: "absolute", left: px(addLine), width: pw(addLine, avgCost), height: "100%", background: "#ffd591" }} />
        {/* 成本→目标：盈利绿 */}
        <div style={{ position: "absolute", left: px(avgCost), width: pw(avgCost, target), height: "100%", background: "#b7eb8f", borderRadius: "0 5px 5px 0" }} />

        {/* 竖向标记线 */}
        {markers.map(({ price, color }) => (
          <div key={price} style={{ position: "absolute", left: px(price), top: 0, width: 2, height: "100%", background: color, transform: "translateX(-1px)", opacity: 0.8 }} />
        ))}

        {/* 当前价光标（闪烁圆点） */}
        {currentPrice != null && (
          <div style={{
            position: "absolute", left: px(cur), top: "50%",
            width: 14, height: 14, borderRadius: "50%",
            background: dotColor, border: "2px solid #fff",
            boxShadow: `0 0 0 2px ${dotColor}44`,
            transform: "translate(-50%, -50%)", zIndex: 3,
          }} />
        )}
      </div>

      {/* ── 标签行 ── */}
      <div style={{ position: "relative", height: 40, marginTop: 4 }}>
        {markers.map(({ price, label, color }, i) => (
          <div key={label} style={{
            position: "absolute", left: px(price), transform: "translateX(-50%)",
            textAlign: "center", lineHeight: 1.2,
            top: i % 2 === 0 ? 0 : 18,
          }}>
            <div style={{ fontSize: 9, color, fontWeight: 700, whiteSpace: "nowrap" }}>{label}</div>
            <div style={{ fontSize: 10, color: "#666" }}>{price.toFixed(2)}</div>
          </div>
        ))}
        {/* 当前价格标签 */}
        {currentPrice != null && (
          <div style={{
            position: "absolute", left: px(cur), transform: "translateX(-50%)",
            textAlign: "center", lineHeight: 1.2, top: 0, zIndex: 4,
          }}>
            <div style={{ fontSize: 9, color: dotColor, fontWeight: 700 }}>▼</div>
            <div style={{ fontSize: 10, color: dotColor, fontWeight: 700 }}>{cur.toFixed(2)}</div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── 持仓卡片 ─────────────────────────────────────────────────────────────────
const STATUS_COLOR: Record<string, string> = {
  take_profit: "#52c41a", stop_loss: "#ff4d4f", holding: "#1677ff", data_missing: "#aaa",
};
const STATUS_LABEL: Record<string, string> = {
  take_profit: "触及止盈 ✓", stop_loss: "触及止损 ✗", holding: "持仓中", data_missing: "无行情",
};
const REC_TYPE_COLOR: Record<string, string> = {
  aggressive: "#cf1322", aggressive_main: "#d4380d",
  aggressive_backup: "#fa8c16", stable: "#1677ff", stable_stock: "#52c41a",
};
const REC_TYPE_LABEL: Record<string, string> = {
  aggressive: "激进", aggressive_main: "激进主推",
  aggressive_backup: "激进备选", stable: "稳健ETF", stable_stock: "稳健个股",
};

function PositionCard({
  item,
  onEdit,
  onClose,
  onAddBuy,
}: {
  item: any;
  onEdit: (item: any) => void;
  onClose: (id: number, name: string) => void;
  onAddBuy: (code: string, name: string) => void;
}) {
  const st = item.threshold_status ?? "holding";
  const borderColor = STATUS_COLOR[st] ?? "#d9d9d9";
  const pnl = item.unrealized_profit ?? 0;
  const pnlPct = item.unrealized_return_pct ?? 0;
  const pnlColor = pnl > 0 ? "#cf1322" : pnl < 0 ? "#389e0d" : "#555";
  const changePct = item.change_pct;

  return (
    <Card
      size="small"
      style={{ borderTop: `3px solid ${borderColor}` }}
      bodyStyle={{ padding: "10px 12px" }}
      title={
        <Space size={4} wrap>
          <Text strong style={{ fontSize: 15 }}>{item.code}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>{item.name}</Text>
          {item.source && item.source !== "manual" && <Tag style={{ fontSize: 10 }}>{item.source}</Tag>}
        </Space>
      }
      extra={
        <Space size={6}>
          {item.is_realtime && <Badge status="processing" />}
          <Tag color={STATUS_COLOR[st]} style={{ fontSize: 11 }}>{STATUS_LABEL[st]}</Tag>
          <Button size="small" icon={<PlusOutlined />} onClick={() => onAddBuy(item.code, item.name)}>加仓</Button>
          <Button size="small" icon={<EditOutlined />} type="primary" ghost onClick={() => onEdit(item)}>修改</Button>
          <Popconfirm
            title={`平仓 ${item.name}`}
            description="将以当前行情价平仓，确认？"
            onConfirm={() => onClose(item.id, item.name)}
            okText="确认平仓" cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Button size="small" danger icon={<MinusCircleOutlined />}>平仓</Button>
          </Popconfirm>
        </Space>
      }
    >
      {/* ── 核心数据行 ── */}
      <Row gutter={[8, 4]} style={{ marginBottom: 6 }}>
        <Col span={6} style={{ textAlign: "center" }}>
          <div style={{ fontSize: 11, color: "#aaa" }}>当前价</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: (changePct ?? 0) >= 0 ? "#cf1322" : "#389e0d", lineHeight: 1.2 }}>
            {item.current_price != null ? item.current_price.toFixed(3) : <Text type="secondary">-</Text>}
          </div>
          {changePct != null && (
            <div style={{ fontSize: 11, color: (changePct) >= 0 ? "#cf1322" : "#389e0d" }}>{fmtPct(changePct)}</div>
          )}
        </Col>
        <Col span={6} style={{ textAlign: "center" }}>
          <div style={{ fontSize: 11, color: "#aaa" }}>均价 / 数量</div>
          <div style={{ fontSize: 13, fontWeight: 600 }}>{item.avg_cost?.toFixed(3)}</div>
          <div style={{ fontSize: 11, color: "#888" }}>{item.quantity}股</div>
        </Col>
        <Col span={6} style={{ textAlign: "center" }}>
          <div style={{ fontSize: 11, color: "#aaa" }}>市值</div>
          <div style={{ fontSize: 13, fontWeight: 600 }}>{fmtMoney(item.market_value)}</div>
          <div style={{ fontSize: 11, color: "#888" }}>成本{fmtMoney(item.cost_amount)}</div>
        </Col>
        <Col span={6} style={{ textAlign: "center" }}>
          <div style={{ fontSize: 11, color: "#aaa" }}>浮盈</div>
          <div style={{ fontSize: 14, fontWeight: 700, color: pnlColor }}>
            {item.unrealized_profit != null ? (pnl >= 0 ? "+" : "") + fmtMoney(pnl) : "-"}
          </div>
          <div style={{ fontSize: 11, color: pnlColor }}>{fmtPct(pnlPct)}</div>
        </Col>
      </Row>

      {/* ── 价格横轴 ── */}
      <PriceBar
        avgCost={item.avg_cost}
        currentPrice={item.current_price}
        targetPrice={item.target_price}
        stopLossPrice={item.stop_loss_price}
      />

      {/* ── 补仓/止损明确标注 ── */}
      <Row gutter={4} style={{ marginBottom: 6, fontSize: 11 }}>
        <Col span={8}>
          <div style={{ background: "#fff1f0", padding: "3px 6px", borderRadius: 4, textAlign: "center" }}>
            <Text style={{ fontSize: 10, color: "#ff4d4f" }}>止损线</Text>
            <div style={{ fontWeight: 700, color: "#ff4d4f" }}>{fmtPrice(item.stop_loss_price)}</div>
            {item.stop_loss_price && item.avg_cost && (
              <div style={{ fontSize: 9, color: "#ff7875" }}>
                -{((item.avg_cost - item.stop_loss_price) / item.avg_cost * 100).toFixed(1)}%
              </div>
            )}
          </div>
        </Col>
        <Col span={8}>
          <div style={{ background: "#fff7e6", padding: "3px 6px", borderRadius: 4, textAlign: "center" }}>
            <Text style={{ fontSize: 10, color: "#fa8c16" }}>补仓线</Text>
            <div style={{ fontWeight: 700, color: "#fa8c16" }}>
              {item.stop_loss_price && item.avg_cost
                ? fmtPrice((item.stop_loss_price + item.avg_cost) / 2)
                : "-"}
            </div>
            {item.stop_loss_price && item.avg_cost && (
              <div style={{ fontSize: 9, color: "#ffa940" }}>
                -{(((item.avg_cost + item.stop_loss_price) / 2 - item.avg_cost) / item.avg_cost * -100).toFixed(1)}%
              </div>
            )}
          </div>
        </Col>
        <Col span={8}>
          <div style={{ background: "#f6ffed", padding: "3px 6px", borderRadius: 4, textAlign: "center" }}>
            <Text style={{ fontSize: 10, color: "#52c41a" }}>目标线</Text>
            <div style={{ fontWeight: 700, color: "#52c41a" }}>{fmtPrice(item.target_price)}</div>
            {item.target_price && item.avg_cost && (
              <div style={{ fontSize: 9, color: "#73d13d" }}>
                +{((item.target_price - item.avg_cost) / item.avg_cost * 100).toFixed(1)}%
              </div>
            )}
          </div>
        </Col>
      </Row>

      {/* ── 操作建议 ── */}
      {item.action_advice && (
        <div style={{
          fontSize: 11, padding: "5px 8px",
          background: st === "stop_loss" ? "#fff1f0" : st === "take_profit" ? "#f6ffed" : "#f5f5f5",
          borderLeft: `3px solid ${borderColor}`,
          borderRadius: 3, lineHeight: 1.6, color: "#444",
        }}>
          {item.action_advice}
        </div>
      )}

      {/* 行情时间戳 */}
      {item.quote_time && (
        <div style={{ textAlign: "right", fontSize: 10, color: "#bbb", marginTop: 4 }}>
          {item.is_realtime ? "实时" : "历史"} · {String(item.quote_time).replace("T", " ").slice(0, 19)}
        </div>
      )}
    </Card>
  );
}

// ─── 关注列表区块 ─────────────────────────────────────────────────────────────
function WatchlistSection({ onAddFromOutside }: { onAddFromOutside?: (fn: (data: any) => void) => void }) {
  const { message } = App.useApp();
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editItem, setEditItem] = useState<any>(null);
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const [quoteLookup, setQuoteLookup] = useState<any>(null);
  const [quoteLooking, setQuoteLooking] = useState(false);
  const [searchOptions, setSearchOptions] = useState<{ value: string; label: React.ReactNode; code: string; name: string; industry: string | null }[]>([]);
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadList = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const res = await getWatchlist();
      setItems(res.items ?? []);
    } catch {
      if (!silent) message.error("加载关注列表失败");
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => {
    loadList();
    // 交易时间内每 30s 刷新一次
    pollRef.current = setInterval(() => loadList(true), 30000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [loadList]);

  const openAdd = useCallback((preset?: { code?: string; name?: string; industry?: string; source?: string }) => {
    setEditItem(null);
    form.resetFields();
    setQuoteLookup(null);
    if (preset) {
      form.setFieldsValue({ ...preset });
      if (preset.code) {
        setQuoteLooking(true);
        getPortfolioQuote(preset.code)
          .then((q) => { setQuoteLookup(q); form.setFieldsValue({ mode2_base_price: q.price }); })
          .catch(() => {})
          .finally(() => setQuoteLooking(false));
      }
    }
    setModalOpen(true);
  }, [form]);

  // 暴露 openAdd 给外部（如盘前选股一键关注）
  useEffect(() => {
    if (onAddFromOutside) onAddFromOutside(openAdd);
  }, [onAddFromOutside, openAdd]);

  const openEdit = useCallback((item: any) => {
    setEditItem(item);
    form.resetFields();
    form.setFieldsValue({
      code: item.code,
      name: item.name,
      industry: item.industry,
      note: item.note,
      mode1_enabled: item.mode1_enabled,
      mode1_target_price: item.mode1_target_price,
      mode1_floor_price: item.mode1_floor_price,
      mode2_enabled: item.mode2_enabled,
      mode2_base_price: item.mode2_base_price,
      mode2_up_pct: item.mode2_up_pct,
      mode2_down_pct: item.mode2_down_pct,
      mode3_enabled: item.mode3_enabled,
    });
    setQuoteLookup(item.current_price ? { price: item.current_price, name: item.name, change_pct: item.change_pct } : null);
    setModalOpen(true);
  }, [form]);

  const handleCodeLookup = async () => {
    const code = form.getFieldValue("code");
    if (!code) return;
    setQuoteLooking(true);
    try {
      const q = await getPortfolioQuote(code);
      setQuoteLookup(q);
      form.setFieldsValue({ name: q.name || form.getFieldValue("name"), mode2_base_price: q.price });
    } catch {
      message.warning("未找到该股票行情");
    } finally {
      setQuoteLooking(false);
    }
  };

  const handleSearchInput = (val: string) => {
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    if (!val || val.length < 1) { setSearchOptions([]); return; }
    searchTimerRef.current = setTimeout(async () => {
      try {
        const results = await searchStocks(val);
        setSearchOptions(results.map((r) => ({
          value: r.code,
          code: r.code,
          name: r.name,
          industry: r.industry,
          label: (
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span><strong>{r.code}</strong> <span style={{ color: "#555" }}>{r.name}</span></span>
              {r.industry && <Tag style={{ fontSize: 10, margin: 0 }}>{r.industry}</Tag>}
            </div>
          ),
        })));
      } catch { /* silent */ }
    }, 280);
  };

  const handleSearchSelect = async (code: string, opt: any) => {
    form.setFieldsValue({ code: opt.code, name: opt.name, industry: opt.industry ?? form.getFieldValue("industry") });
    setQuoteLooking(true);
    try {
      const q = await getPortfolioQuote(opt.code);
      setQuoteLookup(q);
      form.setFieldsValue({ mode2_base_price: q.price });
    } catch {
      setQuoteLookup(null);
    } finally {
      setQuoteLooking(false);
    }
  };

  const handleSubmit = async () => {
    let values: any;
    try { values = await form.validateFields(); } catch { return; }
    setSubmitting(true);
    try {
      if (editItem) {
        await updateWatchItem(editItem.id, values);
        message.success("更新成功");
      } else {
        await addWatchItem({ ...values, source: values.source || "manual" });
        message.success("已加入关注列表");
      }
      setModalOpen(false);
      await loadList();
    } catch (e: any) {
      message.error(e.message || "操作失败");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: number, name: string) => {
    try {
      await removeWatchItem(id);
      message.success(`已移除 ${name}`);
      await loadList(true);
    } catch (e: any) {
      message.error(e.message || "删除失败");
    }
  };

  const handleToggleStatus = async (item: any) => {
    const newStatus = item.status === "active" ? "paused" : "active";
    try {
      await updateWatchItem(item.id, { status: newStatus });
      await loadList(true);
    } catch (e: any) {
      message.error(e.message || "操作失败");
    }
  };

  const handleQuickMonitor = async (item: any) => {
    const price = item.current_price;
    if (!price) {
      message.warning("暂无实时价格，无法一键设置，请手动编辑");
      return;
    }
    const target = Math.round(price * 1.10 * 1000) / 1000;
    const floor  = Math.round(price * 0.90 * 1000) / 1000;
    try {
      await updateWatchItem(item.id, {
        mode1_enabled: true,
        mode1_target_price: target,
        mode1_floor_price:  floor,
        mode2_enabled: true,
        mode2_base_price: price,
        mode2_up_pct:   5,
        mode2_down_pct: 5,
        mode3_enabled: true,
      });
      message.success(`已开启全部盯盘模式：目标价 ${target} / 下限 ${floor}，涨跌幅 ±5%`);
      await loadList(true);
    } catch (e: any) {
      message.error(e.message || "操作失败");
    }
  };

  const [filterKw, setFilterKw] = useState("");

  const columns = [
    {
      title: "名称 / 代码",
      key: "stock",
      render: (_: any, r: any) => (
        <Space direction="vertical" size={0}>
          <Space size={4}>
            <Text strong style={{ fontSize: 14 }}>{r.name}</Text>
            {r.status === "paused" && <Tag color="default" style={{ fontSize: 10 }}>已暂停</Tag>}
          </Space>
          <Space size={4}>
            <Text type="secondary" style={{ fontSize: 11 }}>{r.code}</Text>
            {r.industry && <Tag style={{ fontSize: 10 }}>{r.industry}</Tag>}
          </Space>
        </Space>
      ),
    },
    {
      title: "当前价",
      key: "price",
      sorter: (a: any, b: any) => (a.change_pct ?? -999) - (b.change_pct ?? -999),
      render: (_: any, r: any) => {
        if (r.current_price == null) return <Text type="secondary">-</Text>;
        const up = (r.change_pct ?? 0) >= 0;
        return (
          <Space direction="vertical" size={0}>
            <Space size={4}>
              {r.is_realtime && <Badge status="processing" />}
              <Text strong style={{ color: up ? "#cf1322" : "#389e0d" }}>{r.current_price.toFixed(3)}</Text>
            </Space>
            {r.change_pct != null && (
              <Text style={{ fontSize: 11, color: up ? "#cf1322" : "#389e0d" }}>
                {r.change_pct >= 0 ? "+" : ""}{r.change_pct.toFixed(2)}%
              </Text>
            )}
          </Space>
        );
      },
    },
    {
      title: "盯盘模式",
      key: "modes",
      render: (_: any, r: any) => (
        <Space wrap size={4}>
          <Tag color={r.mode1_enabled ? "blue" : "default"} style={{ fontSize: 10 }}>
            目标价{r.mode1_enabled ? "✓" : ""}
          </Tag>
          <Tag color={r.mode2_enabled ? "orange" : "default"} style={{ fontSize: 10 }}>
            涨跌幅{r.mode2_enabled ? "✓" : ""}
          </Tag>
          <Tag color={r.mode3_enabled ? "green" : "default"} style={{ fontSize: 10 }}>
            RSI{r.mode3_enabled ? "✓" : ""}
          </Tag>
        </Space>
      ),
    },
    {
      title: "推送状态",
      key: "notify",
      render: (_: any, r: any) => (
        <Space direction="vertical" size={0}>
          {r.last_notified_mode1 && <Text style={{ fontSize: 10, color: "#1677ff" }}>Mode1: {r.last_notified_mode1 === "target" ? "已推目标价" : "已推下限价"}</Text>}
          {r.last_notified_mode2 && <Text style={{ fontSize: 10, color: "#fa8c16" }}>Mode2: {r.last_notified_mode2 === "up" ? "已推上涨" : "已推下跌"}</Text>}
          {r.last_notified_mode3_date && <Text style={{ fontSize: 10, color: "#52c41a" }}>Mode3: {r.last_notified_mode3_date}</Text>}
          {!r.last_notified_mode1 && !r.last_notified_mode2 && !r.last_notified_mode3_date && (
            <Text type="secondary" style={{ fontSize: 10 }}>待触发</Text>
          )}
        </Space>
      ),
    },
    {
      title: "操作",
      key: "action",
      render: (_: any, r: any) => (
        <Space size={4} wrap>
          <Tooltip title={r.current_price ? `目标价 ±10%（${Math.round(r.current_price*1.1*1000)/1000} / ${Math.round(r.current_price*0.9*1000)/1000}），涨跌幅 ±5%，RSI 全开` : "需要实时价格"}>
            <Button
              size="small"
              type="primary"
              ghost
              onClick={() => handleQuickMonitor(r)}
              disabled={!r.current_price}
            >
              一键盯盘
            </Button>
          </Tooltip>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)}>编辑</Button>
          <Button size="small" onClick={() => handleToggleStatus(r)}>
            {r.status === "active" ? "暂停" : "恢复"}
          </Button>
          <Popconfirm
            title={`移除 ${r.name}`}
            onConfirm={() => handleDelete(r.id, r.name)}
            okText="确认" cancelText="取消" okButtonProps={{ danger: true }}
          >
            <Button size="small" danger>移除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const collapseItems = [
    {
      key: "mode1",
      label: (
        <Space>
          <Form.Item name="mode1_enabled" valuePropName="checked" noStyle>
            <Switch size="small" />
          </Form.Item>
          <Text style={{ fontSize: 13 }}>模式一：目标价触发</Text>
          <Text type="secondary" style={{ fontSize: 11 }}>（达到目标价或触及下限价时推送）</Text>
        </Space>
      ),
      children: (
        <Row gutter={8}>
          <Col span={12}>
            <Form.Item label="目标价（上涨触发）" name="mode1_target_price">
              <InputNumber style={{ width: "100%" }} precision={3} min={0.001} placeholder="留空则不触发" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item label="下限价（下跌触发）" name="mode1_floor_price">
              <InputNumber style={{ width: "100%" }} precision={3} min={0.001} placeholder="留空则不触发" />
            </Form.Item>
          </Col>
        </Row>
      ),
    },
    {
      key: "mode2",
      label: (
        <Space>
          <Form.Item name="mode2_enabled" valuePropName="checked" noStyle>
            <Switch size="small" />
          </Form.Item>
          <Text style={{ fontSize: 13 }}>模式二：涨跌幅触发</Text>
          <Text type="secondary" style={{ fontSize: 11 }}>（以基准价为基础，涨/跌 X% 时推送）</Text>
        </Space>
      ),
      children: (
        <Row gutter={8}>
          <Col span={8}>
            <Form.Item label="基准价" name="mode2_base_price" tooltip="添加时自动取当前实时价">
              <InputNumber style={{ width: "100%" }} precision={3} min={0.001} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item label="上涨触发（%）" name="mode2_up_pct">
              <InputNumber style={{ width: "100%" }} precision={1} min={0.1} step={0.5} placeholder="如 3" />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item label="下跌触发（%）" name="mode2_down_pct">
              <InputNumber style={{ width: "100%" }} precision={1} min={0.1} step={0.5} placeholder="如 2" />
            </Form.Item>
          </Col>
        </Row>
      ),
    },
    {
      key: "mode3",
      label: (
        <Space>
          <Form.Item name="mode3_enabled" valuePropName="checked" noStyle>
            <Switch size="small" />
          </Form.Item>
          <Text style={{ fontSize: 13 }}>模式三：RSI14 超卖回升</Text>
          <Text type="secondary" style={{ fontSize: 11 }}>（RSI14 从 &lt;30 回升至 ≥30 时推送，每日一次）</Text>
        </Space>
      ),
      children: (
        <Text type="secondary" style={{ fontSize: 12 }}>
          无需额外配置。系统自动计算最近14日 RSI，当 RSI 从超卖区（&lt;30）回升至 ≥30 时推送一次飞书通知。
        </Text>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12, gap: 8, flexWrap: "wrap" }}>
        <Input
          placeholder="搜索名称 / 代码 / 行业"
          prefix={<SearchOutlined style={{ color: "#bbb" }} />}
          allowClear
          value={filterKw}
          onChange={(e) => setFilterKw(e.target.value)}
          style={{ width: 220 }}
          size="small"
        />
        <Space>
          <Button icon={<SyncOutlined />} size="small" onClick={() => loadList(true)}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openAdd()}>添加关注</Button>
        </Space>
      </div>

      {loading ? (
        <Spin style={{ display: "block", margin: "60px auto" }} />
      ) : items.length === 0 ? (
        <Empty description="暂无关注股票，点击「添加关注」或从盘前选股/ETF分析/持续上涨页一键添加">
          <Button type="primary" icon={<PlusOutlined />} onClick={() => openAdd()}>添加关注</Button>
        </Empty>
      ) : (
        <Table
          dataSource={items.filter((r) => {
            if (!filterKw) return true;
            const kw = filterKw.toLowerCase();
            return (
              r.code?.toLowerCase().includes(kw) ||
              r.name?.toLowerCase().includes(kw) ||
              r.industry?.toLowerCase().includes(kw)
            );
          })}
          columns={columns}
          rowKey="id"
          size="small"
          pagination={false}
          rowClassName={(r) => r.status === "paused" ? "opacity-50" : ""}
        />
      )}

      <Modal
        title={editItem ? `编辑关注 · ${editItem.name}` : "添加关注"}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        okText={editItem ? "保存" : "确认添加"}
        confirmLoading={submitting}
        width={520}
        destroyOnClose
      >
        <Form form={form} layout="vertical" size="small">
          <Row gutter={8}>
            <Col span={12}>
              <Form.Item label="股票代码 / 名称搜索" name="code" rules={[{ required: true, message: "请输入股票代码" }]}>
                <AutoComplete
                  options={searchOptions}
                  onSearch={handleSearchInput}
                  onSelect={handleSearchSelect}
                  disabled={!!editItem}
                  placeholder="输入代码或中文名称搜索"
                  allowClear
                  onClear={() => { setSearchOptions([]); setQuoteLookup(null); }}
                  style={{ width: "100%" }}
                  notFoundContent={null}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="股票名称" name="name" rules={[{ required: true, message: "请输入股票名称" }]}>
                <Input placeholder="可自动获取或手填" />
              </Form.Item>
            </Col>
          </Row>
          {quoteLookup && (
            <div style={{ marginBottom: 8, padding: "4px 8px", background: "#f0f9ff", borderRadius: 4, fontSize: 12 }}>
              <Text strong>{quoteLookup.name}</Text>
              <Text type="secondary" style={{ marginLeft: 8 }}>当前价: </Text>
              <Text strong style={{ color: "#cf1322" }}>{quoteLookup.price?.toFixed(3)}</Text>
              {quoteLookup.change_pct != null && (
                <Text style={{ marginLeft: 6, color: quoteLookup.change_pct >= 0 ? "#cf1322" : "#389e0d" }}>
                  {quoteLookup.change_pct >= 0 ? "+" : ""}{quoteLookup.change_pct.toFixed(2)}%
                </Text>
              )}
            </div>
          )}
          <Form.Item label="行业" name="industry">
            <Input placeholder="可选" />
          </Form.Item>

          <Collapse items={collapseItems} ghost style={{ marginBottom: 8 }} />

          <Form.Item label="备注" name="note">
            <Input.TextArea rows={2} placeholder="可选" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────
export default function HomePage() {
  const router = useRouter();
  const { message } = App.useApp();
  const [positions, setPositions] = useState<any[]>([]);
  const [summary, setSummary] = useState<any>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [preMarket, setPreMarket] = useState<any>(null);

  // 新建/加仓 Modal
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [addForm] = Form.useForm();
  const [addSubmitting, setAddSubmitting] = useState(false);
  const [quoteLookup, setQuoteLookup] = useState<any>(null);
  const [quoteLooking, setQuoteLooking] = useState(false);

  // 编辑 Modal
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editItem, setEditItem] = useState<any>(null);
  const [editForm] = Form.useForm();
  const [editSubmitting, setEditSubmitting] = useState(false);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadPositions = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    else setRefreshing(true);
    try {
      const res = await getPositions();
      setPositions(res.items ?? []);
      setSummary(res.summary ?? {});
      setLastRefresh(new Date());
    } catch {
      if (!silent) message.error("加载持仓失败");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [message]);

  useEffect(() => {
    loadPositions();
    getPreMarketLatest().catch(() => null).then(setPreMarket);
  }, [loadPositions]);

  // 自动轮询：交易时间 8s，非交易时间 60s
  useEffect(() => {
    const schedule = () => {
      const interval = isMarketOpen() ? 8000 : 60000;
      pollRef.current = setInterval(() => loadPositions(true), interval);
    };
    schedule();
    // 每分钟重新判断是否处于交易时间，调整轮询间隔
    const resetRef = setInterval(() => {
      if (pollRef.current) clearInterval(pollRef.current);
      schedule();
    }, 60000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      clearInterval(resetRef);
    };
  }, [loadPositions]);

  // ── 加仓/建仓 ──────────────────────────────────────────────────────────────
  const handleOpenAdd = useCallback((code = "", name = "", presets?: { target_price?: number; stop_loss_price?: number }) => {
    addForm.resetFields();
    setQuoteLookup(null);
    if (code) {
      addForm.setFieldsValue({
        code, name, quantity: 100,
        ...(presets?.target_price ? { target_price: presets.target_price } : {}),
        ...(presets?.stop_loss_price ? { stop_loss_price: presets.stop_loss_price } : {}),
      });
      // 查询实时价
      setQuoteLooking(true);
      getPortfolioQuote(code).then((q) => {
        setQuoteLookup(q);
        addForm.setFieldsValue({ buy_price: q.price });
      }).catch(() => {}).finally(() => setQuoteLooking(false));
    }
    setAddModalOpen(true);
  }, [addForm]);

  const handleCodeLookup = async () => {
    const code = addForm.getFieldValue("code");
    if (!code) return;
    setQuoteLooking(true);
    try {
      const q = await getPortfolioQuote(code);
      setQuoteLookup(q);
      addForm.setFieldsValue({
        buy_price: q.price,
        name: q.name || addForm.getFieldValue("name"),
      });
    } catch {
      message.warning("未找到该股票行情，请手动填写价格");
    } finally {
      setQuoteLooking(false);
    }
  };

  const handleAddSubmit = async () => {
    let values: any;
    try {
      values = await addForm.validateFields();
    } catch {
      return; // 表单校验失败，错误已内联展示
    }
    setAddSubmitting(true);
    try {
      await createPosition({ ...values, source: "manual" });
      message.success("建仓/加仓成功");
      setAddModalOpen(false);
      await loadPositions();
    } catch (e: any) {
      message.error(e.message || "操作失败");
    } finally {
      setAddSubmitting(false);
    }
  };

  // ── 编辑止盈止损 ───────────────────────────────────────────────────────────
  const handleOpenEdit = useCallback((item: any) => {
    setEditItem(item);
    // resetFields 确保 v6 中 form store 干净，再设值
    editForm.resetFields();
    editForm.setFieldsValue({
      quantity: item.quantity,
      avg_cost: item.avg_cost,
      target_price: item.target_price,
      stop_loss_price: item.stop_loss_price,
      note: item.note,
    });
    setEditModalOpen(true);
  }, [editForm]);

  const handleEditSubmit = async () => {
    let values: any;
    try {
      values = await editForm.validateFields();
    } catch {
      return; // 表单校验失败，错误已内联展示
    }
    if (!editItem) {
      message.error("持仓数据丢失，请关闭弹窗重试");
      return;
    }
    setEditSubmitting(true);
    try {
      await updatePosition(editItem.id, values);
      message.success("修改成功");
      setEditModalOpen(false);
      await loadPositions(true);
    } catch (e: any) {
      message.error(e.message || "修改失败");
    } finally {
      setEditSubmitting(false);
    }
  };

  // ── 平仓 ───────────────────────────────────────────────────────────────────
  const handleClose = async (id: number, name: string) => {
    try {
      await closePosition(id);
      message.success(`${name} 平仓成功`);
      await loadPositions();
    } catch (e: any) {
      message.error(e.message || "平仓失败");
    }
  };

  // ── 渲染 ───────────────────────────────────────────────────────────────────
  const activePositions = positions.filter((p) => p.status === "active");
  const alertPositions = activePositions.filter((p) =>
    p.threshold_status === "take_profit" || p.threshold_status === "stop_loss"
  );

  const portfolioTab = (
    <div>
      {/* ── 操作栏 ── */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16, gap: 12, flexWrap: "wrap" }}>
        <Text type="secondary">
          {isMarketOpen() ? (
            <><Badge status="processing" /> 交易中 · 每8秒刷新</>
          ) : (
            "非交易时段 · 每60秒刷新"
          )}
          {lastRefresh && <Text type="secondary" style={{ marginLeft: 8, fontSize: 11 }}>
            最后更新 {lastRefresh.toLocaleTimeString("zh-CN")}
          </Text>}
        </Text>
        <Space wrap>
          <Button
            icon={<SyncOutlined spin={refreshing} />}
            onClick={() => loadPositions(true)}
            loading={refreshing}
          >刷新</Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => handleOpenAdd()}
          >新建持仓</Button>
        </Space>
      </div>

      {/* ── 持仓汇总 ── */}
      {!loading && (summary.active_count > 0 || activePositions.length > 0) && (
        <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
          <Col xs={12} md={5}>
            <Card size="small">
              <Statistic title="持仓市值" value={summary.market_value ?? 0} precision={2} suffix="元"
                valueStyle={{ fontSize: 16, color: "#1677ff" }} />
            </Card>
          </Col>
          <Col xs={12} md={5}>
            <Card size="small">
              <Statistic title="持仓成本" value={summary.total_cost ?? 0} precision={2} suffix="元"
                valueStyle={{ fontSize: 16 }} />
            </Card>
          </Col>
          <Col xs={12} md={5}>
            <Card size="small">
              <Statistic
                title="浮动盈亏"
                value={summary.unrealized_profit ?? 0}
                precision={2} suffix="元"
                valueStyle={{ fontSize: 16, color: (summary.unrealized_profit ?? 0) >= 0 ? "#cf1322" : "#389e0d" }}
              />
              {summary.unrealized_return_pct != null && (
                <Text style={{ fontSize: 11, color: (summary.unrealized_return_pct ?? 0) >= 0 ? "#cf1322" : "#389e0d" }}>
                  {fmtPct(summary.unrealized_return_pct)}
                </Text>
              )}
            </Card>
          </Col>
          <Col xs={12} md={4}>
            <Card size="small">
              <Statistic title="已实现盈亏" value={summary.realized_profit ?? 0} precision={2} suffix="元"
                valueStyle={{ fontSize: 16, color: (summary.realized_profit ?? 0) >= 0 ? "#cf1322" : "#389e0d" }} />
            </Card>
          </Col>
          <Col xs={12} md={5}>
            <Card size="small">
              <Statistic
                title="预警持仓"
                value={summary.threshold_hit_count ?? 0}
                suffix={`/ ${summary.active_count ?? 0} 只`}
                valueStyle={{ fontSize: 16, color: (summary.threshold_hit_count ?? 0) > 0 ? "#ff4d4f" : "#52c41a" }}
              />
              {(summary.threshold_hit_count ?? 0) > 0 && (
                <Text style={{ fontSize: 11, color: "#ff4d4f" }}>止盈/止损触发，需操作！</Text>
              )}
            </Card>
          </Col>
        </Row>
      )}

      {/* ── 预警提示 ── */}
      {alertPositions.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          {alertPositions.map((p) => (
            <div key={p.id} style={{
              padding: "6px 12px", marginBottom: 6, borderRadius: 6,
              background: p.threshold_status === "stop_loss" ? "#fff1f0" : "#f6ffed",
              border: `1px solid ${p.threshold_status === "stop_loss" ? "#ffccc7" : "#b7eb8f"}`,
              display: "flex", alignItems: "center", gap: 12,
            }}>
              <Text strong style={{ color: p.threshold_status === "stop_loss" ? "#ff4d4f" : "#52c41a" }}>
                {p.threshold_status === "stop_loss" ? "⚠️ 止损触发" : "✅ 止盈触发"}
              </Text>
              <Text>{p.code} {p.name}</Text>
              <Text type="secondary">当前 {p.current_price?.toFixed(3)} | {p.threshold_status === "stop_loss" ? `止损 ${p.stop_loss_price?.toFixed(3)}` : `目标 ${p.target_price?.toFixed(3)}`}</Text>
              <Text style={{ fontSize: 11, color: "#888" }}>{p.action_advice}</Text>
            </div>
          ))}
        </div>
      )}

      {/* ── 持仓列表 ── */}
      {loading ? (
        <Spin size="large" style={{ display: "block", margin: "80px auto" }} />
      ) : activePositions.length === 0 ? (
        <Card style={{ marginBottom: 16 }}>
          <Empty
            description={
              <Space direction="vertical" size={8} align="center">
                <Text>暂无持仓，点击「新建持仓」开始监控</Text>
                {preMarket?.trade_date && (
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    今日盘前推荐：激进{preMarket.aggressive?.length ?? 0}只 稳健{preMarket.stable?.length ?? 0}只
                    <Button size="small" type="link" onClick={() => router.push("/pre-market")}>查看 →</Button>
                  </Text>
                )}
              </Space>
            }
          >
            <Button type="primary" icon={<PlusOutlined />} onClick={() => handleOpenAdd()}>新建持仓</Button>
          </Empty>
        </Card>
      ) : (
        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
          {activePositions.map((item) => (
            <Col key={item.id} xs={24} md={12} xl={8}>
              <PositionCard
                item={item}
                onEdit={handleOpenEdit}
                onClose={handleClose}
                onAddBuy={(code, name) => handleOpenAdd(code, name)}
              />
            </Col>
          ))}
        </Row>
      )}

      {/* ── 今日推荐 · 待建仓 ── */}
      {preMarket?.trade_date && (() => {
        const heldCodes = new Set(activePositions.map((p: any) => p.code));
        const recs: any[] = [
          ...(preMarket.aggressive ?? []).map((r: any) => ({ ...r, _type: "aggressive" })),
          ...(preMarket.fallback_main ?? []).map((r: any) => ({ ...r, _type: "aggressive_main" })),
          ...(preMarket.fallback_backup ?? []).map((r: any) => ({ ...r, _type: "aggressive_backup" })),
          ...(preMarket.stable ?? []).map((r: any) => ({ ...r, _type: r.result_type ?? "stable" })),
        ].filter((r) => r.code && !heldCodes.has(r.code));

        if (recs.length === 0) return null;
        return (
          <div style={{ marginBottom: 16 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
              <Text strong style={{ fontSize: 14 }}>
                今日推荐 · 待建仓
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>{preMarket.trade_date}</Text>
              </Text>
              <Button size="small" type="link" onClick={() => router.push("/pre-market")}>查看完整分析 →</Button>
            </div>
            <Row gutter={[12, 12]}>
              {recs.map((rec, idx) => {
                const typeColor = REC_TYPE_COLOR[rec._type] ?? "#888";
                const typeLabel = REC_TYPE_LABEL[rec._type] ?? rec._type;
                const isFallback = rec._type === "aggressive_main" || rec._type === "aggressive_backup";
                return (
                  <Col key={`${rec.code}-${idx}`} xs={24} sm={12} md={8} xl={6}>
                    <Card
                      size="small"
                      style={{ borderTop: `3px solid ${typeColor}`, background: "#fafafa" }}
                      bodyStyle={{ padding: "8px 10px" }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 6 }}>
                        <div>
                          <Text strong style={{ fontSize: 14 }}>{rec.code}</Text>
                          <Text type="secondary" style={{ fontSize: 11, marginLeft: 6 }}>{rec.name}</Text>
                        </div>
                        <Tag color={typeColor} style={{ fontSize: 10, margin: 0 }}>{typeLabel}</Tag>
                      </div>
                      <Row gutter={4} style={{ marginBottom: 6 }}>
                        <Col span={8} style={{ textAlign: "center" }}>
                          <div style={{ fontSize: 10, color: "#aaa" }}>收盘价</div>
                          <div style={{ fontSize: 13, fontWeight: 600 }}>{rec.close_price?.toFixed(3) ?? "-"}</div>
                        </Col>
                        <Col span={8} style={{ textAlign: "center" }}>
                          <div style={{ fontSize: 10, color: "#52c41a" }}>目标价</div>
                          <div style={{ fontSize: 13, fontWeight: 600, color: "#52c41a" }}>{rec.target_price?.toFixed(3) ?? "-"}</div>
                        </Col>
                        <Col span={8} style={{ textAlign: "center" }}>
                          <div style={{ fontSize: 10, color: "#ff4d4f" }}>止损价</div>
                          <div style={{ fontSize: 13, fontWeight: 600, color: "#ff4d4f" }}>{rec.stop_loss_price?.toFixed(3) ?? "-"}</div>
                        </Col>
                      </Row>
                      {isFallback && (
                        <div style={{ fontSize: 10, color: "#fa8c16", marginBottom: 4, background: "#fffbe6", padding: "2px 4px", borderRadius: 3 }}>
                          纯技术面筛选（催化不足降级）
                        </div>
                      )}
                      {rec.suggestion && (
                        <div style={{ fontSize: 10, color: "#666", lineHeight: 1.5, marginBottom: 6, maxHeight: 40, overflow: "hidden" }}>
                          {rec.suggestion.slice(0, 80)}{rec.suggestion.length > 80 ? "…" : ""}
                        </div>
                      )}
                      <Button
                        block size="small" type="primary" ghost
                        icon={<PlusOutlined />}
                        style={{ borderColor: typeColor, color: typeColor }}
                        onClick={() => handleOpenAdd(rec.code, rec.name ?? "", {
                          target_price: rec.target_price,
                          stop_loss_price: rec.stop_loss_price,
                        })}
                      >
                        一键建仓
                      </Button>
                    </Card>
                  </Col>
                );
              })}
            </Row>
          </div>
        );
      })()}

      {/* ── 快捷导航 ── */}
      <Divider style={{ margin: "16px 0 12px" }}>
        <Text type="secondary" style={{ fontSize: 12 }}>其他功能</Text>
      </Divider>
      <Row gutter={[12, 12]}>
        {[
          { icon: <RadarChartOutlined />, title: "盘前选股", desc: preMarket?.trade_date ? `${preMarket.trade_date} | 激进${preMarket.aggressive?.length ?? 0}+稳健${preMarket.stable?.length ?? 0}只` : "每日7AM自动选股", path: "/pre-market", color: "#cf1322" },
          { icon: <FundOutlined />, title: "ETF分析", desc: "ETF轮动与盘后分析", path: "/etf-analysis", color: "#1677ff" },
          { icon: <RiseOutlined />, title: "持续上涨", desc: "日K趋势筛选", path: "/ten-bagger", color: "#52c41a" },
          { icon: <ReadOutlined />, title: "资讯中心", desc: "每小时财经资讯汇总", path: "/news-center", color: "#722ed1" },
          { icon: <SettingOutlined />, title: "配置中心", desc: "LLM与数据源设置", path: "/settings", color: "#888" },
        ].map(({ icon, title, desc, path, color }) => (
          <Col key={path} xs={12} md={8} lg={5}>
            <Card hoverable size="small" onClick={() => router.push(path)} style={{ cursor: "pointer" }}>
              <Space>
                <div style={{ fontSize: 20, color }}>{icon}</div>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 13 }}>{title}</div>
                  <div style={{ fontSize: 11, color: "#888" }}>{desc}</div>
                </div>
              </Space>
            </Card>
          </Col>
        ))}
      </Row>

      {/* ── 新建/加仓 Modal ── */}
      <Modal
        title="新建 / 加仓"
        open={addModalOpen}
        onOk={handleAddSubmit}
        onCancel={() => setAddModalOpen(false)}
        okText="确认建仓"
        confirmLoading={addSubmitting}
        width={420}
        destroyOnClose
      >
        <Form form={addForm} layout="vertical" size="small">
          <Form.Item label="股票代码" name="code" rules={[{ required: true, message: "请输入股票代码" }]}>
            <Input
              placeholder="如 600519、000001"
              suffix={
                <Button type="link" size="small" icon={<SearchOutlined />} loading={quoteLooking} onClick={handleCodeLookup}>
                  查询
                </Button>
              }
              onPressEnter={handleCodeLookup}
              style={{ textTransform: "uppercase" }}
            />
          </Form.Item>
          {quoteLookup && (
            <div style={{ marginBottom: 8, padding: "4px 8px", background: "#f0f9ff", borderRadius: 4, fontSize: 12 }}>
              <Text strong>{quoteLookup.name}</Text>
              <Text type="secondary" style={{ marginLeft: 8 }}>当前价: </Text>
              <Text strong style={{ color: "#cf1322" }}>{quoteLookup.price?.toFixed(3)}</Text>
              {quoteLookup.change_pct != null && (
                <Text style={{ marginLeft: 6, color: quoteLookup.change_pct >= 0 ? "#cf1322" : "#389e0d" }}>
                  {fmtPct(quoteLookup.change_pct)}
                </Text>
              )}
            </div>
          )}
          <Form.Item label="股票名称" name="name">
            <Input placeholder="可自动获取或手填" />
          </Form.Item>
          <Row gutter={8}>
            <Col span={12}>
              <Form.Item label="买入价格" name="buy_price" rules={[{ required: true, message: "请输入买入价" }]}>
                <InputNumber style={{ width: "100%" }} placeholder="元" precision={3} min={0.001} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="买入数量" name="quantity" initialValue={100} rules={[{ required: true }]}>
                <InputNumber style={{ width: "100%" }} placeholder="股" min={1} step={100} />
              </Form.Item>
            </Col>
          </Row>
          <div style={{ marginBottom: 8 }}>
            <Tooltip title="止损价 = 买入价 × 97%（−3%）；目标价 = 买入价 × 105%（+5%）；补仓线 = (止损价 + 成本价) ÷ 2，仅用于图表展示，不参与存储">
              <Button
                size="small" block type="dashed"
                onClick={() => {
                  const price = addForm.getFieldValue("buy_price");
                  if (!price) { return; }
                  addForm.setFieldsValue({
                    stop_loss_price: Math.round(price * 0.97 * 1000) / 1000,
                    target_price: Math.round(price * 1.05 * 1000) / 1000,
                  });
                }}
              >
                一键生成止盈/止损（+5% / −3%）
              </Button>
            </Tooltip>
          </div>
          <Row gutter={8}>
            <Col span={12}>
              <Form.Item label="目标价（止盈）" name="target_price" tooltip="不填则按配置自动计算">
                <InputNumber style={{ width: "100%" }} placeholder="留空自动计算" precision={3} min={0.001} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="止损价" name="stop_loss_price" tooltip="不填则按配置自动计算">
                <InputNumber style={{ width: "100%" }} placeholder="留空自动计算" precision={3} min={0.001} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item label="备注" name="note">
            <Input.TextArea rows={2} placeholder="可选" />
          </Form.Item>
        </Form>
      </Modal>

      {/* ── 编辑止盈止损 Modal ── */}
      <Modal
        title={`修改 ${editItem?.name ?? ""} 参数`}
        open={editModalOpen}
        onOk={handleEditSubmit}
        onCancel={() => setEditModalOpen(false)}
        okText="保存"
        confirmLoading={editSubmitting}
        width={420}
      >
        <Form form={editForm} layout="vertical" size="small">
          <Row gutter={8}>
            <Col span={12}>
              <Form.Item label="持仓数量（股）" name="quantity" rules={[{ type: "number", min: 1, message: "至少 1 股" }]}>
                <InputNumber style={{ width: "100%" }} min={1} step={100} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="持仓均价" name="avg_cost" rules={[{ type: "number", min: 0.001, message: "均价须大于 0" }]}>
                <InputNumber style={{ width: "100%" }} precision={3} min={0.001} />
              </Form.Item>
            </Col>
          </Row>
          <div style={{ marginBottom: 8 }}>
            <Tooltip title="止损价 = 均价 × 97%（−3%）；目标价 = 均价 × 105%（+5%）；补仓线 = (止损价 + 均价) ÷ 2，仅用于图表展示，不参与存储">
              <Button
                size="small" block type="dashed"
                onClick={() => {
                  const cost = editForm.getFieldValue("avg_cost");
                  if (!cost) { return; }
                  editForm.setFieldsValue({
                    stop_loss_price: Math.round(cost * 0.97 * 1000) / 1000,
                    target_price: Math.round(cost * 1.05 * 1000) / 1000,
                  });
                }}
              >
                一键生成止盈/止损（+5% / −3%）
              </Button>
            </Tooltip>
          </div>
          <Row gutter={8}>
            <Col span={12}>
              <Form.Item label="目标价（止盈）" name="target_price">
                <InputNumber style={{ width: "100%" }} precision={3} min={0.001} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="止损价" name="stop_loss_price">
                <InputNumber style={{ width: "100%" }} precision={3} min={0.001} />
              </Form.Item>
            </Col>
          </Row>
          {editItem && (
            <div style={{ marginBottom: 8, fontSize: 11, color: "#888" }}>
              当前价 {editItem.current_price?.toFixed(3) ?? "-"} | 修改均价后止盈/止损线会按新均价重新计算（若留空则保持原值）
            </div>
          )}
          <Form.Item label="备注" name="note">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );

  return (
    <div>
      <div style={{ marginBottom: 8 }}>
        <Title level={3} style={{ marginBottom: 0 }}>
          <DashboardOutlined style={{ marginRight: 8 }} />实时盯盘工作台
        </Title>
      </div>
      <Tabs
        defaultActiveKey="portfolio"
        items={[
          {
            key: "portfolio",
            label: <><DashboardOutlined /> 持仓 &amp; 盘前</>,
            children: portfolioTab,
          },
          {
            key: "watchlist",
            label: <><EyeOutlined /> 关注列表</>,
            children: <WatchlistSection />,
          },
        ]}
      />
    </div>
  );
}
