const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8010/api";

async function fetchAPI<T = any>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${path}: ${res.status} ${body}`);
  }
  return res.json();
}

// ETF 分析
export async function getEtfWatchlist() {
  return fetchAPI<{ items: any[]; summary: any }>("/etf/watchlist");
}
export async function getEtfRotationPool() {
  return fetchAPI<{ items: any[]; count: number; source_policy: string }>("/etf/watchlist/rotation_pool");
}
export async function importEtfRotationPool(data: { overwrite_existing?: boolean } = {}) {
  return fetchAPI<any>("/etf/watchlist/import_rotation_pool", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ overwrite_existing: data.overwrite_existing ?? false }),
  });
}
export async function addManualEtfNews(data: {
  title: string;
  content?: string;
  publish_time?: string;
  source?: string;
  event_type?: string;
  sentiment?: string;
  sectors?: string[];
  keywords?: string[];
}) {
  return fetchAPI<any>("/etf/news/manual", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
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
export async function getEtfDetail(code: string, lookbackDays = 120) {
  return fetchAPI<any>(`/etf/detail/${encodeURIComponent(code)}?lookback_days=${lookbackDays}`);
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

// 持续上涨
export async function runRisingScreener(filterMode: string = "4m") {
  return fetchAPI<any>("/ten-bagger/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filter_mode: filterMode }),
  });
}
export async function getKline(code: string, days = 180) {
  return fetchAPI<any[]>(`/ten-bagger/${encodeURIComponent(code)}/kline?days=${days}`);
}
export async function analyzeStockRising(data: Record<string, any>) {
  return fetchAPI<any>("/ten-bagger/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

// 资讯中心
export async function getNewsCenterToday() {
  return fetchAPI<any>("/news-center/today");
}
export async function collectFinanceNews(data: { use_llm?: boolean; limit_per_source?: number } = {}) {
  return fetchAPI<any>("/news-center/collect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      use_llm: data.use_llm ?? true,
      limit_per_source: data.limit_per_source ?? 40,
    }),
  });
}
export async function summarizeFinanceNews(data: { summary_date?: string; use_llm?: boolean } = {}) {
  const q = new URLSearchParams();
  if (data.summary_date) q.set("summary_date", data.summary_date);
  q.set("use_llm", String(data.use_llm ?? true));
  return fetchAPI<any>(`/news-center/summarize?${q}`, { method: "POST" });
}
export async function getFinanceNewsSources() {
  return fetchAPI<{ items: any[] }>("/news-center/sources");
}
export async function addFinanceNewsSource(data: {
  name: string;
  url: string;
  category?: string;
  source_type?: string;
  enabled?: boolean;
}) {
  return fetchAPI<any>("/news-center/sources", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...data, source_type: data.source_type ?? "rss", enabled: data.enabled ?? true }),
  });
}
export async function updateFinanceNewsSource(id: number, data: Record<string, any>) {
  return fetchAPI<any>(`/news-center/sources/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}
export async function disableFinanceNewsSource(id: number) {
  return fetchAPI<any>(`/news-center/sources/${id}`, { method: "DELETE" });
}
export async function getFinanceNewsSummaries(limit = 30) {
  return fetchAPI<{ items: any[] }>(`/news-center/summaries?limit=${limit}`);
}
export async function getFinanceNewsArticles(params: { target_date?: string; limit?: number } = {}) {
  const q = new URLSearchParams();
  if (params.target_date) q.set("target_date", params.target_date);
  if (params.limit) q.set("limit", String(params.limit));
  return fetchAPI<{ items: any[] }>(`/news-center/articles?${q}`);
}

// 设置
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

// 盘前选股
export async function triggerPreMarket(tradeDate?: string) {
  const q = tradeDate ? `?trade_date=${encodeURIComponent(tradeDate)}` : "";
  return fetchAPI<any>(`/pre-market/run${q}`, { method: "POST" });
}
export async function getPreMarketTask(taskId: string) {
  return fetchAPI<any>(`/pre-market/tasks/${encodeURIComponent(taskId)}`);
}
export async function getPreMarketLatest() {
  return fetchAPI<any>("/pre-market/latest");
}
export async function getPreMarketHistory(limit = 30) {
  return fetchAPI<any[]>(`/pre-market/history?limit=${limit}`);
}
export async function getPreMarketByDate(dateStr: string) {
  return fetchAPI<any>(`/pre-market/${encodeURIComponent(dateStr)}`);
}
export async function getPreMarketCatalysts(dateStr: string) {
  return fetchAPI<any[]>(`/pre-market/${encodeURIComponent(dateStr)}/catalysts`);
}
export async function getPreMarketPerformance(days = 30) {
  return fetchAPI<any>(`/pre-market/performance?days=${days}`);
}

// 持仓管理
export async function getPositions(includeClosed = false) {
  return fetchAPI<{ items: any[]; summary: any }>(
    `/portfolio/positions${includeClosed ? "?include_closed=true" : ""}`
  );
}
export async function createPosition(data: {
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
export async function updatePosition(id: number, data: {
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
export async function closePosition(id: number, data: {
  quantity?: number;
  close_price?: number;
  note?: string;
} = {}) {
  return fetchAPI<any>(`/portfolio/positions/${id}/close`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}
export async function getPositionHistory(id: number) {
  return fetchAPI<any[]>(`/portfolio/positions/${id}/history`);
}
export async function getPortfolioQuote(code: string) {
  return fetchAPI<any>(`/portfolio/quote/${encodeURIComponent(code)}`);
}

// 关注列表
export async function getWatchlist() {
  return fetchAPI<{ items: any[] }>("/watchlist");
}
export async function addWatchItem(data: {
  code: string;
  name: string;
  industry?: string;
  source?: string;
  note?: string;
  mode1_enabled?: boolean;
  mode1_target_price?: number;
  mode1_floor_price?: number;
  mode2_enabled?: boolean;
  mode2_base_price?: number;
  mode2_up_pct?: number;
  mode2_down_pct?: number;
  mode3_enabled?: boolean;
}) {
  return fetchAPI<any>("/watchlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}
export async function updateWatchItem(id: number, data: {
  name?: string;
  industry?: string;
  note?: string;
  status?: string;
  mode1_enabled?: boolean;
  mode1_target_price?: number;
  mode1_floor_price?: number;
  mode2_enabled?: boolean;
  mode2_base_price?: number;
  mode2_up_pct?: number;
  mode2_down_pct?: number;
  mode3_enabled?: boolean;
}) {
  return fetchAPI<any>(`/watchlist/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}
export async function removeWatchItem(id: number) {
  return fetchAPI<any>(`/watchlist/${id}`, { method: "DELETE" });
}
export async function searchStocks(q: string) {
  return fetchAPI<{ code: string; name: string; industry: string | null }[]>(
    `/watchlist/search?q=${encodeURIComponent(q)}`
  );
}
