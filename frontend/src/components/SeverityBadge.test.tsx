import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Severity } from "../api/types";
import SeverityBadge from "./SeverityBadge";

const ALL_SEVERITIES: Severity[] = ["low", "medium", "high", "critical", "needs_human_review"];

describe("SeverityBadge", () => {
  it.each(ALL_SEVERITIES)("renders a badge for severity=%s", (severity) => {
    render(<SeverityBadge severity={severity} />);
    const badge = screen.getByTestId("severity-badge");
    expect(badge).toHaveClass(`severity-badge--${severity}`);
  });

  it("gives each scored severity a distinct color class from every other", () => {
    const classNames = ALL_SEVERITIES.map((severity) => `severity-badge--${severity}`);
    expect(new Set(classNames).size).toBe(ALL_SEVERITIES.length);
  });

  it("visibly distinguishes needs_human_review from every scored severity", () => {
    const { unmount } = render(<SeverityBadge severity="needs_human_review" />);
    const reviewBadge = screen.getByTestId("severity-badge");
    // Off the low->critical color ramp: none of the scored-severity classes apply.
    expect(reviewBadge).not.toHaveClass("severity-badge--low");
    expect(reviewBadge).not.toHaveClass("severity-badge--medium");
    expect(reviewBadge).not.toHaveClass("severity-badge--high");
    expect(reviewBadge).not.toHaveClass("severity-badge--critical");
    expect(reviewBadge).toHaveTextContent("Needs human review");
    unmount();

    render(<SeverityBadge severity="critical" />);
    const criticalBadge = screen.getByTestId("severity-badge");
    expect(criticalBadge).not.toHaveClass("severity-badge--needs_human_review");
    expect(criticalBadge).toHaveTextContent("Critical");
  });
});
