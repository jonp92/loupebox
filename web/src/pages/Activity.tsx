import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api, type DayStats, type Site } from "../api";

const RANGES = [7, 14, 30, 90];

const SERIES = [
  { key: "accepted", name: "Accepted", color: "var(--chart-1)" },
  { key: "quarantined", name: "Quarantined as spam", color: "var(--chart-2)" },
  { key: "blocked", name: "Blocked", color: "var(--chart-3)" },
] as const;
type SeriesKey = (typeof SERIES)[number]["key"];

// Duplicates are retries/double-clicks, not abuse, so they stay out of "blocked" (table only).
const blocked = (d: DayStats) => d.honeypot + d.origin_denied + d.rate_limited + d.daily_limit + d.challenge_failed;
const value = (d: DayStats, k: SeriesKey) => (k === "blocked" ? blocked(d) : d[k]);

const fmt = new Intl.NumberFormat();
const dayLabel = (day: string, long = false) =>
  new Date(day + "T00:00:00Z").toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    ...(long ? { weekday: "short" } : {}),
    timeZone: "UTC",
  });

function niceStep(max: number): number {
  const raw = Math.max(max, 1) / 4;
  const pow = 10 ** Math.floor(Math.log10(raw));
  const n = raw / pow;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * pow;
}

/** Rect with only the top corners rounded (data end), square at the baseline side. */
function topRounded(x: number, y: number, w: number, h: number, r: number): string {
  r = Math.min(r, w / 2, h);
  return `M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h} Z`;
}

