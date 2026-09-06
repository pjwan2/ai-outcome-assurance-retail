// Captures real screenshots of the operator UI against a live backend, for
// README documentation. Not part of the app, build, or CI — a one-off dev
// script, so `playwright` is deliberately NOT a tracked devDependency (it
// would otherwise force every `npm ci` in CI to download a full browser).
// One-time setup to (re)generate screenshots:
//   npm install -D playwright && npx playwright install chromium
// Usage: node scripts/screenshot.mjs <base_url> <out_dir>
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const baseUrl = process.argv[2] ?? "http://localhost:5173";
const outDir = process.argv[3] ?? "../docs/screenshots";
mkdirSync(outDir, { recursive: true });

const TABS = ["Case Overview", "Agent Runs", "Evidence & Claims", "Guardrails", "Review Queue", "Trace & Release"];

const SLUG = {
  "Case Overview": "case-overview",
  "Agent Runs": "agent-runs",
  "Evidence & Claims": "evidence-claims",
  Guardrails: "guardrails",
  "Review Queue": "review-queue",
  "Trace & Release": "trace-release",
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
await page.goto(baseUrl, { waitUntil: "networkidle" });
await page.waitForSelector(".app-shell", { timeout: 15000 });
await page.waitForTimeout(800);

for (const tab of TABS) {
  await page.getByRole("button", { name: tab, exact: true }).click();
  await page.waitForTimeout(500);
  const path = `${outDir}/${SLUG[tab]}.png`;
  await page.screenshot({ path });
  console.log(`saved ${path}`);
}

await browser.close();
