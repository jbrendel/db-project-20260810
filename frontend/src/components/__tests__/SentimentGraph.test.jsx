import { render, screen, fireEvent } from "@testing-library/react";
import { SentimentGraph } from "../SentimentGraph";

test("shows inline empty line but keeps headline with <2 dated points", () => {
  render(
    <SentimentGraph
      timeline={[{ month: "2026-01", avg_score: 0.5, item_count: 1 },
                 { month: "2026-02", avg_score: null, item_count: 0 }]}
      summary={{ overall_avg: 0.5, undated_scored_count: 2, unknown_count: 0 }}
    />,
  );
  expect(screen.getByText(/not enough dated/i)).toBeInTheDocument();
  expect(screen.getByText(/overall sentiment/i)).toBeInTheDocument();
  expect(screen.getByText(/2 undated items/i)).toBeInTheDocument();
});

test("renders headline, undated + unknown notes when charted", () => {
  render(
    <SentimentGraph
      timeline={[{ month: "2026-01", avg_score: 0.5, item_count: 1 },
                 { month: "2026-02", avg_score: -0.2, item_count: 2 }]}
      summary={{ overall_avg: 0.15, undated_scored_count: 3, unknown_count: 4 }}
    />,
  );
  expect(screen.getByText(/overall sentiment/i)).toBeInTheDocument();
  expect(screen.getByText(/3 undated items/i)).toBeInTheDocument();
  expect(screen.getByText(/4 items could not be scored/i)).toBeInTheDocument();
});

test("omits the unknown note when unknown_count is 0", () => {
  render(
    <SentimentGraph
      timeline={[{ month: "2026-01", avg_score: 0.5, item_count: 1 },
                 { month: "2026-02", avg_score: -0.2, item_count: 2 }]}
      summary={{ overall_avg: 0.15, undated_scored_count: 0, unknown_count: 0 }}
    />,
  );
  expect(screen.queryByText(/could not be scored/i)).not.toBeInTheDocument();
});

const TL = [{ month: "2026-01", avg_score: 0.5, item_count: 1 },
            { month: "2026-02", avg_score: -0.2, item_count: 2 }];
const ITEMS = [
  { published_at: "2026-01-10T00:00:00Z", sentiment_score: 0.5,
    sentiment_label: "positive", title: "Good news", source: "n.com",
    snippet: "s", url: "https://n.com/a" },
  { published_at: "2026-02-02T00:00:00Z", sentiment_score: -0.5,
    sentiment_label: "negative", title: "Bad news", source: "n.com",
    snippet: "s", url: "https://n.com/b" },
];

test("offers a mode selector defaulting to monthly average", () => {
  sessionStorage.clear();
  render(<SentimentGraph timeline={TL}
    summary={{ overall_avg: 0.15, undated_scored_count: 0, unknown_count: 0 }}
    items={ITEMS} />);
  const avg = screen.getByLabelText(/monthly average/i);
  const items = screen.getByLabelText(/individual items/i);
  expect(avg).toBeChecked();
  expect(items).not.toBeChecked();
});

test("switches to individual-items mode without crashing", () => {
  sessionStorage.clear();
  render(<SentimentGraph timeline={TL}
    summary={{ overall_avg: 0.15, undated_scored_count: 0, unknown_count: 0 }}
    items={ITEMS} />);
  fireEvent.click(screen.getByLabelText(/individual items/i));
  expect(screen.getByLabelText(/individual items/i)).toBeChecked();
  // Headline still present after switching modes.
  expect(screen.getByText(/overall sentiment/i)).toBeInTheDocument();
});

test("items mode with no dated items shows an empty line", () => {
  sessionStorage.clear();
  render(<SentimentGraph timeline={TL}
    summary={{ overall_avg: 0.15, undated_scored_count: 0, unknown_count: 0 }}
    items={[]} />);
  fireEvent.click(screen.getByLabelText(/individual items/i));
  expect(screen.getByText(/no dated, scored items to plot/i))
    .toBeInTheDocument();
});
