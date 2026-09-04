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
          <Route path="/evaluation" element={<p>Evaluation page</p>} />
          <Route path="/upload" element={<p>Upload page</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("Layout", () => {
  it("renders the main navigation with Contracts, Guardrail Status, Evaluation, About, and Upload links", () => {
    renderLayout();
    const nav = screen.getByRole("navigation", { name: /main/i });
    expect(nav).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Contracts" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Guardrail Status" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Evaluation" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "About" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Upload" })).toBeInTheDocument();
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

  it("renders Upload as a primary-button CTA, distinct from the wayfinding links", () => {
    renderLayout();
    const uploadLink = screen.getByRole("link", { name: "Upload" });
    expect(uploadLink).toHaveClass("btn");
    expect(uploadLink).toHaveClass("btn-primary");
    expect(uploadLink).not.toHaveClass("app-nav-link");
  });

  it("sets a route-specific document title", () => {
    renderLayout("/guardrail");
    expect(document.title).toContain("Guardrail verification");
  });
});
