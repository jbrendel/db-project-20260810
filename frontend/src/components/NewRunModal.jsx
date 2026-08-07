import { useEffect, useRef, useState } from "react";
import * as api from "../api";

const BORDERLINE = [
  { key: "reddit", label: "Reddit" },
  { key: "forums", label: "Other forums" },
];

// The modal does NOT navigate — on success it calls onCreated(run) + onClose();
// the parent (HomePage, inside the Router) navigates (Task 17/18 separation).
export function NewRunModal({ onClose, onCreated }) {
  const [inputText, setInputText] = useState("");
  const [lookback, setLookback] = useState(36);
  const [borderline, setBorderline] = useState({});
  const [fieldError, setFieldError] = useState({ field: null, message: null });
  const [nonFieldError, setNonFieldError] = useState(null);
  const [pending, setPending] = useState(false);
  const inputRef = useRef(null);
  const dialogRef = useRef(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKey(e) {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab") trapFocus(e, dialogRef.current);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  function clientValidate() {
    if (!inputText.trim()) {
      setFieldError({ field: "input_text", message: "Please enter a name or URL." });
      return false;
    }
    const months = Number(lookback);
    if (!Number.isInteger(months) || months < 1 || months > 600) {
      setFieldError({
        field: "lookback_months",
        message: "Look-back must be a whole number of months (1–600).",
      });
      return false;
    }
    return true;
  }

  async function onSubmit(e) {
    e.preventDefault();
    setFieldError({ field: null, message: null });
    setNonFieldError(null);
    if (!clientValidate()) return;
    setPending(true);
    try {
      const run = await api.createRun({
        input_text: inputText.trim(),
        lookback_months: Number(lookback),
        borderline_options: borderline,
      });
      onCreated(run);
      onClose();
    } catch (err) {
      const body = err.body || {};
      if (err.status === 400 && body.field) {
        setFieldError({ field: body.field, message: body.detail });
        // A field without a dedicated inline slot (e.g. borderline_options)
        // would otherwise show nothing; surface it as a non-field line too.
        if (!["input_text", "lookback_months"].includes(body.field)) {
          setNonFieldError(body.detail);
        }
      } else if (err.status === 400) {
        setNonFieldError(body.detail || "Please check your input.");
      } else {
        // §13: a non-400 create failure (5xx / network / timeout) shows the
        // fixed retry line, not the raw server body.
        setNonFieldError("Could not start the run — please retry.");
      }
      setPending(false);
    }
  }

  const errFor = (field) =>
    fieldError.field === field ? fieldError.message : null;

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label="Start a new run"
        ref={dialogRef}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h2>New run</h2>
        <form onSubmit={onSubmit}>
          <label htmlFor="input_text">Name or URL</label>
          <input
            id="input_text"
            ref={inputRef}
            value={inputText}
            aria-describedby={errFor("input_text") ? "err-input" : undefined}
            onChange={(e) => setInputText(e.target.value)}
          />
          {errFor("input_text") && (
            <p id="err-input" className="field-error">
              {errFor("input_text")}
            </p>
          )}

          <label htmlFor="lookback">Look-back (months)</label>
          <input
            id="lookback"
            type="number"
            min="1"
            max="600"
            value={lookback}
            aria-describedby={
              errFor("lookback_months") ? "err-lookback" : undefined
            }
            onChange={(e) => setLookback(e.target.value)}
          />
          {errFor("lookback_months") && (
            <p id="err-lookback" className="field-error">
              {errFor("lookback_months")}
            </p>
          )}

          <fieldset className="borderline">
            <legend>Extra sources</legend>
            {BORDERLINE.map((b) => (
              <label key={b.key} className="checkbox">
                <input
                  type="checkbox"
                  checked={!!borderline[b.key]}
                  onChange={(e) =>
                    setBorderline((prev) => ({
                      ...prev,
                      [b.key]: e.target.checked,
                    }))
                  }
                />
                {b.label}
              </label>
            ))}
          </fieldset>

          {nonFieldError && <p className="field-error">{nonFieldError}</p>}

          <div className="modal-actions">
            <button type="button" onClick={onClose} disabled={pending}>
              Cancel
            </button>
            <button type="submit" disabled={pending}>
              Start
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function trapFocus(e, container) {
  if (!container) return;
  const focusable = container.querySelectorAll(
    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
  );
  if (focusable.length === 0) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first.focus();
  }
}
