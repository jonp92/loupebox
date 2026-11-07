/**
 * The editor shown over the page after a capture: draw black boxes over anything private, or a highlighter over
 * the problem. Boxes are solid and are burned into the picture before it is exported, so the hidden pixels never
 * leave the browser (a blur could be read back; a solid fill cannot).
 *
 * Shapes are kept in 0..1 coordinates, so the same drawing is exact at the preview size and at the sent size.
 * Pointer (mouse, pen, touch) and keyboard both work: arrow keys move a cursor, Enter starts and finishes a shape.
 */
import { h } from "./dom";
import type { Strings } from "./i18n";
import { icon } from "./icons";
import type { ImageLimits } from "./images";

export type Op =
  | { kind: "hide"; x: number; y: number; w: number; h: number }
  | { kind: "mark"; points: [number, number][] };

type Point = { x: number; y: number };

const PREVIEW_EDGE = 1600; // the editing canvas; the picture that is sent is made from the full capture
const MIN_BOX = 0.004; // smaller than this (fraction of the picture) is a stray click, not a box
const KEY_STEP = 0.02;
const KEY_STEP_BIG = 0.1;
const HIGHLIGHT = "rgba(255, 214, 10, 0.5)";

const clamp01 = (n: number) => Math.min(1, Math.max(0, n));
const box = (a: Point, b: Point): Extract<Op, { kind: "hide" }> => ({
  kind: "hide",
  x: Math.min(a.x, b.x),
  y: Math.min(a.y, b.y),
  w: Math.abs(a.x - b.x),
  h: Math.abs(a.y - b.y),
});

/** The picture with the shapes on top, at any size. */
export function paintOps(ctx: CanvasRenderingContext2D, frame: CanvasImageSource, w: number, h: number, ops: Op[]): void {
  ctx.drawImage(frame, 0, 0, w, h);
  for (const op of ops) {
    if (op.kind === "hide") {
      ctx.fillStyle = "#000"; // opaque: nothing of the picture shows through
      ctx.fillRect(op.x * w, op.y * h, op.w * w, op.h * h);
    } else {
      ctx.strokeStyle = HIGHLIGHT;
      ctx.lineWidth = Math.max(w, h) * 0.014;
      ctx.lineCap = ctx.lineJoin = "round";
      ctx.beginPath();
      op.points.forEach(([px, py], i) => (i ? ctx.lineTo(px * w, py * h) : ctx.moveTo(px * w, py * h)));
      if (op.points.length === 1) ctx.lineTo(op.points[0][0] * w + 0.01, op.points[0][1] * h); // a tap is a dot
      ctx.stroke();
    }
  }
}

const toBlob = (canvas: HTMLCanvasElement, type: string, quality?: number) =>
  new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, type, quality));

/** The edited picture at the size the site takes: PNG if it fits, else JPEG. `null` when even that is too big. */
export async function exportPicture(frame: HTMLCanvasElement, ops: Op[], limits: ImageLimits): Promise<Blob | null> {
  const scale = Math.min(1, limits.maxEdge / Math.max(frame.width, frame.height));
  const out = document.createElement("canvas");
  out.width = Math.max(1, Math.round(frame.width * scale));
  out.height = Math.max(1, Math.round(frame.height * scale));
  const ctx = out.getContext("2d");
  if (!ctx) return null;
  paintOps(ctx, frame, out.width, out.height, ops);
  for (const [type, quality] of [["image/png"], ["image/jpeg", 0.85], ["image/jpeg", 0.7]] as [string, number?][]) {
    const blob = await toBlob(out, type, quality);
    if (blob && blob.size <= limits.maxBytes) return blob;
  }
  return null;
}

export interface Redactor {
  /** The edited picture, `"size"` when it cannot be made small enough, or `null` when the visitor cancelled. */
  result: Promise<Blob | "size" | null>;
  /** Close the editor without a picture (the widget is going away). */
  cancel(): void;
}

