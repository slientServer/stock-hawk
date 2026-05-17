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
  addEtfWatch,
  backfillEtfKline,
  backfillMissingEtfKlines,
  getEtfAnalysisHistory,
  getEtfAnalysisLatest,
  getEtfAnalysisRecord,
  getEtfAnalysisTask,
  getEtfWatchlist,
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

function mergeAllocationPlans(recommendations: any[], llmRecommendations: any[]) {
  const seen = new Set<string>();
  return [...recommendations, ...llmRecommendations].filter((item) => {
    const key = item?.code || `${item?.name || ""}:${item?.sector || ""}`;
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function boardRecommendationLabel(recommendations: any[]) {
  return recommendations.some((item) => item?.is_watched) ? "关注列表 ETF：" : "全市场优选 ETF：";
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
  const [editing, setEditing] = useState<any>(null);
  const [recordDetail, setRecordDetail] = useState<any>(null);
  const [submitting, setSubmitting] = useState(false);
  const [addForm] = Form.useForm();
  const [editForm] = Form.useForm();
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

  const summary = watchlist.summary || {};
  const marketHotBoards = useMemo(() => (latest?.market_hot_boards || []) as any[], [latest]);
  const marketRotationBoards = useMemo(() => (latest?.market_rotation_boards || []) as any[], [latest]);
  const marketEarlySignals = useMemo(() => (latest?.market_early_signals || []) as string[], [latest]);
  const selectedAllocationPlan = useMemo(
    () => mergeAllocationPlans(latest?.recommendations || [], latest?.llm_recommendations || []).slice(0, 5),
    [latest],
  );
  const allocationTotalPct = selectedAllocationPlan.reduce(
    (sum: number, item: any) => sum + Number(item?.position_pct || 0),
    0,
  );
  const boardEtfRecommendations = useMemo(() => {
    const rows: any[] = [];
    const collect = (boards: any[], boardGroup: string) => {
      boards.forEach((board: any) => {
        (board?.recommended_etfs || []).forEach((etf: any) => {
          rows.push({
            ...etf,
            board_name: board?.name,
            board_group: boardGroup,
            board_change_pct: board?.change_pct,
            recommendation_source: board?.recommendation_source,
          });
        });
      });
    };
    collect(marketHotBoards, "当前热门");
    collect(marketRotationBoards, "下轮候选");
    rows.sort((a, b) => {
      if (a.is_watched !== b.is_watched) return a.is_watched ? 1 : -1;
      return Number(b.score || 0) - Number(a.score || 0);
    });
    return rows;
  }, [marketHotBoards, marketRotationBoards]);

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

  const boardRecommendationColumns: ColumnsType<any> = useMemo(
    () => [
      {
        title: "板块",
        key: "board",
        width: 170,
        render: (_: any, row: any) => (
          <Space orientation="vertical" size={2}>
            <Text strong>{row.board_name || "-"}</Text>
            <Space size={4} wrap>
              <Tag color={row.board_group === "当前热门" ? "red" : "blue"}>{row.board_group}</Tag>
              {row.board_change_pct != null ? <Tag>{pct(row.board_change_pct)}</Tag> : null}
            </Space>
          </Space>
        ),
      },
      {
        title: "ETF",
        key: "etf",
        width: 210,
        render: (_: any, row: any) => (
          <Space orientation="vertical" size={2}>
            <Text strong>{row.name || row.code}</Text>
            <Text type="secondary">{row.code}</Text>
          </Space>
        ),
      },
      {
        title: "来源",
        key: "source",
        width: 120,
        render: (_: any, row: any) =>
          row.is_watched ? <Tag color="blue">关注列表</Tag> : <Tag color="gold">全市场优选</Tag>,
      },
      {
        title: "评分/涨跌",
        key: "score",
        width: 130,
        render: (_: any, row: any) => (
          <Space orientation="vertical" size={2}>
            <Text>{row.score != null ? row.score : "-"}</Text>
            {row.change_pct != null ? <Text type={Number(row.change_pct) >= 0 ? "danger" : "success"}>{pct(row.change_pct)}</Text> : null}
          </Space>
        ),
      },
      {
        title: "理由",
        dataIndex: "match_reason",
        key: "reason",
        render: (value: string) => <Paragraph style={{ margin: 0 }} ellipsis={{ rows: 2 }}>{value || "-"}</Paragraph>,
      },
      {
        title: "操作",
        key: "action",
        width: 110,
        render: (_: any, row: any) =>
          row.is_watched ? (
            <Text type="secondary">已关注</Text>
          ) : (
            <Button size="small" icon={<PlusOutlined />} onClick={() => openAddFromRecommendation(row)}>
              加入关注
            </Button>
          ),
      },
    ],
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
            <Text type="secondary">{row.code}</Text>
            {row.sector ? <Tag>{row.sector}</Tag> : null}
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
        title: "备注",
        dataIndex: "note",
        key: "note",
        ellipsis: true,
        render: (v: string) => v || "-",
      },
      {
        title: "操作",
        key: "action",
        width: 140,
        fixed: "right" as const,
        render: (_: any, row: any) => (
          <Space size={6}>
            <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>编辑</Button>
            <Button size="small" danger icon={<DeleteOutlined />} onClick={() => handleRemove(row)} />
          </Space>
        ),
      },
    ],
    [handleRemove, openEdit],
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
            <Text type="secondary">{row.code}</Text>
            {row.sector ? <Tag>{row.sector}</Tag> : null}
            {row.is_holding ? <Tag color="blue">持仓</Tag> : null}
          </Space>
        ),
      },
      { title: "现价", dataIndex: "current_price", key: "current_price", width: 80, render: price },
      { title: "趋势", key: "trend", width: 80, render: (_: any, row: any) => trendTag(row.trend) },
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
        title: "技术/量能/资金/板块/资讯/位置",
        key: "scores",
        width: 280,
        render: (_: any, row: any) => {
          const s = row.scores || {};
          return (
            <Text type="secondary" style={{ fontSize: 12 }}>
              {s.technical ?? "-"} / {s.volume ?? "-"} / {s.fund_flow ?? "-"} / {s.sector_rotation ?? "-"} / {s.news ?? "-"} / {s.valuation ?? "-"}
            </Text>
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
        title: "操作建议",
        key: "action",
        width: 100,
        render: (_: any, row: any) => actionTag(row.action, row.action_label),
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
            技术 + 板块轮动 + 量能资金 + 资讯 + 价格位置多因子综合评分，工作日 18:30 自动分析
          </Text>
        </div>
        <Space wrap>
          <Space size={6}>
            <Text type="secondary">LLM 增强</Text>
            <Switch checked={useLlm} onChange={setUseLlm} />
          </Space>
          <Button icon={<PlusOutlined />} onClick={() => setAdding(true)}>添加 ETF</Button>
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
        <Col xs={12} lg={4}><Card size="small"><Statistic title="关注数" value={summary.total ?? 0} /></Card></Col>
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
          <Card size="small" title="当前热门板块" extra={<Text type="secondary">{shortTime(latest?.market_boards_fetched_at || latest?.analysis_time)}</Text>} style={{ height: "100%" }}>
            {marketHotBoards.length ? (
              <Space orientation="vertical" size={12} style={{ width: "100%" }}>
                {marketHotBoards.slice(0, 5).map((board: any, index: number) => (
                  <div key={`${board.name || index}-hot`} style={{ paddingBottom: index === Math.min(marketHotBoards.length, 5) - 1 ? 0 : 8, borderBottom: index === Math.min(marketHotBoards.length, 5) - 1 ? "none" : "1px solid #f0f0f0" }}>
                    <Space size={6} wrap>
                      <Tag color={index < 3 ? "red" : "default"}>#{index + 1}</Tag>
                      <Text strong>{board.name}</Text>
                      <Tag color={board.board_type === "concept" ? "geekblue" : "purple"}>{board.board_type === "concept" ? "概念" : "行业"}</Tag>
                      {board.change_pct != null ? <Tag color="red">{pct(board.change_pct)}</Tag> : null}
                      {board.return_5d != null ? <Tag>5日 {pct(board.return_5d)}</Tag> : null}
                      {board.volume_ratio != null ? <Tag>量比 {board.volume_ratio}</Tag> : null}
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
          <Card size="small" title="下面可能轮动到的板块" extra={marketRotationBoards.length ? <Tag color="blue">{marketRotationBoards.length} 个候选</Tag> : null} style={{ height: "100%" }}>
            {marketRotationBoards.length || marketEarlySignals.length ? (
              <Space orientation="vertical" size={12} style={{ width: "100%" }}>
                {marketRotationBoards.slice(0, 5).map((board: any, index: number) => (
                  <div key={`${board.name || index}-rot`} style={{ paddingBottom: index === Math.min(marketRotationBoards.length, 5) - 1 ? 0 : 8, borderBottom: index === Math.min(marketRotationBoards.length, 5) - 1 ? "none" : "1px solid #f0f0f0" }}>
                    <Space size={6} wrap>
                      <Tag color="blue">#{index + 1}</Tag>
                      <Text strong>{board.name}</Text>
                      <Tag color={board.board_type === "concept" ? "geekblue" : "purple"}>{board.board_type === "concept" ? "概念" : "行业"}</Tag>
                      {board.return_5d != null ? <Tag>5日 {pct(board.return_5d)}</Tag> : null}
                      {board.return_20d != null ? <Tag>20日 {pct(board.return_20d)}</Tag> : null}
                      {board.volume_ratio != null ? <Tag>量比 {board.volume_ratio}</Tag> : null}
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
            title="当前选中的 ETF 配置方案"
            extra={selectedAllocationPlan.length ? <Text type="secondary">合计 {allocationTotalPct.toFixed(1)}%</Text> : null}
            style={{ height: "100%" }}
          >
            {selectedAllocationPlan.length ? (
              <Space orientation="vertical" size={10} style={{ width: "100%" }}>
                {selectedAllocationPlan.map((item: any, index: number) => (
                  <div key={`${item.code || index}-allocation`}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                      <Space size={6} wrap>
                        {actionTag(item.action, item.action_label)}
                        <Text strong>{item.name || item.code}</Text>
                        <Text type="secondary">{item.code}</Text>
                        {item.sector ? <Tag>{item.sector}</Tag> : null}
                      </Space>
                      <Text strong>{item.position_pct != null ? `${item.position_pct}%` : "-"}</Text>
                    </div>
                    <Progress percent={Number(item.position_pct || 0)} showInfo={false} strokeColor="#cf1322" style={{ margin: "4px 0 0 0" }} />
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      入场 {price(item.entry_price)} · 止盈 {price(item.target_price)} · 止损 {price(item.stop_loss_price)}
                    </Text>
                  </div>
                ))}
              </Space>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无选中配置方案，最新分析未生成买入建议" />
            )}
          </Card>
        </Col>
      </Row>

      {boardEtfRecommendations.length ? (
        <Card
          size="small"
          title="板块相关 ETF 推荐"
          extra={<Text type="secondary">含关注列表与全市场优选</Text>}
          style={{ marginTop: 16 }}
        >
          <Table
            rowKey={(row: any) => `${row.board_group}-${row.board_name}-${row.code}`}
            dataSource={boardEtfRecommendations}
            columns={boardRecommendationColumns}
            size="small"
            pagination={false}
            scroll={{ x: 900 }}
          />
        </Card>
      ) : null}

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
              <Card size="small">
                <Table
                  rowKey="id"
                  dataSource={watchlist.items}
                  columns={watchColumns}
                  size="small"
                  pagination={{ pageSize: 12 }}
                  locale={{ emptyText: <Empty description="尚未添加 ETF，点击右上角添加" /> }}
                  scroll={{ x: 1100 }}
                />
              </Card>
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
