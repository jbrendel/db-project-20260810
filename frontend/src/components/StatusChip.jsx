// Run and category vocabularies DIFFER on the same status value (§13), so the
// caller passes an explicit `variant`. Every chip is label + icon (never colour
// alone, WCAG 1.4.1); spinners carry an aria-label matching the label.

const RUN_LABELS = {
  green: { label: "Complete", icon: "✓" },
  yellow: { label: "Partial", icon: "⚠" },
  red: { label: "Failed", icon: "✕" },
  blue: { label: "Running", icon: "spinner" },
};

function categoryMeta(status, count) {
  switch (status) {
    case "green":
      return { label: `Found (${count ?? 0})`, icon: "✓" };
    case "yellow":
      return { label: "None found", icon: "–" };
    case "red":
      return { label: "Error", icon: "✕" };
    default: // pending / running
      return { label: "Working", icon: "spinner" };
  }
}

export function StatusChip({ variant, status, count, succeeded, total }) {
  let meta;
  if (variant === "run") {
    meta = RUN_LABELS[status] || { label: status, icon: "" };
    // A Partial run reports how many categories completed without error, so
    // the user sees the scope of the partial result (e.g. "Partial (3 of 5)").
    if (
      status === "yellow" &&
      Number.isInteger(succeeded) &&
      Number.isInteger(total)
    ) {
      meta = { label: `Partial (${succeeded} of ${total})`, icon: "⚠" };
    }
  } else {
    meta = categoryMeta(status, count);
  }
  const isSpinner = meta.icon === "spinner";
  return (
    <span className={`chip chip-${variant} chip-${status}`} data-status={status}>
      {isSpinner ? (
        <span className="spinner" role="img" aria-label={meta.label} />
      ) : (
        <span aria-hidden="true" className="chip-icon">
          {meta.icon}
        </span>
      )}
      <span className="chip-label">{meta.label}</span>
    </span>
  );
}
