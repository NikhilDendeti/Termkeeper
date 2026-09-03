import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError, getContractAuditTrail, getContractReasoningChain } from "../api/client";
import type { AuditLogEntry, ClauseReasoningChain } from "../api/types";
import ErrorState from "../components/ErrorState";
import Icon from "../components/Icon";
import LoadingState from "../components/LoadingState";
import SeverityBadge from "../components/SeverityBadge";
import {
  clauseTypeLabel,
  formatDateTime,
  mismatchTypeLabel,
  pipelineStageLabel,
  platformRecordTypeLabel,
  termTypeLabel,
} from "../utils/format";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; chain: ClauseReasoningChain[]; auditTrail: AuditLogEntry[] };

type Tab = "reasoning-chain" | "audit-trail";

/**
 * Selecting a contract shows its full reasoning chain plus its audit
 * trail, in two sections of one page. See
 * specs/frontend/contract-dashboard/spec.md - "Contract detail shows the
 * full reasoning chain" and "Audit trail is reachable per contract".
 */
export default function ContractDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [tab, setTab] = useState<Tab>("reasoning-chain");
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setState({ status: "loading" });

    Promise.all([getContractReasoningChain(id), getContractAuditTrail(id)])
      .then(([chain, auditTrail]) => {
        if (!cancelled) setState({ status: "ready", chain, auditTrail });
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
  }, [id, reloadToken]);

  return (
    <>
      <Link to="/" className="back-link">
        <Icon name="arrow-left" size={14} />
        All contracts
      </Link>
      <div className="page-header">
        <div className="page-header-text">
          <h1 className="page-title">Contract detail</h1>
          <p className="page-subtitle">
            <code>{id}</code>
          </p>
        </div>
      </div>

      {state.status === "loading" && <LoadingState label="Loading contract..." />}

      {state.status === "error" && (
        <ErrorState message={state.message} onRetry={() => setReloadToken((n) => n + 1)} />
      )}

      {state.status === "ready" && (
        <>
          <div className="tab-bar" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "reasoning-chain"}
              className={tab === "reasoning-chain" ? "tab-button is-active" : "tab-button"}
              onClick={() => setTab("reasoning-chain")}
            >
              Reasoning chain
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "audit-trail"}
              className={tab === "audit-trail" ? "tab-button is-active" : "tab-button"}
              onClick={() => setTab("audit-trail")}
            >
              Audit trail
            </button>
          </div>

          {tab === "reasoning-chain" && <ReasoningChainSection chain={state.chain} />}
          {tab === "audit-trail" && <AuditTrailSection entries={state.auditTrail} />}
        </>
      )}
    </>
  );
}

