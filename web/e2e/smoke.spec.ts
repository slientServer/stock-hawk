import { expect, test, type Page } from "@playwright/test";

const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000/api";
const healthUrl = apiBase.replace(/\/api\/?$/, "/health");

type PageFailure = {
  type: "pageerror" | "console" | "response";
  message: string;
};

function attachFailureGuards(page: Page) {
  const failures: PageFailure[] = [];

  page.on("pageerror", (error) => {
    failures.push({ type: "pageerror", message: error.message });
  });

  page.on("console", (message) => {
    if (message.type() === "error") {
      const text = message.text();
      if (text.startsWith("Warning: [antd:")) return;
      failures.push({ type: "console", message: text });
    }
  });

  page.on("response", (response) => {
    const status = response.status();
    if (status >= 500) {
      failures.push({
        type: "response",
        message: `${status} ${response.url()}`,
      });
    }
  });

  return failures;
}

async function expectHealthyPage(page: Page, path: string, heading: string) {
  const failures = attachFailureGuards(page);
  await page.goto(path, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle", { timeout: 8_000 }).catch(() => {});
  const headingRole = page.getByRole("heading", { name: heading });
  if ((await headingRole.count()) > 0) {
    await expect(headingRole).toBeVisible();
  } else {
    await expect(page.getByText(heading, { exact: true }).first()).toBeVisible();
  }
  await expect(page.getByText("Stock Hawk")).toBeVisible();
  expect(failures, JSON.stringify(failures, null, 2)).toEqual([]);
}

test("backend health is available", async ({ request }) => {
  const response = await request.get(healthUrl);
  expect(response.ok()).toBeTruthy();
  const payload = await response.json();
  expect(payload.status).toBe("healthy");
});

test.describe("static application pages", () => {
  const pages = [
    { path: "/", heading: "产业链总览" },
    { path: "/advisor", heading: "投研助手" },
    { path: "/signals", heading: "信号中心" },
    { path: "/data", heading: "数据管理" },
    { path: "/reports", heading: "研报库" },
    { path: "/backtest", heading: "回测面板" },
    { path: "/eod-screener", heading: "尾盘选股" },
    { path: "/graph", heading: "知识图谱" },
    { path: "/audit", heading: "审计中心" },
    { path: "/settings", heading: "系统设置" },
  ];

  for (const item of pages) {
    test(`${item.path} renders`, async ({ page }) => {
      await expectHealthyPage(page, item.path, item.heading);
    });
  }
});

test("top navigation reaches core sections", async ({ page }) => {
  const failures = attachFailureGuards(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "产业链总览" })).toBeVisible();
  await page.waitForLoadState("networkidle", { timeout: 8_000 }).catch(() => {});

  await page.getByRole("menuitem", { name: /投研/ }).click();
  await page.waitForURL("**/advisor");
  await expect(page.getByText("投研助手", { exact: true })).toBeVisible();

  await page.getByRole("menuitem", { name: /图谱/ }).click();
  await page.waitForURL("**/graph");
  await expect(page.getByRole("heading", { name: "知识图谱" })).toBeVisible();

  await page.getByRole("menuitem", { name: /尾盘选股/ }).click();
  await page.waitForURL("**/eod-screener");
  await expect(page.getByRole("heading", { name: "尾盘选股" })).toBeVisible();

  await page.getByRole("menuitem", { name: /设置/ }).click();
  await page.waitForURL("**/settings");
  await expect(page.getByRole("heading", { name: "系统设置" })).toBeVisible();

  expect(failures, JSON.stringify(failures, null, 2)).toEqual([]);
});

