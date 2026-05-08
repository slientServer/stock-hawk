"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert, Button, Card, Col, Empty, Input, Progress, Radio, Row, Space,
  Spin, Statistic, Table, Tag, Tooltip, Typography,
} from "antd";
import {
  ApartmentOutlined, ClearOutlined, EyeOutlined, FileSearchOutlined,
  FundOutlined, RobotOutlined, SendOutlined, StockOutlined, ThunderboltOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { useRouter, useSearchParams } from "next/navigation";
import { CartesianGrid, Legend, Line, LineChart, Bar, BarChart, ResponsiveContainer, Tooltip as RechartsTooltip, XAxis, YAxis, Cell } from "recharts";
import {
  getAdvisorChainAnalysis,
  getAdvisorFundFlow,
  getAdvisorOverview,
  getAdvisorPicks,
  getAdvisorWatchlist,
  getChainDetail,
  getChainScores,
  getChainTopology,
  getChains,
  streamAdvisorStockAnalysis,
} from "@/lib/api";
import { formatConfidence, formatSignalType, formatStage, formatTrendType } from "@/lib/labels";

const { Text, Paragraph } = Typography;

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  id?: string;
  streaming?: boolean;
  status?: string;
  raw?: any;
};

function chainNameOf(chain: any) {
  return chain?.name ?? chain?.chain_name ?? chain?.chain_id ?? "";
}

function latestScoreOf(chain: any) {
  const latest = chain?.latest_score;
  if (typeof latest === "object" && latest !== null) return Number(latest.score ?? chain.score ?? 0);
  return Number(latest ?? chain?.score ?? 0);
}

function scoreColor(score: number) {
  if (score >= 80) return "#f5222d";
  if (score >= 60) return "#fa8c16";
  if (score >= 40) return "#faad14";
  return "#8c8c8c";
}

function pctText(value: any) {
  return value == null ? "-" : `${Number(value).toFixed(2)}%`;
}

function amountText(value: any) {
  const amount = Number(value ?? 0);
  if (!amount) return "-";
  if (amount >= 100000000) return `${(amount / 100000000).toFixed(1)}亿`;
  if (amount >= 10000) return `${(amount / 10000).toFixed(1)}万`;
  return amount.toFixed(0);
}

function riskTypeLabel(type?: string) {
  const labels: Record<string, string> = {
    price_risk: "价格风险",
    data_quality: "数据缺口",
    special_treatment: "ST风险",
    signal_tracking: "信号跟踪",
  };
  return labels[type || ""] || type || "跟踪";
}

function scoreChartData(scores: any[]) {
  return (scores ?? []).map((item) => ({
    date: item.score_date,
    label: item.score_date ? item.score_date.slice(5, 10) : "-",
    score: Number(item.score ?? 0),
    signal_count: item.signal_count ?? 0,
  }));
}

function stageLabel(position?: string | null) {
  const text = String(position || "").toLowerCase();
  if (text.includes("upstream") || text.includes("上")) return "上游";
  if (text.includes("midstream") || text.includes("中")) return "中游";
  if (text.includes("downstream") || text.includes("下")) return "下游";
  if (text.includes("equipment") || text.includes("设备")) return "设备";
  if (text.includes("material") || text.includes("材料")) return "材料";
  return position || "环节";
}

function stageTheme(position?: string | null) {
  const label = stageLabel(position);
  if (label === "上游" || label === "材料") return { tag: "green", bg: "#f6ffed", border: "#b7eb8f" };
  if (label === "中游") return { tag: "blue", bg: "#e6f4ff", border: "#91caff" };
  if (label === "下游") return { tag: "orange", bg: "#fff7e6", border: "#ffd591" };
  if (label === "设备") return { tag: "purple", bg: "#f9f0ff", border: "#d3adf7" };
  return { tag: "default", bg: "#fafafa", border: "#f0f0f0" };
}

function normalizeCompanies(input: any): any[] {
  if (!Array.isArray(input)) return [];
  return input
    .map((item) => ({
      code: String(item?.code ?? item?.stock_code ?? "").trim(),
      name: item?.name ?? item?.stock_name ?? item?.company_name ?? "",
    }))
    .filter((item) => item.code || item.name);
}

function signalStocks(signal: any) {
  const explicit = normalizeCompanies(signal?.target_stocks);
  if (explicit.length > 0) return explicit;
  const codes = signal?.target_codes;
  if (Array.isArray(codes)) {
    return codes.map((code: any) => ({ code: String(code), name: "" })).filter((item: any) => item.code);
  }
  if (codes && typeof codes === "object") {
    return Object.values(codes).flatMap((value: any) => (
      Array.isArray(value) ? value : [value]
    )).map((code: any) => ({ code: String(code), name: "" })).filter((item: any) => item.code);
  }
  return [];
}

export default function AdvisorPage() {
  return (
    <Suspense fallback={<Spin size="large" style={{ display: "block", margin: "100px auto" }} />}>
      <AdvisorLoader />
    </Suspense>
  );
}

