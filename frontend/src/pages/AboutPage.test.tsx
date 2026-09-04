import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import AboutPage from "./AboutPage";

function renderPage() {
  return render(
    <MemoryRouter>
      <AboutPage />
    </MemoryRouter>,
  );
}

describe("AboutPage", () => {
  it("renders the page title and a one-line product summary", () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "About Termkeeper" })).toBeInTheDocument();
    expect(screen.getByText(/Razorpay AI Buildathon/i)).toBeInTheDocument();
  });

  it("lists all six pipeline stages, in order", () => {
    renderPage();
    const list = screen.getByTestId("pipeline-list");
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(6);
    expect(items[0]).toHaveTextContent("Clause segmentation");
    expect(items[3]).toHaveTextContent("Razorpay cross-check");
    expect(items[3]).toHaveTextContent("RazorpayX Payouts");
    expect(items[5]).toHaveTextContent("Aggregate report");
  });

  it("links to the live guardrail page rather than duplicating its content", () => {
    renderPage();
    const link = screen.getByRole("link", { name: /view live guardrail scan/i });
    expect(link).toHaveAttribute("href", "/guardrail");
    // The guardrail page's own PASS/FAIL banner and file lists must not be
    // duplicated here - only a summary and a link out.
    expect(screen.queryByTestId("guardrail-result")).not.toBeInTheDocument();
  });

  it("lists every OpenSpec change actually present under openspec/changes/", () => {
    renderPage();
    const list = screen.getByTestId("changes-list");
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(9);

    const expectedSlugs = [
      "add-django-foundation",
      "add-razorpay-crosscheck",
      "add-risk-scoring-report",
      "add-evaluation-harness",
      "add-report-ui",
      "add-react-frontend",
      "add-confirmed-platform-evidence",
      "close-pitch-accuracy-gaps",
      "switch-llm-provider-to-openai",
    ];
    for (const slug of expectedSlugs) {
      expect(list).toHaveTextContent(slug);
    }
  });

  it("states verified backend and frontend test counts, not a promotional claim", () => {
    renderPage();

    const backendTile = screen.getByText("Backend tests").closest(".stat-tile") as HTMLElement;
    expect(within(backendTile).getByText(/^\d+$/)).toBeInTheDocument();
    expect(within(backendTile).getByText(/pytest, all passing/i)).toBeInTheDocument();

    const frontendTile = screen.getByText("Frontend tests").closest(".stat-tile") as HTMLElement;
    expect(within(frontendTile).getByText(/^\d+$/)).toBeInTheDocument();
    expect(within(frontendTile).getByText(/vitest, all passing/i)).toBeInTheDocument();

    expect(screen.getByText(/pytest -q/)).toBeInTheDocument();
  });

  it("mentions the quote-grounding fallback guardrail by name", () => {
    renderPage();
    expect(screen.getAllByText(/needs_human_review/).length).toBeGreaterThan(0);
    expect(screen.getByText(/deterministic template/i)).toBeInTheDocument();
  });
});
