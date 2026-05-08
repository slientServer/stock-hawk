const fs = require("fs");
const { chromium } = require("../web/node_modules/@playwright/test");

const DEFAULT_HOSTS = ["17", "79", "69", "70", "80", "82", "29", "1", "64"];

function uniqHosts(hosts) {
  const result = [];
  for (const host of [...(hosts || []), ...DEFAULT_HOSTS]) {
    const value = String(host || "").trim();
    if (value && !result.includes(value)) result.push(value);
  }
  return result;
}

function buildQuery(params) {
  return Object.entries(params)
    .map(([key, value]) => {
      const raw = String(value);
      if (key === "fs") return `${key}=${raw.replace(/ /g, "+")}`;
      if (key === "fields") return `${key}=${raw}`;
      return `${encodeURIComponent(key)}=${encodeURIComponent(raw)}`;
    })
    .join("&");
}

async function fetchPages(page, urls, params, maxPages) {
  const errors = [];
  for (const url of urls) {
    const records = [];
    let requestUrl = "";
    try {
      for (let pn = 1; pn <= maxPages; pn += 1) {
        const query = buildQuery({ ...params, pn });
        requestUrl = `${url}?${query}`;
        const payload = await page.evaluate(async (targetUrl) => {
          const response = await fetch(targetUrl, { credentials: "include" });
          const text = await response.text();
          return { ok: response.ok, status: response.status, text };
        }, requestUrl);
        if (!payload.ok) throw new Error(`HTTP ${payload.status}: ${payload.text.slice(0, 200)}`);
        const json = JSON.parse(payload.text);
        const data = json.data || {};
        const diff = Array.isArray(data.diff) ? data.diff : [];
        if (pn === 1 && diff.length === 0) throw new Error("empty diff");
        records.push(...diff);
        const total = Number(data.total || records.length);
        if (records.length >= total || diff.length === 0) break;
      }
      if (records.length > 0) return { records, request_url: requestUrl };
    } catch (error) {
      errors.push(`${url}: ${error.message || String(error)}`);
    }
  }
  throw new Error(errors.slice(0, 8).join("; "));
}

async function main() {
  const input = JSON.parse(fs.readFileSync(0, "utf8") || "{}");
  const hosts = uniqHosts(input.hosts || []);
  const urls = hosts.map((host) => `https://${host}.push2.eastmoney.com/api/qt/clist/get`);
  const maxPages = Number(input.max_pages || 5);
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.goto("https://quote.eastmoney.com/center/boardlist.html#concept_board", {
      waitUntil: "domcontentloaded",
      timeout: Number(input.page_timeout_ms || 15000),
    });
    const result = await fetchPages(page, urls, input.params || {}, maxPages);
    process.stdout.write(JSON.stringify({ ok: true, ...result }));
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  process.stdout.write(JSON.stringify({ ok: false, error: error.message || String(error) }));
  process.exitCode = 1;
});
