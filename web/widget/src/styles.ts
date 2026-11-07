/**
 * Styles live in the widget's shadow root, so the page can't break them and they can't leak out.
 * Colors are CSS custom properties: set `--gm-accent` etc. on `loupebox-widget` from the page, or use the
 * `colors` option. Nothing here relies on inline `style` attributes, so strict page CSPs are fine.
 */
export const css = `
:host {
  all: initial;
  display: block;
  --gm-accent: #007a94; --gm-accent-text: #ffffff; --gm-bg: #ffffff; --gm-text: #0f1720; --gm-muted: #5a6b82;
  --gm-border: #d5dee8; --gm-surface: #eaf0f5; --gm-danger: #c62a3e; --gm-ok: #17794a;
  --gm-radius: 12px; --gm-font: system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --gm-z: 2147483000;
  font-family: var(--gm-font); color: var(--gm-text); font-size: 14px; line-height: 1.45;
}
:host([data-theme="dark"]) {
  --gm-accent: #00e5ff; --gm-accent-text: #0b0e14; --gm-bg: #121722; --gm-text: #e6edf7; --gm-muted: #7889a3;
  --gm-border: #263044; --gm-surface: #1a2130; --gm-danger: #ff7a8a; --gm-ok: #6fdba0;
}
@media (prefers-color-scheme: dark) {
  :host([data-theme="auto"]) {
    --gm-accent: #00e5ff; --gm-accent-text: #0b0e14; --gm-bg: #121722; --gm-text: #e6edf7; --gm-muted: #7889a3;
    --gm-border: #263044; --gm-surface: #1a2130; --gm-danger: #ff7a8a; --gm-ok: #6fdba0;
  }
}
*, *::before, *::after { box-sizing: border-box; }
[hidden] { display: none !important; }
button, input, textarea, select { font: inherit; color: inherit; }
:focus-visible { outline: 2px solid var(--gm-accent); outline-offset: 2px; }

.launcher {
  position: fixed; bottom: 20px; z-index: var(--gm-z); display: inline-flex; align-items: center; gap: 8px;
  padding: 10px 16px; border: 0; border-radius: 999px; cursor: pointer; font-weight: 600;
  background: var(--gm-accent); color: var(--gm-accent-text); box-shadow: 0 4px 16px rgba(0,0,0,.25);
  transition: transform .15s ease;
}
.launcher:hover { transform: translateY(-1px); }
[data-position="bottom-right"] .launcher, [data-position="bottom-right"] .panel { right: 20px; }
[data-position="bottom-left"] .launcher, [data-position="bottom-left"] .panel { left: 20px; }

.panel {
  background: var(--gm-bg); color: var(--gm-text); border: 1px solid var(--gm-border);
  border-radius: var(--gm-radius); padding: 16px;
}
[data-mode="floating"] .panel {
  position: fixed; bottom: 76px; z-index: var(--gm-z); width: 360px; max-width: calc(100vw - 24px);
  max-height: calc(100vh - 100px); overflow: auto; box-shadow: 0 12px 40px rgba(0,0,0,.28);
}
.head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 12px; }
h2, h3 { margin: 0; font-size: 16px; line-height: 1.3; }
.close { border: 0; background: none; padding: 4px; border-radius: 6px; cursor: pointer; color: var(--gm-muted); display: inline-flex; }
.close:hover { color: var(--gm-text); background: var(--gm-surface); }

form { display: grid; gap: 12px; margin: 0; }
fieldset { border: 0; margin: 0; padding: 0; min-width: 0; }
legend, label, .label { display: block; font-weight: 600; font-size: 13px; margin-bottom: 4px; padding: 0; }
.hint { font-weight: 400; color: var(--gm-muted); }
input[type="text"], input[type="email"], textarea, select {
  width: 100%; padding: 8px 10px; border: 1px solid var(--gm-border); border-radius: calc(var(--gm-radius) / 1.6);
  background: var(--gm-bg); color: var(--gm-text);
}
textarea { min-height: 96px; resize: vertical; }
[aria-invalid="true"] { border-color: var(--gm-danger); }
.err { color: var(--gm-danger); font-size: 12px; margin: 4px 0 0; }
.check { display: flex; gap: 8px; align-items: center; font-weight: 400; }

.types { display: flex; flex-wrap: wrap; gap: 8px; }
.type {
  display: inline-flex; align-items: center; gap: 6px; padding: 5px 12px; border: 1px solid var(--gm-border);
  border-radius: 999px; background: var(--gm-surface); cursor: pointer; font-size: 13px; font-weight: 500;
}
.type:hover { border-color: var(--gm-type, var(--gm-accent)); }
.type[aria-checked="true"] { background: var(--gm-type, var(--gm-accent)); border-color: var(--gm-type, var(--gm-accent)); color: #fff; }
.type .emoji { font-size: 14px; line-height: 1; }

.rating { display: flex; gap: 4px; }
.star { border: 0; background: none; padding: 2px; font-size: 24px; line-height: 1; cursor: pointer; color: var(--gm-border); }
.star[data-on="true"] { color: #ecc94b; }

.image-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.add-image {
  display: inline-flex; align-items: center; gap: 6px; padding: 7px 12px; border: 1px solid var(--gm-border);
  border-radius: calc(var(--gm-radius) / 1.6); background: var(--gm-surface); cursor: pointer; font-weight: 500;
}
.add-image:hover:not([disabled]) { border-color: var(--gm-accent); }
.add-image[disabled] { opacity: .55; cursor: not-allowed; }
.images .hint { margin: 4px 0 0; font-size: 12px; }
.thumbs { display: flex; flex-wrap: wrap; gap: 8px; list-style: none; margin: 8px 0 0; padding: 0; }
.thumbs li {
  position: relative; width: 64px; height: 64px; border: 1px solid var(--gm-border); border-radius: 8px;
  background: var(--gm-surface); display: grid; place-items: center; color: var(--gm-muted);
}
.thumbs img { width: 100%; height: 100%; object-fit: cover; border-radius: 7px; display: block; }
.thumbs .remove {
  position: absolute; top: -8px; right: -8px; width: 24px; height: 24px; padding: 0; border-radius: 50%;
  border: 1px solid var(--gm-border); background: var(--gm-bg); color: var(--gm-text); cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center;
}
.thumbs .remove svg { width: 12px; height: 12px; }
.panel[data-dragging="true"] { outline: 2px dashed var(--gm-accent); outline-offset: -6px; }
.add-image svg, .tool svg { flex: none; }
:host([data-capturing]) .panel, :host([data-capturing]) .launcher { visibility: hidden !important; }

.editor {
  position: fixed; inset: 0; z-index: calc(var(--gm-z) + 1); display: grid; place-items: center; padding: 8px;
  background: rgba(10, 12, 20, .78);
}
.editor-box {
  display: flex; flex-direction: column; gap: 8px; width: min(1100px, 100%); max-height: 100%; padding: 14px;
  background: var(--gm-bg); color: var(--gm-text); border: 1px solid var(--gm-border); border-radius: var(--gm-radius);
  box-shadow: 0 12px 40px rgba(0,0,0,.4);
}
.editor-box h2 { margin: 0; }
.editor-box .hint { margin: 0; font-size: 12px; }
.editor-stage { flex: 1; min-height: 0; display: grid; place-items: center; background: var(--gm-surface); border-radius: 8px; overflow: hidden; }
.editor-canvas { max-width: 100%; max-height: calc(100vh - 220px); cursor: crosshair; touch-action: none; display: block; }
.editor-bar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; justify-content: space-between; }
.editor-bar .tools, .editor-bar .actions { display: flex; flex-wrap: wrap; gap: 8px; }
.tool, .plain {
  display: inline-flex; align-items: center; gap: 6px; padding: 8px 12px; border: 1px solid var(--gm-border);
  border-radius: calc(var(--gm-radius) / 1.6); background: var(--gm-surface); cursor: pointer; font-weight: 500;
}
.tool[aria-pressed="true"] { background: var(--gm-accent); border-color: var(--gm-accent); color: var(--gm-accent-text); }
.plain[disabled] { opacity: .5; cursor: not-allowed; }
.sr-only { position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
@media (max-width: 480px) { .editor-bar .actions { width: 100%; } .editor-bar .actions button { flex: 1; } }
.honeypot { position: absolute; left: -9999px; width: 1px; height: 1px; overflow: hidden; }
.status { margin: 0; min-height: 1.2em; font-size: 13px; }
.status[data-kind="error"] { color: var(--gm-danger); }
.submit, .again {
  border: 0; border-radius: calc(var(--gm-radius) / 1.6); padding: 10px 14px; font-weight: 600; cursor: pointer;
  background: var(--gm-accent); color: var(--gm-accent-text);
}
.submit[disabled] { opacity: .65; cursor: progress; }
.done { text-align: center; padding: 12px 4px; display: grid; gap: 8px; justify-items: center; }
.done p { margin: 0; color: var(--gm-muted); }
.done .tick { color: var(--gm-ok); font-size: 28px; line-height: 1; }

@media (max-width: 480px) {
  [data-mode="floating"] .panel { left: 8px !important; right: 8px !important; width: auto; max-width: none; bottom: 72px; }
  input[type="text"], input[type="email"], textarea, select { font-size: 16px; }
}
@media (prefers-reduced-motion: reduce) { .launcher { transition: none; } }
`;
