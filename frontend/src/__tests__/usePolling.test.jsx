import { renderHook } from "@testing-library/react";
import { vi } from "vitest";
import { usePolling } from "../usePolling";

function setHidden(value) {
  Object.defineProperty(document, "hidden", {
    value,
    configurable: true,
  });
}

test("fetches on mount, polls while active", () => {
  vi.useFakeTimers();
  setHidden(false);
  const fn = vi.fn().mockResolvedValue({});
  renderHook(() => usePolling(fn, true, []));
  expect(fn).toHaveBeenCalledTimes(1); // mount fetch
  vi.advanceTimersByTime(2000);
  expect(fn).toHaveBeenCalledTimes(2); // one poll
  vi.useRealTimers();
});

test("does not poll while hidden", () => {
  vi.useFakeTimers();
  setHidden(true);
  const fn = vi.fn().mockResolvedValue({});
  renderHook(() => usePolling(fn, true, []));
  expect(fn).toHaveBeenCalledTimes(1); // mount fetch still happens
  vi.advanceTimersByTime(4000);
  expect(fn).toHaveBeenCalledTimes(1); // ticks skipped while hidden
  setHidden(false);
  vi.useRealTimers();
});

test("refetches on visibility restore", () => {
  setHidden(false);
  const fn = vi.fn().mockResolvedValue({});
  renderHook(() => usePolling(fn, true, []));
  expect(fn).toHaveBeenCalledTimes(1);
  document.dispatchEvent(new Event("visibilitychange"));
  expect(fn).toHaveBeenCalledTimes(2);
});

test("backs off after a failure (skips a tick)", async () => {
  vi.useFakeTimers();
  setHidden(false);
  const fn = vi.fn().mockRejectedValue(new Error("boom"));
  renderHook(() => usePolling(fn, true, []));
  // mount call rejects; its .catch sets skip.n = 1.
  await vi.runAllTicks();
  await Promise.resolve();
  const afterMount = fn.mock.calls.length; // 1
  vi.advanceTimersByTime(2000); // this tick should be skipped
  expect(fn).toHaveBeenCalledTimes(afterMount); // no new call: backed off
  vi.useRealTimers();
});