function AdvisorLoader() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const selectedChain = searchParams.get("chain") || "";
  const [overview, setOverview] = useState<any>(null);
  const [picks, setPicks] = useState<any>(null);
  const [watchlist, setWatchlist] = useState<any>(null);
  const [chains, setChains] = useState<any[]>([]);
  const [analysis, setAnalysis] = useState<any>(null);
  const [chainDetail, setChainDetail] = useState<any>(null);
  const [scoreHistory, setScoreHistory] = useState<any[]>([]);
  const [topology, setTopology] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [chainLoading, setChainLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const [o, p, w, c] = await Promise.all([
      getAdvisorOverview().catch(() => null),
      getAdvisorPicks(50).catch(() => null),
      getAdvisorWatchlist(50).catch(() => null),
      getChains(100).catch(() => []),
    ]);
    setOverview(o);
    setPicks(p);
    setWatchlist(w);
    setChains(Array.isArray(c) ? c : []);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!selectedChain) {
      setAnalysis(null);
      setChainDetail(null);
      setScoreHistory([]);
      setTopology(null);
      return;
    }
    setChainLoading(true);
    Promise.all([
      getAdvisorChainAnalysis(selectedChain).catch(() => null),
      getChainDetail(selectedChain).catch(() => null),
      getChainScores(selectedChain, 60).catch(() => []),
      getChainTopology(selectedChain).catch(() => null),
    ]).then(([a, d, s, t]) => {
      setAnalysis(a);
      setChainDetail(d);
      setScoreHistory(Array.isArray(s) ? s : []);
      setTopology(t);
    }).finally(() => setChainLoading(false));
  }, [selectedChain]);

  if (loading) return <Spin size="large" style={{ display: "block", margin: "100px auto" }} />;

  return <AdvisorContent
    overview={overview}
    picks={picks}
    watchlist={watchlist}
    chains={chains}
    selectedChain={selectedChain}
    analysis={analysis}
    chainDetail={chainDetail}
    scoreHistory={scoreHistory}
    topology={topology}
    chainLoading={chainLoading}
    router={router}
  />;
}

function AdvisorContent({
  overview,
  picks,
  watchlist,
  chains,
  selectedChain,
  analysis,
  chainDetail,
  scoreHistory,
  topology,
  chainLoading,
  router,
}: any) {
  const chainFilter = selectedChain || "";
  const filteredPicks = useMemo(() => {
    const items = picks?.items ?? [];
    return chainFilter ? items.filter((item: any) => (item.chain_names ?? []).includes(chainFilter)) : items;
  }, [picks, chainFilter]);

  const filteredAlerts = useMemo(() => {
    const alerts = watchlist?.alerts ?? [];
    if (!chainFilter) return alerts;
    const pickCodes = new Set(filteredPicks.map((item: any) => item.code));
    return alerts.filter((item: any) => pickCodes.has(item.code));
  }, [watchlist, chainFilter, filteredPicks]);

  const pickColumns = useMemo(() => [
    {
      title: "标的",
      key: "stock",
      width: 160,
      render: (_: any, row: any) => (
        <a onClick={() => router.push(`/stock/${row.code}`)}>
          <Text strong>{row.name}</Text><br />
          <Text type="secondary">{row.code}</Text>
        </a>
      ),
    },
    {
      title: "评分",
      dataIndex: "score",
      key: "score",
      width: 140,
      render: (v: number) => <Progress percent={Math.round(v)} size="small" strokeColor={scoreColor(Number(v || 0))} />,
    },
    { title: "层级", dataIndex: "tier", key: "tier", width: 100, render: (v: string) => <Tag color={v === "核心候选" ? "red" : v === "卫星候选" ? "orange" : "blue"}>{v}</Tag> },
    { title: "产业链", dataIndex: "chain_names", key: "chain_names", width: 220, render: (v: string[]) => (v ?? []).map((x) => <Tag key={x}>{x}</Tag>) },
    { title: "信号", dataIndex: "signal_count", key: "signal_count", width: 70 },
    { title: "近5日", key: "ret5", width: 90, render: (_: any, row: any) => row.metrics?.return_5d != null ? `${row.metrics.return_5d}%` : "-" },
    {
      title: "选股逻辑",
      dataIndex: "logic",
      key: "logic",
      width: 520,
      render: (value: string, row: any) => (
        <Space orientation="vertical" size={4} style={{ width: "100%" }}>
          <Paragraph style={{ marginBottom: 0, lineHeight: 1.6 }}>{value || "-"}</Paragraph>
          {(row.risk_flags ?? []).length > 0 && (
            <Space wrap size={[4, 4]}>
              {row.risk_flags.map((flag: string) => <Tag key={flag} color="volcano">{flag}</Tag>)}
            </Space>
          )}
        </Space>
      ),
    },
  ], [router]);

  const watchColumns = useMemo(() => [
    {
      title: "标的",
      key: "stock",
      width: 170,
      render: (_: any, row: any) => (
        <Space orientation="vertical" size={3}>
          <a onClick={() => router.push(`/stock/${row.code}`)}>{row.name} {row.code}</a>
          <Space size={4} wrap>
            <Tag color={row.level === "warning" ? "orange" : "blue"} style={{ marginInlineEnd: 0 }}>{row.level}</Tag>
            <Tag style={{ marginInlineEnd: 0 }}>{riskTypeLabel(row.risk_type)}</Tag>
            <Text type="secondary" style={{ fontSize: 11 }}>评分 {row.score ?? "-"}</Text>
          </Space>
        </Space>
      ),
    },
    {
      title: "风险原因",
      dataIndex: "reasons",
      key: "reasons",
      width: 260,
      render: (value: string[], row: any) => (
        <Space orientation="vertical" size={4}>
          <Paragraph style={{ marginBottom: 0, fontSize: 12, lineHeight: 1.5 }}>
            {(value ?? []).join("；") || "-"}
          </Paragraph>
          {(row.data_gaps ?? []).length > 0 && (
            <Space wrap size={[4, 4]}>
              {row.data_gaps.map((gap: string) => <Tag key={gap} color="volcano" style={{ marginInlineEnd: 0 }}>{gap}</Tag>)}
            </Space>
          )}
        </Space>
      ),
    },
    {
      title: "行情",
      key: "metrics",
      width: 210,
      render: (_: any, row: any) => (
        <Space orientation="vertical" size={2}>
          <Text style={{ fontSize: 12 }}>近5日 {pctText(row.metrics?.return_5d)} / 近20日 {pctText(row.metrics?.return_20d)}</Text>
          <Text style={{ fontSize: 12 }}>60日回撤 {pctText(row.metrics?.drawdown_60d)}</Text>
          <Text type="secondary" style={{ fontSize: 11 }}>
            20日均额 {amountText(row.metrics?.avg_amount_20d)} · {row.metrics?.latest_trade_date || "-"}
          </Text>
        </Space>
      ),
    },
    {
      title: "信号/产业链",
      key: "signals",
      width: 300,
      render: (_: any, row: any) => (
        <Space orientation="vertical" size={4} style={{ width: "100%" }}>
          <Space wrap size={[4, 4]}>
            {(row.chain_names ?? []).slice(0, 3).map((name: string) => <Tag key={name} style={{ marginInlineEnd: 0 }}>{name}</Tag>)}
            <Text type="secondary" style={{ fontSize: 11 }}>信号 {row.signal_count ?? 0}</Text>
          </Space>
          <Paragraph ellipsis={{ rows: 2 }} style={{ marginBottom: 0, fontSize: 12, lineHeight: 1.5 }}>
            {row.latest_signal || "暂无最新信号"}
          </Paragraph>
        </Space>
      ),
    },
    {
      title: "财报/建议",
      key: "financial",
      width: 260,
      render: (_: any, row: any) => (
        <Space orientation="vertical" size={3}>
          <Text style={{ fontSize: 12 }}>
            {row.financial?.report_date || "无财报"} · 净利 {pctText(row.financial?.net_profit_yoy)}
          </Text>
          <Text type="secondary" style={{ fontSize: 11 }}>
            营收 {pctText(row.financial?.revenue_yoy)} · PE {row.financial?.pe_ratio ?? "-"}
          </Text>
          <Paragraph ellipsis={{ rows: 2 }} style={{ marginBottom: 0, fontSize: 12, lineHeight: 1.5 }}>
            {row.action_suggestion || "-"}
          </Paragraph>
        </Space>
      ),
    },
  ], [router]);

  const selectChain = (name?: string) => {
    router.replace(name ? `/advisor?chain=${encodeURIComponent(name)}` : "/advisor", { scroll: false });
  };

  const pageContext = useMemo(() => ({
    selected_chain: selectedChain || null,
    overview_counts: overview?.counts ?? {},
    visible_chain_count: chains.length,
    visible_chains: chains.slice(0, 20).map((chain: any) => ({
      name: chainNameOf(chain),
      score: latestScoreOf(chain),
      score_delta: chain.score_delta ?? null,
      signal_count: chain.signal_count ?? 0,
      score_date: chain.score_date ?? null,
    })),
    chain_analysis: analysis,
    chain_detail: chainDetail ? {
      chain_name: chainDetail.chain_name ?? chainDetail.name ?? selectedChain,
      latest_score: chainDetail.latest_score,
      active_signal_count: chainDetail.active_signal_count,
      segment_count: chainDetail.segments?.length ?? 0,
      company_count: chainDetail.companies?.length ?? chainDetail.company_count ?? 0,
      signals: (chainDetail.signals ?? []).slice(0, 12),
    } : null,
    score_history: scoreHistory.slice(-20),
    topology: topology ? {
      chain: topology.chain,
      segments: (topology.segments ?? []).map((segment: any) => ({
        position: segment.position,
        segment_name: segment.segment_name ?? segment.name,
        company_count: segment.companies?.length ?? 0,
        companies: (segment.companies ?? []).slice(0, 10),
      })),
    } : null,
    visible_picks: filteredPicks.slice(0, 12),
    visible_watch_alerts: filteredAlerts.slice(0, 12),
  }), [
    selectedChain, overview, chains, analysis, chainDetail, scoreHistory,
    topology, filteredPicks, filteredAlerts,
  ]);

  return (
    <div style={{ width: "100%" }}>
      <Row gutter={[12, 12]} align="top">
        <Col xs={24} xl={17} xxl={18}>
          <AnalysisSection
            chains={chains}
            selectedChain={selectedChain}
            analysis={analysis}
            chainDetail={chainDetail}
            scoreHistory={scoreHistory}
            topology={topology}
            loading={chainLoading}
            onSelect={selectChain}
            router={router}
          />
          <PicksSection
            items={filteredPicks}
            columns={pickColumns}
            chainFilter={chainFilter}
            methodology={picks?.methodology}
            router={router}
          />
          <WatchSection alerts={filteredAlerts} columns={watchColumns} chainFilter={chainFilter} />
        </Col>
        <Col xs={24} xl={7} xxl={6}>
          <div style={{ position: "sticky", top: 72 }}>
            <StockChatSection selectedChain={selectedChain} pageContext={pageContext} />
          </div>
        </Col>
      </Row>
    </div>
  );
}

