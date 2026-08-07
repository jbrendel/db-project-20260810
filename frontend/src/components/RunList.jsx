import { useNavigate } from "react-router-dom";
import * as api from "../api";
import { StatusChip } from "./StatusChip.jsx";

function formatTime(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString();
}

export function RunList({ runs, onChanged }) {
  const navigate = useNavigate();

  async function onDelete(e, run) {
    e.stopPropagation();
    if (!window.confirm(`Delete the run for "${run.input_text}"?`)) return;
    await api.deleteRun(run.id);
    onChanged();
  }

  if (!runs.length) {
    return <p className="empty">No runs yet. Start one with “New run”.</p>;
  }

  return (
    <ul className="run-list">
      {runs.map((run) => (
        <li
          key={run.id}
          className="run-row"
          role="button"
          tabIndex={0}
          onClick={() => navigate(`/runs/${run.id}`)}
          onKeyDown={(e) => {
            if (e.key === "Enter") navigate(`/runs/${run.id}`);
          }}
        >
          <span className="run-name">{run.input_text}</span>
          <span className="run-time">{formatTime(run.started_at)}</span>
          <StatusChip variant="run" status={run.status} />
          <button
            className="delete-btn"
            aria-label={`Delete run for ${run.input_text}`}
            onClick={(e) => onDelete(e, run)}
          >
            🗑
          </button>
        </li>
      ))}
    </ul>
  );
}
