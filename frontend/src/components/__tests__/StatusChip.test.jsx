import { render, screen } from "@testing-library/react";
import { StatusChip } from "../StatusChip";

test("run variant uses run vocabulary", () => {
  render(<StatusChip variant="run" status="green" />);
  expect(screen.getByText("Complete")).toBeInTheDocument();
});

test("run yellow reads Partial", () => {
  render(<StatusChip variant="run" status="yellow" />);
  expect(screen.getByText("Partial")).toBeInTheDocument();
});

test("run yellow shows X of Y when counts are provided", () => {
  render(<StatusChip variant="run" status="yellow" succeeded={3} total={5} />);
  expect(screen.getByText("Partial (3 of 5)")).toBeInTheDocument();
});

test("category green shows Found with count", () => {
  render(<StatusChip variant="category" status="green" count={4} />);
  expect(screen.getByText("Found (4)")).toBeInTheDocument();
});

test("category yellow reads None found", () => {
  render(<StatusChip variant="category" status="yellow" />);
  expect(screen.getByText("None found")).toBeInTheDocument();
});

test("running spinner carries an accessible label", () => {
  render(<StatusChip variant="run" status="blue" />);
  expect(screen.getByLabelText("Running")).toBeInTheDocument();
});
