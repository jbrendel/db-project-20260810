import { render, screen, fireEvent } from "@testing-library/react";
import { SentimentGraph, monthTicks } from "../SentimentGraph";

function item(category, date, score, label, over) {
  return {
    category, published_at: date, sentiment_score: score,
    sentiment_label: label, title: `${category}-${date}`, source: "n.com",
    snippet: "s", url: `https://n.com/${category}-${date}`, ...over,
  };
}

// News is all +1, Reddit is all -1, so the mean is 0 with both selected.
const ITEMS = [
  item("News", "2026-01-10T00:00:00Z", 1.0, "positive"),
  item("News", "2026-02-10T00:00:00Z", 1.0, "positive"),
  item("Reddit", "2026-01-15T00:00:00Z", -1.0, "negative"),
  item("Reddit", "2026-02-15T00:00:00Z", -1.0, "negative"),
];

test("headline is the mean of the scored, selected items", () => {
  render(<SentimentGraph items={ITEMS} />);
  expect(screen.getByText(/overall sentiment/i))
    .toHaveTextContent("Overall sentiment: 0");
});

test("shows a checkbox per graphed category, all on by default", () => {
  render(<SentimentGraph items={ITEMS} />);
  expect(screen.getByLabelText("News")).toBeChecked();
  expect(screen.getByLabelText("Reddit")).toBeChecked();
});

test("disabling a category re-scopes the average (isolate Reddit)", () => {
  render(<SentimentGraph items={ITEMS} />);
  fireEvent.click(screen.getByLabelText("News")); // turn News off
  expect(screen.getByText(/overall sentiment/i))
    .toHaveTextContent("Overall sentiment: -1");
});

test("deselecting all categories prompts to select one", () => {
  render(<SentimentGraph items={ITEMS} />);
  fireEvent.click(screen.getByLabelText("News"));
  fireEvent.click(screen.getByLabelText("Reddit"));
  expect(screen.getByText(/select a category to plot/i)).toBeInTheDocument();
});

test("reports undated-scored and unknown counts", () => {
  const items = [
    item("News", "2026-01-10T00:00:00Z", 0.5, "positive"),
    item("News", null, 0.2, "neutral"),          // undated but scored
    item("News", "2026-02-10T00:00:00Z", null, null),  // unscored
  ];
  render(<SentimentGraph items={items} />);
  expect(screen.getByText(/1 undated items/i)).toBeInTheDocument();
  expect(screen.getByText(/1 items could not be scored/i)).toBeInTheDocument();
});

test("empty state when there are no dated, scored items", () => {
  render(<SentimentGraph items={[item("News", null, 0.5, "positive")]} />);
  expect(screen.getByText(/no dated, scored items to plot/i))
    .toBeInTheDocument();
});

test("single category hides the checkbox row", () => {
  render(<SentimentGraph items={[item("News", "2026-01-10T00:00:00Z", 0.5,
                                       "positive")]} />);
  expect(screen.queryByLabelText("News")).not.toBeInTheDocument();
});

test("monthTicks returns month-start ticks across a short range", () => {
  const ticks = monthTicks(Date.UTC(2026, 0, 10), Date.UTC(2026, 7, 20));
  expect(ticks.length).toBeGreaterThanOrEqual(7);      // Jan..Aug
  expect(ticks.every((t) => new Date(t).getUTCDate() === 1)).toBe(true);
});

test("monthTicks thins a multi-year range to a readable count", () => {
  const ticks = monthTicks(Date.UTC(2023, 0, 1), Date.UTC(2026, 7, 1));
  expect(ticks.length).toBeGreaterThan(0);
  expect(ticks.length).toBeLessThanOrEqual(14);
});

test("monthTicks handles an empty/invalid range", () => {
  expect(monthTicks(5, 1)).toEqual([]);
});