test("overview page exposes research data foundation", async ({ page, request }) => {
  const overviewResponse = await request.get(`${apiBase}/advisor/overview`);
  expect(overviewResponse.ok()).toBeTruthy();
  const overview = await overviewResponse.json();

  const failures = attachFailureGuards(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle", { timeout: 8_000 }).catch(() => {});

  await expect(page.getByRole("heading", { name: "产业链总览" })).toBeVisible();
  await expect(page.getByText("数据覆盖", { exact: true })).toBeVisible();
  await expect(page.getByText("数据底座", { exact: true })).toBeVisible();
  if ((overview.blockers ?? []).length > 0) {
    await expect(page.getByText(overview.blockers[0])).toBeVisible();
  }

  expect(failures, JSON.stringify(failures, null, 2)).toEqual([]);
});

test("advisor page exposes chain-first research workflow", async ({ page, request }) => {
  const picksResponse = await request.get(`${apiBase}/advisor/picks?limit=3`);
  expect(picksResponse.ok()).toBeTruthy();
  const picks = await picksResponse.json();

  const failures = attachFailureGuards(page);
  await page.goto("/advisor", { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle", { timeout: 8_000 }).catch(() => {});

  await expect(page.getByText("投研助手", { exact: true })).toBeVisible();
  await expect(page.getByText("候选股", { exact: true })).toBeVisible();
  await expect(page.getByText("产业链分析", { exact: true })).toBeVisible();
  await expect(page.getByText("盯盘风险", { exact: true })).toBeVisible();

  if ((picks.items ?? []).length > 0) {
    await expect(page.getByText(picks.items[0].name).first()).toBeVisible();
  } else {
    await expect(page.getByText("暂无候选股，请先采集行情/信号数据")).toBeVisible();
  }

  expect(failures, JSON.stringify(failures, null, 2)).toEqual([]);
});

test("eod screener manual run explains the executed trade date", async ({ page }) => {
  const failures = attachFailureGuards(page);
  await page.goto("/eod-screener", { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle", { timeout: 8_000 }).catch(() => {});

  await page.getByRole("button", { name: /执行选股/ }).click();
  await expect(page.getByText(/实际执行交易日/)).toBeVisible();
  await expect(page.getByText(/基础候选/)).toBeVisible();

  expect(failures, JSON.stringify(failures, null, 2)).toEqual([]);
});

test("graph page mirrors persisted discovery blocker after api restart", async ({ page, request }) => {
  const statusResponse = await request.get(`${apiBase}/discovery/status`);
  expect(statusResponse.ok()).toBeTruthy();
  const status = await statusResponse.json();
  const discoveryStatus = status.result?.status;
  const sourceAssessment = status.result?.source_assessment;

  const failures = attachFailureGuards(page);
  await page.goto("/graph", { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle", { timeout: 8_000 }).catch(() => {});

  await expect(page.getByRole("heading", { name: "知识图谱" })).toBeVisible();
  if (discoveryStatus) {
    await expect(page.getByText(discoveryStatus)).toBeVisible();
  }
  if (discoveryStatus === "llm_unavailable") {
    await expect(page.getByText("LLM 阻塞")).toBeVisible();
  }
  if (discoveryStatus === "market_source_unavailable" || sourceAssessment?.action_required) {
    await expect(page.getByText(/数据源待修复|需要处理/)).toBeVisible();
    await expect(page.getByText("建议修复步骤")).toBeVisible();
  }
  if (sourceAssessment?.resolution_steps?.[0]) {
    await expect(page.getByText(sourceAssessment.resolution_steps[0])).toBeVisible();
  }

  expect(failures, JSON.stringify(failures, null, 2)).toEqual([]);
});

test("settings page marks required configuration", async ({ page }) => {
  const failures = attachFailureGuards(page);
  await page.goto("/settings", { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle", { timeout: 8_000 }).catch(() => {});

  await expect(page.getByRole("heading", { name: "系统设置" })).toBeVisible();
  await expect(page.getByText("配置清单")).toBeVisible();
  await expect(page.getByText("LLM 提供商", { exact: true })).toBeVisible();
  await expect(page.getByText("Custom Base URL").first()).toBeVisible();
  await expect(page.getByText("Custom Token")).toBeVisible();
  await expect(page.getByText("Custom Model")).toBeVisible();
  await expect(page.getByText("DeepSeek")).toHaveCount(0);
  await expect(page.getByText("OpenAI")).toHaveCount(0);
  await expect(page.getByText("Eastmoney Cookie")).toHaveCount(0);
  await expect(page.getByText("Eastmoney User-Agent")).toHaveCount(0);
  await expect(page.getByText("Market Proxy URL")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "测试 AKShare / 东方财富" })).toHaveCount(0);
  await expect(page.getByText("Tushare Token").first()).toBeVisible();
  await expect(page.getByText("必填").first()).toBeVisible();
  await expect(page.getByText("完整能力必填").first()).toBeVisible();

  expect(failures, JSON.stringify(failures, null, 2)).toEqual([]);
});

test("first graph chain detail page renders when graph data exists", async ({ page, request }) => {
  const graphResponse = await request.get(`${apiBase}/graph/chains`);
  expect(graphResponse.ok()).toBeTruthy();
  const graphPayload = await graphResponse.json();
  const chains = graphPayload.chains ?? [];
  test.skip(chains.length === 0, "No graph chains are available");

  const first = chains[0];
  const name = typeof first === "string" ? first : first.name ?? first.chain_name ?? first.chain_id;
  test.skip(!name, "First graph chain has no usable name");

  await expectHealthyPage(page, `/chain/${encodeURIComponent(name)}`, name);
  await expect(page.getByText("产业链结构", { exact: true })).toBeVisible();
});

test("first stock detail page renders when stock data exists", async ({ page, request }) => {
  const stocksResponse = await request.get(`${apiBase}/stocks?limit=1`);
  expect(stocksResponse.ok()).toBeTruthy();
  const stocks = await stocksResponse.json();
  test.skip(!Array.isArray(stocks) || stocks.length === 0, "No stocks are available");

  const first = stocks[0];
  test.skip(!first?.code, "First stock has no usable code");

  const failures = attachFailureGuards(page);
  await page.goto(`/stock/${first.code}`, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle", { timeout: 8_000 }).catch(() => {});
  await expect(page.getByRole("heading", { name: new RegExp(first.code) })).toBeVisible();
  await expect(page.getByRole("heading", { name: "财务报告" })).toBeVisible();
  expect(failures, JSON.stringify(failures, null, 2)).toEqual([]);
});