export function openRedactor(input: {
  frame: HTMLCanvasElement;
  strings: Strings;
  limits: ImageLimits;
  mount: ParentNode;
  id: string;
}): Redactor {
  const { frame, strings: s, limits, id } = input;
  const ops: Op[] = [];
  let draft: Op | null = null;
  let tool: "hide" | "mark" = "hide";
  let anchor: Point | null = null; // keyboard: the first corner of a box, or null
  let penDown = false; // keyboard: drawing with the highlighter
  let cursor: Point = { x: 0.5, y: 0.5 };
  let keyboardFocus = false;
  let finish!: (value: Blob | "size" | null) => void;
  const result = new Promise<Blob | "size" | null>((resolve) => (finish = resolve));

  const preview = h("canvas", {
    class: "editor-canvas",
    tabindex: "0",
    role: "application",
    "aria-label": s.editorCanvasLabel,
    "aria-describedby": `${id}-editor-help`,
  });
  const k = Math.min(1, PREVIEW_EDGE / Math.max(frame.width, frame.height));
  preview.width = Math.max(1, Math.round(frame.width * k));
  preview.height = Math.max(1, Math.round(frame.height * k));
  const ctx = preview.getContext("2d");

  const live = h("p", { class: "sr-only", role: "status", "aria-live": "polite" });
  const announce = (text: string) => (live.textContent = text);
  const undo = h("button", { type: "button", class: "plain" }, s.undo);
  const clear = h("button", { type: "button", class: "plain" }, s.clear);
  const cancel = h("button", { type: "button", class: "plain" }, s.cancel);
  const use = h("button", { type: "button", class: "submit" }, s.useCapture);
  const hide = h("button", { type: "button", class: "tool", "aria-pressed": "true" }, icon("hide"), s.toolHide);
  const mark = h("button", { type: "button", class: "tool", "aria-pressed": "false" }, icon("mark"), s.toolMark);

  const root = h(
    "div",
    { class: "editor", role: "dialog", "aria-modal": "true", "aria-labelledby": `${id}-editor-title` },
    h(
      "div",
      { class: "editor-box" },
      h("h2", { id: `${id}-editor-title` }, s.editorTitle),
      h("p", { class: "hint", id: `${id}-editor-help` }, `${s.editorHelp} ${s.editorHelpKeys}`),
      h("div", { class: "editor-stage" }, preview),
      h(
        "div",
        { class: "editor-bar" },
        h("div", { class: "tools", role: "group", "aria-label": s.toolLabel }, hide, mark),
        h("div", { class: "actions" }, undo, clear, cancel, use),
      ),
      live,
    ),
  );

  function paint(): void {
    undo.disabled = clear.disabled = ops.length === 0;
    if (!ctx) return;
    paintOps(ctx, frame, preview.width, preview.height, draft ? [...ops, draft] : ops);
    if (keyboardFocus) {
      // A crosshair for the keyboard cursor. Only on the preview; it is never part of the exported picture.
      const x = cursor.x * preview.width;
      const y = cursor.y * preview.height;
      ctx.lineWidth = 3;
      for (const [style, extra] of [["#fff", 2], ["#0a7d9c", 0]] as const) {
        ctx.strokeStyle = style;
        ctx.lineWidth = 2 + extra;
        ctx.beginPath();
        ctx.moveTo(x - 14, y);
        ctx.lineTo(x + 14, y);
        ctx.moveTo(x, y - 14);
        ctx.lineTo(x, y + 14);
        ctx.stroke();
      }
    }
  }

  function commit(): void {
    if (!draft) return;
    if (draft.kind === "mark" || (draft.w >= MIN_BOX && draft.h >= MIN_BOX)) ops.push(draft);
    draft = null;
    anchor = null;
    penDown = false;
    paint();
  }

  function discardDraft(): void {
    draft = null;
    anchor = null;
    penDown = false;
    paint();
  }

  function setTool(next: "hide" | "mark"): void {
    tool = next;
    hide.setAttribute("aria-pressed", String(next === "hide"));
    mark.setAttribute("aria-pressed", String(next === "mark"));
    discardDraft();
  }

  // --- pointer: mouse, pen and touch ------------------------------------------------------------

  const at = (e: MouseEvent): Point => {
    const r = preview.getBoundingClientRect();
    return r.width && r.height
      ? { x: clamp01((e.clientX - r.left) / r.width), y: clamp01((e.clientY - r.top) / r.height) }
      : { x: 0, y: 0 };
  };
  let start: Point | null = null;
  preview.addEventListener("pointerdown", (e) => {
    if ((e as PointerEvent).pointerType === "mouse" && e.button !== 0) return;
    e.preventDefault();
    preview.setPointerCapture?.((e as PointerEvent).pointerId);
    start = at(e);
    draft = tool === "hide" ? { ...box(start, start) } : { kind: "mark", points: [[start.x, start.y]] };
    paint();
  });
  preview.addEventListener("pointermove", (e) => {
    if (!draft || !start) return;
    const p = at(e);
    if (draft.kind === "hide") draft = box(start, p);
    else draft.points.push([p.x, p.y]);
    paint();
  });
  preview.addEventListener("pointerup", () => {
    start = null;
    commit();
  });
  preview.addEventListener("pointercancel", () => {
    start = null;
    discardDraft();
  });

  // --- keyboard: arrow keys move, Enter starts and finishes a shape -----------------------------

  preview.addEventListener("focus", () => {
    keyboardFocus = true;
    paint();
  });
  preview.addEventListener("blur", () => {
    keyboardFocus = false;
    discardDraft();
  });
  preview.addEventListener("keydown", (e) => {
    const move = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
    if (move) {
      e.preventDefault();
      const step = e.shiftKey ? KEY_STEP_BIG : KEY_STEP;
      cursor = { x: clamp01(cursor.x + move[0] * step), y: clamp01(cursor.y + move[1] * step) };
      if (draft?.kind === "hide" && anchor) draft = box(anchor, cursor);
      else if (draft?.kind === "mark" && penDown) draft.points.push([cursor.x, cursor.y]);
      paint();
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (draft) {
        commit();
        announce(s.shapeAdded);
      } else if (tool === "hide") {
        anchor = { ...cursor };
        draft = box(anchor, cursor);
        announce(s.cornerSet);
      } else {
        penDown = true;
        draft = { kind: "mark", points: [[cursor.x, cursor.y]] };
        announce(s.penDown);
      }
    } else if (e.key === "Escape" && draft) {
      e.stopPropagation(); // cancels the shape, not the whole editor
      discardDraft();
    }
  });

  // --- buttons and the dialog itself ------------------------------------------------------------

  hide.addEventListener("click", () => setTool("hide"));
  mark.addEventListener("click", () => setTool("mark"));
  undo.addEventListener("click", () => {
    ops.pop();
    paint();
  });
  clear.addEventListener("click", () => {
    ops.length = 0;
    paint();
  });

  function close(value: Blob | "size" | null): void {
    root.remove();
    frame.width = frame.height = 0; // let go of the full-size capture
    finish(value);
  }
  cancel.addEventListener("click", () => close(null));
  use.addEventListener("click", async () => {
    use.disabled = true;
    const picture = await exportPicture(frame, ops, limits);
    close(picture ?? "size");
  });
  root.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      close(null);
    } else if (e.key === "Tab") {
      // Keep Tab inside the editor while it is open.
      const items = [...root.querySelectorAll<HTMLElement>("button, canvas")].filter((el) => !(el as HTMLButtonElement).disabled);
      const first = items[0];
      const last = items[items.length - 1];
      const active = (root.getRootNode() as ShadowRoot).activeElement;
      if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    }
  });

  input.mount.append(root);
  paint();
  preview.focus();
  return { result, cancel: () => close(null) };
}
