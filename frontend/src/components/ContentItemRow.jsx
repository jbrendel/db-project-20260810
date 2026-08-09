function formatDate(iso) {
  return new Date(iso).toLocaleDateString();
}

// Defense-in-depth: the backend already drops non-http(s) URLs, but never
// render an unsafe scheme (javascript:/data:/file:) as a clickable href.
function isSafeHttpUrl(url) {
  try {
    const parsed = new URL(url, window.location.origin);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

function SentimentPill({ score, label }) {
  if (score === null || score === undefined || !label) {
    return (
      <span className="sentiment-pill sentiment-unknown"
            aria-label="Sentiment unknown">
        —
      </span>
    );
  }
  const shown = score > 0 ? `+${score}` : `${score}`;
  return (
    <span className={`sentiment-pill sentiment-${label}`}>
      {label} {shown}
    </span>
  );
}

export function ContentItemRow({ item }) {
  const safe = isSafeHttpUrl(item.url);
  return (
    <li className="item-row">
      {safe ? (
        <a href={item.url} target="_blank" rel="noopener noreferrer">
          {item.title}
        </a>
      ) : (
        <span className="item-title-unsafe">{item.title}</span>
      )}
      <div className="item-meta">
        <span className="item-source">{item.source}</span>
        {item.is_undated ? (
          <span className="item-undated" title="Publish date unknown">
            undated
          </span>
        ) : (
          <span className="item-date">{formatDate(item.published_at)}</span>
        )}
        <SentimentPill score={item.sentiment_score}
                       label={item.sentiment_label} />
      </div>
      {item.snippet && <p className="item-snippet">{item.snippet}</p>}
    </li>
  );
}
