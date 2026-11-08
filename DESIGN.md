# Loupebox design brief

Read this and `tokens.css` before touching any UI code. Use tokens only: no raw hex values, no one-off radii, sizes or fonts.

## Intent

Loupebox is a quiet instrument for close inspection, like a jeweler's loupe over a tray of small things. It is a serious product that may become a SaaS, so the identity lives in a few deliberate details. Tables, forms and settings stay conventional.

The identity is carried by:
1. The brass loupe logo and lens ring.
2. The amber unread gem.
3. Mono type for data.
4. Hairline rules instead of boxes.
5. Calm, specific empty states.

Not allowed: glassy gradients, cyan glow, a rounded card for every stat, decorative illustration, gauges and dials.

## Color rules

| Role | Token | Means |
|---|---|---|
| Brass | `--accent` | Brand, primary action, active nav edge, tags, identity (Superadmin badge border) |
| Amber | `--unread*` | **Unread only.** Never use it for warnings, roles or decoration. |
| Coral | `--danger` | Problem or risk state: Disabled, 2FA off, failed service |
| Sage | `--ok` | Healthy or on: Active, 2FA on, service healthy |

- Status is always a dot or gem plus a text label. Never color alone.
- Brass is the only filled accent. Primary button: `--accent` background, `--on-accent` text.
- Secondary controls are outlined with `--border-control`.

## Typography

- **Sans** (`--font-sans`) for UI copy, titles and nav.
- **Mono** (`--font-mono`) for data: counts, stat numerals, emails, IDs, timestamps, URLs and origins, tags, and all uppercase labels.
- Uppercase labels: `--text-label`, weight 500, `--tracking-label`, mono.
- Page title: `--text-page`, weight 600, `--tracking-title`.
- Minimum body size is 13px, and use `--text-muted` or darker for any text.

## Shape and layout

- Prefer ruled rows and hairlines. Use cards only for the feedback detail, sheets and menus; feedback lists are ruled rows. A card gets `--surface`, `--border` and `--radius-card`.
- Badges and tags are outlined, `--radius-tag`, mono uppercase. All roles use a badge. Superadmin's border is `--accent`.
- Every interactive element is at least `--target-min` tall and wide. Inputs are `--input-height`.
- Shell: persistent sidebar (`--sidebar-width`) at 1024px and up, off-canvas drawer below. Sidebar groups: **Triage** (Dashboard, Sites) and **Admin** (Users, Audit, System). Active item: `--surface-selected` with a 2px `--accent` left edge.
- Content is capped at `--content-max`. Section tabs are plain text with a 2px `--accent` underline on the active one.
- Create flows open in a bottom sheet on mobile (`--radius-sheet`, `--scrim` behind) and a dialog on desktop. Do not keep long create forms permanently below lists.

## Components

- **Logo:** a loupe ring in `--accent` with a check inside, plus the wordmark in sans, weight 600.
- **Unread status:** an amber filled gem plus the mono label `UNREAD` in `--unread-text`, and a straight 3px left edge in `--unread-edge` on the row. Read items use an outlined gem in `--text-muted`. Archived uses a box icon.
- **Feedback item:** a ruled row (hairline below, no radius, no fill; the unread edge is an inset bar) with checkbox, status, category chip, title (`--text-row`, weight 600 when unread), mono email, then assignee, tag, "Replied" (brass) and attachment count. Compact density puts it in three columns on desktop.
- **Row hover:** the whole row, edge included, fills with `--surface` with square corners. Never round the hover or outline only part of the row; `--surface-selected` is not used because muted, accent and unread text fall under 4.5:1 on it.
- **Stat rows:** a label, then dotted leader, then a mono numeral. No box.
- **Received-count medallion:** a brass lens ring with tick marks and a short handle around the mono count. Use it once per screen at most, only on the dashboard.
- **Empty state:** a hollow gem in `--text-muted`, a short plain sentence, and a mono "CLEAR" tag. No illustrations.
- **Status in tables:** a dot plus mono uppercase label, left-aligned to the column start.

## Additional tokens

- **No warn token.** Amber is unread only. Problems use `--danger`; neutral caution uses `--text-muted` plus a label. Ask before adding a warning state.
- **Soft tints:** `--ok-soft`, `--danger-soft`, `--accent-soft` (derived via color-mix). No amber tint.
- **Star:** `--star` (brass). Filled when starred, outlined in `--border-control` when not. Never amber.
- **Shadow:** `--shadow-pop` for menus, popovers and sheets only. Cards and rows stay flat.
- **Charts:** `--chart-1..4` (brass, sage, steel, secondary text). Never amber. Label series directly or with a legend, never color alone. `--danger` only for failure series.
- **Theme:** an explicit `data-theme` always wins; otherwise follow the OS; dark is the fallback.

## Accessibility

- Text meets 4.5:1 in both themes, UI borders 3:1. Re-check any new color.
- Real `<button>`, `<a>`, `<input>` with `<label>`. Icon-only buttons need `aria-label`.
- Visible focus uses the global `:focus-visible` rule.

## Migration plan (for Claude Code)

Do not edit anything until step 1 is approved.

1. **Audit.** Report the framework, where hex colors, radii and fonts are hard-coded, and where shared layout/templates live. Propose the plan.
2. **Tokens.** Add `tokens.css`. If Tailwind or similar is used, map the theme to these variables. Add the theme toggle with `data-theme` and an OS-preference fallback.
3. **Fonts.** Self-host Hanken Grotesk and IBM Plex Mono. No CDN at runtime.
4. **Shell.** Sidebar, mobile drawer, header with theme toggle and account menu.
5. **Primitives.** Button, badge, status, input, select, tabs, ruled row, card, sheet, empty state.
6. **Screens, one per approval.** Dashboard, feedback list (comfortable and compact), site detail tabs, sites list and create sheet, users, system status, audit, public form.
7. **Cleanup.** Delete old styles and unused tokens. Check contrast, keyboard focus and both themes on each screen.

## Reference screens

The mockups are on the "Loupebox Directions" canvas. Boards D to K are the chosen direction. They are hand-written inline-style HTML for review, so use them as visual reference and rebuild them from the tokens and primitives above. Do not copy their markup.
