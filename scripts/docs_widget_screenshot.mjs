// Takes docs/images/widget-{dark,light}.png: the open feedback panel on the docs site.
//
//   Build the site (zensical build), serve it (python -m http.server 8099 -d site), then run
//   PUPPETEER_CORE=/path/to/node_modules/puppeteer-core node scripts/docs_widget_screenshot.mjs
//
// The widget loads from the live server, so nothing is sent: the panel is only opened. Set CHROME and PAGE_URL to override.
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";

const require = createRequire(import.meta.url);
const puppeteer = require(process.env.PUPPETEER_CORE || "puppeteer-core");

const PAGE = process.env.PAGE_URL || "http://localhost:8099/collect/widget/";
const OUT = process.env.OUT || path.join(path.dirname(fileURLToPath(import.meta.url)), "../docs/images");
const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

const browser = await puppeteer.launch({ executablePath: CHROME, headless: "new" });
try {
  for (const scheme of ["dark", "light"]) {
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 900, deviceScaleFactor: 2 });
    await page.emulateMediaFeatures([{ name: "prefers-color-scheme", value: scheme }]);
    await page.goto(PAGE, { waitUntil: "networkidle0" });
    const panel = await page.evaluateHandle(async () => {
      const host = [...document.querySelectorAll("*")].find((e) => e.shadowRoot?.querySelector(".launcher"));
      host.shadowRoot.querySelector(".launcher").click();
      await new Promise((r) => setTimeout(r, 500));
      return host.shadowRoot.querySelector(".panel");
    });
    await panel.asElement().screenshot({ path: `${OUT}/widget-${scheme}.png` });
    console.log(`ok   widget-${scheme}`);
    await page.close();
  }
} finally {
  await browser.close();
}
