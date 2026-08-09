import "@testing-library/jest-dom/vitest"; // registers toBeInTheDocument etc.

// jsdom has no ResizeObserver; recharts' ResponsiveContainer needs it.
global.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
