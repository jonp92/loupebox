/**
 * Styles live in the widget's shadow root, so the page can't break them and they can't leak out.
 * Colors are CSS custom properties: set `--gm-accent` etc. on `ganymede-widget` from the page, or use the
 * `colors` option. Nothing here relies on inline `style` attributes, so strict page CSPs are fine.
 */
export const css = `
:host {
  all: initial;
  display: block;
  --gm-accent: #5b5bd6; --gm-accent-text: #ffffff; --gm-bg: #ffffff; --gm-text: #171923; --gm-muted: #6a6f85;
  --gm-border: #dfe2ec; --gm-surface: #f4f5fa; --gm-danger: #c53030; --gm-ok: #2f855a;
  --gm-radius: 12px; --gm-font: system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --gm-z: 2147483000;
  font-family: var(--gm-font); color: var(--gm-text); font-size: 14px; line-height: 1.45;
}
:host([data-theme="dark"]) {
  --gm-accent: #8c8cf5; --gm-accent-text: #10111a; --gm-bg: #181b25; --gm-text: #e8eaf2; --gm-muted: #98a0b8;
  --gm-border: #2b3040; --gm-surface: #20242f; --gm-danger: #fc8181; --gm-ok: #68d391;
}
@media (prefers-color-scheme: dark) {
  :host([data-theme="auto"]) {
    --gm-accent: #8c8cf5; --gm-accent-text: #10111a; --gm-bg: #181b25; --gm-text: #e8eaf2; --gm-muted: #98a0b8;
    --gm-border: #2b3040; --gm-surface: #20242f; --gm-danger: #fc8181; --gm-ok: #68d391;
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
