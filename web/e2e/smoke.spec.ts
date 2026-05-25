import { expect, test, type Page } from "@playwright/test";

const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8010/api";
const healthUrl = apiBase.replace(/\/api\/?$/, "/health");

function attachFailureGuards(page: Page) {
  const failures: string[] = [];
  page.on("pageerror", (error) => failures.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error" && !message.text().startsWith("Warning: [antd:")) {
      failures.push(message.text());
    }
  });
  page.on("response", (response) => {
    if (response.status() >= 500) failures.push(`${response.status()} ${response.url()}`);
  });
  return failures;
}

async function expectHealthyPage(page: Page, path: string, heading: string) {
  const failures = attachFailureGuards(page);
  await page.goto(path, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle", { timeout: 8_000 }).catch(() => {});
  await expect(page.getByRole("heading", { name: heading })).toBeVisible();
  await expect(page.getByText("Stock Hawk")).toBeVisible();
  expect(failures, JSON.stringify(failures, null, 2)).toEqual([]);
}

test("backend health is available", async ({ request }) => {
  const response = await request.get(healthUrl);
  expect(response.ok()).toBeTruthy();
});

test.describe("current application pages", () => {
  const pages = [
    { path: "/", heading: "今日工作台" },
    { path: "/etf-analysis", heading: "ETF 板块轮动分析" },
    { path: "/ten-bagger", heading: "持续上涨选股" },
    { path: "/pre-market", heading: "盘前选股" },
    { path: "/news-center", heading: "资讯中心" },
    { path: "/settings", heading: "系统设置" },
  ];

  for (const item of pages) {
    test(`${item.path} renders`, async ({ page }) => {
      await expectHealthyPage(page, item.path, item.heading);
    });
  }
});

test("top navigation reaches retained sections", async ({ page }) => {
  const failures = attachFailureGuards(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "今日工作台" })).toBeVisible();

  await page.getByRole("menuitem", { name: /ETF分析/ }).click();
  await page.waitForURL("**/etf-analysis");
  await expect(page.getByRole("heading", { name: "ETF 板块轮动分析" })).toBeVisible();

  await page.getByRole("menuitem", { name: /持续上涨/ }).click();
  await page.waitForURL("**/ten-bagger");
  await expect(page.getByRole("heading", { name: "持续上涨选股" })).toBeVisible();

  await page.getByRole("menuitem", { name: /盘前选股/ }).click();
  await page.waitForURL("**/pre-market");
  await expect(page.getByRole("heading", { name: "盘前选股" })).toBeVisible();

  await page.getByRole("menuitem", { name: /资讯中心/ }).click();
  await page.waitForURL("**/news-center");
  await expect(page.getByRole("heading", { name: "资讯中心" })).toBeVisible();

  await page.getByRole("menuitem", { name: /设置/ }).click();
  await page.waitForURL("**/settings");
  await expect(page.getByRole("heading", { name: "系统设置" })).toBeVisible();

  expect(failures, JSON.stringify(failures, null, 2)).toEqual([]);
});
