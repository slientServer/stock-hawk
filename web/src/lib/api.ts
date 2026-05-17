const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000/api";

async function fetchAPI<T = any>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${path}: ${res.status} ${body}`);
  }
  return res.json();
}

// ─── 产业链 ─────────────────────────
export async function getChains(limit = 20) {
  return fetchAPI<any[]>(`/chains?limit=${limit}`);
}
export async function getChainDetail(chainId: string) {
  return fetchAPI<any>(`/chains/${encodeURIComponent(chainId)}`);
}
export async function getChainScores(chainId: string, days = 30) {
  return fetchAPI<any[]>(`/chains/${encodeURIComponent(chainId)}/scores?days=${days}`);
}

// ─── 信号 ───────────────────────────
export async function getSignals(params?: { chain_id?: string; signal_type?: string; limit?: number; offset?: number }) {
  const q = new URLSearchParams();
  if (params?.chain_id) q.set("chain_id", params.chain_id);
  if (params?.signal_type) q.set("signal_type", params.signal_type);
  if (params?.limit) q.set("limit", String(params.limit));
  if (params?.offset) q.set("offset", String(params.offset));
  return fetchAPI<{ total: number; items: any[] }>(`/signals?${q}`);
}
export async function getSignalTypes() {
  return fetchAPI<any[]>("/signals/types");
}
export async function triggerSignalScan(chain_id?: string) {
  return fetchAPI<any>("/signals/scan", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ chain_id: chain_id || null }) });
}
export async function getScanStatus() {
  return fetchAPI<any>("/signals/scan/status");
}

// ─── 股票 ───────────────────────────
export async function getDataStats() {
  return fetchAPI<any>("/stocks/stats");
}
export async function getDataStatsDetail() {
  return fetchAPI<any>("/stocks/stats/detail");
}
export async function getStocks(params?: { keyword?: string; limit?: number }) {
  const q = new URLSearchParams();
  if (params?.keyword) q.set("keyword", params.keyword);
  if (params?.limit) q.set("limit", String(params.limit));
  return fetchAPI<any[]>(`/stocks?${q}`);
}
export async function getStock(code: string) {
  return fetchAPI<any>(`/stocks/${code}`);
}
export async function getStockSnapshot(code: string) {
  return fetchAPI<any>(`/stocks/${code}/snapshot`);
}
export async function getKline(code: string, days = 60) {
  return fetchAPI<any[]>(`/stocks/${code}/kline?days=${days}`);
}
export async function getFinancials(code: string, periods = 8) {
  return fetchAPI<any[]>(`/stocks/${code}/financials?periods=${periods}`);
}
export async function refreshFinancialReports(data: { codes?: string[]; years?: number } = {}) {
  return fetchAPI<any>("/stocks/financials/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}
export async function triggerDataCollect(data: { task: string; codes?: string[]; days?: number; years?: number }) {
  return fetchAPI<any>("/stocks/collect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}
export async function getDataCollectStatus() {
  return fetchAPI<any>("/stocks/collect/status");
}
export async function getDataCompleteness() {
  return fetchAPI<any>("/stocks/data-completeness");
}
export async function getDataPreview(source: string, limit = 20) {
  return fetchAPI<any>(`/stocks/data-preview?source=${encodeURIComponent(source)}&limit=${limit}`);
}

// ─── 持仓管理 ───────────────────────
export async function getPortfolioQuote(code: string) {
  return fetchAPI<any>(`/portfolio/quote/${encodeURIComponent(code)}`);
}
export async function getPortfolioPositions(params?: { include_closed?: boolean }) {
  const q = new URLSearchParams();
  if (params?.include_closed) q.set("include_closed", "true");
  return fetchAPI<any>(`/portfolio/positions?${q}`);
}
export async function createPortfolioPosition(data: {
  code: string;
  name?: string;
  quantity?: number;
  buy_price?: number;
  target_price?: number;
  stop_loss_price?: number;
  note?: string;
  source?: string;
}) {
  return fetchAPI<any>("/portfolio/positions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}
export async function updatePortfolioPosition(id: number, data: {
  quantity?: number;
  avg_cost?: number;
  target_price?: number;
  stop_loss_price?: number;
  note?: string;
}) {
  return fetchAPI<any>(`/portfolio/positions/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}
