import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import * as api from "../../api";
import { RunList } from "../RunList";

const runs = [
  { id: 1, input_text: "Acme", status: "blue", started_at: null },
  { id: 2, input_text: "Globex", status: "green", started_at: null },
];

test("renders rows with status chips", () => {
  render(
    <MemoryRouter>
      <RunList runs={runs} onChanged={() => {}} />
    </MemoryRouter>,
  );
  expect(screen.getByText("Acme")).toBeInTheDocument();
  expect(screen.getByText("Running")).toBeInTheDocument();
  expect(screen.getByText("Complete")).toBeInTheDocument();
});

test("delete confirms then calls api and refetches", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  vi.spyOn(api, "deleteRun").mockResolvedValue(null);
  const onChanged = vi.fn();
  render(
    <MemoryRouter>
      <RunList runs={runs} onChanged={onChanged} />
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByLabelText(/delete run for acme/i));
  expect(api.deleteRun).toHaveBeenCalledWith(1);
});

test("empty state when no runs", () => {
  render(
    <MemoryRouter>
      <RunList runs={[]} onChanged={() => {}} />
    </MemoryRouter>,
  );
  expect(screen.getByText(/no runs yet/i)).toBeInTheDocument();
});
