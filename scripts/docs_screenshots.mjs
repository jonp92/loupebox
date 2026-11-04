// Takes the screenshots used in docs/ (docs/images/<name>-dark.png and -light.png) from a running Loupebox.
//
// It signs in as the demo admin from scripts/docs_demo_data.py, so run it against a THROWAWAY database:
//
//   1. Seed:   DATABASE_URL=sqlite:////tmp/loupebox-docs.db python -m scripts.docs_demo_data
//   2. API:    run uvicorn app.main:app from a folder with no .env, with that DATABASE_URL, JWT_SECRET set,
//              ADMIN_ORIGINS='["http://127.0.0.1:4173"]' and ENVIRONMENT=development.
//   3. Web:    cd web && VITE_API_URL=http://127.0.0.1:8000 npm run build && npx vite preview --port 4173
//   4. Shoot:  npm i --no-save puppeteer-core (anywhere) and run
//              PUPPETEER_CORE=/path/to/node_modules/puppeteer-core node scripts/docs_screenshots.mjs
//
// Set CHROME to your Chrome binary if it is not in the macOS default location. Set ONLY=name,name to retake a few.
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";

const require = createRequire(import.meta.url);
const puppeteer = require(process.env.PUPPETEER_CORE || "puppeteer-core");

const WEB = process.env.WEB_URL || "http://127.0.0.1:4173";
const OUT = process.env.OUT || path.join(path.dirname(fileURLToPath(import.meta.url)), "../docs/images");
const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const EMAIL = process.env.ADMIN_EMAIL || "alex@example.com";
const PASSWORD = process.env.ADMIN_PASSWORD || "demo-password-123";
const ONLY = process.env.ONLY ? new Set(process.env.ONLY.split(",")) : null;
const DESKTOP = { width: 1280, height: 800, deviceScaleFactor: 1 };
const PHONE = { width: 390, height: 780, deviceScaleFactor: 2, isMobile: true, hasTouch: true };

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const click = async (page, text, selector = "button, a") => {
  const el = await page.evaluateHandle(
    (t, s) => [...document.querySelectorAll(s)].find((e) => e.textContent.trim().startsWith(t)), text, selector);
  if (!el.asElement()) throw new Error(`No "${text}" on the page`);
  await el.asElement().click();
};

async function signIn(page) {
  await page.goto(`${WEB}/login`, { waitUntil: "networkidle0" });
  await page.waitForSelector('input[name="email"]:not([disabled])');
  await page.type('input[name="email"]', EMAIL);
  await page.type('input[name="password"]', PASSWORD);
  await Promise.all([page.waitForNavigation({ waitUntil: "networkidle0" }).catch(() => {}), page.keyboard.press("Enter")]);
  await page.waitForSelector("nav, .nav, header", { timeout: 15000 });
}

// The item with notes and a reply from scripts/docs_demo_data.py.
async function openItem(page, ctx) {
  await page.goto(ctx.docs, { waitUntil: "networkidle0" });
  await page.evaluate(() => [...document.querySelectorAll("a")].find((a) => a.textContent.includes("Webhooks"))?.click());
  await page.waitForFunction(() => document.body.innerText.includes("Internal notes"));
}

async function siteUrl(page, name) {
  await page.goto(`${WEB}/sites`, { waitUntil: "networkidle0" });
  const href = await page.evaluate((n) => [...document.querySelectorAll("a")].find((a) => a.textContent.includes(n))?.href, name);
  if (!href) throw new Error(`Site ${name} not found`);
  return href.replace(/\/$/, "");
}

// Each shot: [name, viewport, async (page, ctx) => ...]. ctx.docs is the Acme Docs site URL.
const shots = [
  ["feedback-list", DESKTOP, async (p, c) => { await p.goto(c.docs, { waitUntil: "networkidle0" }); }],
  ["sites", DESKTOP, async (p) => { await p.goto(`${WEB}/sites`, { waitUntil: "networkidle0" }); }],
  ["settings", { ...DESKTOP, height: 1100 }, async (p, c) => { await p.goto(`${c.docs}/settings`, { waitUntil: "networkidle0" }); }],
  ["members", DESKTOP, async (p, c) => { await p.goto(`${c.docs}/members`, { waitUntil: "networkidle0" }); }],
  ["notifications", DESKTOP, async (p, c) => { await p.goto(`${c.docs}/notifications`, { waitUntil: "networkidle0" }); }],
  ["activity", DESKTOP, async (p, c) => { await p.goto(`${c.docs}/activity`, { waitUntil: "networkidle0" }); }],
  ["audit", DESKTOP, async (p) => { await p.goto(`${WEB}/audit`, { waitUntil: "networkidle0" }); }],
  ["two-factor", { ...DESKTOP, height: 900 }, async (p) => {
    await p.goto(`${WEB}/profile`, { waitUntil: "networkidle0" });
    await click(p, "Turn on").catch(() => click(p, "Set up")).catch(() => click(p, "Enable"));
    await p.waitForSelector("img[alt*='QR' i], canvas, svg", { timeout: 8000 }).catch(() => {});
    await wait(500);
  }],
  ["detail", { ...DESKTOP, height: 1000 }, async (p, c) => { await openItem(p, c); }],
  ["reply", { ...DESKTOP, height: 1000 }, async (p, c) => {
    await openItem(p, c);
    await p.evaluate(() => [...document.querySelectorAll("h2,h3")].find((h) => /repl/i.test(h.textContent))?.scrollIntoView());
  }],
  ["bulk", DESKTOP, async (p, c) => {
    await p.goto(c.docs, { waitUntil: "networkidle0" });
    const boxes = await p.$$('input[type="checkbox"][aria-label="Select this feedback"]');
    for (const b of boxes.slice(0, 3)) await b.click();
    await p.evaluate(() => window.scrollTo(0, 0)); // the bulk bar sticks to the bottom of the window
    await wait(300);
  }],
  ["assignee", DESKTOP, async (p, c) => {
    await p.goto(c.docs, { waitUntil: "networkidle0" });
    await p.evaluate(() => document.querySelector(".assignee, [class*='assignee']")?.click());
    await wait(500);
  }],
  ["phone", PHONE, async (p, c) => { await p.goto(c.docs, { waitUntil: "networkidle0" }); }],
];

const browser = await puppeteer.launch({ executablePath: CHROME, headless: "new" });
try {
  for (const scheme of ["dark", "light"]) {
    const context = await browser.createBrowserContext();
    const page = await context.newPage();
    await page.evaluateOnNewDocument((s) => localStorage.setItem("theme", s), scheme);
    await page.setViewport(DESKTOP);
    await page.emulateTimezone("UTC"); // SQLite returns times without a zone; read them as UTC like the server wrote them
    if (!ONLY || ONLY.has("login")) {
      await page.goto(`${WEB}/login`, { waitUntil: "networkidle0" });
      await wait(300);
      await page.screenshot({ path: `${OUT}/login-${scheme}.png` });
    }
    await signIn(page);
    const ctx = { docs: await siteUrl(page, "Acme Docs") };
    for (const [name, viewport, run] of shots) {
      if (ONLY && !ONLY.has(name)) continue;
      await page.setViewport(viewport);
      try {
        await run(page, ctx);
        await wait(400);
        await page.screenshot({ path: `${OUT}/${name}-${scheme}.png` });
        console.log(`ok   ${name}-${scheme}`);
      } catch (err) {
        console.log(`FAIL ${name}-${scheme}: ${err.message}`);
      }
    }
    await context.close();
  }
} finally {
  await browser.close();
}