export async function closePortfolioPosition(id: number, data: { quantity?: number; close_price?: number; note?: string }) {
  return fetchAPI<any>(`/portfolio/positions/${id}/close`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}
export async function getPortfolioTransactions(params?: { code?: string; limit?: number }) {
  const q = new URLSearchParams();
  if (params?.code) q.set("code", params.code);
  if (params?.limit) q.set("limit", String(params.limit));
  return fetchAPI<any[]>(`/portfolio/transactions?${q}`);
}

// ─── 个股分析 ───────────────────────
export async function runStockAnalysis(data: { code: string; lookback_days?: number; use_llm?: boolean; save?: boolean }) {
  return fetchAPI<any>("/stock-analysis/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}
export async function createStockAnalysisTask(data: { code: string; lookback_days?: number; use_llm?: boolean; save?: boolean }) {
  return fetchAPI<any>("/stock-analysis/tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}
export async function getStockAnalysisTasks(limit = 30) {
  return fetchAPI<any[]>(`/stock-analysis/tasks?limit=${limit}`);
}
export async function getStockAnalysisTask(taskId: string) {
  return fetchAPI<any>(`/stock-analysis/tasks/${encodeURIComponent(taskId)}`);
}
export async function getStockAnalysisHistory(params?: { code?: string; limit?: number }) {
  const q = new URLSearchParams();
  if (params?.code) q.set("code", params.code);
  if (params?.limit) q.set("limit", String(params.limit));
  return fetchAPI<any[]>(`/stock-analysis/history?${q}`);
}
export async function getLatestStockAnalysis(code: string) {
  return fetchAPI<any>(`/stock-analysis/latest/${encodeURIComponent(code)}`);
}
export async function getStockAnalysisReport(id: number | string) {
  return fetchAPI<any>(`/stock-analysis/reports/${encodeURIComponent(String(id))}`);
}

// ─── ETF 分析 ───────────────────────
export async function getEtfWatchlist() {
  return fetchAPI<{ items: any[]; summary: any }>("/etf/watchlist");
}
export async function addEtfWatch(data: {
  code: string;
  name?: string;
  sector?: string;
  is_holding?: boolean;
  cost_price?: number;
  quantity?: number;
  target_price?: number;
  stop_loss_price?: number;
  note?: string;
}) {
  return fetchAPI<any>("/etf/watchlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}
export async function updateEtfWatch(id: number, data: {
  name?: string;
  sector?: string;
  is_holding?: boolean;
  cost_price?: number;
  quantity?: number;
  target_price?: number;
  stop_loss_price?: number;
  note?: string;
}) {
  return fetchAPI<any>(`/etf/watchlist/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}
export async function removeEtfWatch(id: number) {
  return fetchAPI<any>(`/etf/watchlist/${id}`, { method: "DELETE" });
}
export async function runEtfAnalysis(data: { use_llm?: boolean; lookback_days?: number; trigger_type?: string } = {}) {
  return fetchAPI<any>("/etf/analysis/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      use_llm: data.use_llm ?? true,
      lookback_days: data.lookback_days ?? 120,
      trigger_type: data.trigger_type ?? "manual",
    }),
  });
}
export async function getEtfAnalysisTask(taskId: string) {
  return fetchAPI<any>(`/etf/analysis/tasks/${encodeURIComponent(taskId)}`);
}
export async function getEtfAnalysisHistory(limit = 30) {
  return fetchAPI<any[]>(`/etf/analysis/history?limit=${limit}`);
}
export async function getEtfAnalysisLatest() {
  return fetchAPI<any>("/etf/analysis/latest");
}
export async function getEtfAnalysisRecord(id: number | string) {
  return fetchAPI<any>(`/etf/analysis/records/${encodeURIComponent(String(id))}`);
}
export async function backfillEtfKline(code: string, lookbackDays = 120) {
  return fetchAPI<any>("/etf/kline/backfill", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, lookback_days: lookbackDays }),
  });
}
export async function backfillMissingEtfKlines(recordId?: number, lookbackDays = 120) {
  return fetchAPI<any>("/etf/analysis/backfill_missing", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ record_id: recordId, lookback_days: lookbackDays }),
  });
}
export async function refreshEtfQuotes(codes?: string[]) {
  return fetchAPI<any>("/etf/quote/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ codes: codes && codes.length ? codes : null }),
  });
}

// ─── 回测 ───────────────────────────
export async function runBacktest(body: { start_date: string; end_date: string; signal_type?: string; chain_id?: string }) {
  return fetchAPI<any>("/backtest/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}
export async function getBacktestResults(params?: { task_id?: string; limit?: number }) {
  const q = new URLSearchParams();
  if (params?.task_id) q.set("task_id", params.task_id);
  if (params?.limit) q.set("limit", String(params.limit));
  return fetchAPI<any[]>(`/backtest/results?${q}`);
}

// ─── 报告 ───────────────────────────
export async function getReports(limit = 20) {
  return fetchAPI<any[]>(`/reports?limit=${limit}`);
}
export async function getReportDetail(id: number | string) {
  return fetchAPI<any>(`/reports/${id}`);
}
export async function triggerWorkflow(body: { workflow_type: string; chain_id?: string }) {
  return fetchAPI<any>("/reports/trigger", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

// ─── 图谱 ───────────────────────────
export async function getGraphChains() {
  return fetchAPI<any>("/graph/chains");
}
export async function getChainTopology(chainName: string) {
  return fetchAPI<any>(`/graph/chains/${encodeURIComponent(chainName)}/topology`);
}
export async function searchCompany(keyword: string) {
  return fetchAPI<any>(`/graph/search?keyword=${encodeURIComponent(keyword)}`);
}
export async function triggerChainDiscovery(
  params: { top_n?: number; min_change_pct?: number; dry_run?: boolean; allow_local_fallback?: boolean } = {},
) {
  const q = new URLSearchParams();
  q.set("top_n", String(params.top_n ?? 20));
  q.set("min_change_pct", String(params.min_change_pct ?? 0));
  q.set("dry_run", String(params.dry_run ?? false));
  q.set("allow_local_fallback", String(params.allow_local_fallback ?? false));
  return fetchAPI<any>(`/discovery/trigger?${q}`, { method: "POST" });
}
export async function getChainDiscoveryStatus() {
  return fetchAPI<any>("/discovery/status");
}

// ─── 审计 ───────────────────────────
export async function getAuditStats() {
  return fetchAPI<any>("/audit/stats");
}
export async function getDataQuality() {
  return fetchAPI<any>("/audit/data-quality");
}
export async function getAgentLogs(params?: { agent_id?: string; limit?: number }) {
  const q = new URLSearchParams();
  if (params?.agent_id) q.set("agent_id", params.agent_id);
  if (params?.limit) q.set("limit", String(params.limit));
  return fetchAPI<any[]>(`/audit/agent-logs?${q}`);
}
export async function getCollectLogs(limit = 50) {
  return fetchAPI<any[]>(`/audit/collect-logs?limit=${limit}`);
}

// ─── 自动任务 ───────────────────────
export async function getAutomationJobs() {
  return fetchAPI<any>("/automation/jobs");
}
export async function getAutomationRuns(params?: { workflow_type?: string; status?: string; limit?: number }) {
  const q = new URLSearchParams();
  if (params?.workflow_type) q.set("workflow_type", params.workflow_type);
  if (params?.status) q.set("status", params.status);
  if (params?.limit) q.set("limit", String(params.limit));
  return fetchAPI<any[]>(`/automation/runs?${q}`);
}
export async function triggerAutomation(data: { workflow_type: string; params?: Record<string, any> }) {
  return fetchAPI<any>("/automation/trigger", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ workflow_type: data.workflow_type, params: data.params ?? {} }),
  });
}

// ─── 投研工作台 ─────────────────────
export async function getAdvisorOverview() {
  return fetchAPI<any>("/advisor/overview");
}
export async function getAdvisorPicks(limit = 30) {
  return fetchAPI<any>(`/advisor/picks?limit=${limit}`);
}
export async function getAdvisorWatchlist(limit = 30) {
  return fetchAPI<any>(`/advisor/watchlist?limit=${limit}`);
}
export async function getAdvisorChainAnalysis(chainName: string) {
  return fetchAPI<any>(`/advisor/chains/${encodeURIComponent(chainName)}/analysis`);
}
export async function getAdvisorFundFlow(params?: { chain_name?: string; period?: number }) {
  const q = new URLSearchParams();
  if (params?.chain_name) q.set("chain_name", params.chain_name);
  if (params?.period) q.set("period", String(params.period));
  return fetchAPI<any>(`/advisor/fund-flow?${q}`);
}
export async function chatAdvisorStockAnalysis(data: {
  message: string;
  history?: { role: "user" | "assistant"; content: string }[];
  filters?: Record<string, any>;
  codes?: string[];
  limit?: number;
  use_llm?: boolean;
  page_context?: Record<string, any>;
}) {
  return fetchAPI<any>("/advisor/stock-analysis/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function streamAdvisorStockAnalysis(
  data: {
    message: string;
    history?: { role: "user" | "assistant"; content: string }[];
    filters?: Record<string, any>;
    codes?: string[];
    limit?: number;
    use_llm?: boolean;
    page_context?: Record<string, any>;
  },
  handlers: {
    onDelta?: (chunk: string) => void;
    onDone?: (payload: any) => void;
    onMeta?: (payload: any) => void;
    onStatus?: (payload: any) => void;
    onError?: (message: string) => void;
  },
) {
  const res = await fetch(`${API_BASE}/advisor/stock-analysis/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API /advisor/stock-analysis/chat/stream: ${res.status} ${body}`);
  }
  if (!res.body) throw new Error("Streaming response body is empty");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line);
      if (event.event === "delta") handlers.onDelta?.(String(event.data ?? ""));
      if (event.event === "done") handlers.onDone?.(event.data);
      if (event.event === "meta") handlers.onMeta?.(event.data);
      if (event.event === "status") handlers.onStatus?.(event.data);
      if (event.event === "error") handlers.onError?.(event.data?.message || "请求失败");
    }
  }
}

// ─── 尾盘选股 ─────────────────────────
export async function runEodScreener(tradeDate?: string, includeBacktest = true, mode: "intraday" | "stored" | "daily" = "intraday") {
  return fetchAPI<any>("/eod-screener/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ trade_date: tradeDate || null, include_backtest: includeBacktest, mode, lookback_days: 30 }),
  });
}
export async function getEodMarketCoverage(tradeDate?: string) {
  const q = new URLSearchParams();
  if (tradeDate) q.set("trade_date", tradeDate);
  return fetchAPI<any>(`/eod-screener/coverage?${q}`);
}
export async function collectEodFullMarket(data: { trade_date?: string; lookback_days?: number; run_after?: boolean; mode?: "intraday" | "daily" | "auto" } = {}) {
  return fetchAPI<any>("/eod-screener/collect-full-market", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      trade_date: data.trade_date || null,
      lookback_days: data.lookback_days ?? 30,
      mode: data.mode ?? "intraday",
      run_after: data.run_after ?? false,
    }),
  });
}
export async function getEodScreenerResults(params?: { trade_date?: string; limit?: number }) {
  const q = new URLSearchParams();
  if (params?.trade_date) q.set("trade_date", params.trade_date);
  if (params?.limit) q.set("limit", String(params.limit));
  return fetchAPI<any[]>(`/eod-screener/results?${q}`);
}
export async function getEodScreenerStockHistory(code: string, limit = 30) {
  return fetchAPI<any[]>(`/eod-screener/results/${code}/history?limit=${limit}`);
}
export async function getEodScreenerConfig() {
  return fetchAPI<any>("/eod-screener/config");
}
export async function updateEodScreenerConfig(data: Record<string, any>) {
  return fetchAPI<any>("/eod-screener/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}
export async function runEodBacktest(body: { start_date: string; end_date: string; code?: string }) {
  return fetchAPI<any>("/eod-screener/backtest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
export async function getEodBacktestResults(params?: { task_id?: string; limit?: number }) {
  const q = new URLSearchParams();
  if (params?.task_id) q.set("task_id", params.task_id);
  if (params?.limit) q.set("limit", String(params.limit));
  return fetchAPI<any[]>(`/eod-screener/backtest/results?${q}`);
}

// ─── 设置 ───────────────────────────
export async function getSettings() {
  return fetchAPI<any>("/settings");
}
export async function getSchedulerInfo() {
  return fetchAPI<any>("/settings/scheduler");
}
export async function updateSettings(data: Record<string, any>) {
  return fetchAPI<any>("/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}
export async function testLlmSettings(data: { custom_base_url?: string } = {}) {
  return fetchAPI<any>("/settings/llm/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}
