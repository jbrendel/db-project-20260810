import { render, screen } from "@testing-library/react";
import { ContentItemRow } from "../ContentItemRow";

test("safe https url renders as a link", () => {
  render(
    <ContentItemRow
      item={{
        title: "Headline",
        url: "https://n.com/a",
        source: "n.com",
        is_undated: true,
        snippet: "s",
      }}
    />,
  );
  const link = screen.getByRole("link", { name: "Headline" });
  expect(link).toHaveAttribute("href", "https://n.com/a");
  expect(link).toHaveAttribute("rel", "noopener noreferrer");
});

test("unsafe javascript: url renders title as text, not a link", () => {
  render(
    <ContentItemRow
      item={{
        title: "Sketchy",
        url: "javascript:alert(1)",
        source: "n.com",
        is_undated: true,
        snippet: "s",
      }}
    />,
  );
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  expect(screen.getByText("Sketchy")).toBeInTheDocument();
});

test("shows a sentiment pill for a scored item", () => {
  render(
    <ContentItemRow
      item={{ title: "H", url: "https://n.com/a", source: "n.com",
              is_undated: true, snippet: "s", sentiment_score: 0.6,
              sentiment_label: "positive" }}
    />,
  );
  expect(screen.getByText(/positive/i)).toBeInTheDocument();
  expect(screen.getByText(/\+0\.6/)).toBeInTheDocument();
});

test("shows a muted marker when sentiment is unknown", () => {
  render(
    <ContentItemRow
      item={{ title: "H", url: "https://n.com/a", source: "n.com",
              is_undated: true, snippet: "s", sentiment_score: null,
              sentiment_label: null }}
    />,
  );
  expect(screen.getByLabelText(/sentiment unknown/i)).toBeInTheDocument();
});
