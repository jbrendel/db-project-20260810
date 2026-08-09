import { render, screen } from "@testing-library/react";
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
