// UI smoke test against the REAL running stack (docker compose up -d). Also saves screenshots.
// Run:  cd web && node tests/smoke.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";

const WEB = process.env.WEB || "http://localhost:3100";
const SHOTS = new URL("../../docs/screenshots/", import.meta.url).pathname;
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));

async function shot(name) { await page.screenshot({ path: `${SHOTS}${name}.png`, fullPage: true }); }
const ok = (name) => console.log(`PASS ${name}`);

// 1. landing: renders, hero + diagram + 3 stats (real numbers or "not measured yet")
await page.goto(WEB);
await page.getByRole("heading", { name: /One gateway/ }).waitFor();
assert.equal(await page.locator(".stat").count(), 3);
assert.ok(await page.locator("svg[aria-label='Request flow diagram']").isVisible());
console.log("  landing stats:", (await page.locator(".stat .n").allTextContents()).join(" | "));
await shot("1-landing"); ok("landing renders");

// 2. playground: single request, then burst with bob -> at least one 429
await page.goto(`${WEB}/playground`);
await page.getByRole("button", { name: "Send", exact: true }).click();
await page.getByTestId("result").waitFor();
assert.match(await page.getByTestId("result").innerText(), /HTTP 200/);
await page.locator("select").selectOption("bob");
await page.getByRole("button", { name: /Burst test/ }).click();
await page.waitForFunction(() => document.querySelectorAll("[data-testid=strip] .sq").length === 20, null, { timeout: 30000 });
const codes = await page.locator("[data-testid=strip] .sq").allTextContents();
console.log("  burst result codes:", codes.join(" "));
assert.ok(codes.includes("429"), "burst against bob must show at least one 429");
await shot("2-playground"); ok(`playground burst shows ${codes.filter((c) => c === "429").length} x 429 of 20`);

// 3. jobs: submit 3 jobs (1 doomed), wait for a SUCCEEDED badge
await page.goto(`${WEB}/jobs`);
await page.locator("input[type=number]").first().fill("3");
await page.getByRole("button", { name: "Submit" }).click();
await page.getByTestId("jobs-table").locator("text=SUCCEEDED").first().waitFor({ timeout: 30000 });
await shot("3-jobs"); ok("jobs page shows a SUCCEEDED job");

// 4. prompts: run optimiser, report appears
await page.goto(`${WEB}/prompts`);
await page.getByRole("button", { name: "Run optimiser" }).click();
await page.getByTestId("report").waitFor({ timeout: 30000 });
assert.match(await page.getByTestId("report").innerText(), /cost saved/);
await shot("4-prompts"); ok("prompts optimiser report renders");

// 5. metrics: counters render
await page.goto(`${WEB}/metrics`);
await page.getByTestId("metrics").waitFor();
assert.ok((await page.getByTestId("metrics").locator(".stat").count()) >= 5);
await shot("5-metrics"); ok("metrics cards render");

await browser.close();
assert.deepEqual(errors, [], "no page errors");
console.log("ALL UI SMOKE CHECKS PASSED");
