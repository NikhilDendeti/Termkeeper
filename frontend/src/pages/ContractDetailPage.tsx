import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  ApiError,
  getContractAuditTrail,
  getContractDocument,
  getContractReasoningChain,
} from "../api/client";
import type { AuditLogEntry, ClauseReasoningChain, ContractDocument } from "../api/types";
import EmptyState from "../components/EmptyState";
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
  razorpayReferenceTypeLabel,
  termTypeLabel,
} from "../utils/format";

type SectionState<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: T };

type Tab = "document" | "reasoning-chain" | "audit-trail";

const TAB_IDS: Record<Tab, { tab: string; panel: string }> = {
  document: { tab: "tab-document", panel: "panel-document" },
  "reasoning-chain": { tab: "tab-reasoning-chain", panel: "panel-reasoning-chain" },
  "audit-trail": { tab: "tab-audit-trail", panel: "panel-audit-trail" },
};

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "An unexpected error occurred.";
}

/**
 * Selecting a contract shows its original document, its full reasoning
 * chain, and its audit trail, in three sections of one page. See
 * specs/frontend/contract-dashboard/spec.md - "Contract detail shows the
 * full reasoning chain" and "Audit trail is reachable per contract" - the
 * document tab itself predates a formal spec (added directly in response
 * to a real gap: nothing surfaced the original submitted text anywhere).
 *
 * The three sections are fetched and retried independently (three separate
 * effects/reload tokens, not one combined Promise.all) so a failure or slow
 * response on one endpoint never blocks the other two, which may already
 * have data to show.
 */
export default function ContractDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [tab, setTab] = useState<Tab>("document");

  const [documentState, setDocumentState] = useState<SectionState<ContractDocument>>({
    status: "loading",
  });
  const [docReloadToken, setDocReloadToken] = useState(0);

  const [chainState, setChainState] = useState<SectionState<ClauseReasoningChain[]>>({
    status: "loading",
  });
  const [chainReloadToken, setChainReloadToken] = useState(0);

  const [auditState, setAuditState] = useState<SectionState<AuditLogEntry[]>>({
    status: "loading",
  });
  const [auditReloadToken, setAuditReloadToken] = useState(0);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setDocumentState({ status: "loading" });

    getContractDocument(id)
      .then((document) => {
        if (!cancelled) setDocumentState({ status: "ready", data: document });
      })
      .catch((error: unknown) => {
        if (!cancelled) setDocumentState({ status: "error", message: errorMessage(error) });
      });

    return () => {
      cancelled = true;
    };
  }, [id, docReloadToken]);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setChainState({ status: "loading" });

    getContractReasoningChain(id)
      .then((chain) => {
        if (!cancelled) setChainState({ status: "ready", data: chain });
      })
      .catch((error: unknown) => {
        if (!cancelled) setChainState({ status: "error", message: errorMessage(error) });
      });

    return () => {
      cancelled = true;
    };
  }, [id, chainReloadToken]);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setAuditState({ status: "loading" });

    getContractAuditTrail(id)
      .then((auditTrail) => {
        if (!cancelled) setAuditState({ status: "ready", data: auditTrail });
      })
      .catch((error: unknown) => {
        if (!cancelled) setAuditState({ status: "error", message: errorMessage(error) });
      });

    return () => {
      cancelled = true;
    };
  }, [id, auditReloadToken]);

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

      <div className="tab-bar" role="tablist">
        <button
          type="button"
          role="tab"
          id={TAB_IDS.document.tab}
          aria-controls={TAB_IDS.document.panel}
          aria-selected={tab === "document"}
          className={tab === "document" ? "tab-button is-active" : "tab-button"}
          onClick={() => setTab("document")}
        >
          Document
        </button>
        <button
          type="button"
          role="tab"
          id={TAB_IDS["reasoning-chain"].tab}
          aria-controls={TAB_IDS["reasoning-chain"].panel}
          aria-selected={tab === "reasoning-chain"}
          className={tab === "reasoning-chain" ? "tab-button is-active" : "tab-button"}
          onClick={() => setTab("reasoning-chain")}
        >
          Reasoning chain
        </button>
        <button
          type="button"
          role="tab"
          id={TAB_IDS["audit-trail"].tab}
          aria-controls={TAB_IDS["audit-trail"].panel}
          aria-selected={tab === "audit-trail"}
          className={tab === "audit-trail" ? "tab-button is-active" : "tab-button"}
          onClick={() => setTab("audit-trail")}
        >
          Audit trail
        </button>
      </div>

      {tab === "document" && (
        <div role="tabpanel" id={TAB_IDS.document.panel} aria-labelledby={TAB_IDS.document.tab}>
          {documentState.status === "loading" && <LoadingState label="Loading document..." />}
          {documentState.status === "error" && (
            <ErrorState
              message={documentState.message}
              onRetry={() => setDocReloadToken((n) => n + 1)}
            />
          )}
          {documentState.status === "ready" && <DocumentSection document={documentState.data} />}
        </div>
      )}

      {tab === "reasoning-chain" && (
        <div
          role="tabpanel"
          id={TAB_IDS["reasoning-chain"].panel}
          aria-labelledby={TAB_IDS["reasoning-chain"].tab}
        >
          {chainState.status === "loading" && <LoadingState label="Loading reasoning chain..." />}
          {chainState.status === "error" && (
            <ErrorState
              message={chainState.message}
              onRetry={() => setChainReloadToken((n) => n + 1)}
            />
          )}
          {chainState.status === "ready" && <ReasoningChainSection chain={chainState.data} />}
        </div>
      )}

      {tab === "audit-trail" && (
        <div
          role="tabpanel"
          id={TAB_IDS["audit-trail"].panel}
          aria-labelledby={TAB_IDS["audit-trail"].tab}
        >
          {auditState.status === "loading" && <LoadingState label="Loading audit trail..." />}
          {auditState.status === "error" && (
            <ErrorState
              message={auditState.message}
              onRetry={() => setAuditReloadToken((n) => n + 1)}
            />
          )}
          {auditState.status === "ready" && <AuditTrailSection entries={auditState.data} />}
        </div>
      )}
    </>
  );
}

