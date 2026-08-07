function formatDate(iso) {
  return new Date(iso).toLocaleDateString();
}

export function ContentItemRow({ item }) {
  return (
    <li className="item-row">
      <a href={item.url} target="_blank" rel="noopener noreferrer">
        {item.title}
      </a>
      <div className="item-meta">
        <span className="item-source">{item.source}</span>
        {item.is_undated ? (
          <span className="item-undated" title="Publish date unknown">
            undated
          </span>
        ) : (
          <span className="item-date">{formatDate(item.published_at)}</span>
        )}
      </div>
      {item.snippet && <p className="item-snippet">{item.snippet}</p>}
    </li>
  );
}
