import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import * as api from "../api";
import { usePolling } from "../usePolling.js";
import { RunList } from "./RunList.jsx";
import { NewRunModal } from "./NewRunModal.jsx";

export function HomePage() {
  const navigate = useNavigate();
  const [runs, setRuns] = useState([]);
  const [stale, setStale] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);

  const loadRuns = useCallback(async () => {
    try {
      const data = await api.listRuns();
      setRuns(data.results);
      setStale(false);
    } catch (err) {
      setStale(true);
      throw err; // let usePolling count the failure and back off
    }
  }, []);

  const anyBlue = runs.some((r) => r.status === "blue");
  usePolling(loadRuns, anyBlue, [anyBlue]);

  return (
    <div className="page">
      <header className="app-header">
        <h1>Drumbeat</h1>
        <button className="primary" onClick={() => setModalOpen(true)}>
          New run
        </button>
      </header>

      {stale && (
        <div className="banner" role="status">
          Connection problem — retrying. Showing last-known data.
        </div>
      )}

      <RunList runs={runs} onChanged={loadRuns} />

      {modalOpen && (
        <NewRunModal
          onClose={() => setModalOpen(false)}
          onCreated={(run) => navigate(`/runs/${run.id}`)}
        />
      )}
    </div>
  );
}
