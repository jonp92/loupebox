// Fails when a color pair in the admin UI or widget themes drops below WCAG AA (4.5:1 text, 3:1 controls),
// or when the dark tokens in the prefers-color-scheme block drift from the explicit dark theme.
// Plain node, no dependencies: `npm run check:contrast`.
import { readFileSync } from "node:fs";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8").replace(/\/\*.*?\*\//gs, "");

// The declarations of the first `selector { ... }` rule, as {name: value} with var() references resolved.
function tokens(src, selector) {
  const start = src.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`selector not found: ${selector}`);
  const body = src.slice(start, src.indexOf("}", start));
  const out = {};
  for (const [, name, value] of body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) out[name] = value.trim();
  for (const name in out) out[name] = out[name].replace(/var\((--[\w-]+)\)/g, (_, ref) => out[ref] ?? "");
  return out;
}

const luminance = (hex) => {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const lin = (c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
};
const ratio = (a, b) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

const TEXT = 4.5;
const CONTROL = 3;
// [foreground, background, minimum ratio]. Names are token names without the prefix.
const ADMIN = [
  ...["bg", "surface", "surface-2"].flatMap((bg) => [["text", bg, TEXT], ["muted", bg, TEXT]]),
  ["accent", "bg", TEXT], ["accent", "surface", TEXT], ["accent", "accent-soft", TEXT],
  ["on-accent", "accent-fill", TEXT], ["on-accent", "accent-fill-hover", TEXT],
  ["danger", "surface", TEXT], ["danger", "danger-soft", TEXT],
  ["ok", "surface", TEXT], ["ok", "ok-soft", TEXT],
  ["warn", "surface", TEXT], ["warn", "warn-soft", TEXT],
  ["border-control", "bg", CONTROL], ["border-control", "surface", CONTROL],
];
const WIDGET = [
  ...["bg", "surface"].flatMap((bg) => [["text", bg, TEXT], ["muted", bg, TEXT]]),
  ["accent", "bg", TEXT], ["accent-text", "accent", TEXT],
  ["danger", "bg", TEXT], ["ok", "bg", TEXT],
];

const css = read("../src/styles.css");
const widget = read("../widget/src/styles.ts");
const mediaDark = tokens(css, ':root:not([data-theme="light"])');
const adminDark = tokens(css, ':root[data-theme="dark"], .topbar');

const themes = [
  ["admin light", tokens(css, ":root"), "--", ADMIN],
  ["admin dark", adminDark, "--", ADMIN],
  ["widget light", tokens(widget, ":host"), "--gm-", WIDGET],
  ["widget dark", tokens(widget, ':host([data-theme="dark"])'), "--gm-", WIDGET],
];

let failures = 0;
const fail = (message) => { failures += 1; console.error(`FAIL ${message}`); };

for (const [theme, vars, prefix, pairs] of themes) {
  for (const [fg, bg, min] of pairs) {
    const [a, b] = [vars[prefix + fg], vars[prefix + bg]];
    if (!/^#[0-9a-f]{6}$/i.test(a ?? "") || !/^#[0-9a-f]{6}$/i.test(b ?? "")) {
      fail(`${theme}: ${fg} on ${bg} is not a resolvable #rrggbb color (${a}, ${b})`);
    } else if (ratio(a, b) < min) {
      fail(`${theme}: ${fg} ${a} on ${bg} ${b} is ${ratio(a, b).toFixed(2)}:1, needs ${min}:1`);
    }
  }
}
for (const name of Object.keys(adminDark)) {
  if (name in mediaDark && mediaDark[name] !== adminDark[name]) fail(`dark tokens differ: ${name}`);
}

if (failures) process.exit(1);
console.log(`contrast ok: ${themes.map(([name, , , pairs]) => `${name} ${pairs.length}`).join(", ")} pairs`);
