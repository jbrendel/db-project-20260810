import { useState } from "react";
import {
  ResponsiveContainer, ComposedChart, Line, Scatter, XAxis, YAxis, Tooltip,
  ReferenceLine, CartesianGrid, Cell,
} from "recharts";

// Sentiment sign -> dot colour (matches the per-item pill palette).
const DOT_COLORS = {
  positive: "#1f8a4c", neutral: "#8a94a6", negative: "#c0392b",
};

function dotColor(label) {
  return DOT_COLORS[label] || DOT_COLORS.neutral;
}

function round3(n) {
  return Math.round(n * 1000) / 1000;
}

function monthMid(month) {
  const [y, m] = month.split("-").map(Number);
  return Date.UTC(y, m - 1, 15); // plot a month's average at mid-month
}

// First-of-month tick timestamps spanning [minMs, maxMs], thinned to ~<=12
// ticks. A numeric time XAxis won't auto-generate readable date ticks, so we
// supply them explicitly (fixes a bare x-axis).
export function monthTicks(minMs, maxMs) {
  if (!(maxMs >= minMs)) return [];
  const lo = new Date(minMs);
  let y = lo.getUTCFullYear();
  let m = lo.getUTCMonth();
  const hi = new Date(maxMs);
  const span = (hi.getUTCFullYear() - y) * 12 + (hi.getUTCMonth() - m);
  const step = Math.max(1, Math.ceil((span + 1) / 12));
  const ticks = [];
  let t = Date.UTC(y, m, 1);
  while (t <= maxMs) {
    ticks.push(t);
    m += step;
    while (m >= 12) { m -= 12; y += 1; }
    t = Date.UTC(y, m, 1);
  }
  return ticks;
}

function fmtMonth(t) {
  return new Date(t).toLocaleDateString(undefined,
    { year: "2-digit", month: "short" });
}

function fmtScore(s) {
  return s > 0 ? `+${s}` : `${s}`;
}

const isScored = (i) =>
  i.sentiment_score !== null && i.sentiment_score !== undefined;

// Monthly averages of the given dated+scored items, as line points.
function monthlyAverages(datedScored) {
  const buckets = new Map();
  for (const i of datedScored) {
    const d = new Date(i.published_at);
    const key = `${d.getUTCFullYear()}-`
      + `${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(i.sentiment_score);
  }
  return [...buckets.entries()]
    .map(([month, scores]) => ({
      x: monthMid(month), month, count: scores.length,
      avg: round3(scores.reduce((a, b) => a + b, 0) / scores.length),
    }))
    .sort((a, b) => a.x - b.x);
}

// Custom tooltip: an item dot shows its title/meta/snippet; an average-line
// point shows the month's average and count.
function ChartTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null;
  const p = payload[0].payload;
  if (p && p.title) {
    return (
      <div className="sentiment-tip">
        <div className="tip-title">{p.title}</div>
        <div className="tip-meta">
          {p.category ? `${p.category} · ` : ""}{p.source} ·{" "}
          {new Date(p.x).toLocaleDateString()} · {fmtScore(p.y)}
        </div>
        {p.snippet && <div className="tip-snippet">{p.snippet}</div>}
        <div className="tip-hint">Click the dot to open the article.</div>
      </div>
    );
  }
  return (
    <div className="sentiment-tip">
      <div className="tip-meta">
        {p.month} · avg {p.avg} ({p.count} items)
      </div>
    </div>
  );
}

// Every dated+scored item as a clickable dot at (publish date, score), coloured
// by sentiment, with the monthly-average line overlaid. Category checkboxes
// re-scope BOTH the dots and the line to the selected categories, so a
// low-volume category (e.g. forums) isn't hidden behind high-volume news.
export function SentimentGraph({ items }) {
  const all = items || [];

  // Categories that actually appear on the graph (have a dated+scored item),
  // in first-appearance order (RunView tags items in category display order).
  const categories = [];
  for (const i of all) {
    if (i.published_at && isScored(i) && !categories.includes(i.category)) {
      categories.push(i.category);
    }
  }

  const [disabled, setDisabled] = useState(() => new Set()); // off categories
  const isOn = (c) => !disabled.has(c);
  const toggle = (c) => setDisabled((prev) => {
    const next = new Set(prev);
    if (next.has(c)) next.delete(c); else next.add(c);
    return next;
  });

  const selected = all.filter((i) => isOn(i.category));
  const scored = selected.filter(isScored);
  const datedScored = scored.filter((i) => i.published_at);

  const scatterData = datedScored.map((i) => ({
    x: new Date(i.published_at).getTime(), y: i.sentiment_score,
    sentiment_label: i.sentiment_label, title: i.title, source: i.source,
    snippet: i.sentiment_summary || i.snippet, url: i.url, category: i.category,
  }));
  const lineData = monthlyAverages(datedScored);
  const overall = scored.length
    ? round3(scored.reduce((a, i) => a + i.sentiment_score, 0) / scored.length)
    : null;
  const undatedScored = scored.filter((i) => !i.published_at).length;
  const unknown = selected.filter((i) => !isScored(i)).length;

  const xVals = scatterData.map((d) => d.x).concat(lineData.map((d) => d.x));
  let xMin = xVals.length ? Math.min(...xVals) : 0;
  let xMax = xVals.length ? Math.max(...xVals) : 0;
  if (xMin === xMax) { // single point: pad by ~15 days so a tick renders
    xMin -= 15 * 864e5;
    xMax += 15 * 864e5;
  }

  const openItem = (node) => {
    const url = node && (node.url || (node.payload && node.payload.url));
    if (url) window.open(url, "_blank", "noopener,noreferrer");
  };

  return (
    <div className="sentiment-graph">
      <div className="sentiment-headline">
        Overall sentiment: <strong>{overall ?? "—"}</strong>
      </div>
      {categories.length > 1 && (
        <div className="sentiment-cats" role="group"
             aria-label="Filter categories on the sentiment graph">
          {categories.map((c) => (
            <label key={c} className="sentiment-cat">
              <input type="checkbox" checked={isOn(c)}
                     onChange={() => toggle(c)} />
              {c}
            </label>
          ))}
        </div>
      )}
      {scatterData.length > 0 ? (
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis type="number" dataKey="x" domain={[xMin, xMax]}
                   ticks={monthTicks(xMin, xMax)} tick={{ fontSize: 12 }}
                   tickFormatter={fmtMonth} />
            <YAxis domain={[-1, 1]} ticks={[-1, -0.5, 0, 0.5, 1]}
                   tick={{ fontSize: 12 }} width={36} />
            <ReferenceLine y={0} stroke="#888" />
            <Tooltip content={<ChartTooltip />} />
            <Scatter data={scatterData} dataKey="y" cursor="pointer"
                     onClick={openItem} isAnimationActive={false}>
              {scatterData.map((d, i) => (
                <Cell key={i} fill={dotColor(d.sentiment_label)} />
              ))}
            </Scatter>
            {lineData.length >= 2 && (
              <Line data={lineData} dataKey="avg" type="monotone"
                    stroke="#2f5bea" dot={false} connectNulls
                    isAnimationActive={false} />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      ) : (
        <p className="muted sentiment-empty-line">
          {selected.length === 0
            ? "Select a category to plot its items."
            : "No dated, scored items to plot for the selected categories."}
        </p>
      )}
      {undatedScored > 0 && (
        <p className="muted sentiment-note">
          {undatedScored} undated items are scored but not on the timeline.
        </p>
      )}
      {unknown > 0 && (
        <p className="muted sentiment-note">
          {unknown} items could not be scored.
        </p>
      )}
    </div>
  );
}
