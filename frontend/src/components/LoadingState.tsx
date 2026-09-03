interface LoadingStateProps {
  label?: string;
}

/**
 * Shared visible-loading-state block. See
 * specs/frontend/contract-dashboard/spec.md - "Network and error states
 * are handled visibly" (a visible loading state while a request is in
 * flight - never an indefinite spinner with no explanation, hence the
 * accompanying label text).
 */
export default function LoadingState({ label = "Loading..." }: LoadingStateProps) {
  return (
    <div className="state-block" role="status" aria-live="polite" data-testid="loading-state">
      <div className="spinner" aria-hidden="true" />
      <p className="state-block-title">{label}</p>
    </div>
  );
}
