import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import Layout from "./Layout";

function renderLayout(initialPath = "/") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<p>Contracts page</p>} />
          <Route path="/guardrail" element={<p>Guardrail page</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("Layout", () => {
  it("renders the main navigation with Contracts and Guardrail Status links", () => {
    renderLayout();
    const nav = screen.getByRole("navigation", { name: /main/i });
    expect(nav).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Contracts" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Guardrail Status" })).toBeInTheDocument();
  });

  it("renders the routed page content via the Outlet", () => {
    renderLayout("/");
    expect(screen.getByText("Contracts page")).toBeInTheDocument();
  });

  it("marks the active nav link for the current route", () => {
    renderLayout("/guardrail");
    expect(screen.getByRole("link", { name: "Guardrail Status" })).toHaveClass("is-active");
    expect(screen.getByRole("link", { name: "Contracts" })).not.toHaveClass("is-active");
  });
});
