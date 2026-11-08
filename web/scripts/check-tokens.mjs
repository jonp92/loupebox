// Fails when the admin UI hard-codes a color. Colors come from src/tokens.css; see "Design system" in CLAUDE.md.
// Plain node, no dependencies: `npm run check:tokens` (also runs as part of `npm run build`).
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const SRC = new URL("../src/", import.meta.url).pathname;
// Real black and white by design: the QR code must contrast, and the avatar canvas needs a white ground.
const ALLOWED = new Set(["TwoFactor.tsx", "avatar.ts"]);
const COLOR = /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/;

const files = (dir) =>
  readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? files(join(dir, e.name)) : /\.(tsx?|css)$/.test(e.name) ? [join(dir, e.name)] : [],
  );

let failures = 0;
for (const file of files(SRC)) {
  const name = file.slice(SRC.length);
  if (name === "tokens.css" || ALLOWED.has(name.split("/").pop())) continue;
  readFileSync(file, "utf8").split("\n").forEach((line, i) => {
    if (COLOR.test(line.replace(/\/\*.*?\*\//g, ""))) {
      failures += 1;
      console.error(`FAIL ${name}:${i + 1} hard-coded color: ${line.trim().slice(0, 90)}`);
    }
  });
}
if (failures) process.exit(1);
console.log("tokens ok: no hard-coded colors outside tokens.css");
