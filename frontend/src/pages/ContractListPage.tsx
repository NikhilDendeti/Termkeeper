import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, getContracts } from "../api/client";
import type { ContractSummary } from "../api/types";
import ErrorState from "../components/ErrorState";
import Icon from "../components/Icon";
import LoadingState from "../components/LoadingState";
import SeverityBadge from "../components/SeverityBadge";
import { formatDateTime, formatScore, razorpayReferenceTypeLabel } from "../utils/format";
import { scoreToSeverityBand } from "../utils/riskBand";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; contracts: ContractSummary[] };

/**
 * The frontend's landing view. See
 * specs/frontend/contract-dashboard/spec.md - "Contract list is the
 * landing view".
 */
export default function ContractListPage() {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });

    getContracts()
      .then((contracts) => {
        if (!cancelled) setState({ status: "ready", contracts });
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
          <h1 className="page-title">Contracts</h1>
          <p className="page-subtitle">Every ingested contract and its current risk status.</p>
        </div>
      </div>

      {state.status === "loading" && <LoadingState label="Loading contracts..." />}

      {state.status === "error" && (
        <ErrorState message={state.message} onRetry={() => setReloadToken((n) => n + 1)} />
      )}

      {state.status === "ready" && state.contracts.length === 0 && (
        <div className="state-block empty-block card" data-testid="empty-state">
          <span className="state-block-icon" aria-hidden="true">
            <Icon name="inbox" size={20} />
          </span>
          <p className="state-block-title">No contracts yet</p>
          <p className="state-block-detail">
            Once a contract has been ingested through the pipeline, it will appear here.
          </p>
        </div>
      )}

      {state.status === "ready" && state.contracts.length > 0 && (
        <>
          <ContractStatRow contracts={state.contracts} />
          <ol className="contract-list" data-testid="contract-list">
            {state.contracts.map((contract) => {
              const band: "unscored" | ReturnType<typeof scoreToSeverityBand> =
                contract.overall_risk_score !== null
                  ? scoreToSeverityBand(contract.overall_risk_score)
                  : "unscored";
              return (
                <li
                  key={contract.contract_id}
                  className={`card contract-card-wrap contract-card-wrap--${band}`}
                >
                  <Link to={`/contracts/${contract.contract_id}`} className="contract-card">
                    <div className="contract-card-top">
                      <span className="contract-card-title">{contract.engagement_id}</span>
                      <div className="contract-card-score">
                        {contract.overall_risk_score !== null ? (
                          <SeverityBadge severity={scoreToSeverityBand(contract.overall_risk_score)} />
                        ) : (
                          <span className="score-value is-empty">Not yet scored</span>
                        )}
                        {contract.needs_human_review_count > 0 && (
                          <SeverityBadge severity="needs_human_review" />
                        )}
                      </div>
                    </div>
                    <div className="contract-card-meta">
                      <span>
                        Score:{" "}
                        <span className="score-value font-numeric">
                          {formatScore(contract.overall_risk_score)}
                        </span>
                      </span>
                      <span>{razorpayReferenceTypeLabel(contract.razorpay_reference_type)}</span>
                      <span>
                        {contract.needs_human_review_count}{" "}
                        {contract.needs_human_review_count === 1 ? "clause" : "clauses"} needing review
                      </span>
                      <span>Ingested {formatDateTime(contract.created_at)}</span>
                      <code>{contract.contract_id}</code>
                    </div>
                  </Link>
                  <Link
                    to={`/contracts/${contract.contract_id}`}
                    className="contract-card-doc-link"
                    aria-label={`View the original document for ${contract.engagement_id}`}
                  >
                    <Icon name="file-text" size={13} />
                    View document
                  </Link>
                </li>
              );
            })}
          </ol>
        </>
      )}
    </>
  );
}

/**
 * At-a-glance portfolio summary above the list - purely derived from the
 * already-fetched `contracts` array, no extra requests. Surfaces the
 * headline numbers (volume, what needs attention, overall exposure)
 * before the user scans individual rows.
 */
function ContractStatRow({ contracts }: { contracts: ContractSummary[] }) {
  const totalNeedsReview = contracts.reduce((sum, c) => sum + c.needs_human_review_count, 0);
  const scored = contracts.filter((c) => c.overall_risk_score !== null);
  const avgScore =
    scored.length > 0
      ? scored.reduce((sum, c) => sum + (c.overall_risk_score ?? 0), 0) / scored.length
      : null;

  return (
    <div className="stat-grid">
      <div className="card stat-tile">
        <p className="stat-tile-label">Total contracts</p>
        <p className="stat-tile-value font-numeric">{contracts.length}</p>
      </div>
      <div className="card stat-tile">
        <p className="stat-tile-label">Clauses needing review</p>
        <p className={`stat-tile-value font-numeric${totalNeedsReview > 0 ? " is-attention" : ""}`}>
          {totalNeedsReview}
        </p>
      </div>
      <div className="card stat-tile">
        <p className="stat-tile-label">Average risk score</p>
        <p
          className={`stat-tile-value font-numeric${
            avgScore !== null ? ` stat-tile-value--${scoreToSeverityBand(avgScore)}` : ""
          }`}
        >
          {formatScore(avgScore)}
        </p>
        <p className="stat-tile-hint">{scored.length} of {contracts.length} scored</p>
      </div>
    </div>
  );
}
