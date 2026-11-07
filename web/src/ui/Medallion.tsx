/** A small brass lens (the logo's ring and handle) around a mono count. Once per screen, on the dashboard only. */
export function Medallion({ count, label }: { count: number; label: string }) {
  const text = count.toLocaleString();
  return (
    <svg className="medallion" viewBox="0 0 88 88" role="img" aria-label={`${text} ${label}`} focusable="false">
      <circle className="medallion-face" cx="38" cy="38" r="31" />
      <circle className="medallion-ring" cx="38" cy="38" r="31" />
      <line className="medallion-handle" x1="61" y1="61" x2="80" y2="80" />
      <text className="medallion-count" x="38" y="38" textAnchor="middle" dominantBaseline="central" fontSize={text.length > 4 ? 15 : text.length > 2 ? 19 : 24}>{text}</text>
    </svg>
  );
}
