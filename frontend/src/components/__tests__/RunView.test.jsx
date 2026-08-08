import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { vi } from "vitest";
import * as api from "../../api";
import { RunView } from "../RunView";

function renderAt(id) {
  return render(
    <MemoryRouter initialEntries={[`/runs/${id}`]}>
      <Routes>
        <Route path="/runs/:id" element={<RunView />} />
      </Routes>
    </MemoryRouter>,
  );
}

test("red run with zero items shows whole-run empty state", async () => {
  vi.spyOn(api, "getRun").mockResolvedValue({
    id: 5,
    input_text: "Acme",
    status: "red",
    started_at: "2025-01-01T00:00:00Z",
    ended_at: "2025-01-01T00:01:00Z",
    executive_overview: "No third-party content was found.",
    total_item_count: 0,
    warnings: [],
    categories: [{ key: "news", status: "red", item_count: 0, items: [] }],
  });
  renderAt(5);
  await waitFor(() =>
    expect(screen.getByText(/found no third-party content anywhere/i))
      .toBeInTheDocument(),
  );
  // The wall of empty category sections is replaced by the single empty state.
  expect(screen.queryByText("News articles")).not.toBeInTheDocument();
});

test("shows a link back to the runs list", async () => {
  vi.spyOn(api, "getRun").mockResolvedValue({
    id: 3,
    input_text: "Acme",
    status: "green",
    started_at: "2025-01-01T00:00:00Z",
    ended_at: "2025-01-01T00:01:00Z",
    executive_overview: "ok",
    total_item_count: 1,
    warnings: [],
    categories: [],
  });
  renderAt(3);
  await waitFor(() =>
    expect(screen.getByRole("link", { name: /all runs/i }))
      .toHaveAttribute("href", "/"),
  );
});

test("yellow run header shows the X-of-Y partial badge", async () => {
  vi.spyOn(api, "getRun").mockResolvedValue({
    id: 8,
    input_text: "Acme",
    status: "yellow",
    started_at: "2025-01-01T00:00:00Z",
    ended_at: "2025-01-01T00:02:00Z",
    executive_overview: "partial",
    total_item_count: 2,
    warnings: [],
    categories: [
      { key: "news", status: "green", item_count: 2, items: [] },
      { key: "podcasts", status: "yellow", item_count: 0, items: [] },
      { key: "blog_posts", status: "red", item_count: 0, items: [] },
    ],
  });
  renderAt(8);
  await waitFor(() =>
    expect(screen.getByText("Partial (2 of 3)")).toBeInTheDocument(),
  );
});

test("shows the stale banner when the poll fn rejects", async () => {
  vi.spyOn(api, "getRun").mockRejectedValue(new Error("network"));
  renderAt(9);
  await waitFor(() =>
    expect(screen.getByText(/connection problem/i)).toBeInTheDocument(),
  );
});

test("hides overview until it exists and renders categories", async () => {
  vi.spyOn(api, "getRun").mockResolvedValue({
    id: 7,
    input_text: "Globex",
    status: "green",
    started_at: "2025-01-01T00:00:00Z",
    ended_at: "2025-01-01T00:02:00Z",
    executive_overview: "All good.",
    total_item_count: 1,
    warnings: [],
    categories: [
      {
        key: "news",
        status: "green",
        item_count: 1,
        summary: "s",
        items: [
          {
            title: "H",
            url: "https://n.com/a",
            source: "n.com",
            is_undated: true,
            snippet: "x",
          },
        ],
      },
    ],
  });
  renderAt(7);
  await waitFor(() =>
    expect(screen.getByText("All good.")).toBeInTheDocument(),
  );
  // "News articles" appears in both the index nav and the section head.
  expect(screen.getAllByText("News articles").length).toBeGreaterThan(0);
});
