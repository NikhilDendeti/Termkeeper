import { Link } from "react-router-dom";

import Icon, { type IconName } from "./Icon";

interface EmptyStateProps {
  icon?: IconName;
  title: string;
  detail?: string;
  /** Optional next-step CTA - e.g. linking a first-time user from an empty list to Upload. */
  linkTo?: string;
  linkLabel?: string;
}

/**
 * Shared visible-empty-state block - the empty-data counterpart to
 * LoadingState/ErrorState, previously hand-copied at every call site.
 */
export default function EmptyState({
  icon = "inbox",
  title,
  detail,
  linkTo,
  linkLabel = "Get started",
}: EmptyStateProps) {
  return (
    <div className="state-block empty-block card" data-testid="empty-state">
      <span className="state-block-icon" aria-hidden="true">
        <Icon name={icon} size={20} />
      </span>
      <p className="state-block-title">{title}</p>
      {detail && <p className="state-block-detail">{detail}</p>}
      {linkTo && (
        <div className="state-block-actions">
          <Link to={linkTo} className="btn btn-secondary btn--sm">
            {linkLabel}
            <Icon name="arrow-right" size={14} />
          </Link>
        </div>
      )}
    </div>
  );
}
