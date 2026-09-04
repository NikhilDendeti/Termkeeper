import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, getContracts } from "../api/client";
import type { ContractSummary } from "../api/types";
import EmptyState from "../components/EmptyState";
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

type FilterBand = "all" | "needs_review" | "critical" | "high" | "medium" | "low" | "unscored";
type SortBy = "newest" | "score_desc" | "score_asc";

/**
 * The frontend's landing view. See
 * specs/frontend/contract-dashboard/spec.md - "Contract list is the
 * landing view".
 */
export default function ContractListPage() {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [reloadToken, setReloadToken] = useState(0);
  const [search, setSearch] = useState("");
  const [filterBand, setFilterBand] = useState<FilterBand>("all");
  const [sortBy, setSortBy] = useState<SortBy>("newest");

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

  const visibleContracts = useMemo(() => {
    if (state.status !== "ready") return [];
    const query = search.trim().toLowerCase();

    const filtered = state.contracts.filter((contract) => {
      if (query) {
        const matchesQuery =
          contract.engagement_id.toLowerCase().includes(query) ||
          contract.contract_id.toLowerCase().includes(query);
        if (!matchesQuery) return false;
      }

      if (filterBand === "all") return true;
      if (filterBand === "needs_review") return contract.needs_human_review_count > 0;
      if (filterBand === "unscored") return contract.overall_risk_score === null;
      return (
        contract.overall_risk_score !== null &&
        scoreToSeverityBand(contract.overall_risk_score) === filterBand
      );
    });

    if (sortBy === "newest") return filtered;

    const direction = sortBy === "score_desc" ? -1 : 1;
    return [...filtered].sort((a, b) => {
      if (a.overall_risk_score === null && b.overall_risk_score === null) return 0;
      if (a.overall_risk_score === null) return 1;
      if (b.overall_risk_score === null) return -1;
      return (a.overall_risk_score - b.overall_risk_score) * direction;
    });
  }, [state, search, filterBand, sortBy]);

  const hasActiveFilters = search.trim() !== "" || filterBand !== "all";

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
        <EmptyState
          title="No contracts yet"
          detail="Once a contract has been ingested through the pipeline, it will appear here."
          linkTo="/upload"
          linkLabel="Upload a contract"
        />
      )}

      {state.status === "ready" && state.contracts.length > 0 && (
        <>
          <ContractStatRow contracts={state.contracts} />

          <div className="list-toolbar">
            <input
              type="search"
              className="form-input list-toolbar-search"
              placeholder="Search by engagement or contract ID..."
              aria-label="Search contracts"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            <select
              className="form-select"
              aria-label="Filter by status"
              value={filterBand}
              onChange={(event) => setFilterBand(event.target.value as FilterBand)}
            >
              <option value="all">All statuses</option>
              <option value="needs_review">Needs review</option>
              <option value="critical">Critical</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
              <option value="unscored">Not yet scored</option>
            </select>
            <select
              className="form-select"
              aria-label="Sort contracts"
              value={sortBy}
              onChange={(event) => setSortBy(event.target.value as SortBy)}
            >
              <option value="newest">Newest first</option>
              <option value="score_desc">Highest risk first</option>
              <option value="score_asc">Lowest risk first</option>
            </select>
          </div>

          {visibleContracts.length === 0 ? (
            <div className="state-block empty-block card" data-testid="empty-filter-state">
              <span className="state-block-icon" aria-hidden="true">
                <Icon name="inbox" size={20} />
              </span>
              <p className="state-block-title">No contracts match your filters</p>
              {hasActiveFilters && (
                <div className="state-block-actions">
                  <button
                    type="button"
                    className="btn btn-secondary btn--sm"
                    onClick={() => {
                      setSearch("");
                      setFilterBand("all");
                    }}
                  >
                    Clear filters
                  </button>
                </div>
              )}
            </div>
          ) : (
            <ol className="contract-list" data-testid="contract-list">
              {visibleContracts.map((contract) => {
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
                        <span className="font-numeric">Ingested {formatDateTime(contract.created_at)}</span>
                        <code>{contract.contract_id}</code>
                      </div>
                      <span className="contract-card-doc-link" aria-hidden="true">
                        <Icon name="file-text" size={13} />
                        View document
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ol>
          )}
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
      <dl className="card stat-tile">
        <dt className="stat-tile-label">Total contracts</dt>
        <dd className="stat-tile-value font-numeric">{contracts.length}</dd>
      </dl>
      <dl className="card stat-tile">
        <dt className="stat-tile-label">Clauses needing review</dt>
        <dd className={`stat-tile-value font-numeric${totalNeedsReview > 0 ? " is-attention" : ""}`}>
          {totalNeedsReview}
        </dd>
      </dl>
      <dl className="card stat-tile">
        <dt className="stat-tile-label">Average risk score</dt>
        <dd
          className={`stat-tile-value font-numeric${
            avgScore !== null ? ` stat-tile-value--${scoreToSeverityBand(avgScore)}` : ""
          }`}
        >
          {formatScore(avgScore)}
        </dd>
        <dd className="stat-tile-hint">{scored.length} of {contracts.length} scored</dd>
      </dl>
    </div>
  );
}
