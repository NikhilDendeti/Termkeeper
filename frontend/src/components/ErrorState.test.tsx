import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import ErrorState from "./ErrorState";

describe("ErrorState", () => {
  it("renders a visible, specific error message", () => {
    render(<ErrorState message="Network error while requesting /contracts/" />);
    expect(screen.getByTestId("error-state")).toBeInTheDocument();
    expect(screen.getByText("Network error while requesting /contracts/")).toBeInTheDocument();
  });

  it("does not render a retry button when no handler is provided", () => {
    render(<ErrorState message="failed" />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("invokes onRetry when the retry button is clicked", async () => {
    const onRetry = vi.fn();
    const user = userEvent.setup();
    render(<ErrorState message="failed" onRetry={onRetry} />);

    await user.click(screen.getByRole("button", { name: /retry/i }));

    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("does not render a link when linkTo is not provided", () => {
    render(<ErrorState message="failed" />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("renders a link to the given path with a custom label when linkTo is provided", () => {
    render(
      <MemoryRouter>
        <ErrorState message="failed" linkTo="/contracts/c1" linkLabel="View partial result" />
      </MemoryRouter>,
    );

    const link = screen.getByRole("link", { name: /view partial result/i });
    expect(link).toHaveAttribute("href", "/contracts/c1");
  });

  it("renders both the retry button and the link when both are provided", () => {
    render(
      <MemoryRouter>
        <ErrorState message="failed" onRetry={vi.fn()} linkTo="/contracts/c1" />
      </MemoryRouter>,
    );

    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
    expect(screen.getByRole("link")).toBeInTheDocument();
  });
});