function StockChatSection({ selectedChain, pageContext }: { selectedChain?: string; pageContext: any }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const listRef = useRef<HTMLDivElement | null>(null);
  const storageKey = useMemo(() => `stock-hawk:advisor-chat:${selectedChain || "global"}`, [selectedChain]);

  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(storageKey);
      setMessages(saved ? JSON.parse(saved) : []);
    } catch {
      setMessages([]);
    }
  }, [storageKey]);

  useEffect(() => {
    try {
      window.localStorage.setItem(storageKey, JSON.stringify(messages.slice(-40)));
    } catch {
      // Local history is best effort only.
    }
  }, [messages, storageKey]);

  useEffect(() => {
    const node = listRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages, sending]);

  const send = async () => {
    const text = input.trim();
    if (!text || sending) return;
    const userMessage: ChatMessage = { role: "user", content: text, id: `${Date.now()}-user` };
    const assistantId = `${Date.now()}-assistant`;
    const requestHistory = messages.map((item) => ({ role: item.role, content: item.content }));
    setMessages((prev) => [
      ...prev,
      userMessage,
      { role: "assistant", content: "", id: assistantId, streaming: true },
    ]);
    setInput("");
    setSending(true);
    try {
      await streamAdvisorStockAnalysis(
        {
          message: text,
          history: requestHistory,
          filters: selectedChain ? { chain_name: selectedChain } : {},
          limit: 10,
          page_context: pageContext,
        },
        {
          onStatus: (payload) => {
            const statusText = payload?.message ? String(payload.message) : "";
            if (!statusText) return;
            setMessages((prev) => prev.map((item) => (
              item.id === assistantId ? { ...item, status: statusText } : item
            )));
          },
          onMeta: (response) => {
            const payload = response?.result ?? {};
            setMessages((prev) => prev.map((item) => (
              item.id === assistantId ? { ...item, raw: payload } : item
            )));
          },
          onDelta: (chunk) => {
            setMessages((prev) => prev.map((item) => (
              item.id === assistantId ? { ...item, content: `${item.content}${chunk}` } : item
            )));
          },
          onDone: (response) => {
            const payload = response?.result ?? {};
            setMessages((prev) => prev.map((item) => (
              item.id === assistantId
                ? {
                  ...item,
                  content: payload.answer || item.content || response?.error_message || "没有返回分析结果",
                  raw: payload,
                  status: undefined,
                  streaming: false,
                }
                : item
            )));
          },
          onError: (message) => {
            setMessages((prev) => prev.map((item) => (
              item.id === assistantId
                ? { ...item, content: `请求失败：${message}`, status: undefined, streaming: false }
                : item
            )));
          },
        },
      );
    } catch (e: any) {
      setMessages((prev) => prev.map((item) => (
        item.id === assistantId
          ? { ...item, content: `请求失败：${e?.message || "unknown error"}`, status: undefined, streaming: false }
          : item
      )));
    } finally {
      setSending(false);
    }
  };

  return (
    <Card
      title={<Space><RobotOutlined />投研助手</Space>}
      extra={
        <Space size={8}>
          <Text type="secondary">{selectedChain || "整体"}</Text>
          {messages.length > 0 && (
            <Tooltip title="清空历史">
              <Button size="small" icon={<ClearOutlined />} onClick={() => setMessages([])} />
            </Tooltip>
          )}
        </Space>
      }
      styles={{ body: { padding: 0 } }}
    >
      <div style={{ height: "calc(100vh - 130px)", maxHeight: "calc(100vh - 130px)", display: "flex", flexDirection: "column" }}>
        <div ref={listRef} style={{ flex: 1, overflowY: "auto", padding: 16 }}>
          {messages.length === 0 ? (
            <Empty description="直接追问当前页面数据" style={{ marginTop: 80 }} />
          ) : (
            <Space orientation="vertical" size={12} style={{ width: "100%" }}>
              {messages.map((item, index) => (
                <ChatBubble item={item} index={index} key={item.id ?? `${item.role}-${index}`} />
              ))}
            </Space>
          )}
        </div>
        <div style={{ borderTop: "1px solid #f0f0f0", padding: 12, background: "#fff" }}>
          {messages.length === 0 && (
            <Space wrap size={[6, 6]} style={{ marginBottom: 10 }}>
              {["筛低风险标的", "解释候选股逻辑", "比较核心候选"].map((item) => (
                <Button key={item} size="small" onClick={() => setInput(item)}>{item}</Button>
              ))}
            </Space>
          )}
          <div style={{ border: "1px solid #d9d9d9", borderRadius: 8, padding: "6px 8px" }}>
            <Input.TextArea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onPressEnter={(e) => {
                if (!e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              autoSize={{ minRows: 2, maxRows: 5 }}
              maxLength={12000}
              variant="borderless"
              placeholder={selectedChain ? `围绕 ${selectedChain} 提问` : "围绕当前整体投研视图提问"}
            />
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 4 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>{input.length}/12000</Text>
              <Button
                type="primary"
                shape="circle"
                icon={<SendOutlined />}
                loading={sending}
                disabled={!input.trim()}
                onClick={send}
              />
            </div>
          </div>
        </div>
      </div>
    </Card>
  );
}

function ChatBubble({ item, index }: { item: ChatMessage; index: number }) {
  const pickColumns = [
    {
      title: "标的",
      key: "stock",
      render: (_: any, row: any) => (
        <span>{row.name} <Text type="secondary">{row.code}</Text></span>
      ),
    },
    { title: "评分", dataIndex: "score", key: "score", width: 90 },
    { title: "层级", dataIndex: "tier", key: "tier", width: 100 },
    {
      title: "近5日",
      key: "ret5",
      width: 90,
      render: (_: any, row: any) => row.metrics?.return_5d != null ? `${row.metrics.return_5d}%` : "-",
    },
  ];
  const isUser = item.role === "user";

  return (
    <div
      key={`${item.role}-${index}`}
      style={{ display: "flex", justifyContent: isUser ? "flex-end" : "flex-start" }}
    >
      <div
        style={{
          maxWidth: isUser ? "88%" : "96%",
          border: "1px solid #f0f0f0",
          background: isUser ? "#e6f4ff" : "#fafafa",
          borderRadius: 8,
          padding: 12,
        }}
      >
        <Space style={{ marginBottom: 6 }}>
          {isUser ? <UserOutlined /> : <RobotOutlined />}
          <Text strong>{isUser ? "你" : "助手"}</Text>
          {item.raw?.confidence && <Tag>{item.raw.confidence}</Tag>}
          {item.streaming && <Tag color="processing">生成中</Tag>}
        </Space>
        <Paragraph style={{ whiteSpace: "pre-line", marginBottom: 0 }}>
          {item.content || (item.streaming ? item.status || " " : "")}
        </Paragraph>
        {(item.raw?.data_gaps ?? []).length > 0 && (
          <Alert
            style={{ marginTop: 10 }}
            type="info"
            showIcon
            title="数据限制"
            description={item.raw.data_gaps.join("；")}
          />
        )}
        {(item.raw?.picks ?? []).length > 0 && (
          <Table
            style={{ marginTop: 10 }}
            rowKey="code"
            size="small"
            pagination={false}
            scroll={{ x: 420 }}
            dataSource={item.raw.picks.slice(0, 5)}
            columns={pickColumns}
          />
        )}
        {(item.raw?.follow_up_questions ?? []).length > 0 && (
          <Space wrap size={[4, 4]} style={{ marginTop: 10 }}>
            {item.raw.follow_up_questions.map((question: string) => <Tag key={question}>{question}</Tag>)}
          </Space>
        )}
      </div>
    </div>
  );
}

function PicksSection({
  items,
  columns,
  chainFilter,
  methodology,
  router,
}: { items: any[]; columns: any[]; chainFilter?: string; methodology?: string; router: any }) {
  const tierCounts = items.reduce((acc: Record<string, number>, item: any) => {
    const tier = item.tier || "未分层";
    acc[tier] = (acc[tier] || 0) + 1;
    return acc;
  }, {});

  return (
    <Card
      title={<Space size={4}><StockOutlined /><span style={{ fontSize: 13 }}>候选股</span></Space>}
      style={{ marginTop: 10, borderRadius: 6 }}
      styles={{ body: { padding: 12 } }}
      extra={
        chainFilter ? (
          <Space size={4}>
            <Text type="secondary" style={{ fontSize: 12 }}>已按 {chainFilter} 过滤</Text>
            <a onClick={() => router.push("/advisor")} style={{ fontSize: 12 }}>全部</a>
          </Space>
        ) : <Text type="secondary" style={{ fontSize: 11 }}>{methodology}</Text>
      }
    >
      {items.length > 0 && (
        <Space wrap size={[6, 6]} style={{ marginBottom: 12 }}>
          {Object.entries(tierCounts).map(([tier, count]) => (
            <Tag key={tier} color={tier === "核心候选" ? "red" : tier === "卫星候选" ? "orange" : "blue"}>
              {tier} {count}
            </Tag>
          ))}
        </Space>
      )}
      {items.length === 0 ? (
        <Empty description="暂无候选股，请先采集行情/信号数据" />
      ) : (
        <Table
          rowKey="code"
          dataSource={items}
          columns={columns}
          pagination={{ pageSize: 8 }}
          size="small"
          scroll={{ x: 1300 }}
        />
      )}
    </Card>
  );
}

function AnalysisSection({
  chains,
  selectedChain,
  analysis,
  chainDetail,
  scoreHistory,
  topology,
  loading,
  onSelect,
  router,
}: any) {
  const chartData = scoreChartData(scoreHistory);
  const selectedSummary = chains.find((chain: any) => chainNameOf(chain) === selectedChain);
  const score = latestScoreOf(chainDetail ?? selectedSummary);
  const signals = chainDetail?.signals ?? analysis?.key_signals ?? [];
  const segments = topology?.segments ?? chainDetail?.segments ?? [];
  const companies = topology?.companies ?? chainDetail?.companies ?? [];

  return (
    <Space orientation="vertical" size={10} style={{ width: "100%" }}>
      <ChainButtons chains={chains} selectedChain={selectedChain} onSelect={onSelect} />
      {loading ? (
        <Card><Spin /></Card>
      ) : !selectedChain ? (
        <>
          <OverallChains chains={chains} router={router} />
          <FundFlowSection selectedChain="" />
        </>
      ) : (
        <Space orientation="vertical" size={10} style={{ width: "100%" }}>
          <Row gutter={[8, 8]}>
            <Col xs={24} md={8}><MetricCard title="当前评分" value={Number(score || 0).toFixed(0)} color={scoreColor(score)} suffix={chainDetail?.latest_score?.score_date ?? selectedSummary?.score_date ?? ""} /></Col>
            <Col xs={24} md={8}><MetricCard title="图谱覆盖" value={`${segments.length}/${companies.length || chainDetail?.company_count || 0}`} suffix="环节/公司" /></Col>
            <Col xs={24} md={8}><MetricCard title="活跃信号" value={chainDetail?.active_signal_count ?? signals.length} suffix={`置信度 ${formatConfidence(analysis?.confidence)}`} /></Col>
          </Row>
          <ChainSummary analysis={analysis} />
          <FundFlowSection selectedChain={selectedChain} />
          <TransmissionPath analysis={analysis} segments={segments} allCompanies={companies} router={router} />
          <ScoreTrend data={chartData} />
          <KeySignals signals={signals} chainName={selectedChain} router={router} />
        </Space>
      )}
    </Space>
  );
}

function ChainButtons({ chains, selectedChain, onSelect }: any) {
  return (
    <div style={{ background: "#fff", border: "1px solid #f0f0f0", borderRadius: 6, padding: "10px 12px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center", marginBottom: 8 }}>
        <Space size={4}>
          <FileSearchOutlined />
          <Text strong style={{ fontSize: 13 }}>产业链分析</Text>
        </Space>
        <Text type="secondary" style={{ fontSize: 12 }}>{selectedChain || "整体"}</Text>
      </div>
      <Space wrap size={[6, 6]}>
        <Button size="small" type={!selectedChain ? "primary" : "default"} onClick={() => onSelect()}>
          整体
        </Button>
        {chains.map((chain: any) => {
          const name = chainNameOf(chain);
          if (!name) return null;
          const score = latestScoreOf(chain);
          const selected = selectedChain === name;
          return (
            <Button
              key={name}
              size="small"
              type={selected ? "primary" : "default"}
              onClick={() => onSelect(name)}
              style={{
                borderColor: selected ? scoreColor(score) : undefined,
                background: selected ? scoreColor(score) : undefined,
              }}
            >
              {name} <Tag color={selected ? "default" : score >= 60 ? "orange" : "blue"} style={{ marginInlineEnd: 0, marginInlineStart: 4, fontSize: 11 }}>{Number(score || 0).toFixed(0)}</Tag>
            </Button>
          );
        })}
      </Space>
    </div>
  );
}

function FundFlowSection({ selectedChain }: { selectedChain: string }) {
  const [period, setPeriod] = useState(5);
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    getAdvisorFundFlow({ chain_name: selectedChain || undefined, period })
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [selectedChain, period]);

  const items = data?.items ?? [];
  const north = data?.north_flow_summary;
  const dataGaps = data?.data_gaps;

  const chartData = items.map((item: any) => ({
    name: item.name?.length > 6 ? item.name.slice(0, 6) + "…" : item.name,
    fullName: item.name,
    main_net: item.main_net_total ? +(item.main_net_total / 1e8).toFixed(2) : 0,
    retail_net: item.retail_net_total ? +(item.retail_net_total / 1e8).toFixed(2) : 0,
  }));

  // 逐日趋势数据：合并所有分组的 trend 到同一时间轴
  const trendData = useMemo(() => {
    if (!items.length) return [];
    // 取有数据的 items
    const withTrend = items.filter((item: any) => item.trend?.length > 0);
    if (!withTrend.length) return [];
    // 收集所有日期
    const dateSet = new Set<string>();
    withTrend.forEach((item: any) => item.trend.forEach((t: any) => dateSet.add(t.date)));
    const dates = Array.from(dateSet).sort();
    // 按日期构建行：每行一天，每个产业链/环节一列
    return dates.map((d) => {
      const row: any = { date: d.slice(5) }; // MM-DD 格式
      withTrend.forEach((item: any) => {
        const point = item.trend.find((t: any) => t.date === d);
        const key = item.name?.length > 6 ? item.name.slice(0, 6) + "…" : item.name;
        row[key] = point ? +(point.main_net / 1e8).toFixed(2) : 0;
      });
      return row;
    });
  }, [items]);

  const trendKeys = useMemo(() => {
    const withTrend = items.filter((item: any) => item.trend?.length > 0);
    return withTrend.map((item: any) => item.name?.length > 6 ? item.name.slice(0, 6) + "…" : item.name);
  }, [items]);

  const COLORS = ["#cf1322", "#1890ff", "#fa8c16", "#52c41a", "#722ed1", "#eb2f96", "#13c2c2"];

  const [highlightKey, setHighlightKey] = useState<string | null>(null);
  const toggleHighlight = (key: string) => {
    setHighlightKey((prev) => prev === key ? null : key);
  };

  return (
    <Card
      title={<Space size={4}><FundOutlined /><span style={{ fontSize: 13 }}>资金流向</span></Space>}
      style={{ marginTop: 10, borderRadius: 6 }}
      styles={{ body: { padding: 12 } }}
      extra={
        <Radio.Group size="small" value={period} onChange={(e) => setPeriod(e.target.value)}>
          <Radio.Button value={1}>1日</Radio.Button>
          <Radio.Button value={3}>3日</Radio.Button>
          <Radio.Button value={5}>5日</Radio.Button>
          <Radio.Button value={15}>15日</Radio.Button>
          <Radio.Button value={30}>30日</Radio.Button>
        </Radio.Group>
      }
    >
      {loading ? (
        <Spin size="small" />
      ) : dataGaps?.length ? (
        <Alert type="info" showIcon title={dataGaps[0]} />
      ) : items.length === 0 ? (
        <Empty description="暂无资金流数据" />
      ) : (
        <Space orientation="vertical" size={12} style={{ width: "100%" }}>
          {/* 北向资金概况 */}
          {north?.north_net_period != null && (
            <Row gutter={16}>
              <Col>
                <Statistic
                  title={`北向近${period}日净流入`}
                  value={(north.north_net_period / 1e8).toFixed(2)}
                  suffix="亿"
                  styles={{ content: { fontSize: 16, color: north.north_net_period >= 0 ? "#cf1322" : "#3f8600" } }}
                />
              </Col>
              {north.north_net_latest != null && (
                <Col>
                  <Statistic
                    title="最新日净流入"
                    value={(north.north_net_latest / 1e8).toFixed(2)}
                    suffix="亿"
                    styles={{ content: { fontSize: 16, color: north.north_net_latest >= 0 ? "#cf1322" : "#3f8600" } }}
                  />
                </Col>
              )}
              {north.latest_date && (
                <Col>
                  <Text type="secondary" style={{ fontSize: 11, lineHeight: "52px" }}>{north.latest_date}</Text>
                </Col>
              )}
            </Row>
          )}

          {/* 柱状图 - 各产业链/环节主力净流入对比 */}
          {chartData.length > 0 && (
            <div style={{ height: 200 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} unit="亿" />
                  <RechartsTooltip
                    formatter={(value: any, name: any) => [`${value} 亿`, name === "main_net" ? "主力净流入" : "散户净流入"]}
                    labelFormatter={(label: any, payload: any) => payload?.[0]?.payload?.fullName || label}
                  />
                  <Bar dataKey="main_net" name="主力净流入" radius={[3, 3, 0, 0]}>
                    {chartData.map((entry: any, index: number) => (
                      <Cell key={index} fill={entry.main_net >= 0 ? "#cf1322" : "#3f8600"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* 逐日趋势折线图 */}
          {trendData.length > 1 && (
            <>
              <Text strong style={{ fontSize: 12 }}>逐日主力净流入趋势（亿元）</Text>
              <div style={{ height: 200 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={trendData} margin={{ top: 5, right: 10, left: 10, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} unit="亿" />
                    <RechartsTooltip formatter={(value: any) => [`${value} 亿`]} />
                    <Legend
                      wrapperStyle={{ fontSize: 11, cursor: "pointer" }}
                      onClick={(e: any) => { if (e?.dataKey) toggleHighlight(e.dataKey); }}
                      formatter={(value: any) => (
                        <span style={{
                          color: highlightKey && highlightKey !== value ? "#ccc" : undefined,
                          fontWeight: highlightKey === value ? 600 : undefined,
                        }}>{value}</span>
                      )}
                    />
                    {trendKeys.map((key: string, i: number) => (
                      <Line
                        key={key}
                        type="monotone"
                        dataKey={key}
                        stroke={COLORS[i % COLORS.length]}
                        strokeWidth={highlightKey === key ? 3 : 2}
                        strokeOpacity={highlightKey && highlightKey !== key ? 0.15 : 1}
                        dot={{ r: highlightKey === key ? 4 : 3 }}
                      />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </>
          )}

          {/* Top 流入/流出个股 */}
          <Row gutter={16}>
            <Col xs={24} sm={12}>
              <Text strong style={{ fontSize: 12 }}>主力流入 Top</Text>
              <div style={{ marginTop: 4 }}>
                {items.flatMap((item: any) => item.top_inflow ?? []).sort((a: any, b: any) => b.main_net - a.main_net).slice(0, 5).map((s: any, idx: number) => (
                  <Tag key={`${s.code}-in-${idx}`} color="red" style={{ marginBottom: 4 }}>
                    {s.name !== s.code ? s.name : s.code}({s.code}) +{(s.main_net / 1e8).toFixed(2)}亿
                  </Tag>
                ))}
                {items.flatMap((item: any) => item.top_inflow ?? []).length === 0 && <Text type="secondary" style={{ fontSize: 11 }}>暂无</Text>}
              </div>
            </Col>
            <Col xs={24} sm={12}>
              <Text strong style={{ fontSize: 12 }}>主力流出 Top</Text>
              <div style={{ marginTop: 4 }}>
                {items.flatMap((item: any) => item.top_outflow ?? []).sort((a: any, b: any) => a.main_net - b.main_net).slice(0, 5).map((s: any, idx: number) => (
                  <Tag key={`${s.code}-out-${idx}`} color="green" style={{ marginBottom: 4 }}>
                    {s.name !== s.code ? s.name : s.code}({s.code}) {(s.main_net / 1e8).toFixed(2)}亿
                  </Tag>
                ))}
                {items.flatMap((item: any) => item.top_outflow ?? []).length === 0 && <Text type="secondary" style={{ fontSize: 11 }}>暂无</Text>}
              </div>
            </Col>
          </Row>
        </Space>
      )}
    </Card>
  );
}

function OverallChains({ chains, router }: any) {
  if (chains.length === 0) return <Empty description="暂无产业链数据" />;
  return (
    <Row gutter={[8, 8]}>
      {chains.slice(0, 9).map((chain: any) => {
        const name = chainNameOf(chain);
        const score = latestScoreOf(chain);
        return (
          <Col xs={24} sm={12} xl={8} xxl={6} key={name}>
            <Card
              hoverable
              onClick={() => router.replace(`/advisor?chain=${encodeURIComponent(name)}`)}
              style={{ borderRadius: 6 }}
              styles={{ body: { padding: "10px 12px" } }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                <Text strong style={{ fontSize: 13 }}>{name}</Text>
                <Tag color={score >= 60 ? "orange" : "blue"} style={{ marginInlineEnd: 0 }}>{Number(score || 0).toFixed(0)}</Tag>
              </div>
              <Progress percent={Math.round(score)} strokeColor={scoreColor(score)} size="small" showInfo={false} />
              <Text type="secondary" style={{ fontSize: 11 }}>
                信号 {chain.signal_count ?? 0}
                {chain.score_delta != null && ` · ${Number(chain.score_delta) > 0 ? "+" : ""}${Number(chain.score_delta).toFixed(0)}`}
              </Text>
            </Card>
          </Col>
        );
      })}
    </Row>
  );
}

function MetricCard({ title, value, suffix, color }: { title: string; value: any; suffix?: string; color?: string }) {
  return (
    <Card style={{ borderRadius: 6, borderLeft: `3px solid ${color || "#1677ff"}` }} styles={{ body: { padding: "10px 14px" } }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <Text type="secondary" style={{ fontSize: 12 }}>{title}</Text>
        <Text type="secondary" style={{ fontSize: 11 }}>{suffix || ""}</Text>
      </div>
      <Text strong style={{ color, fontSize: 20, lineHeight: 1.4 }}>{value}</Text>
    </Card>
  );
}

function ChainSummary({ analysis }: { analysis: any }) {
  if (!analysis) return <Alert type="info" showIcon title="暂无产业链归因数据" />;
  return (
    <Card title={<span style={{ fontSize: 13 }}>归因摘要</span>} style={{ borderRadius: 6 }} styles={{ body: { padding: 12 } }}>
      <Paragraph style={{ marginBottom: 8, fontSize: 13 }}>{analysis.summary}</Paragraph>
      <Space wrap size={[4, 4]}>
        <Tag color="blue">趋势: {formatTrendType(analysis.trend_type)}</Tag>
        <Tag color="purple">阶段: {formatStage(analysis.current_stage)}</Tag>
        <Tag>置信度: {formatConfidence(analysis.confidence)}</Tag>
      </Space>
      {(analysis.data_gaps ?? []).length > 0 && (
        <Alert style={{ marginTop: 8 }} type="info" showIcon description={analysis.data_gaps.join("；")} />
      )}
    </Card>
  );
}

function ScoreTrend({ data }: { data: any[] }) {
  if (data.length === 0) return <Alert type="info" showIcon title="暂无评分趋势" />;
  return (
    <Card title={<span style={{ fontSize: 13 }}>评分趋势</span>} style={{ borderRadius: 6 }} styles={{ body: { padding: "8px 12px" } }}>
      <div style={{ height: 180 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 12, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="label" minTickGap={24} tick={{ fontSize: 11 }} />
            <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} width={32} />
            <RechartsTooltip labelFormatter={(_, items) => items?.[0]?.payload?.date ?? "-"} />
            <Line type="monotone" dataKey="score" stroke="#1677ff" dot={false} strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

function TransmissionPath({ analysis, segments, allCompanies, router }: { analysis: any; segments: any[]; allCompanies?: any[]; router: any }) {
  const path = (analysis?.transmission_path ?? []).length > 0
    ? analysis.transmission_path
    : (segments ?? []).map((segment: any) => ({
      position: segment.position,
      segment: segment.segment_name ?? segment.name,
      companies: segment.companies ?? [],
      company_count: segment.companies?.length ?? 0,
    }));

  if (path.length === 0) return <Alert type="info" showIcon title="暂无产业链传导路径" />;

  // If all segments have empty companies but we have top-level companies, distribute them
  const allEmpty = path.every((item: any) => normalizeCompanies(item.companies).length === 0);
  const fallbackCompanies = normalizeCompanies(allCompanies);

  return (
    <Card
      title={<Space size={4}><ApartmentOutlined /><span style={{ fontSize: 13 }}>传导路径</span></Space>}
      style={{ borderRadius: 6 }}
      styles={{ body: { padding: 12 } }}
    >
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 8 }}>
        {path.map((item: any, index: number) => {
          const companies = normalizeCompanies(item.companies);
          const theme = stageTheme(item.position);
          const segment = item.segment ?? item.segment_name ?? item.name ?? "-";
          return (
            <div
              key={`${item.position}-${segment}-${index}`}
              style={{
                background: theme.bg,
                border: `1px solid ${theme.border}`,
                borderRadius: 6,
                padding: "8px 10px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 6 }}>
                <Tag color={theme.tag} style={{ marginInlineEnd: 0, fontSize: 11 }}>{stageLabel(item.position)}</Tag>
                <Text strong style={{ fontSize: 12 }}>{segment}</Text>
                <Text type="secondary" style={{ fontSize: 11, marginLeft: "auto" }}>{companies.length || item.company_count || 0}家</Text>
              </div>
              {companies.length === 0 ? (
                <Text type="secondary" style={{ fontSize: 11 }}>暂无公司数据</Text>
              ) : (
                <Space wrap size={[3, 4]}>
                  {companies.map((company) => (
                    <Tag
                      key={`${segment}-${company.code || company.name}`}
                      style={{ cursor: company.code ? "pointer" : "default", marginInlineEnd: 0, fontSize: 11 }}
                      onClick={() => company.code && router.push(`/stock/${company.code}`)}
                    >
                      {company.name || company.code}
                    </Tag>
                  ))}
                </Space>
              )}
            </div>
          );
        })}
      </div>
      {allEmpty && fallbackCompanies.length > 0 && (
        <div style={{ marginTop: 8, padding: "6px 10px", background: "#fafafa", borderRadius: 4 }}>
          <Text type="secondary" style={{ fontSize: 11 }}>图谱公司（未分配至环节）：</Text>
          <Space wrap size={[3, 4]} style={{ marginTop: 4 }}>
            {fallbackCompanies.slice(0, 20).map((company) => (
              <Tag
                key={company.code || company.name}
                style={{ cursor: company.code ? "pointer" : "default", marginInlineEnd: 0, fontSize: 11 }}
                onClick={() => company.code && router.push(`/stock/${company.code}`)}
              >
                {company.name || company.code}
              </Tag>
            ))}
            {fallbackCompanies.length > 20 && <Text type="secondary" style={{ fontSize: 11 }}>等 {fallbackCompanies.length} 家</Text>}
          </Space>
        </div>
      )}
    </Card>
  );
}

function KeySignals({ signals, chainName, router }: { signals: any[]; chainName: string; router: any }) {
  return (
    <Card
      title={<Space size={4}><ThunderboltOutlined /><span style={{ fontSize: 13 }}>关键信号</span></Space>}
      extra={<a onClick={() => router.push(`/signals?chain_id=${encodeURIComponent(chainName)}`)}>全部</a>}
      style={{ borderRadius: 6 }}
      styles={{ body: { padding: 12 } }}
    >
      {signals.length === 0 ? (
        <Empty description="暂无信号" />
      ) : (
        <Space orientation="vertical" size={6} style={{ width: "100%" }}>
          {signals.slice(0, 8).map((signal: any, index: number) => {
            const stocks = signalStocks(signal);
            return (
              <div
                key={`${signal.id ?? signal.signal_type}-${index}`}
                style={{ border: "1px solid #f0f0f0", borderRadius: 6, padding: "8px 10px", background: "#fff" }}
              >
                <Space wrap size={[4, 4]} style={{ marginBottom: 4 }}>
                  <Tag color="blue" style={{ fontSize: 11 }}>{formatSignalType(signal.signal_type)}</Tag>
                  {stocks.length > 0 ? (
                    stocks.map((stock) => (
                      <Tag
                        key={`${signal.id ?? index}-${stock.code || stock.name}`}
                        color="geekblue"
                        style={{ cursor: stock.code ? "pointer" : "default", fontSize: 11 }}
                        onClick={() => stock.code && router.push(`/stock/${stock.code}`)}
                      >
                        {stock.name || stock.code}
                      </Tag>
                    ))
                  ) : (
                    <Tag style={{ fontSize: 11 }}>未关联标的</Tag>
                  )}
                  {signal.trigger_date && <Text type="secondary" style={{ fontSize: 11 }}>{signal.trigger_date.slice(0, 10)}</Text>}
                </Space>
                <Paragraph style={{ marginBottom: 0, fontSize: 12, lineHeight: 1.5 }}>{signal.detail || "-"}</Paragraph>
              </div>
            );
          })}
        </Space>
      )}
    </Card>
  );
}

function WatchSection({ alerts, columns, chainFilter }: { alerts: any[]; columns: any[]; chainFilter?: string }) {
  return (
    <Card
      title={<Space size={4}><EyeOutlined /><span style={{ fontSize: 13 }}>盯盘风险</span></Space>}
      style={{ marginTop: 10, borderRadius: 6 }}
      styles={{ body: { padding: 12 } }}
      extra={chainFilter ? <Text type="secondary" style={{ fontSize: 11 }}>联动 {chainFilter}</Text> : undefined}
    >
      {alerts.length === 0 ? (
        <Empty description="暂无盯盘提醒" />
      ) : (
        <Table
          rowKey={(row: any) => `${row.code}-${row.reasons?.join(",")}`}
          dataSource={alerts}
          columns={columns}
          pagination={{ pageSize: 8 }}
          scroll={{ x: 1200 }}
          size="small"
        />
      )}
    </Card>
  );
}
