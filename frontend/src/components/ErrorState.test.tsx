import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
});
