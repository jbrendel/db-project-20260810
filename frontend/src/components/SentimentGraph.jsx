import { useState } from "react";
import {
  ResponsiveContainer, ComposedChart, LineChart, Line, Scatter, XAxis, YAxis,
  Tooltip, ReferenceLine, CartesianGrid, Cell,
} from "recharts";

// Sentiment sign -> dot colour (matches the per-item pill palette).
const DOT_COLORS = {
  positive: "#1f8a4c", neutral: "#8a94a6", negative: "#c0392b",
};

function dotColor(label) {
  return DOT_COLORS[label] || DOT_COLORS.neutral;
}

function monthMid(month) {
  const [y, m] = month.split("-").map(Number);
  return Date.UTC(y, m - 1, 15); // plot a month's average at mid-month
}

// First-of-month tick timestamps spanning [minMs, maxMs], thinned to ~<=12
// ticks. A numeric time XAxis won't auto-generate readable date ticks, so we
// supply them explicitly (fixes a bare x-axis in the scatter mode).
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

// Run-level average sentiment over the lookback window. Two modes:
//   "avg"   — the monthly-average line (default);
//   "items" — every dated+scored item as a clickable dot, with the monthly
//             average overlaid, for exploring positive/negative outliers.
export function SentimentGraph({ timeline, summary, items }) {
  const [mode, setMode] = useState(() => {
    try {
      return sessionStorage.getItem("sentimentMode") || "avg";
    } catch {
      return "avg";
    }
  });
  const chooseMode = (m) => {
    setMode(m);
    try {
      sessionStorage.setItem("sentimentMode", m);
    } catch {
      /* ignore storage errors */
    }
  };

  const monthPoints = (timeline || []).filter((b) => b.avg_score !== null);
  const hasLine = monthPoints.length >= 2;
  const lineData = monthPoints.map((b) => ({
    x: monthMid(b.month), avg: b.avg_score, count: b.item_count,
    month: b.month,
  }));
  const scatterData = (items || []).map((i) => ({
    x: new Date(i.published_at).getTime(), y: i.sentiment_score,
    sentiment_label: i.sentiment_label, title: i.title, source: i.source,
    snippet: i.sentiment_summary || i.snippet, url: i.url,
    category: i.category,
  }));

  const overall = summary?.overall_avg;
  const canChart = mode === "items" ? scatterData.length > 0 : hasLine;

  // Explicit numeric-time domain + month ticks for the scatter mode's x-axis.
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
      <div className="sentiment-modes" role="radiogroup"
           aria-label="Sentiment chart mode">
        <label className="sentiment-mode">
          <input type="radio" name="sentiment-mode" checked={mode === "avg"}
                 onChange={() => chooseMode("avg")} />
          Monthly average
        </label>
        <label className="sentiment-mode">
          <input type="radio" name="sentiment-mode" checked={mode === "items"}
                 onChange={() => chooseMode("items")} />
          Individual items
        </label>
      </div>
      {canChart && mode === "items" && (
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
            {hasLine && (
              <Line data={lineData} dataKey="avg" type="monotone"
                    stroke="#2f5bea" dot={false} connectNulls
                    isAnimationActive={false} />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      )}
      {canChart && mode === "avg" && (
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={timeline} accessibilityLayer
                     margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="month" tick={{ fontSize: 12 }} minTickGap={24} />
            <YAxis domain={[-1, 1]} ticks={[-1, -0.5, 0, 0.5, 1]}
                   tick={{ fontSize: 12 }} width={36} />
            <ReferenceLine y={0} stroke="#888" />
            <Tooltip
              formatter={(v, _n, item) => [
                v === null ? "no data"
                  : `${v} (${item?.payload?.item_count ?? 0} items)`,
                "avg sentiment"]} />
            <Line type="monotone" dataKey="avg_score" stroke="#2f5bea"
                  connectNulls dot={{ r: 3 }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      )}
      {!canChart && (
        <p className="muted sentiment-empty-line">
          {mode === "items"
            ? "No dated, scored items to plot yet."
            : "Not enough dated, scored items to chart a trend yet."}
        </p>
      )}
      {summary?.undated_scored_count > 0 && (
        <p className="muted sentiment-note">
          {summary.undated_scored_count} undated items are scored but not on the
          timeline.
        </p>
      )}
      {summary?.unknown_count > 0 && (
        <p className="muted sentiment-note">
          {summary.unknown_count} items could not be scored.
        </p>
      )}
    </div>
  );
}
