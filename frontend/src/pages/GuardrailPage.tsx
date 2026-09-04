import { useEffect, useState } from "react";

import { ApiError, getGuardrailStatus } from "../api/client";
import type { GuardrailScanResult } from "../api/types";
import ErrorState from "../components/ErrorState";
import Icon from "../components/Icon";
import LoadingState from "../components/LoadingState";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; result: GuardrailScanResult };

/**
 * Live proof that razorpay_integration's production path issues no write
 * calls. See specs/frontend/contract-dashboard/spec.md - "Guardrail status
 * is visible" (an unambiguous pass or fail, never an intermediate or
 * silent state).
 */
export default function GuardrailPage() {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });

    getGuardrailStatus()
      .then((result) => {
        if (!cancelled) setState({ status: "ready", result });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        const message =
          error instanceof ApiError ? error.message : "An unexpected error occurred.";
        setState({ status: "error", message });
      });

    return () => {
      cancelled = true;
    };
  }, [reloadToken]);

  return (
    <>
      <div className="page-header">
        <div className="page-header-text">
          <h1 className="page-title">Guardrail verification</h1>
          <p className="page-subtitle">
            A live static scan of <code>razorpay_integration</code>&apos;s production-path source,
            proving the code path never issues a write call against live Razorpay data. Re-run on
            every load - not a cached claim.
          </p>
        </div>
      </div>

      {state.status === "loading" && <LoadingState label="Running guardrail scan..." />}

      {state.status === "error" && (
        <ErrorState message={state.message} onRetry={() => setReloadToken((n) => n + 1)} />
      )}

      {state.status === "ready" && (
        <>
          <div className="stat-grid" data-testid="guardrail-stats">
            <div className="card stat-tile">
              <p className="stat-tile-label">Status</p>
              <p
                className={`stat-tile-value ${
                  state.result.passed ? "stat-tile-value--low" : "stat-tile-value--critical"
                }`}
              >
                {state.result.passed ? "Pass" : "Fail"}
              </p>
            </div>
            <div className="card stat-tile">
              <p className="stat-tile-label">Files scanned</p>
              <p className="stat-tile-value font-numeric">{state.result.scanned_files.length}</p>
            </div>
            <div className="card stat-tile">
              <p className="stat-tile-label">Write-call violations</p>
              <p
                className={`stat-tile-value font-numeric${
                  state.result.violations.length > 0 ? " is-attention" : ""
                }`}
              >
                {state.result.violations.length}
              </p>
              <p className="stat-tile-hint">0 = no write path exists</p>
            </div>
          </div>

          <div
            className={
              state.result.passed
                ? "guardrail-result-banner guardrail-result-banner--pass"
                : "guardrail-result-banner guardrail-result-banner--fail"
            }
            role="status"
            data-testid="guardrail-result"
          >
            <span className="guardrail-result-icon" aria-hidden="true">
              <Icon name={state.result.passed ? "check-circle" : "x-circle"} size={22} />
            </span>
            <span>
              {state.result.passed
                ? "PASS — no write calls found in any scanned file."
                : `FAIL — ${state.result.violations.length} write-call violation(s) found.`}
            </span>
          </div>

          <div className="section">
            <h2 className="section-title">
              Scanned files
              <span className="section-title-count font-numeric">
                {state.result.scanned_files.length}
              </span>
            </h2>
            {state.result.scanned_files.length > 0 ? (
              <ul className="file-list" data-testid="scanned-files">
                {state.result.scanned_files.map((file) => (
                  <li key={file} className="file-list-item">
                    <Icon name="file-text" size={14} />
                    <span className="file-list-item-path">{file}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="empty-note">No files were scanned.</p>
            )}
          </div>

          {!state.result.passed && (
            <div className="section">
              <h2 className="section-title">
                Violations
                <span className="section-title-count font-numeric">
                  {state.result.violations.length}
                </span>
              </h2>
              <ul data-testid="violation-list">
                {state.result.violations.map((violation, index) => (
                  <li
                    key={`${violation.file}:${violation.line}:${index}`}
                    className="violation-item"
                  >
                    <Icon name="alert-triangle" size={14} />
                    <span>
                      <code>
                        {violation.file}:{violation.line}
                      </code>{" "}
                      &mdash; matched call <code>{violation.matched_call}</code>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </>
  );
}
