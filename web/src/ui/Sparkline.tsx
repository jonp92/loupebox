/** Received per day as thin bars, oldest first; today (the last bar) is the accent. A text alternative carries the numbers. */
export function Sparkline({ values, label }: { values: number[]; label: string }) {
  const max = Math.max(1, ...values);
  const step = 100 / values.length;
  return (
    <svg className="spark" viewBox="0 0 100 24" preserveAspectRatio="none" role="img" aria-label={label} focusable="false">
      {values.map((v, i) => {
        const h = v ? Math.max(1.5, (v / max) * 24) : 0.75;
        return <rect key={i} className={i === values.length - 1 ? "spark-today" : v ? "spark-bar" : "spark-zero"} x={i * step + step * 0.15} y={24 - h} width={step * 0.7} height={h} />;
      })}
    </svg>
  );
}
