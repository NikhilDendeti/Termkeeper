import type { Severity } from "../api/types";
import { severityLabel } from "../utils/format";
import Icon from "./Icon";

interface SeverityBadgeProps {
  severity: Severity;
}

/**
 * Color-codes each of the five severity values so they're distinct at a
 * glance (see index.css - ".severity-badge--*"). `needs_human_review` is
 * deliberately off the low->critical color ramp entirely - a violet hue, a
 * dashed border, and a question-mark glyph instead of the scored
 * severities' solid dot - so a clause awaiting human review can never be
 * read as if it had already been scored. See
 * specs/frontend/contract-dashboard/spec.md - "Needs-human-review clause
 * visibly distinct".
 */
export default function SeverityBadge({ severity }: SeverityBadgeProps) {
  const isNeedsReview = severity === "needs_human_review";
  return (
    <span
      className={`severity-badge severity-badge--${severity}`}
      data-testid="severity-badge"
      role="status"
    >
      {isNeedsReview ? (
        <Icon name="help-circle" size={12} className="severity-badge-icon" />
      ) : (
        <span className="severity-badge-dot" aria-hidden="true" />
      )}
      {severityLabel(severity)}
    </span>
  );
}
