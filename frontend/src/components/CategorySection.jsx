import { useState } from "react";
import { StatusChip } from "./StatusChip.jsx";
import { ContentItemRow } from "./ContentItemRow.jsx";

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

// All categories start collapsed on first load; the user's per-section toggle
// is remembered for the session (sessionStorage).
function defaultExpanded() {
  return false;
}

export function CategorySection({ category, sessionKey }) {
  const storageKey = sessionKey ? `${sessionKey}:${category.key}` : null;
  const [expanded, setExpanded] = useState(() => {
    if (storageKey) {
      const saved = sessionStorage.getItem(storageKey);
      if (saved !== null) return saved === "1";
    }
    return defaultExpanded();
  });

  function toggle() {
    setExpanded((prev) => {
      const next = !prev;
      if (storageKey) sessionStorage.setItem(storageKey, next ? "1" : "0");
      return next;
    });
  }

  const working =
    category.status === "pending" || category.status === "running";
  const label = CATEGORY_LABELS[category.key] || category.key;

  return (
    <section className="category" id={`cat-${category.key}`}>
      <button
        className="category-head"
        aria-expanded={expanded}
        onClick={toggle}
      >
        <span className="category-name">{label}</span>
        <StatusChip
          variant="category"
          status={category.status}
          count={category.item_count}
        />
      </button>
      {/* Body stays in the DOM (hidden when collapsed) so its state copy is
          always available to assistive tech and tests. */}
      <div className="category-body" hidden={!expanded}>
          {category.summary && <p className="category-summary">{category.summary}</p>}
          {working && <p className="muted">Working…</p>}
          {category.status === "yellow" && (
            <p className="muted">
              No content found for this category in the selected time window.
            </p>
          )}
          {category.status === "red" && (
            // Always a generic message — internal/LLM error detail is logged
            // server-side, never shown to the user.
            <p className="field-error">
              This category could not be researched due to an error. You can
              retry via Refresh.
            </p>
          )}
          {category.items && category.items.length > 0 && (
            <ul className="item-list">
              {category.items.map((item, i) => (
                <ContentItemRow key={item.url + i} item={item} />
              ))}
            </ul>
          )}
      </div>
    </section>
  );
}
