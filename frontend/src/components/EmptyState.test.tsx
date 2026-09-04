import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import EmptyState from "./EmptyState";

function renderWithRouter(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

describe("EmptyState", () => {
  it("renders a visible empty-state block with a title", () => {
    renderWithRouter(<EmptyState title="No contracts yet" />);
    expect(screen.getByTestId("empty-state")).toBeInTheDocument();
    expect(screen.getByText("No contracts yet")).toBeInTheDocument();
  });

  it("renders optional detail text when provided", () => {
    renderWithRouter(<EmptyState title="No contracts yet" detail="Upload one to get started." />);
    expect(screen.getByText("Upload one to get started.")).toBeInTheDocument();
  });

  it("renders no detail text when omitted", () => {
    renderWithRouter(<EmptyState title="No contracts yet" />);
    expect(screen.getByTestId("empty-state").querySelector(".state-block-detail")).toBeNull();
  });

  it("renders a next-step link when linkTo is provided", () => {
    renderWithRouter(<EmptyState title="No contracts yet" linkTo="/upload" linkLabel="Upload a contract" />);
    const link = screen.getByRole("link", { name: /upload a contract/i });
    expect(link).toHaveAttribute("href", "/upload");
  });

  it("renders no link when linkTo is omitted", () => {
    renderWithRouter(<EmptyState title="No contracts yet" />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
