"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Progress,
  Row,
  Space,
  Spin,
  Statistic,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import {
  DeleteOutlined,
  EditOutlined,
  EyeOutlined,
  HistoryOutlined,
  PlusOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  addManualEtfNews,
  addEtfWatch,
  addWatchItem,
  backfillEtfKline,
  backfillMissingEtfKlines,
  getEtfDetail,
  getEtfAnalysisHistory,
  getEtfAnalysisLatest,
  getEtfAnalysisRecord,
  getEtfAnalysisTask,
  getEtfWatchlist,
  importEtfRotationPool,
  refreshEtfQuotes,
  removeEtfWatch,
  runEtfAnalysis,
  updateEtfWatch,
} from "@/lib/api";

const { Title, Text, Paragraph } = Typography;

function money(value?: number | null, signed = false) {
  if (value == null) return "-";
  const num = Number(value);
  const sign = num < 0 ? "-" : signed && num > 0 ? "+" : "";
  const abs = Math.abs(num);
  if (abs >= 100000000) return `${sign}${(abs / 100000000).toFixed(2)}亿`;
  if (abs >= 10000) return `${sign}${(abs / 10000).toFixed(2)}万`;
  return `${sign}${abs.toFixed(2)}`;
}

function price(value?: number | null) {
  return value == null ? "-" : Number(value).toFixed(3);
}

function pct(value?: number | null) {
  return value == null ? "-" : `${value > 0 ? "+" : ""}${Number(value).toFixed(2)}%`;
}

function boardActivityText(board: any) {
  if (board?.volume_ratio == null) return null;
  const label = board?.volume_ratio_source === "turnover_rate_ratio" ? "换手" : "量比";
  return `${label} ${Number(board.volume_ratio).toFixed(2)}`;
}

function shortTime(value?: string | null) {
  if (!value) return "-";
  return value.length > 10 ? value.slice(5, 16).replace("T", " ") : value;
}

