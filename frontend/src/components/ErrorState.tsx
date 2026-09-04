import { Link } from "react-router-dom";

import Icon from "./Icon";

interface ErrorStateProps {
  message: string;
  onRetry?: () => void;
  /**
   * Optional path to a next step that still exists despite the error - e.g.
   * a contract's partial detail page after an analyze failure that left
   * real partial progress in the database. See
   * specs/frontend/upload-page/spec.md - "A partial failure is shown
   * plainly, with a path forward" and design.md ("reusing ErrorState with
   * an additional link, not a new component").
   */
  linkTo?: string;
  linkLabel?: string;
}

/**
 * Shared visible-error-state block, rendered whenever an `ApiError`
 * (network failure or non-2xx response) reaches a page. See
 * specs/frontend/contract-dashboard/spec.md - "Backend unreachable": an
 * explicit error message rather than an empty or frozen screen.
 */
export default function ErrorState({ message, onRetry, linkTo, linkLabel = "View result" }: ErrorStateProps) {
  return (
    <div className="state-block error-block card" role="alert" data-testid="error-state">
      <span className="state-block-icon" aria-hidden="true">
        <Icon name="alert-triangle" size={20} />
      </span>
      <p className="state-block-title">Something went wrong</p>
      <p className="state-block-detail">{message}</p>
      {onRetry || linkTo ? (
        <div className="state-block-actions">
          {onRetry ? (
            <button type="button" className="btn btn-secondary btn--sm" onClick={onRetry}>
              Retry
            </button>
          ) : null}
          {linkTo ? (
            <Link to={linkTo} className="btn btn-secondary btn--sm">
              {linkLabel}
              <Icon name="arrow-right" size={14} />
            </Link>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
