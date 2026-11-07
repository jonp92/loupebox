// Fails when a color pair in the admin UI or widget themes drops below WCAG AA (4.5:1 text, 3:1 controls),
// or when the OS-light block in tokens.css drifts from the explicit light theme.
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
  return out;
}

// Resolves var() references and `color-mix(in srgb, A n%, B)` to #rrggbb, given the theme's token map.
function resolve(vars) {
  const hex = (n) => Math.round(n).toString(16).padStart(2, "0");
  const mix = (a, pct, b) => "#" + [1, 3, 5].map((i) => hex(parseInt(a.slice(i, i + 2), 16) * pct / 100 + parseInt(b.slice(i, i + 2), 16) * (100 - pct) / 100)).join("");
  const out = {};
  const value = (name, seen = []) => {
    let v = vars[name] ?? "";
    for (let n = 0; n < 5; n++) {
      v = v.replace(/var\((--[\w-]+)\)/g, (_, ref) => value(ref));
      v = v.replace(/color-mix\(in srgb,\s*(#\w{6})\s+(\d+)%,\s*(#\w{6})\)/g, (_, a, pct, b) => mix(a, Number(pct), b));
    }
    return v;
  };
  for (const name in vars) out[name] = value(name);
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
  ...["bg", "surface", "surface-selected", "surface-chip"].flatMap((bg) => [["text", bg, TEXT], ["text-secondary", bg, TEXT], ["text-muted", bg, TEXT]]),
  ["text-muted", "bg-sidebar", TEXT],
  ["accent", "bg", TEXT], ["accent", "surface", TEXT], ["accent", "accent-soft", TEXT],
  ["on-accent", "accent", TEXT],
  ["unread-text", "bg", TEXT], ["unread-text", "surface", TEXT],
  ["danger", "bg", TEXT], ["danger", "surface", TEXT], ["danger", "danger-soft", TEXT],
  ["ok", "bg", TEXT], ["ok", "surface", TEXT], ["ok", "ok-soft", TEXT],
  ["border-control", "bg", CONTROL], ["border-control", "surface", CONTROL],
];
const WIDGET = [
  ...["bg", "surface"].flatMap((bg) => [["text", bg, TEXT], ["muted", bg, TEXT]]),
  ["accent", "bg", TEXT], ["accent-text", "accent", TEXT],
  ["danger", "bg", TEXT], ["ok", "bg", TEXT],
];

const css = read("../src/tokens.css");
const widget = read("../widget/src/styles.ts");
const derived = tokens(css, ":root"); // theme-independent tints, resolved per theme
const lightRaw = tokens(css, ':root[data-theme="light"]');
const darkRaw = tokens(css, ':root[data-theme="dark"]');
const mediaLight = tokens(css, ':root:not([data-theme="dark"]):not([data-theme="light"])');

const themes = [
  ["admin light", resolve({ ...derived, ...lightRaw }), "--", ADMIN],
  ["admin dark", resolve({ ...derived, ...darkRaw }), "--", ADMIN],
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
for (const name of Object.keys(mediaLight)) {
  if (mediaLight[name] !== lightRaw[name]) fail(`OS-light tokens differ from the light theme: ${name}`);
}

if (failures) process.exit(1);
console.log(`contrast ok: ${themes.map(([name, , , pairs]) => `${name} ${pairs.length}`).join(", ")} pairs`);