function thresholdTag(status?: string) {
  if (status === "take_profit") return <Tag color="red">止盈</Tag>;
  if (status === "stop_loss") return <Tag color="green">止损</Tag>;
  if (status === "data_missing") return <Tag color="orange">缺行情</Tag>;
  if (status === "watch") return <Tag>观察</Tag>;
  return <Tag color="blue">持有</Tag>;
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

function trendTag(trend?: string) {
  const map: Record<string, { color: string; label: string }> = {
    up: { color: "red", label: "上行" },
    down: { color: "green", label: "下行" },
    consolidation: { color: "blue", label: "震荡" },
  };
  const c = map[trend || ""] || { color: "default", label: trend || "-" };
  return <Tag color={c.color}>{c.label}</Tag>;
}

function hotSectorBasis(sector: any) {
  if (sector?.reason) return sector.reason;
  const basis = sector?.basis;
  if (Array.isArray(basis) && basis.length) return basis.join("；");
  return [
    sector?.etf_count != null ? `覆盖 ETF ${sector.etf_count} 只` : "",
    sector?.avg_return_5d != null ? `5日平均涨幅 ${pct(sector.avg_return_5d)}` : "",
    sector?.avg_return_20d != null ? `20日平均涨幅 ${pct(sector.avg_return_20d)}` : "",
    sector?.avg_volume_ratio != null ? `平均量比 ${sector.avg_volume_ratio}` : "",
    sector?.news_sentiment_score != null ? `新闻情绪分 ${sector.news_sentiment_score}` : "",
  ].filter(Boolean).join("；") || "暂无可展示依据";
}

function compactReason(value?: string | null, max = 72) {
  if (!value) return "";
  return value.length > max ? `${value.slice(0, max)}...` : value;
}

function parseTagInput(value?: string | null) {
  return String(value || "")
    .split(/[,，、\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function mergeAllocationPlans(recommendations: any[], llmRecommendations: any[]) {
  const seen = new Set<string>();
  return [...recommendations, ...llmRecommendations].filter((item) => {
    const key = item?.code || `${item?.name || ""}:${item?.sector || ""}`;
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function numberOrNull(value: any) {
  if (value == null || value === "") return null;
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function operationPlan(item: any, totalAmount?: number | null) {
  const plan = item?.tomorrow_plan || {};
  const pctValue = numberOrNull(plan.target_position_pct ?? item?.position_pct) || 0;
  const targetAmount = totalAmount != null ? totalAmount * pctValue / 100 : null;
  const current = numberOrNull(item?.current_price);
  const quantity = numberOrNull(item?.quantity);
  const currentAmount = current != null && quantity != null ? current * quantity : null;
  const currentPct = totalAmount != null && totalAmount > 0 && currentAmount != null
    ? Number((currentAmount / totalAmount * 100).toFixed(1))
    : null;
  const remainingAddPct = currentPct != null ? Math.max(pctValue - currentPct, 0) : pctValue;
  const plannedInitialPct = numberOrNull(plan.initial_add_position_pct) ?? Number((pctValue * 0.5).toFixed(1));
  const initialWeight = pctValue > 0 ? Math.min(Math.max(plannedInitialPct / pctValue, 0), 1) : 0.5;
  const addPct = Number((remainingAddPct * initialWeight).toFixed(1));
  const pullbackPct = Number(Math.max(remainingAddPct - addPct, 0).toFixed(1));
  const reducePct = numberOrNull(plan.reduce_position_pct) ?? Number((pctValue * 0.5).toFixed(1));
  const stopReducePct = numberOrNull(plan.stop_reduce_position_pct) ?? pctValue;
  const entry = numberOrNull(plan.add_price ?? item?.entry_price);
  const pullback = numberOrNull(plan.pullback_add_price);
  const target = numberOrNull(plan.reduce_price ?? item?.target_price);
  const stop = numberOrNull(plan.stop_loss_price ?? item?.stop_loss_price);
  const amountText = (pctPart: number) =>
    totalAmount != null && pctPart > 0 ? `，约 ${money(totalAmount * pctPart / 100)}` : "";
  const ma = plan.moving_averages || item?.moving_averages || {};
  const maText = ["ma5", "ma10", "ma20", "ma60"]
    .map((key) => (ma?.[key] != null ? `${key.toUpperCase()} ${price(ma[key])}` : ""))
    .filter(Boolean)
    .join(" / ");
  return {
    targetAmount,
    currentAmount,
    currentPct,
    addText: entry
      ? addPct > 0
        ? `不高于 ${price(entry)} 先补 ${addPct.toFixed(1)}%${amountText(addPct)}`
        : `已达目标仓位，低于 ${price(entry)} 不再追补`
      : "",
    pullbackText: pullback && pullbackPct > 0
      ? `回踩 ${price(pullback)} 再补 ${pullbackPct.toFixed(1)}%${amountText(pullbackPct)}`
      : "",
    takeProfitText: target && reducePct > 0
      ? `冲高到 ${price(target)} 减 ${reducePct.toFixed(1)}%${amountText(reducePct)}`
      : "",
    stopText: stop && stopReducePct > 0
      ? `跌破 ${price(stop)} 风控减 ${stopReducePct.toFixed(1)}%${amountText(stopReducePct)}`
      : "",
    maText: maText || plan.ma_basis || "",
    primary: plan.primary || "",
  };
}

function boardLabel(item: any) {
  const name = item?.name || item?.sector || item?.code;
  if (!name) return "";
  const change = item?.change_pct ?? item?.avg_return_5d;
  return change != null ? `${name}(${pct(change)})` : String(name);
}

function planNames(items: any[], limit = 3) {
  return items
    .slice(0, limit)
    .map((item) => item?.name || item?.sector || item?.code)
    .filter(Boolean)
    .join("、");
}

function allocationContext(latest: any, plan: any[], totalPct: number, hotBoards: any[], rotationBoards: any[], earlySignals: string[]) {
  const hotText = hotBoards.slice(0, 3).map(boardLabel).filter(Boolean).join("、");
  const rotationText = rotationBoards.slice(0, 3).map(boardLabel).filter(Boolean).join("、");
  const topPlanText = planNames(plan, 3);
  const scoreLeader = [...plan].sort((a, b) => Number(b?.score || 0) - Number(a?.score || 0))[0];
  const leaderText = scoreLeader
    ? `${scoreLeader.name || scoreLeader.code}${scoreLeader.score != null ? `（评分 ${scoreLeader.score}）` : ""}`
    : "";
  const cashPct = Math.max(0, 100 - totalPct);
  const marketParts = [
    latest?.summary ? `系统综述：${latest.summary}` : "",
    hotText ? `当前强势方向集中在 ${hotText}` : "",
    rotationText ? `下一轮候选关注 ${rotationText}` : "",
    earlySignals.length ? `另有 ${earlySignals.length} 条早期轮动信号，需要等价格和量能确认` : "",
  ].filter(Boolean);
  const planParts = plan.length
    ? [
        topPlanText ? `配置优先选择 ${topPlanText}` : "",
        leaderText ? `其中 ${leaderText} 是当前方案里评分靠前的核心候选` : "",
        `组合目标仓位 ${totalPct.toFixed(1)}%，保留约 ${cashPct.toFixed(1)}% 现金，避免在轮动确认前一次性打满`,
        "补仓价参考均线支撑和当前价格位置，先小幅试仓，回踩确认后再补；冲高到目标价先减半，跌破风控价按计划降仓。",
      ].filter(Boolean)
    : [
        "当前没有 ETF 同时满足买入/加仓评分和短期风险闸门，明日配置维持空仓/观望。",
        "短期轮出、当日大跌或5日收益转弱的标的不会进入配置方案，先等待价格重新站稳均线和资金回流。",
      ];
  return {
    market: marketParts.join("；") || "当前缺少可用的板块快照，暂按关注 ETF 的技术和资金评分生成配置。",
    plan: planParts.join("；"),
  };
}

function boardRecommendationLabel(recommendations: any[]) {
  return recommendations.some((item) => item?.is_watched) ? "关注列表 ETF：" : "全市场优选 ETF：";
}

function groupWatchItems(items: any[]) {
  const map = new Map<string, any[]>();
  for (const item of items) {
    const key = item?.sector || item?.pool_group || "未分类";
    map.set(key, [...(map.get(key) || []), item]);
  }
  return Array.from(map.entries()).map(([group, rows]) => ({ group, rows }));
}

function buildPriceChartRows(kline: any[] = []) {
  const closes: number[] = [];
  return kline.map((row) => {
    const close = numberOrNull(row?.close);
    closes.push(close ?? NaN);
    const ma = (period: number) => {
      const values = closes.slice(-period).filter((v) => Number.isFinite(v));
      return values.length === period ? Number((values.reduce((sum, v) => sum + v, 0) / period).toFixed(3)) : null;
    };
    return {
      date: String(row?.trade_date || "").slice(5),
      close,
      ma5: ma(5),
      ma20: ma(20),
    };
  });
}

function quantity(value?: number | null) {
  if (value == null) return "-";
  const num = Number(value);
  const abs = Math.abs(num);
  if (abs >= 100000000) return `${(num / 100000000).toFixed(2)}亿份`;
  if (abs >= 10000) return `${(num / 10000).toFixed(2)}万份`;
  return `${num.toFixed(0)}份`;
}

function volumeStats(kline: any[] = []) {
  const latest = kline[kline.length - 1];
  const latestVolume = numberOrNull(latest?.volume);
  const prev = kline.slice(-21, -1).map((row) => numberOrNull(row?.volume)).filter((v): v is number => v != null);
  const avg20 = prev.length >= 20 ? prev.reduce((sum, v) => sum + v, 0) / prev.length : null;
  const ratio = latestVolume != null && avg20 ? latestVolume / avg20 : null;
  return { latestVolume, avg20, ratio };
}

function pricePosition(technicals: any) {
  const latest = numberOrNull(technicals?.latest_close);
  const high = numberOrNull(technicals?.high_60d);
  const low = numberOrNull(technicals?.low_60d);
  if (latest == null || high == null || low == null || high === low) return null;
  return Number(((latest - low) / (high - low) * 100).toFixed(1));
}

function calcAvg(values: Array<number | null>) {
  const valid = values.filter((v): v is number => v != null);
  return valid.length ? valid.reduce((sum, v) => sum + v, 0) / valid.length : null;
}

function sectorStatsFromLatest(latest: any, sector?: string) {
  const rows = (latest?.individual_analysis || []).filter((item: any) => item?.sector === sector);
  return {
    count: rows.length,
    avgReturn5d: calcAvg(rows.map((item: any) => numberOrNull(item?.technicals?.return_5d))),
    avgReturn20d: calcAvg(rows.map((item: any) => numberOrNull(item?.technicals?.return_20d))),
    avgVolumeRatio: calcAvg(rows.map((item: any) => numberOrNull(item?.technicals?.volume_ratio))),
  };
}

function trendAdvice(technicals: any) {
  const close = numberOrNull(technicals?.latest_close);
  const ma5 = numberOrNull(technicals?.ma5);
  const ma20 = numberOrNull(technicals?.ma20);
  const r5 = numberOrNull(technicals?.return_5d);
  if (close != null && ma5 != null && ma20 != null && close > ma5 && ma5 > ma20) return "走势偏顺；等回踩均线不破再确认。";
  if (close != null && ma20 != null && close < ma20) return "价格仍在 MA20 下方，趋势未完全修复。";
  if (r5 != null && r5 > 3) return "5日涨幅较快，先看量能能否继续配合。";
  return "趋势不极端，重点看后续能否站稳 MA20 并放量。";
}

function volumeAdvice(ratio?: number | null) {
  if (ratio == null) return "20日均量不足，量能暂不作为主要依据。";
  if (ratio >= 1.5) return "明显放量，资金参与度提高。";
  if (ratio >= 1.2) return "温和放量，观察能否连续放量。";
  if (ratio < 0.7) return "明显缩量，短线资金参与不足。";
  return "量能正常，没有明显放大或萎缩。";
}

function positionAdvice(pos?: number | null) {
  if (pos == null) return "60日高低点不足，暂不判断价格位置。";
  if (pos >= 80) return "处在近60日高位区，避免追涨，等回踩。";
  if (pos >= 60) return "位置偏高，适合小仓跟踪，不适合重仓追。";
  if (pos >= 30) return "位置适中，结合趋势和量能决定。";
  return "位置偏低，但要等趋势修复，不能只因为便宜就买。";
}

export default function EtfAnalysisPage() {
  const { message, modal } = App.useApp();
  const [watchlist, setWatchlist] = useState<{ items: any[]; summary: any }>({ items: [], summary: {} });
  const [latest, setLatest] = useState<any>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [useLlm, setUseLlm] = useState(true);
  const [task, setTask] = useState<any>(null);

  const [adding, setAdding] = useState(false);
  const [addingNews, setAddingNews] = useState(false);
  const [editing, setEditing] = useState<any>(null);
  const [recordDetail, setRecordDetail] = useState<any>(null);
  const [etfDetailsByCode, setEtfDetailsByCode] = useState<Record<string, any>>({});
  const [loadingEtfDetails, setLoadingEtfDetails] = useState<Record<string, boolean>>({});
  const [submitting, setSubmitting] = useState(false);
  const [allocationAmount, setAllocationAmount] = useState<number | null>(100000);
  const [addForm] = Form.useForm();
  const [editForm] = Form.useForm();
  const [newsForm] = Form.useForm();
  const taskTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (taskTimer.current) {
      clearInterval(taskTimer.current);
      taskTimer.current = null;
    }
  }, []);

  const loadAll = useCallback(async () => {
    setLoading(true);
    const [wl, lt, hs] = await Promise.all([
      getEtfWatchlist().catch(() => ({ items: [], summary: {} })),
      getEtfAnalysisLatest().catch(() => null),
      getEtfAnalysisHistory(30).catch(() => []),
    ]);
    setWatchlist(wl as any);
    setLatest(lt);
    setHistory(hs as any[]);
    setLoading(false);
  }, []);

  useEffect(() => {
    loadAll();
    return () => stopPolling();
  }, [loadAll, stopPolling]);

  const pollTask = useCallback(
    (taskId: string) => {
      stopPolling();
      taskTimer.current = setInterval(async () => {
        try {
          const t = await getEtfAnalysisTask(taskId);
          setTask(t);
          if (t.status === "completed") {
            stopPolling();
            setRunning(false);
            message.success("ETF 分析完成");
            await loadAll();
          } else if (t.status === "failed") {
            stopPolling();
            setRunning(false);
            message.error(t.error_message || "分析失败");
          }
        } catch (e: any) {
          stopPolling();
          setRunning(false);
          message.error(e?.message || "任务轮询失败");
          loadAll(); // still refresh history in case the record was saved before error
        }
      }, 1500);
    },
    [loadAll, message, stopPolling],
  );

  const handleRun = useCallback(async () => {
    setRunning(true);
    setTask({ status: "queued", progress: 0, step: "提交任务" });
    try {
      const created = await runEtfAnalysis({ use_llm: useLlm, lookback_days: 120 });
      if (created.already_running) {
        message.info("已有 ETF 分析任务运行中，已切换到该任务进度");
      }
      pollTask(created.task_id);
    } catch (e: any) {
      setRunning(false);
      message.error(e?.message || "触发分析失败");
    }
  }, [message, pollTask, useLlm]);

  const handleAdd = useCallback(async () => {
    const values = await addForm.validateFields();
    setSubmitting(true);
    try {
      await addEtfWatch(values);
      message.success("已添加");
      setAdding(false);
      addForm.resetFields();
      loadAll();
    } catch (e: any) {
      message.error(e?.message || "添加失败");
    } finally {
      setSubmitting(false);
    }
  }, [addForm, loadAll, message]);

  const openNewsModal = useCallback(() => {
    newsForm.setFieldsValue({
      source: "manual_verified",
      event_type: "ipo",
      sentiment: "positive",
      sectors: "AI / 科技主线",
      keywords: "长鑫存储，长鑫科技，存储芯片，DRAM，半导体",
    });
    setAddingNews(true);
  }, [newsForm]);

  const handleAddNews = useCallback(async () => {
    const values = await newsForm.validateFields();
    setSubmitting(true);
    try {
      await addManualEtfNews({
        title: values.title,
        content: values.content,
        publish_time: values.publish_time || undefined,
        source: values.source || "manual_verified",
        event_type: values.event_type || "ipo",
        sentiment: values.sentiment || "positive",
        sectors: parseTagInput(values.sectors),
        keywords: parseTagInput(values.keywords),
      });
      message.success("资讯已入库，重新立即分析后会参与匹配");
      setAddingNews(false);
      newsForm.resetFields();
    } catch (e: any) {
      message.error(e?.message || "资讯入库失败");
    } finally {
      setSubmitting(false);
    }
  }, [message, newsForm]);

  const openEdit = useCallback(
    (row: any) => {
      setEditing(row);
      editForm.setFieldsValue({
        name: row.name,
        sector: row.sector,
        is_holding: row.is_holding,
        cost_price: row.cost_price,
        quantity: row.quantity,
        target_price: row.target_price,
        stop_loss_price: row.stop_loss_price,
        note: row.note,
      });
    },
    [editForm],
  );

  const handleEdit = useCallback(async () => {
    const values = await editForm.validateFields();
    setSubmitting(true);
    try {
      await updateEtfWatch(editing.id, values);
      message.success("已更新");
      setEditing(null);
      loadAll();
    } catch (e: any) {
      message.error(e?.message || "更新失败");
    } finally {
      setSubmitting(false);
    }
  }, [editForm, editing, loadAll, message]);

  const handleRemove = useCallback(
    (row: any) => {
      modal.confirm({
        title: `移除 ${row.name || row.code}？`,
        content: "移除后将不再出现在列表，历史分析记录会保留。",
        okType: "danger",
        onOk: async () => {
          await removeEtfWatch(row.id);
          message.success("已移除");
          loadAll();
        },
      });
    },
    [loadAll, message, modal],
  );

  const openRecord = useCallback(
    async (id: number) => {
      try {
        const row = await getEtfAnalysisRecord(id);
        setRecordDetail(row);
      } catch (e: any) {
        message.error(e?.message || "加载记录失败");
      }
    },
    [message],
  );

  const loadEtfDetail = useCallback(
    async (code: string) => {
      if (!code) return;
      if (etfDetailsByCode[code]) return;
      setLoadingEtfDetails((prev) => ({ ...prev, [code]: true }));
      try {
        const detail = await getEtfDetail(code, 120);
        setEtfDetailsByCode((prev) => ({ ...prev, [code]: detail }));
      } catch (e: any) {
        message.error(e?.message || "加载 ETF 详情失败");
      } finally {
        setLoadingEtfDetails((prev) => ({ ...prev, [code]: false }));
      }
    },
    [etfDetailsByCode, message],
  );

  const handleImportRotationPool = useCallback(async () => {
    setSubmitting(true);
    try {
      const result = await importEtfRotationPool({ overwrite_existing: false });
      message.success(`轮动观测池已导入：新增 ${result.created}，更新 ${result.updated}，保留 ${result.unchanged}`);
      await loadAll();
    } catch (e: any) {
      message.error(e?.message || "导入失败");
    } finally {
      setSubmitting(false);
    }
  }, [loadAll, message]);

  const summary = watchlist.summary || {};
  const groupedWatchItems = useMemo(() => groupWatchItems(watchlist.items || []), [watchlist.items]);
  const rotationPoolCount = useMemo(() => (watchlist.items || []).filter((item: any) => item?.is_rotation_pool).length, [watchlist.items]);
  const customWatchCount = Math.max((summary.total ?? 0) - rotationPoolCount, 0);
  const marketHotBoards = useMemo(() => (latest?.market_hot_boards || []) as any[], [latest]);
  const marketRotationBoards = useMemo(() => (latest?.market_rotation_boards || []) as any[], [latest]);
  const marketEarlySignals = useMemo(() => (latest?.market_early_signals || []) as string[], [latest]);
  const latestAnalysisByCode = useMemo(() => {
    const map: Record<string, any> = {};
    for (const item of latest?.individual_analysis || []) {
      if (item?.code) map[item.code] = item;
    }
    return map;
  }, [latest]);
  const visibleHotBoards = useMemo(() => marketHotBoards.slice(0, 8), [marketHotBoards]);
  const visibleRotationBoards = useMemo(() => marketRotationBoards.slice(0, 8), [marketRotationBoards]);
  const selectedAllocationPlan = useMemo(
    () => mergeAllocationPlans(latest?.recommendations || [], latest?.llm_recommendations || []).slice(0, 5),
    [latest],
  );
  const allocationTotalPct = selectedAllocationPlan.reduce(
    (sum: number, item: any) => sum + Number(item?.position_pct || 0),
    0,
  );
  const allocationExplanation = useMemo(
    () => allocationContext(
      latest,
      selectedAllocationPlan,
      allocationTotalPct,
      marketHotBoards,
      marketRotationBoards,
      marketEarlySignals,
    ),
    [allocationTotalPct, latest, marketEarlySignals, marketHotBoards, marketRotationBoards, selectedAllocationPlan],
  );
  const plannedInvestAmount = allocationAmount != null && allocationTotalPct
    ? allocationAmount * allocationTotalPct / 100
    : null;
  const [backfillingCode, setBackfillingCode] = useState<string | null>(null);
  const [backfillingAll, setBackfillingAll] = useState(false);
  const [refreshingQuotesAll, setRefreshingQuotesAll] = useState(false);
  const [refreshingQuoteCode, setRefreshingQuoteCode] = useState<string | null>(null);

  const handleBackfillOne = useCallback(
    async (code: string) => {
      if (!code) return;
      setBackfillingCode(code);
      try {
        const r = await backfillEtfKline(code, 120);
        if (r?.ok) {
          message.success(`${code} 补全成功（${r.source} · ${r.rows} 条）`);
          await loadAll();
        } else {
          message.error(`${code} 补全失败：${(r?.errors || []).slice(0, 1).join("；") || "全部源失败"}`);
        }
      } catch (e: any) {
        message.error(e?.message || "补全失败");
      } finally {
        setBackfillingCode(null);
      }
    },
    [loadAll, message],
  );

  const handleBackfillAll = useCallback(async () => {
    if (!latest?.id) {
      message.warning("先运行一次分析再补全");
      return;
    }
    setBackfillingAll(true);
    try {
      const r = await backfillMissingEtfKlines(latest.id, 120);
      if (!r?.missing_codes?.length) {
        message.info("没有需要补全的 ETF");
      } else {
        message.success(`已尝试补全 ${r.missing_codes.length} 只：成功 ${r.success_count}，失败 ${r.fail_count}`);
        await loadAll();
      }
    } catch (e: any) {
      message.error(e?.message || "批量补全失败");
    } finally {
      setBackfillingAll(false);
    }
  }, [latest, loadAll, message]);

  const handleRefreshQuotesAll = useCallback(async () => {
    setRefreshingQuotesAll(true);
    try {
      const r = await refreshEtfQuotes();
      if (r?.ok) {
        message.success(`实时行情已刷新（${r.count} 条）`);
        await loadAll();
      } else {
        message.error(r?.error || "刷新失败");
      }
    } catch (e: any) {
      message.error(e?.message || "刷新失败");
    } finally {
      setRefreshingQuotesAll(false);
    }
  }, [loadAll, message]);

  const handleRefreshQuoteOne = useCallback(
    async (code: string) => {
      if (!code) return;
      setRefreshingQuoteCode(code);
      try {
        const r = await refreshEtfQuotes([code]);
        const quote = r?.quotes?.[code];
        if (r?.ok && quote?.price != null) {
          message.success(`${code} 实时行情已刷新（${quote.price}）`);
          await loadAll();
        } else if (r?.ok) {
          message.warning(`${code} 暂无最新行情数据`);
        } else {
          message.error(r?.error || "刷新失败");
        }
      } catch (e: any) {
        message.error(e?.message || "刷新失败");
      } finally {
        setRefreshingQuoteCode(null);
      }
    },
    [loadAll, message],
  );

  const openAddFromRecommendation = useCallback(
    (etf: any) => {
      addForm.setFieldsValue({
        code: etf?.code,
        name: etf?.name,
        sector: etf?.sector,
      });
      setAdding(true);
    },
    [addForm],
  );

  const renderBoardRecommendations = useCallback(
    (board: any) => {
      const boardRecs = Array.isArray(board?.recommended_etfs) ? board.recommended_etfs : [];
      if (!boardRecs.length) {
        return <Text type="secondary" style={{ fontSize: 12 }}>暂无可映射 ETF</Text>;
      }
      return (
        <Space orientation="vertical" size={4} style={{ width: "100%" }}>
          <Text type="secondary" style={{ fontSize: 12 }}>{boardRecommendationLabel(boardRecs)}</Text>
          {boardRecs.map((etf: any, i: number) => (
            <div key={`${etf.code || i}-board-rec`}>
              <Space size={4} wrap>
                <Tag color={etf.is_watched ? "blue" : "gold"}>
                  {etf.name || etf.code}（{etf.code}）
                </Tag>
                {etf.score != null ? <Tag>评分 {etf.score}</Tag> : null}
                {etf.change_pct != null ? <Tag>{pct(etf.change_pct)}</Tag> : null}
                {!etf.is_watched ? <Tag color="orange">未关注</Tag> : null}
                {!etf.is_watched ? (
                  <Button size="small" icon={<PlusOutlined />} onClick={() => openAddFromRecommendation(etf)}>
                    加入关注
                  </Button>
                ) : null}
              </Space>
              {etf.match_reason ? (
                <div style={{ marginTop: 2 }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {compactReason(etf.match_reason, 92)}
                  </Text>
                </div>
              ) : null}
            </div>
          ))}
        </Space>
      );
    },
    [openAddFromRecommendation],
  );

  const watchColumns: ColumnsType<any> = useMemo(
    () => [
      {
        title: "代码 / 名称",
        key: "code",
        width: 180,
        render: (_: any, row: any) => (
          <Space orientation="vertical" size={2}>
            <Text strong>{row.name || row.code}</Text>
            <Text type="secondary">{row.code}{row.alias ? ` · ${row.alias}` : ""}</Text>
            {row.sector ? <Tag>{row.sector}</Tag> : null}
            {row.rotation_direction ? <Tag color="blue">{row.rotation_direction}</Tag> : null}
          </Space>
        ),
      },
      {
        title: "实时行情",
        key: "quote",
        width: 130,
        render: (_: any, row: any) => (
          <Space orientation="vertical" size={2}>
            <Text strong>{price(row.current_price)}</Text>
            <Text type={Number(row.change_pct ?? 0) >= 0 ? "danger" : "success"}>{pct(row.change_pct)}</Text>
          </Space>
        ),
      },
      {
        title: "趋势 / 建议",
        key: "latest_signal",
        width: 150,
        render: (_: any, row: any) => {
          const analysis = latestAnalysisByCode[row.code] || {};
          return (
            <Space orientation="vertical" size={4}>
              {analysis.trend ? trendTag(analysis.trend) : <Tag>未分析</Tag>}
              {analysis.action ? actionTag(analysis.action, analysis.action_label) : <Text type="secondary">-</Text>}
              {analysis.risk_gate_reason ? (
                <Text type="secondary" style={{ fontSize: 12 }}>{compactReason(analysis.risk_gate_reason, 42)}</Text>
              ) : null}
            </Space>
          );
        },
      },
      {
        title: "持仓",
        key: "holding",
        width: 160,
        render: (_: any, row: any) =>
          row.is_holding ? (
            <Space orientation="vertical" size={2}>
              <Text>{row.quantity ?? "-"} 份</Text>
              <Text type="secondary">成本 {price(row.cost_price)}</Text>
              <Text type="secondary">投入 {money(row.cost_amount)}</Text>
            </Space>
          ) : (
            <Tag>仅关注</Tag>
          ),
      },
      {
        title: "盈亏",
        key: "profit",
        width: 150,
        render: (_: any, row: any) => {
          if (!row.is_holding) return <Text type="secondary">-</Text>;
          const positive = Number(row.unrealized_profit ?? 0) >= 0;
          return (
            <Space orientation="vertical" size={2}>
              <Text strong type={positive ? "danger" : "success"}>{money(row.unrealized_profit, true)}</Text>
              <Text type={positive ? "danger" : "success"}>{pct(row.unrealized_return_pct)}</Text>
              <Text type="secondary">市值 {money(row.market_value)}</Text>
            </Space>
          );
        },
      },
      {
        title: "止盈/止损",
        key: "threshold",
        width: 180,
        render: (_: any, row: any) => (
          <Space orientation="vertical" size={4}>
            {thresholdTag(row.threshold_status)}
            <Text type="secondary">
              {price(row.target_price)} / {price(row.stop_loss_price)}
            </Text>
          </Space>
        ),
      },
      {
        title: "观测信号 / 备注",
        key: "note",
        width: 360,
        render: (_: any, row: any) => (
          <Space orientation="vertical" size={2}>
            <Paragraph style={{ margin: 0 }} ellipsis={{ rows: 2 }}>
              {row.observation_signal || "-"}
            </Paragraph>
            {row.note ? (
              <Text type="secondary" style={{ fontSize: 12 }}>
                {compactReason(String(row.note).replace(/\n/g, "；"), 110)}
              </Text>
            ) : null}
          </Space>
        ),
      },
      {
        title: "操作",
        key: "action",
        width: 120,
        fixed: "right" as const,
        render: (_: any, row: any) => (
          <Space size={6}>
            <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>编辑</Button>
            <Button size="small" icon={<EyeOutlined />}
              onClick={() => addWatchItem({ code: row.code, name: row.name || row.code, source: "etf" }).then(() => {}).catch(() => {})}
            >关注</Button>
            <Button size="small" danger icon={<DeleteOutlined />} onClick={() => handleRemove(row)} />
          </Space>
        ),
      },
    ],
    [handleRemove, latestAnalysisByCode, openEdit],
  );

  const recommendationColumns: ColumnsType<any> = useMemo(
    () => [
      {
        title: "标的",
        key: "code",
        width: 160,
        render: (_: any, row: any) => (
          <Space orientation="vertical" size={2}>
            <Text strong>{row.name || row.code}</Text>
            <Text type="secondary">{row.code}</Text>
            {row.sector ? <Tag>{row.sector}</Tag> : null}
          </Space>
        ),
      },
      {
        title: "操作",
        key: "action",
        width: 100,
        render: (_: any, row: any) => actionTag(row.action, row.action_label),
      },
      {
        title: "评分",
        dataIndex: "score",
        key: "score",
        width: 90,
        render: (v: number) => <Text strong>{v ?? "-"}</Text>,
      },
      {
        title: "现价",
        dataIndex: "current_price",
        key: "current_price",
        width: 90,
        render: price,
      },
      {
        title: "建议入场",
        dataIndex: "entry_price",
        key: "entry_price",
        width: 90,
        render: price,
      },
      {
        title: "止盈",
        dataIndex: "target_price",
        key: "target_price",
        width: 90,
        render: (v: number) => <Text type="danger">{price(v)}</Text>,
      },
      {
        title: "止损",
        dataIndex: "stop_loss_price",
        key: "stop_loss_price",
        width: 90,
        render: (v: number) => <Text type="success">{price(v)}</Text>,
      },
      {
        title: "建议仓位",
        dataIndex: "position_pct",
        key: "position_pct",
        width: 100,
        render: (v: number) => (v == null ? "-" : `${v}%`),
      },
      {
        title: "理由",
        dataIndex: "reason",
        key: "reason",
        render: (v: string) => <Paragraph style={{ margin: 0 }} ellipsis={{ rows: 2 }}>{v || "-"}</Paragraph>,
      },
    ],
    [],
  );

  const individualColumns: ColumnsType<any> = useMemo(
    () => [
      {
        title: "ETF",
        key: "code",
        width: 180,
        render: (_: any, row: any) => (
          <Space orientation="vertical" size={2}>
            <Text strong>{row.name || row.code}</Text>
            <Text type="secondary">{row.code}{row.alias ? ` · ${row.alias}` : ""}</Text>
            {row.sector ? <Tag>{row.sector}</Tag> : null}
            {row.rotation_direction ? <Tag color="blue">{row.rotation_direction}</Tag> : null}
            {row.is_holding ? <Tag color="blue">持仓</Tag> : null}
          </Space>
        ),
      },
      { title: "现价", dataIndex: "current_price", key: "current_price", width: 80, render: price },
      { title: "趋势", key: "trend", width: 80, render: (_: any, row: any) => trendTag(row.trend) },
      {
        title: "建议",
        key: "action",
        width: 100,
        render: (_: any, row: any) => actionTag(row.action, row.action_label),
      },
      {
        title: "K线源",
        dataIndex: "kline_source",
        key: "kline_source",
        width: 130,
        render: (v: string) => <Text type="secondary">{v || "-"}</Text>,
      },
      {
        title: "综合评分",
        dataIndex: "score",
        key: "score",
        width: 100,
        sorter: (a: any, b: any) => (a.score ?? 0) - (b.score ?? 0),
        render: (v: number) => <Text strong>{v ?? "-"}</Text>,
      },
      {
        title: "历史趋势",
        key: "hist",
        width: 110,
        render: (_: any, row: any) => {
          const trend = row.score_trend;
          const cbs = row.consecutive_buy_sessions || 0;
          const delta = row.score_delta;
          if (!trend && cbs === 0) return <Text type="secondary">-</Text>;
          const trendTag =
            trend === "rising" ? <Tag color="green">↑ 上升</Tag> :
            trend === "falling" ? <Tag color="red">↓ 下降</Tag> :
            trend === "stable" ? <Tag>→ 平稳</Tag> : null;
          return (
            <Space orientation="vertical" size={2}>
              {trendTag}
              {delta != null ? <Text type="secondary">{delta > 0 ? `+${delta}` : delta}</Text> : null}
              {cbs >= 2 ? <Tag color={cbs >= 3 ? "volcano" : "orange"}>连续买入 {cbs} 次</Tag> : null}
            </Space>
          );
        },
      },
      {
        title: "资金面",
        key: "funds",
        width: 180,
        render: (_: any, row: any) => {
          const f = row.funds || {};
          if (!f.source) return <Text type="secondary">-</Text>;
          return (
            <Space orientation="vertical" size={2}>
              <Text type="secondary">折溢价 {pct(f.discount_rate)}</Text>
              <Text type="secondary">份额变化 {pct(f.share_delta_pct)}</Text>
              <Text type="secondary">规模估算 {money(f.estimated_nav_value)}</Text>
            </Space>
          );
        },
      },
      {
        title: "补全",
        key: "backfill",
        width: 170,
        render: (_: any, row: any) => {
          const klineMissing =
            !row.kline_source ||
            row.kline_source === "missing" ||
            row.kline_source === "cache_stale" ||
            row.technicals?.latest_close == null;
          const quoteMissing = row.current_price == null;
          if (!klineMissing && !quoteMissing) return <Text type="secondary">-</Text>;
          return (
            <Space size={4}>
              {quoteMissing ? (
                <Button
                  size="small"
                  icon={<ReloadOutlined />}
                  loading={refreshingQuoteCode === row.code}
                  onClick={() => handleRefreshQuoteOne(row.code)}
                >
                  刷行情
                </Button>
              ) : null}
              {klineMissing ? (
                <Button
                  size="small"
                  icon={<ReloadOutlined />}
                  loading={backfillingCode === row.code}
                  onClick={() => handleBackfillOne(row.code)}
                >
                  补 K 线
                </Button>
              ) : null}
            </Space>
          );
        },
      },
    ],
    [backfillingCode, handleBackfillOne, handleRefreshQuoteOne, refreshingQuoteCode],
  );

  const renderEtfExpanded = useCallback((code: string) => {
    const detail = etfDetailsByCode[code];
    if (loadingEtfDetails[code]) return <Spin style={{ display: "block", margin: "32px auto" }} />;
    if (!detail) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="正在加载 ETF 详情" />;
    const item = detail.watch_item || {};
    const analysis = detail.latest_analysis || {};
    const technicals = analysis.technicals || detail.technicals || {};
    const chartRows = buildPriceChartRows(detail.kline || []);
    const quote = detail.quote || {};
    const funds = analysis.funds || detail.funds || {};
    const volume = volumeStats(detail.kline || []);
    const position = pricePosition(technicals);
    const sectorStats = sectorStatsFromLatest(latest, item.sector || analysis.sector);
    const newsList = latest?.market_overview?.sector_news_summary?.[item.sector || analysis.sector] || [];
    return (
      <Space orientation="vertical" size={12} style={{ width: "100%", padding: "8px 0" }}>
        {(detail.data_gaps || []).length ? <Alert type="warning" showIcon title="数据缺口" description={(detail.data_gaps || []).join("；")} /> : null}
        <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 4 }}>
          <Descriptions.Item label="代码">{detail.code}</Descriptions.Item>
          <Descriptions.Item label="名称">{item.name || "-"}</Descriptions.Item>
          <Descriptions.Item label="清单名称">{item.alias || "-"}</Descriptions.Item>
          <Descriptions.Item label="分组">{item.sector || "-"}</Descriptions.Item>
          <Descriptions.Item label="轮动方向">{item.rotation_direction || analysis.rotation_direction || "-"}</Descriptions.Item>
          <Descriptions.Item label="现价">{price(item.current_price ?? analysis.current_price)}</Descriptions.Item>
          <Descriptions.Item label="趋势">{trendTag(analysis.trend || technicals.trend)}</Descriptions.Item>
          <Descriptions.Item label="建议">{analysis.action_label || analysis.action || "-"}</Descriptions.Item>
        </Descriptions>
        <Alert type="info" showIcon title="观测备注" description={item.observation_signal || item.note || "-"} />
        <Card size="small" title="关键计算结果和参考建议">
          <Table
            rowKey="key"
            size="small"
            pagination={false}
            columns={[
              { title: "维度", dataIndex: "name", key: "name", width: 90 },
              { title: "计算结果", dataIndex: "result", key: "result" },
              { title: "参考建议", dataIndex: "advice", key: "advice" },
            ]}
            dataSource={[
              {
                key: "technical",
                name: "技术",
                result: `最新价 ${price(technicals.latest_close)}；5日 ${pct(technicals.return_5d)}；20日 ${pct(technicals.return_20d)}；MA5 ${price(technicals.ma5)}；MA20 ${price(technicals.ma20)}；RSI ${technicals.rsi14 ?? "-"}；MACD柱 ${(technicals.macd || {}).hist ?? "-"}`,
                advice: trendAdvice(technicals),
              },
              {
                key: "volume",
                name: "量能",
                result: `最新成交量 ${quantity(volume.latestVolume)}；20日均量 ${quantity(volume.avg20)}；量比 ${volume.ratio == null ? "-" : volume.ratio.toFixed(2)}`,
                advice: volumeAdvice(volume.ratio),
              },
              {
                key: "fund",
                name: "资金",
                result: `成交额 ${money(quote.amount)}；换手率 ${pct(quote.turnover_rate)}；折溢价 ${pct(funds.discount_rate)}；份额变化 ${pct(funds.share_delta_pct)}；估算规模 ${money(funds.estimated_nav_value)}`,
                advice: funds.share_delta_pct == null ? "份额变化缺失时，只用成交额、换手和折溢价作辅助参考。" : "份额增加代表资金申购更积极；折溢价过高时避免追价。",
              },
              {
                key: "sector",
                name: "板块",
                result: `同组 ${sectorStats.count || "-"} 只；5日均涨幅 ${pct(sectorStats.avgReturn5d)}；20日均涨幅 ${pct(sectorStats.avgReturn20d)}；平均量比 ${sectorStats.avgVolumeRatio == null ? "-" : sectorStats.avgVolumeRatio.toFixed(2)}`,
                advice: sectorStats.avgReturn5d != null && sectorStats.avgReturn5d > 0 ? "同组短期表现为正，说明这个方向有轮动热度。" : "同组短期表现不强，先等板块整体走出持续性。",
              },
              {
                key: "news",
                name: "资讯",
                result: `近7日系统匹配资讯 ${newsList.length} 条${newsList[0]?.title ? `；最近：${compactReason(newsList[0].title, 38)}` : ""}`,
                advice: newsList.length ? "有本地资讯支撑，继续看事件是否能转化成成交和价格确认。" : "本地资讯库没有匹配内容，新闻面不作为加分依据。",
              },
              {
                key: "position",
                name: "位置",
                result: `近60日低点 ${price(technicals.low_60d)}；高点 ${price(technicals.high_60d)}；当前处于区间 ${position == null ? "-" : `${position.toFixed(1)}%`}`,
                advice: positionAdvice(position),
              },
            ]}
          />
        </Card>
        <Card size="small" title="价格走势">
          {chartRows.length ? (
            <div style={{ height: 280 }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartRows}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="date" minTickGap={24} />
                  <YAxis domain={["auto", "auto"]} />
                  <Tooltip formatter={(value: any) => price(Number(value))} />
                  <Line type="monotone" dataKey="close" name="收盘" stroke="#1677ff" dot={false} strokeWidth={2} />
                  <Line type="monotone" dataKey="ma5" name="MA5" stroke="#fa8c16" dot={false} strokeWidth={1.5} />
                  <Line type="monotone" dataKey="ma20" name="MA20" stroke="#52c41a" dot={false} strokeWidth={1.5} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无 K 线图表数据" />}
        </Card>
      </Space>
    );
  }, [etfDetailsByCode, latest, loadingEtfDetails]);

  const etfExpandable = useMemo(
    () => ({
      expandedRowRender: (row: any) => renderEtfExpanded(row.code),
      onExpand: (expanded: boolean, row: any) => {
        if (expanded) void loadEtfDetail(row.code);
      },
      rowExpandable: (row: any) => Boolean(row?.code),
    }),
    [loadEtfDetail, renderEtfExpanded],
  );

  const historyColumns: ColumnsType<any> = useMemo(
    () => [
      { title: "时间", dataIndex: "analysis_time", key: "analysis_time", width: 150, render: shortTime },
      {
        title: "触发",
        dataIndex: "trigger_type",
        key: "trigger_type",
        width: 90,
        render: (v: string) => <Tag color={v === "scheduled" ? "blue" : "default"}>{v === "scheduled" ? "定时" : "手动"}</Tag>,
      },
      { title: "ETF数", dataIndex: "etf_count", key: "etf_count", width: 80 },
      {
        title: "热度排行",
        key: "hot",
        render: (_: any, row: any) => {
          const hs = (row.hot_sectors || []).slice(0, 3);
          if (!hs.length) return <Text type="secondary">-</Text>;
          return (
            <Space size={4} wrap>
              {hs.map((s: any, i: number) => (
                <Tag key={i} color="red">{s.sector}{s.score ? ` ${s.score}` : ""}</Tag>
              ))}
            </Space>
          );
        },
      },
      {
        title: "推荐数",
        key: "rec_count",
        width: 80,
        render: (_: any, row: any) => (row.recommendations || []).length,
      },
      {
        title: "LLM",
        dataIndex: "llm_used",
        key: "llm_used",
        width: 70,
        render: (v: boolean) => (v ? <Tag color="purple">已增强</Tag> : <Tag>规则</Tag>),
      },
      {
        title: "操作",
        key: "action",
        width: 100,
        render: (_: any, row: any) => (
          <Button size="small" icon={<EyeOutlined />} onClick={() => openRecord(row.id)}>详情</Button>
        ),
      },
    ],
    [openRecord],
  );

  if (loading) return <Spin size="large" style={{ display: "block", margin: "100px auto" }} />;

  const renderAnalysis = (data: any) => {
    if (!data) return <Empty description="暂无分析记录，点击右上角立即分析" />;
    const recs = data.recommendations || [];
    const llmRecs = data.llm_recommendations || [];
    const rotation = data.rotation_signals || {};
    const hotSectors = data.hot_sectors || [];
    const earlySignals = rotation.early_signals || [];
    const rotatingIn = rotation.rotating_in || [];
    const rotatingOut = rotation.rotating_out || [];
    const llmForecast = rotation.llm_forecast || [];
    const dataGaps = data.data_gaps || [];
    const riskWarnings = data.risk_warnings || [];

    return (
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Card size="small">
          <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 4 }}>
            <Descriptions.Item label="分析时间">{shortTime(data.analysis_time)}</Descriptions.Item>
            <Descriptions.Item label="触发">{data.trigger_type === "scheduled" ? "定时" : "手动"}</Descriptions.Item>
            <Descriptions.Item label="ETF数">{data.etf_count}</Descriptions.Item>
            <Descriptions.Item label="LLM">{data.llm_used ? "已增强" : "规则"}</Descriptions.Item>
          </Descriptions>
          {data.summary ? (
            <Paragraph style={{ marginTop: 12, marginBottom: 0 }}>{data.summary}</Paragraph>
          ) : null}
        </Card>

        {dataGaps.length ? (
          <Alert
            type="warning"
            showIcon
            title="数据缺口"
            description={
              <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                <ul style={{ marginBottom: 0, paddingLeft: 20 }}>
                  {dataGaps.map((g: string, i: number) => <li key={i}>{g}</li>)}
                </ul>
                {data?.id === latest?.id && data?.has_kline_gaps ? (
                  <Button
                    size="small"
                    type="primary"
                    icon={<ReloadOutlined />}
                    loading={backfillingAll}
                    onClick={handleBackfillAll}
                  >
                    批量补全 K 线
                  </Button>
                ) : null}
              </Space>
            }
          />
        ) : null}

        <Card
          title="ETF 热度"
          size="small"
          extra={<Text type="secondary">分析时间 {shortTime(data.analysis_time)}</Text>}
        >
          {hotSectors.length ? (
            <Space orientation="vertical" size={10} style={{ width: "100%" }}>
              {hotSectors.map((s: any, i: number) => (
                <div
                  key={i}
                  style={{
                    paddingBottom: i === hotSectors.length - 1 ? 0 : 10,
                    borderBottom: i === hotSectors.length - 1 ? "none" : "1px solid #f0f0f0",
                  }}
                >
                  <Space size={6} wrap>
                    <Tag color={i < 3 ? "red" : "default"}>#{i + 1}</Tag>
                    <Text strong>{s.sector}</Text>
                    {s.score != null ? <Tag color="red">热度 {s.score}</Tag> : null}
                    {s.avg_return_5d != null ? <Tag>5日 {pct(s.avg_return_5d)}</Tag> : null}
                    {s.avg_return_20d != null ? <Tag>20日 {pct(s.avg_return_20d)}</Tag> : null}
                    {s.avg_volume_ratio != null ? <Tag>量比 {s.avg_volume_ratio}</Tag> : null}
                  </Space>
                  <Paragraph style={{ margin: "6px 0 0 0" }} type="secondary">
                    依据：{hotSectorBasis(s)}
                  </Paragraph>
                </div>
              ))}
            </Space>
          ) : <Empty description="暂无板块数据" />}
        </Card>

        <Row gutter={16}>
          <Col xs={24} lg={12}>
            <Card title="资金正在流入板块" size="small">
              {rotatingIn.length ? (
                <Space orientation="vertical" size={6} style={{ width: "100%" }}>
                  {rotatingIn.map((s: any, i: number) => (
                    <div key={i} style={{ display: "flex", justifyContent: "space-between" }}>
                      <Text strong>{s.sector}</Text>
                      <Text type="secondary">
                        5日 {pct(s.avg_return_5d)} · 20日 {pct(s.avg_return_20d)} · 量比 {s.avg_volume_ratio ?? "-"}
                      </Text>
                    </div>
                  ))}
                </Space>
              ) : <Empty description="暂无明显轮入" />}
            </Card>
          </Col>
          <Col xs={24} lg={12}>
            <Card title="资金流出板块" size="small">
              {rotatingOut.length ? (
                <Space orientation="vertical" size={6} style={{ width: "100%" }}>
                  {rotatingOut.map((s: any, i: number) => (
                    <div key={i} style={{ display: "flex", justifyContent: "space-between" }}>
                      <Text strong>{s.sector}</Text>
                      <Text type="secondary">
                        5日 {pct(s.avg_return_5d)} · 20日 {pct(s.avg_return_20d)}
                      </Text>
                    </div>
                  ))}
                </Space>
              ) : <Empty description="暂无明显轮出" />}
            </Card>
          </Col>
        </Row>

        {earlySignals.length ? (
          <Alert
            type="info"
            showIcon
            title="轮动早期信号"
            description={
              <ul style={{ marginBottom: 0, paddingLeft: 20 }}>
                {earlySignals.map((s: string, i: number) => <li key={i}>{s}</li>)}
              </ul>
            }
          />
        ) : null}

        {llmForecast.length ? (
          <Card title="LLM 板块轮动研判" size="small">
            <Space orientation="vertical" size={6} style={{ width: "100%" }}>
              {llmForecast.map((f: any, i: number) => (
                <div key={i}>
                  <Tag color={f.direction === "in" ? "red" : "green"}>{f.direction === "in" ? "轮入" : "轮出"}</Tag>
                  <Text strong>{f.sector}</Text>
                  {f.confidence ? <Tag style={{ marginLeft: 8 }}>{f.confidence}</Tag> : null}
                  <Paragraph style={{ margin: "4px 0 0 0" }} type="secondary">{f.reason}</Paragraph>
                </div>
              ))}
            </Space>
          </Card>
        ) : null}

        <Card title="买入推荐（含入场价/止盈/止损/建议仓位）" size="small">
          <Table
            rowKey="code"
            dataSource={recs}
            columns={recommendationColumns}
            size="small"
            pagination={false}
            locale={{ emptyText: <Empty description="本次未生成买入推荐" /> }}
            scroll={{ x: 1100 }}
          />
        </Card>

        {llmRecs.length ? (
          <Card title="LLM 补充建议" size="small">
            <Table
              rowKey={(r: any) => r.code || JSON.stringify(r)}
              dataSource={llmRecs}
              size="small"
              pagination={false}
              columns={[
                { title: "代码", dataIndex: "code", key: "code", width: 100 },
                { title: "名称", dataIndex: "name", key: "name", width: 130 },
                { title: "板块", dataIndex: "sector", key: "sector", width: 120 },
                { title: "入场", dataIndex: "entry_price", key: "entry", width: 90, render: price },
                { title: "止盈", dataIndex: "target_price", key: "target", width: 90, render: price },
                { title: "止损", dataIndex: "stop_loss_price", key: "stop", width: 90, render: price },
                { title: "仓位", dataIndex: "position_pct", key: "pos", width: 80, render: (v: any) => (v != null ? `${v}%` : "-") },
                { title: "理由", dataIndex: "reason", key: "reason", render: (v: string) => v || "-" },
              ]}
            />
          </Card>
        ) : null}

        <Card title="ETF 详细分析" size="small">
          <Table
            rowKey="code"
            dataSource={data.individual_analysis || []}
            columns={individualColumns}
            expandable={etfExpandable}
            size="small"
            pagination={{ pageSize: 12 }}
            scroll={{ x: 1260 }}
          />
        </Card>

        {riskWarnings.length ? (
          <Alert
            type="warning"
            showIcon
            title="风险提示"
            description={
              <ul style={{ marginBottom: 0, paddingLeft: 20 }}>
                {riskWarnings.map((w: string, i: number) => <li key={i}>{w}</li>)}
              </ul>
            }
          />
        ) : null}
      </Space>
    );
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16 }}>
        <div>
          <Title level={3} style={{ marginBottom: 4 }}>ETF 板块轮动分析</Title>
          <Text type="secondary">
            A 股主流轮动观测池，工作日 18:30 盘后自动调用大模型生成轮动结论
          </Text>
        </div>
        <Space wrap>
          <Space size={6}>
            <Text type="secondary">LLM 增强</Text>
            <Switch checked={useLlm} onChange={setUseLlm} />
          </Space>
          <Button icon={<PlusOutlined />} onClick={() => setAdding(true)}>添加 ETF</Button>
          <Button icon={<PlusOutlined />} onClick={openNewsModal}>补充资讯</Button>
          <Button loading={submitting} onClick={handleImportRotationPool}>导入主流池</Button>
          <Button
            icon={<ReloadOutlined />}
            loading={refreshingQuotesAll}
            onClick={handleRefreshQuotesAll}
          >
            刷新实时行情
          </Button>
          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            loading={running}
            disabled={!watchlist.items.length}
            onClick={handleRun}
          >
            立即分析
          </Button>
          <Button icon={<ReloadOutlined />} onClick={loadAll}>刷新</Button>
        </Space>
      </div>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={12} lg={4}><Card size="small"><Statistic title="主流观测池" value={rotationPoolCount} suffix="/ 21" /></Card></Col>
        <Col xs={12} lg={4}><Card size="small"><Statistic title="自定义关注" value={customWatchCount} /></Card></Col>
        <Col xs={12} lg={4}><Card size="small"><Statistic title="持仓数" value={summary.holding_count ?? 0} /></Card></Col>
        <Col xs={12} lg={4}><Card size="small"><Statistic title="持仓市值" value={money(summary.total_market_value)} /></Card></Col>
        <Col xs={12} lg={4}>
          <Card size="small">
            <Statistic
              title="浮动盈亏"
              value={money(summary.total_unrealized_profit, true)}
              styles={{ content: { color: Number(summary.total_unrealized_profit ?? 0) >= 0 ? "#cf1322" : "#3f8600" } }}
            />
          </Card>
        </Col>
        <Col xs={12} lg={4}><Card size="small"><Statistic title="最新分析" value={shortTime(latest?.analysis_time)} /></Card></Col>
        <Col xs={12} lg={4}>
          <Card size="small">
            <div style={{ fontSize: 12, color: "#8c8c8c", marginBottom: 4 }}>市场热门板块 TOP3</div>
            <Space size={4} wrap>
              {marketHotBoards.length
                ? marketHotBoards.slice(0, 3).map((s: any, i: number) => <Tag key={i} color="red">{s.name}</Tag>)
                : <Text type="secondary">-</Text>}
            </Space>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} xl={8}>
          <Card
            size="small"
            title="当前热门板块 TOP8"
            extra={<Text type="secondary">{shortTime(latest?.market_boards_fetched_at || latest?.analysis_time)}</Text>}
            style={{ height: "100%" }}
          >
            {marketHotBoards.length ? (
              <Space orientation="vertical" size={12} style={{ width: "100%" }}>
                {visibleHotBoards.map((board: any, index: number) => (
                  <div key={`${board.name || index}-hot`} style={{ paddingBottom: index === visibleHotBoards.length - 1 ? 0 : 8, borderBottom: index === visibleHotBoards.length - 1 ? "none" : "1px solid #f0f0f0" }}>
                    <Space size={6} wrap>
                      <Tag color={index < 3 ? "red" : "default"}>#{index + 1}</Tag>
                      <Text strong>{board.name}</Text>
                      <Tag color={board.board_type === "concept" ? "geekblue" : "purple"}>{board.board_type === "concept" ? "概念" : "行业"}</Tag>
                      {board.change_pct != null ? <Tag color="red">{pct(board.change_pct)}</Tag> : null}
                      {board.return_5d != null ? <Tag>5日 {pct(board.return_5d)}</Tag> : null}
                      {boardActivityText(board) ? <Tag>{boardActivityText(board)}</Tag> : null}
                      {board.leading_stock ? <Tag color="orange">领涨 {board.leading_stock}</Tag> : null}
                    </Space>
                    <Paragraph style={{ margin: "4px 0", fontSize: 12 }} type="secondary">
                      {compactReason(board.reason, 100)}
                    </Paragraph>
                    {renderBoardRecommendations(board)}
                  </div>
                ))}
              </Space>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无热门板块，先运行一次 ETF 分析" />
            )}
          </Card>
        </Col>
        <Col xs={24} xl={8}>
          <Card size="small" title="下面可能轮动到的板块 TOP8" extra={marketRotationBoards.length ? <Tag color="blue">{marketRotationBoards.length} 个候选</Tag> : null} style={{ height: "100%" }}>
            {marketRotationBoards.length || marketEarlySignals.length ? (
              <Space orientation="vertical" size={12} style={{ width: "100%" }}>
                {visibleRotationBoards.map((board: any, index: number) => (
                  <div key={`${board.name || index}-rot`} style={{ paddingBottom: index === visibleRotationBoards.length - 1 ? 0 : 8, borderBottom: index === visibleRotationBoards.length - 1 ? "none" : "1px solid #f0f0f0" }}>
                    <Space size={6} wrap>
                      <Tag color="blue">#{index + 1}</Tag>
                      <Text strong>{board.name}</Text>
                      <Tag color={board.board_type === "concept" ? "geekblue" : "purple"}>{board.board_type === "concept" ? "概念" : "行业"}</Tag>
                      {board.return_5d != null ? <Tag>5日 {pct(board.return_5d)}</Tag> : null}
                      {board.return_20d != null ? <Tag>20日 {pct(board.return_20d)}</Tag> : null}
                      {boardActivityText(board) ? <Tag>{boardActivityText(board)}</Tag> : null}
                    </Space>
                    {board.reason ? (
                      <Paragraph style={{ margin: "4px 0", fontSize: 12 }} type="secondary">{compactReason(board.reason, 100)}</Paragraph>
                    ) : null}
                    {renderBoardRecommendations(board)}
                  </div>
                ))}
                {marketEarlySignals.slice(0, 3).map((item: string, index: number) => (
                  <Text key={`${index}-early`} type="secondary" style={{ fontSize: 12 }}>
                    <Tag color="cyan">早期信号</Tag>
                    {compactReason(item, 80)}
                  </Text>
                ))}
              </Space>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无明确轮动候选" />
            )}
          </Card>
        </Col>
        <Col xs={24} xl={8}>
          <Card
            size="small"
            title="当前选中的 ETF 配置方案（明日操作）"
            extra={selectedAllocationPlan.length ? <Text type="secondary">合计 {allocationTotalPct.toFixed(1)}%</Text> : null}
            style={{ height: "100%" }}
          >
            {selectedAllocationPlan.length ? (
              <Space orientation="vertical" size={10} style={{ width: "100%" }}>
                <div style={{ padding: 10, background: "#fafafa", border: "1px solid #f0f0f0", borderRadius: 6 }}>
                  <Space direction="vertical" size={4} style={{ width: "100%" }}>
                    <Text strong>市场情况</Text>
                    <Paragraph style={{ margin: 0, fontSize: 12 }} type="secondary">
                      {allocationExplanation.market}
                    </Paragraph>
                    <Text strong>配置逻辑</Text>
                    <Paragraph style={{ margin: 0, fontSize: 12 }} type="secondary">
                      {allocationExplanation.plan}
                    </Paragraph>
                  </Space>
                </div>
                <div>
                  <Space size={8} wrap>
                    <Text type="secondary">计划总金额</Text>
                    <InputNumber
                      min={0}
                      step={10000}
                      precision={0}
                      value={allocationAmount}
                      onChange={(value) => setAllocationAmount(value == null ? null : Number(value))}
                      formatter={(value) => `${value}`.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}
                      parser={(value) => Number(String(value || "").replace(/,/g, ""))}
                      style={{ width: 130 }}
                    />
                    {plannedInvestAmount != null ? (
                      <Text type="secondary">计划投入 {money(plannedInvestAmount)}，保留 {money((allocationAmount || 0) - plannedInvestAmount)} 现金</Text>
                    ) : null}
                  </Space>
                </div>
                {selectedAllocationPlan.map((item: any, index: number) => {
                  const op = operationPlan(item, allocationAmount);
                  return (
                    <div key={`${item.code || index}-allocation`}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                        <Space size={6} wrap>
                          {actionTag(item.action, item.action_label)}
                          <Text strong>{item.name || item.code}</Text>
                          <Text type="secondary">{item.code}</Text>
                          {item.sector ? <Tag>{item.sector}</Tag> : null}
                        </Space>
                        <Space size={6}>
                          {op.targetAmount != null ? <Text strong>{money(op.targetAmount)}</Text> : null}
                          <Text type="secondary">{item.position_pct != null ? `${item.position_pct}%` : "-"}</Text>
                        </Space>
                      </div>
                      <Progress percent={Number(item.position_pct || 0)} showInfo={false} strokeColor="#cf1322" style={{ margin: "4px 0 0 0" }} />
                      <Space direction="vertical" size={2} style={{ width: "100%", marginTop: 4 }}>
                        {item.matched_board ? (
                          <Space size={4} wrap>
                            <Tag color="volcano">{item.matched_board}</Tag>
                            {item.board_context ? <Text type="secondary" style={{ fontSize: 12 }}>{item.board_context.replace(/^热门板块「[^」]+」；?/, "")}</Text> : null}
                          </Space>
                        ) : null}
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          入场 {price(item.entry_price)} · 止盈 {price(item.target_price)} · 止损 {price(item.stop_loss_price)}
                        </Text>
                        {op.addText ? <Text style={{ fontSize: 12 }}>补仓：{op.addText}</Text> : null}
                        {op.pullbackText ? <Text style={{ fontSize: 12 }}>二次补仓：{op.pullbackText}</Text> : null}
                        {op.takeProfitText ? <Text style={{ fontSize: 12 }}>减仓：{op.takeProfitText}</Text> : null}
                        {op.stopText ? <Text style={{ fontSize: 12 }}>风控：{op.stopText}</Text> : null}
                        {op.currentPct != null ? <Text type="secondary" style={{ fontSize: 12 }}>当前持仓：约 {op.currentPct.toFixed(1)}%，市值 {money(op.currentAmount)}</Text> : null}
                        {op.maText ? <Text type="secondary" style={{ fontSize: 12 }}>均线：{op.maText}</Text> : null}
                      </Space>
                      {item.reason ? (
                        <Paragraph style={{ margin: "4px 0 0 0", fontSize: 12 }} type="secondary" ellipsis={{ rows: 2 }}>
                          布局理由：{item.reason}
                        </Paragraph>
                      ) : null}
                    </div>
                  );
                })}
              </Space>
            ) : (
              <Space orientation="vertical" size={10} style={{ width: "100%" }}>
                <div style={{ padding: 10, background: "#fafafa", border: "1px solid #f0f0f0", borderRadius: 6 }}>
                  <Space direction="vertical" size={4} style={{ width: "100%" }}>
                    <Text strong>市场情况</Text>
                    <Paragraph style={{ margin: 0, fontSize: 12 }} type="secondary">
                      {allocationExplanation.market}
                    </Paragraph>
                    <Text strong>配置逻辑</Text>
                    <Paragraph style={{ margin: 0, fontSize: 12 }} type="secondary">
                      {allocationExplanation.plan}
                    </Paragraph>
                  </Space>
                </div>
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无通过风险闸门的配置候选，明日先观察" />
              </Space>
            )}
          </Card>
        </Col>
      </Row>

      {running && task ? (
        <Card size="small" style={{ marginTop: 16 }}>
          <Space orientation="vertical" style={{ width: "100%" }}>
            <Text>{task.step || "分析中"}</Text>
            <Progress percent={Number(task.progress ?? 0)} status={task.status === "failed" ? "exception" : "active"} />
          </Space>
        </Card>
      ) : null}

      <Tabs
        style={{ marginTop: 16 }}
        items={[
          {
            key: "watchlist",
            label: `关注列表 (${watchlist.items.length})`,
            children: (
              groupedWatchItems.length ? (
                <Space orientation="vertical" size={12} style={{ width: "100%" }}>
                  {groupedWatchItems.map((group) => (
                    <Card
                      key={group.group}
                      size="small"
                      title={group.group}
                      extra={<Text type="secondary">{group.rows.length} 只</Text>}
                    >
                      <Table
                        rowKey="id"
                        dataSource={group.rows}
                        columns={watchColumns}
                        expandable={etfExpandable}
                        size="small"
                        pagination={false}
                        scroll={{ x: 1220 }}
                      />
                    </Card>
                  ))}
                </Space>
              ) : (
                <Card size="small">
                  <Empty description="尚未导入 ETF，点击右上角导入主流池" />
                </Card>
              )
            ),
          },
          {
            key: "latest",
            label: "最新分析",
            children: renderAnalysis(latest),
          },
          {
            key: "history",
            label: <span><HistoryOutlined /> 历史记录 ({history.length})</span>,
            children: (
              <Card size="small">
                <Table
                  rowKey="id"
                  dataSource={history}
                  columns={historyColumns}
                  size="small"
                  pagination={{ pageSize: 15 }}
                  locale={{ emptyText: <Empty description="暂无历史记录" /> }}
                  scroll={{ x: 800 }}
                />
              </Card>
            ),
          },
        ]}
      />

      <Modal
        title="补充资讯"
        open={addingNews}
        onOk={handleAddNews}
        confirmLoading={submitting}
        onCancel={() => setAddingNews(false)}
        destroyOnHidden
      >
        <Form form={newsForm} layout="vertical">
          <Form.Item name="title" label="标题" rules={[{ required: true, message: "请输入资讯标题" }]}>
            <Input placeholder="如 长鑫科技启动上市进程" maxLength={500} />
          </Form.Item>
          <Form.Item name="content" label="正文 / 来源备注">
            <Input.TextArea rows={3} maxLength={5000} placeholder="粘贴来源摘要、公告要点或链接备注；不要填未经核验的传闻。" />
          </Form.Item>
          <Form.Item name="publish_time" label="发布时间（可选）">
            <Input placeholder="留空则用当前时间；也可填 2026-05-22T18:00:00" />
          </Form.Item>
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item name="event_type" label="事件类型">
                <Input placeholder="ipo / policy / order" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="sentiment" label="情绪">
                <Input placeholder="positive / neutral / negative" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="source" label="来源">
                <Input placeholder="manual_verified" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="sectors" label="关联分组">
            <Input placeholder="AI / 科技主线，新能源 / 资源" />
          </Form.Item>
          <Form.Item name="keywords" label="匹配关键词">
            <Input.TextArea rows={2} placeholder="长鑫存储，长鑫科技，存储芯片，DRAM，半导体" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="添加 ETF"
        open={adding}
        onOk={handleAdd}
        confirmLoading={submitting}
        onCancel={() => { setAdding(false); addForm.resetFields(); }}
        destroyOnHidden
      >
        <Form form={addForm} layout="vertical">
          <Form.Item name="code" label="ETF 代码" rules={[{ required: true, message: "请输入 ETF 代码" }]}>
            <Input placeholder="如 159915" maxLength={10} />
          </Form.Item>
          <Form.Item name="name" label="名称（可选）"><Input placeholder="如 创业板ETF" /></Form.Item>
          <Form.Item name="sector" label="关注分组（可选）"><Input placeholder="如 宽基 / 半导体 / 红利" /></Form.Item>
          <Form.Item name="is_holding" label="是否持仓" valuePropName="checked"><Switch /></Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="cost_price" label="成本价"><InputNumber min={0.001} step={0.001} precision={3} style={{ width: "100%" }} /></Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="quantity" label="持仓份额"><InputNumber min={1} step={100} style={{ width: "100%" }} /></Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="target_price" label="止盈价"><InputNumber min={0.001} step={0.001} precision={3} style={{ width: "100%" }} /></Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="stop_loss_price" label="止损价"><InputNumber min={0.001} step={0.001} precision={3} style={{ width: "100%" }} /></Form.Item>
            </Col>
          </Row>
          <Form.Item name="note" label="备注"><Input.TextArea rows={2} maxLength={200} /></Form.Item>
        </Form>
      </Modal>

      <Modal
        title={editing ? `编辑 · ${editing.name || editing.code}` : "编辑"}
        open={Boolean(editing)}
        onOk={handleEdit}
        confirmLoading={submitting}
        onCancel={() => setEditing(null)}
        destroyOnHidden
      >
        <Form form={editForm} layout="vertical">
          <Form.Item name="name" label="名称"><Input /></Form.Item>
          <Form.Item name="sector" label="关注分组"><Input /></Form.Item>
          <Form.Item name="is_holding" label="是否持仓" valuePropName="checked"><Switch /></Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="cost_price" label="成本价"><InputNumber min={0.001} step={0.001} precision={3} style={{ width: "100%" }} /></Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="quantity" label="持仓份额"><InputNumber min={1} step={100} style={{ width: "100%" }} /></Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="target_price" label="止盈价"><InputNumber min={0.001} step={0.001} precision={3} style={{ width: "100%" }} /></Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="stop_loss_price" label="止损价"><InputNumber min={0.001} step={0.001} precision={3} style={{ width: "100%" }} /></Form.Item>
            </Col>
          </Row>
          <Form.Item name="note" label="备注"><Input.TextArea rows={2} maxLength={200} /></Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`分析详情 · ${shortTime(recordDetail?.analysis_time)}`}
        open={Boolean(recordDetail)}
        onCancel={() => setRecordDetail(null)}
        footer={null}
        width={1200}
        destroyOnHidden
      >
        {renderAnalysis(recordDetail)}
      </Modal>
    </div>
  );
}
