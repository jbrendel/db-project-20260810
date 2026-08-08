import { render, screen, fireEvent } from "@testing-library/react";
import { CategorySection } from "../CategorySection";

test("empty finished category shows None-found copy", () => {
  render(
    <CategorySection
      category={{
        key: "podcasts",
        status: "yellow",
        item_count: 0,
        summary: null,
        items: [],
      }}
    />,
  );
  expect(screen.getByText(/no content found/i)).toBeInTheDocument();
});

test("green category renders items and Found chip", () => {
  render(
    <CategorySection
      category={{
        key: "news",
        status: "green",
        item_count: 1,
        summary: "A summary.",
        items: [
          {
            title: "Headline",
            url: "https://n.com/a",
            source: "n.com",
            is_undated: true,
            snippet: "snip",
          },
        ],
      }}
    />,
  );
  expect(screen.getByText("Found (1)")).toBeInTheDocument();
  expect(screen.getByText("Headline")).toBeInTheDocument();
  expect(screen.getByText("undated")).toBeInTheDocument();
});

test("red category shows a generic error, not the raw server message", () => {
  render(
    <CategorySection
      category={{
        key: "news",
        status: "red",
        item_count: 0,
        error: "Expecting value: line 1 column 1 (char 0)",
        items: [],
      }}
    />,
  );
  // The raw internal error must NOT be shown; only a generic message.
  expect(
    screen.queryByText(/expecting value/i),
  ).not.toBeInTheDocument();
  expect(
    screen.getByText(/could not be researched due to an error/i),
  ).toBeInTheDocument();
  expect(screen.getByText(/retry via refresh/i)).toBeInTheDocument();
});

test("item link opens safely in a new tab (after expanding)", () => {
  render(
    <CategorySection
      category={{
        key: "news",
        status: "green",
        item_count: 1,
        items: [
          {
            title: "Headline",
            url: "https://n.com/a",
            source: "n.com",
            is_undated: false,
            published_at: "2025-01-02T00:00:00Z",
            snippet: "",
          },
        ],
      }}
    />,
  );
  // Categories start collapsed; expand to reveal the (accessible) link.
  fireEvent.click(screen.getByRole("button"));
  const link = screen.getByRole("link", { name: "Headline" });
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveAttribute("rel", "noopener noreferrer");
});

test("categories start collapsed and can be expanded", () => {
  render(
    <CategorySection
      category={{
        key: "news",
        status: "green",
        item_count: 3,
        items: [],
      }}
    />,
  );
  const head = screen.getByRole("button");
  expect(head).toHaveAttribute("aria-expanded", "false"); // collapsed default
  fireEvent.click(head);
  expect(head).toHaveAttribute("aria-expanded", "true");
});
