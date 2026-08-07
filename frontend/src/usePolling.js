import { useEffect, useRef } from "react";

// fn resolves on success and REJECTS on failure so the hook can back off.
// The hook owns backoff: after consecutive failures it skips ticks, resetting
// on success (§12 "retries with backoff").
export function usePolling(fn, active, deps) {
  const saved = useRef(fn);
  saved.current = fn;
  useEffect(() => {
    let timer = null;
    const fails = { n: 0 };
    const skip = { n: 0 };
    // Update BOTH counters inside the handlers: run() is async, so setting
    // skip.n outside would use a stale fails.n (Codex impl-2 point 7).
    const run = () =>
      Promise.resolve(saved.current())
        .then(() => {
          fails.n = 0;
          skip.n = 0;
        })
        .catch(() => {
          fails.n = Math.min(fails.n + 1, 5);
          skip.n = fails.n;
        });
    run(); // fetch on mount
    const tick = () => {
      if (document.hidden) return;
      if (skip.n > 0) {
        skip.n -= 1;
        return;
      } // backoff: skip ticks
      run();
    };
    if (active) timer = setInterval(tick, 2000);
    const onVis = () => {
      if (active && !document.hidden) run();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      if (timer) clearInterval(timer);
      document.removeEventListener("visibilitychange", onVis);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, ...deps]);
}