function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(Math.floor(el.getBoundingClientRect().width));
    const ro = new ResizeObserver(([e]) => setWidth(Math.floor(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

const PLOT_H = 200;
const AXIS_H = 28;
const TOP = 8;
const LEFT = 36;
const GAP = 2;

function StackedColumns({ days }: { days: DayStats[] }) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState<number | null>(null);

  const totals = days.map((d) => SERIES.reduce((s, x) => s + value(d, x.key), 0));
  const max = Math.max(0, ...totals);
  const step = niceStep(max);
  const top = Math.max(step, Math.ceil(max / step) * step);
  const ticks = Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step);

  const plotW = Math.max(0, width - LEFT - 8);
  const band = days.length ? plotW / days.length : 0;
  const barW = Math.max(2, Math.min(24, band * 0.65));
  const y = (v: number) => TOP + PLOT_H - (v / top) * PLOT_H;
  const labelEvery = Math.max(1, Math.ceil(64 / Math.max(band, 1)));

  const tip = hover === null ? null : days[hover];
  const tipX = hover === null ? 0 : LEFT + band * hover + band / 2;

  return (
    <div className="viz" ref={ref}>
      {width > 0 && (
        <svg width={width} height={TOP + PLOT_H + AXIS_H} role="group" aria-label="Daily submissions by outcome">
          {ticks.map((t) => (
            <g key={t}>
              <line x1={LEFT} x2={LEFT + plotW} y1={y(t)} y2={y(t)} className={t === 0 ? "viz-base" : "viz-grid"} />
              <text x={LEFT - 8} y={y(t)} dy="0.32em" textAnchor="end" className="viz-tick">{fmt.format(t)}</text>
            </g>
          ))}
          {days.map((d, i) => {
            const x = LEFT + band * i + (band - barW) / 2;
            let acc = 0;
            let drawn = false;
            const parts = SERIES.map((s, si) => {
              const v = value(d, s.key);
              if (v <= 0) return null;
              const y1 = y(acc + v);
              const y0 = y(acc);
              // 2px surface gap between stacked segments, taken from the upper segment.
              const h = Math.max(1, y0 - y1 - (drawn ? GAP : 0));
              acc += v;
              drawn = true;
              return { s, si, y1, h };
            }).filter((p): p is NonNullable<typeof p> => p !== null);
            const topIdx = parts.length - 1;
            return (
              <g key={d.day} opacity={hover === null || hover === i ? 1 : 0.45}>
                {parts.map((p, pi) => (
                  <path key={p.s.key} d={pi === topIdx ? topRounded(x, p.y1, barW, p.h, 4) : topRounded(x, p.y1, barW, p.h, 0)} fill={p.s.color} />
                ))}
              </g>
            );
          })}
          {days.map((d, i) =>
            i % labelEvery === 0 ? (
              <text key={d.day} x={LEFT + band * i + band / 2} y={TOP + PLOT_H + 18} textAnchor="middle" className="viz-tick">
                {dayLabel(d.day)}
              </text>
            ) : null,
          )}
          {/* Hit targets: full-height bands, larger than the marks; same readout on keyboard focus. */}
          {days.map((d, i) => (
            <rect
              key={d.day}
              x={LEFT + band * i}
              y={TOP}
              width={band}
              height={PLOT_H + AXIS_H}
              fill="transparent"
              tabIndex={0}
              aria-label={`${dayLabel(d.day, true)}: ${SERIES.map((s) => `${fmt.format(value(d, s.key))} ${s.name.toLowerCase()}`).join(", ")}`}
              onPointerEnter={() => setHover(i)}
              onPointerMove={() => setHover(i)}
              onPointerLeave={() => setHover(null)}
              onFocus={() => setHover(i)}
              onBlur={() => setHover(null)}
            />
          ))}
        </svg>
      )}
      {max === 0 && width > 0 && <p className="viz-empty muted">No activity in this period.</p>}
      {tip && (
        <div className="viz-tip" style={{ left: Math.min(Math.max(tipX, 90), Math.max(width - 90, 90)), top: 0 }} role="status">
          <div className="viz-tip-date">{dayLabel(tip.day, true)}</div>
          {SERIES.map((s) => (
            <div key={s.key} className="viz-tip-row">
              <span className="viz-key" style={{ background: s.color }} aria-hidden />
              <strong>{fmt.format(value(tip, s.key))}</strong>
              <span className="muted">{s.name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function DataTable({ days }: { days: DayStats[] }) {
  const rows = [...days].reverse();
  return (
    <div className="table-wrap">
      <table className="viz-table">
        <thead>
          <tr>
            <th>Day (UTC)</th><th>Accepted</th><th>Quarantined</th><th>Honeypot</th>
            <th>Wrong origin</th><th>Challenge</th><th>Rate limited</th><th>Daily cap</th><th>Duplicates</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((d) => (
            <tr key={d.day}>
              <td>{dayLabel(d.day, true)}</td>
              <td>{fmt.format(d.accepted)}</td>
              <td>{fmt.format(d.quarantined)}</td>
              <td>{fmt.format(d.honeypot)}</td>
              <td>{fmt.format(d.origin_denied)}</td>
              <td>{fmt.format(d.challenge_failed)}</td>
              <td>{fmt.format(d.rate_limited)}</td>
              <td>{fmt.format(d.daily_limit)}</td>
              <td>{fmt.format(d.duplicate)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd className="stat-num">{value}</dd>
      {note && <dd className="stat-note">{note}</dd>}
    </div>
  );
}

export default function Activity({ site }: { site: Site }) {
  const [range, setRange] = useState(14);
  const [days, setDays] = useState<DayStats[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [table, setTable] = useState(false);

  useEffect(() => {
    let stale = false;
    setLoading(true);
    api<{ days: DayStats[] }>(`/sites/${site.id}/stats?days=${range}`)
      .then((r) => !stale && (setDays(r.days), setError("")))
      .catch((e) => !stale && setError(e.message))
      .finally(() => !stale && setLoading(false));
    return () => {
      stale = true;
    };
  }, [site.id, range]);

  const sums = useMemo(() => {
    const t = { accepted: 0, quarantined: 0, blocked: 0 };
    for (const d of days ?? []) {
      t.accepted += d.accepted;
      t.quarantined += d.quarantined;
      t.blocked += blocked(d);
    }
    return t;
  }, [days]);
  const all = sums.accepted + sums.quarantined + sums.blocked;
  const junk = all ? Math.round(((sums.quarantined + sums.blocked) / all) * 100) : 0;

  return (
    <>
      <div className="toolbar">
        <label className="inline range">
          Range
          <select value={range} onChange={(e) => setRange(Number(e.target.value))}>
            {RANGES.map((r) => <option key={r} value={r}>Last {r} days</option>)}
          </select>
        </label>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {days && (
        <div style={{ opacity: loading ? 0.6 : 1, transition: "opacity .15s" }}>
          <dl className="stat-rows">
            <Stat label="Accepted" value={fmt.format(sums.accepted)} note="Stored as feedback" />
            <Stat label="Quarantined as spam" value={fmt.format(sums.quarantined)} note="Stored, hidden by default" />
            <Stat label="Blocked" value={fmt.format(sums.blocked)} note="Honeypot, origin, rate and daily limits" />
            <Stat label="Junk share" value={`${junk}%`} note="Quarantined + blocked, of all attempts" />
          </dl>
          <figure className="viz-card">
            <figcaption>
              <div>
                <h2>Submissions per day</h2>
                <p className="muted">Days are UTC. Attempts with an unknown key can't be attributed to a site and aren't counted.</p>
              </div>
              <button onClick={() => setTable(!table)}>{table ? "Chart view" : "Table view"}</button>
            </figcaption>
            <ul className="viz-legend">
              {SERIES.map((s) => (
                <li key={s.key}><span className="viz-key" style={{ background: s.color }} aria-hidden />{s.name}</li>
              ))}
            </ul>
            {table ? <DataTable days={days} /> : <StackedColumns days={days} />}
          </figure>
        </div>
      )}
    </>
  );
}
