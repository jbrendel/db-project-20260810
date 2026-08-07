import { useCallback, useState } from "react";
import { useParams } from "react-router-dom";
import * as api from "../api";
import { usePolling } from "../usePolling.js";
import { StatusChip } from "./StatusChip.jsx";
import { CategorySection } from "./CategorySection.jsx";

const CATEGORY_LABELS = {
  news: "News articles",
  trade_publications: "Trade publications",
  blog_posts: "Blog posts",
  press_releases: "Press releases",
  social_posts: "Social posts",
  newsletters: "Newsletters",
  podcasts: "Podcasts",
  reddit: "Reddit",
  forums: "Forums",
};

function duration(run) {
  if (!run.started_at || !run.ended_at) return null;
  const secs = Math.round(
    (new Date(run.ended_at) - new Date(run.started_at)) / 1000,
  );
  return `${Math.floor(secs / 60)}m ${secs % 60}s`;
}

export function RunView() {
  const { id } = useParams();
  const [run, setRun] = useState(null);
  const [stale, setStale] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api.getRun(id);
      setRun(data);
      setStale(false);
    } catch (err) {
      setStale(true);
      throw err;
    }
  }, [id]);

  const active = run?.status === "blue";
  usePolling(load, active, [id, active]);

  if (!run) {
    return (
      <div className="page">
        {stale && <div className="banner" role="status">Connection problem — retrying.</div>}
        <p className="muted">Loading…</p>
      </div>
    );
  }

  async function onRefresh() {
    if (!window.confirm("Wipe this run's results and start over?")) return;
    await api.refreshRun(run.id);
    load();
  }

  const runEmpty =
    run.status === "red" &&
    (run.total_item_count ?? 0) === 0;

  return (
    <div className="page">
      <header className="run-header">
        <div>
          <h1>{run.input_text}</h1>
          <p className="muted run-times">
            Started {new Date(run.started_at).toLocaleString()}
            {run.ended_at && ` · Ended ${new Date(run.ended_at).toLocaleString()}`}
            {duration(run) && ` · ${duration(run)}`}
          </p>
        </div>
        <div className="run-header-right">
          <StatusChip variant="run" status={run.status} />
          <button onClick={onRefresh}>Refresh</button>
        </div>
      </header>

      {stale && (
        <div className="banner" role="status">
          Connection problem — retrying. Showing last-known data.
        </div>
      )}

      {run.status === "blue" && (
        <div className="banner-blue" role="status">
          Research in progress…
        </div>
      )}

      {run.executive_overview && (
        <div className="overview">
          <h2>Executive overview</h2>
          <p>{run.executive_overview}</p>
        </div>
      )}

      {runEmpty ? (
        <div className="run-empty">
          <p>This run found no third-party content anywhere.</p>
        </div>
      ) : (
        <>
          <nav className="category-index" aria-label="Categories">
            {run.categories.map((c) => (
              <a key={c.key} href={`#cat-${c.key}`}>
                {CATEGORY_LABELS[c.key] || c.key}
              </a>
            ))}
          </nav>
          <div className="categories">
            {run.categories.map((c) => (
              <CategorySection
                key={c.key}
                category={c}
                sessionKey={`run-${run.id}`}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
