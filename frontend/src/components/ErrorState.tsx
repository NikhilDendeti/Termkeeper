import Icon from "./Icon";

interface ErrorStateProps {
  message: string;
  onRetry?: () => void;
}

/**
 * Shared visible-error-state block, rendered whenever an `ApiError`
 * (network failure or non-2xx response) reaches a page. See
 * specs/frontend/contract-dashboard/spec.md - "Backend unreachable": an
 * explicit error message rather than an empty or frozen screen.
 */
export default function ErrorState({ message, onRetry }: ErrorStateProps) {
  return (
    <div className="state-block error-block card" role="alert" data-testid="error-state">
      <span className="state-block-icon" aria-hidden="true">
        <Icon name="alert-triangle" size={20} />
      </span>
      <p className="state-block-title">Something went wrong</p>
      <p className="state-block-detail">{message}</p>
      {onRetry ? (
        <button type="button" className="btn btn-secondary btn--sm" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}
