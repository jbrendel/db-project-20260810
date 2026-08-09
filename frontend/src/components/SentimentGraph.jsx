import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip,
  ReferenceLine, CartesianGrid,
} from "recharts";

// Run-level average sentiment per month over the lookback window. The caller
// mounts this only when there is scored data (summary.scored_count > 0). The
// headline + coverage notes always render; the chart needs >= 2 dated points,
// otherwise an inline empty line replaces it (so overall/undated are never
// hidden — e.g. when every scored item is undated). Null months render as gaps.
export function SentimentGraph({ timeline, summary }) {
  const points = (timeline || []).filter((b) => b.avg_score !== null);
  const hasChart = points.length >= 2;
  const overall = summary?.overall_avg;
  return (
    <div className="sentiment-graph">
      <div className="sentiment-headline">
        Overall sentiment: <strong>{overall ?? "—"}</strong>
      </div>
      {hasChart ? (
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={timeline} accessibilityLayer
                     margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="month" tick={{ fontSize: 12 }} minTickGap={24} />
            <YAxis domain={[-1, 1]} ticks={[-1, -0.5, 0, 0.5, 1]}
                   tick={{ fontSize: 12 }} width={36} />
            <ReferenceLine y={0} stroke="#888" />
            <Tooltip formatter={(v) => [v, "avg sentiment"]} />
            <Line type="monotone" dataKey="avg_score" stroke="#2f5bea"
                  connectNulls dot={{ r: 3 }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <p className="muted sentiment-empty-line">
          Not enough dated, scored items to chart a sentiment trend yet.
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