function ReasoningChainSection({ chain }: { chain: ClauseReasoningChain[] }) {
  if (chain.length === 0) {
    return (
      <div className="state-block empty-block card">
        <span className="state-block-icon" aria-hidden="true">
          <Icon name="file-text" size={20} />
        </span>
        <p className="state-block-title">No clauses found for this contract.</p>
      </div>
    );
  }

  return (
    <ol className="clause-chain" data-testid="clause-chain">
      {chain.map((entry) => (
        <li key={entry.clause_id} className="card clause-entry">
          <details>
            <summary className="clause-entry-summary">
              <span className="clause-entry-summary-left">
                <span className="clause-index">Clause {entry.sequence_index}</span>
                {entry.classification_needs_human_review ? (
                  <SeverityBadge severity="needs_human_review" />
                ) : (
                  <span className="clause-snippet">{clauseTypeLabel(entry.clause_type)}</span>
                )}
              </span>
              <span className="clause-entry-summary-right">
                <Icon name="chevron-right" size={16} className="clause-disclosure-icon" />
              </span>
            </summary>

            <div className="clause-body">
              <section>
                <p className="reasoning-stage-label">Clause text</p>
                <p className="clause-text-block">{entry.clause_text}</p>
              </section>

              <section>
                <p className="reasoning-stage-label">Classification</p>
                {entry.classification_needs_human_review ? (
                  <>
                    <SeverityBadge severity="needs_human_review" />
                    {entry.classification_rationale && (
                      <p className="rationale-text">{entry.classification_rationale}</p>
                    )}
                  </>
                ) : entry.clause_type ? (
                  <>
                    <p>
                      Type: <strong>{clauseTypeLabel(entry.clause_type)}</strong>
                      {entry.classification_confidence !== null && (
                        <span className="confidence-note">
                          {" "}
                          (confidence {entry.classification_confidence.toFixed(2)})
                        </span>
                      )}
                    </p>
                    {entry.classification_rationale && (
                      <p className="rationale-text">{entry.classification_rationale}</p>
                    )}
                  </>
                ) : (
                  <p className="empty-note">Not yet classified</p>
                )}
              </section>

              <section>
                <p className="reasoning-stage-label">Extracted term(s)</p>
                {entry.extracted_terms.length > 0 ? (
                  <ul className="term-list">
                    {entry.extracted_terms.map((term) => (
                      <li key={term.id} className="term-item">
                        <div className="term-item-head">
                          {term.needs_human_review && <SeverityBadge severity="needs_human_review" />}
                          <span>{termTypeLabel(term.term_type)}</span>
                          <span className="confidence-note">
                            (confidence {term.extraction_confidence.toFixed(2)})
                          </span>
                        </div>
                        <span>&ldquo;{term.value_raw}&rdquo;</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="empty-note">No extracted terms</p>
                )}
              </section>

              <section>
                <p className="reasoning-stage-label">Platform evidence</p>
                {entry.platform_evidence.length > 0 ? (
                  <ul className="mismatch-list" data-testid="mismatch-list">
                    {entry.platform_evidence.map((flag) => (
                      <li key={flag.mismatch_id} className="mismatch-item">
                        <div className="mismatch-item-head">
                          <span>{mismatchTypeLabel(flag.mismatch_type)}</span>
                        </div>
                        <span>{flag.description}</span>
                      </li>
                    ))}
                  </ul>
                ) : entry.verified_platform_records.length > 0 ? (
                  <div data-testid="confirmed-platform-evidence">
                    <div className="confirmed-banner">
                      <Icon name="check-circle" size={14} className="confirmed-banner-icon" />
                      <span>Confirmed - matches platform data</span>
                    </div>
                    <ul className="confirmed-list" data-testid="confirmed-record-list">
                      {entry.verified_platform_records.map((record) => (
                        <li key={record.id} className="confirmed-item">
                          <div className="confirmed-item-head">
                            <span>{platformRecordTypeLabel(record.record_type)}</span>
                            <code>{record.razorpay_id}</code>
                            <span className="confidence-note">
                              {formatDateTime(record.razorpay_created_at)}
                            </span>
                          </div>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : (
                  <p className="empty-note" data-testid="no-platform-evidence">
                    No platform evidence available
                  </p>
                )}
              </section>

              <section>
                <p className="reasoning-stage-label">Risk verdict</p>
                {entry.risk_assessment ? (
                  <>
                    <SeverityBadge severity={entry.risk_assessment.severity} />
                    {entry.risk_assessment.severity !== "needs_human_review" && (
                      <span className="confidence-note">
                        {" "}
                        (asymmetry {entry.risk_assessment.asymmetry_score.toFixed(2)})
                      </span>
                    )}
                    <p className="explanation-text">{entry.risk_assessment.explanation}</p>
                    {entry.risk_assessment.suggested_rewrite && (
                      <p className="suggested-rewrite">
                        Suggested rewrite: {entry.risk_assessment.suggested_rewrite}
                      </p>
                    )}
                  </>
                ) : (
                  <p className="empty-note" data-testid="not-yet-assessed">
                    Not yet assessed
                  </p>
                )}
              </section>
            </div>
          </details>
        </li>
      ))}
    </ol>
  );
}

function AuditTrailSection({ entries }: { entries: AuditLogEntry[] }) {
  if (entries.length === 0) {
    return (
      <div className="state-block empty-block card">
        <span className="state-block-icon" aria-hidden="true">
          <Icon name="clock" size={20} />
        </span>
        <p className="state-block-title">No audit log entries found for this contract.</p>
      </div>
    );
  }

  return (
    <ol className="audit-list" data-testid="audit-list">
      {entries.map((entry) => (
        <li key={entry.id} className="card audit-entry">
          <div className="audit-entry-head">
            <span className="audit-stage-name">{pipelineStageLabel(entry.stage)}</span>
            <span className="audit-stage-number">stage {entry.stage}</span>
          </div>
          <p className="audit-scope">
            {entry.clause_id ? (
              <>
                Clause-scoped &middot; <code>{entry.clause_id}</code>
              </>
            ) : (
              "Contract-level entry"
            )}
          </p>
          <dl className="audit-meta-grid">
            <div className="audit-meta-item">
              <dt>Prompt version</dt>
              <dd>{entry.prompt_version}</dd>
            </div>
            <div className="audit-meta-item">
              <dt>Model</dt>
              <dd>{entry.model_name}</dd>
            </div>
            <div className="audit-meta-item">
              <dt>Latency (ms)</dt>
              <dd className="font-numeric">{entry.latency_ms}</dd>
            </div>
            <div className="audit-meta-item">
              <dt>Created at</dt>
              <dd>{formatDateTime(entry.created_at)}</dd>
            </div>
          </dl>
          <details>
            <summary className="raw-response-toggle">
              <Icon name="file-text" size={13} />
              Raw model response
            </summary>
            <pre className="raw-response-pre" data-testid="raw-response">
              {JSON.stringify(entry.llm_response_raw, null, 2)}
            </pre>
          </details>
        </li>
      ))}
    </ol>
  );
}
