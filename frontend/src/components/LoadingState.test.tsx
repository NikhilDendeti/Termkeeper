import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LoadingState from "./LoadingState";

describe("LoadingState", () => {
  it("renders a visible loading indicator with a default label", () => {
    render(<LoadingState />);
    expect(screen.getByTestId("loading-state")).toBeInTheDocument();
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("renders a custom label when provided", () => {
    render(<LoadingState label="Loading contracts..." />);
    expect(screen.getByText("Loading contracts...")).toBeInTheDocument();
  });
});