function DocumentSection({ document }: { document: ContractDocument }) {
  return (
    <div className="card document-card">
      {document.needs_human_review && (
        <div className="needs-review-banner" role="alert" data-testid="needs-review-banner">
          <span className="needs-review-banner-icon" aria-hidden="true">
            <Icon name="alert-triangle" size={16} />
          </span>
          <div>
            <p className="needs-review-banner-title">This contract needs human review</p>
            <p className="needs-review-banner-reason" data-testid="needs-review-reason">
              {document.human_review_reason}
            </p>
          </div>
        </div>
      )}
      <dl className="audit-meta-grid document-meta-grid">
        <div className="audit-meta-item">
          <dt>Engagement</dt>
          <dd>{document.engagement_id}</dd>
        </div>
        <div className="audit-meta-item">
          <dt>Razorpay reference</dt>
          <dd>
            {razorpayReferenceTypeLabel(document.razorpay_reference_type)} &middot;{" "}
            <code>{document.razorpay_reference_id}</code>
          </dd>
        </div>
        <div className="audit-meta-item">
          <dt>Submitted</dt>
          <dd>{formatDateTime(document.created_at)}</dd>
        </div>
        {document.source_filename && (
          <div className="audit-meta-item">
            <dt>Source file</dt>
            <dd>{document.source_filename}</dd>
          </div>
        )}
      </dl>
      <p className="reasoning-stage-label">Original text, as submitted</p>
      <pre className="document-raw-text" data-testid="document-raw-text">
        {document.raw_text}
      </pre>
    </div>
  );
}

function ReasoningChainSection({ chain }: { chain: ClauseReasoningChain[] }) {
  if (chain.length === 0) {
    return <EmptyState icon="file-text" title="No clauses found for this contract." />;
  }

  return (
    <ol className="clause-chain" data-testid="clause-chain">
      {chain.map((entry) => (
        <li key={entry.clause_id} className="card clause-entry">
          <details>
            <summary className="clause-entry-summary">
              <span className="clause-entry-summary-left">
                <span className="clause-index">Clause {entry.sequence_index}</span>
                {entry.risk_assessment ? (
                  <SeverityBadge severity={entry.risk_assessment.severity} />
                ) : entry.classification_needs_human_review ? (
                  <SeverityBadge severity="needs_human_review" />
                ) : null}
                <span className="clause-snippet">{clauseTypeLabel(entry.clause_type)}</span>
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
                    {entry.extracted_terms.map((term) => {
                      const overdueStatus = entry.overdue_statuses.find(
                        (status) => status.term_id === term.id && status.is_overdue,
                      );
                      return (
                        <li key={term.id} className="term-item">
                          <div className="term-item-head">
                            {term.needs_human_review && (
                              <SeverityBadge severity="needs_human_review" />
                            )}
                            <span>{termTypeLabel(term.term_type)}</span>
                            <span className="confidence-note">
                              (confidence {term.extraction_confidence.toFixed(2)})
                            </span>
                          </div>
                          <span>&ldquo;{term.value_raw}&rdquo;</span>
                          {overdueStatus && (
                            <div>
                              <span
                                className="overdue-banner"
                                data-testid="overdue-banner"
                                role="status"
                              >
                                <Icon name="clock" size={12} className="overdue-banner-icon" />
                                Overdue &mdash; expected every {overdueStatus.expected_interval_days}{" "}
                                days, last payout was {overdueStatus.days_since_last_payout} days ago
                              </span>
                            </div>
                          )}
                        </li>
                      );
                    })}
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
    return <EmptyState icon="clock" title="No audit log entries found for this contract." />;
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
              <Icon name="chevron-right" size={13} className="clause-disclosure-icon" />
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
