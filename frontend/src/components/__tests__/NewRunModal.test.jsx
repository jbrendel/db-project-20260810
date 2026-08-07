import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import * as api from "../../api";
import { NewRunModal } from "../NewRunModal";

test("maps a 400 field error to the input and stays open", async () => {
  // Use a VALID input so client pre-validation passes and createRun is hit.
  vi.spyOn(api, "createRun").mockRejectedValue({
    status: 400,
    body: { detail: "Unknown company", field: "input_text" },
  });
  render(<NewRunModal onClose={() => {}} onCreated={() => {}} />);
  fireEvent.change(screen.getByLabelText(/name or url/i), {
    target: { value: "Acme" },
  });
  fireEvent.click(screen.getByRole("button", { name: /start/i }));
  await waitFor(() =>
    expect(screen.getByText(/unknown company/i)).toBeInTheDocument(),
  );
});

test("shows a non-field error on a 5xx and re-enables submit", async () => {
  vi.spyOn(api, "createRun").mockRejectedValue({
    status: 500,
    body: { detail: "boom" },
  });
  render(<NewRunModal onClose={() => {}} onCreated={() => {}} />);
  fireEvent.change(screen.getByLabelText(/name or url/i), {
    target: { value: "Acme" },
  });
  fireEvent.click(screen.getByRole("button", { name: /start/i }));
  await waitFor(() =>
    expect(
      screen.getByText(/could not start the run/i),
    ).toBeInTheDocument(),
  );
  expect(screen.getByRole("button", { name: /start/i })).not.toBeDisabled();
});

test("client-side validation blocks empty input", () => {
  const created = vi.fn();
  vi.spyOn(api, "createRun");
  render(<NewRunModal onClose={() => {}} onCreated={created} />);
  fireEvent.click(screen.getByRole("button", { name: /start/i }));
  expect(screen.getByText(/please enter a name or url/i)).toBeInTheDocument();
  expect(api.createRun).not.toHaveBeenCalled();
});

test("calls onCreated and onClose on success", async () => {
  vi.spyOn(api, "createRun").mockResolvedValue({ id: 7 });
  const created = vi.fn();
  const close = vi.fn();
  render(<NewRunModal onClose={close} onCreated={created} />);
  fireEvent.change(screen.getByLabelText(/name or url/i), {
    target: { value: "Acme" },
  });
  fireEvent.click(screen.getByRole("button", { name: /start/i }));
  await waitFor(() => expect(created).toHaveBeenCalledWith({ id: 7 }));
  expect(close).toHaveBeenCalled();
});
