import { useEffect, useState } from "react";

import { ApiError, getLatestEvalRun } from "../api/client";
import type { CostBucketEntry, EvalRun } from "../api/types";
import ErrorState from "../components/ErrorState";
import Icon from "../components/Icon";
import LoadingState from "../components/LoadingState";
import { formatDateTime, formatPercent } from "../utils/format";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; evalRun: EvalRun | null };

/**
 * The evaluation harness's most recently persisted result: precision/
 * recall/F1 against held-out ground-truth labels, severity calibration,
 * and the false-positive/false-negative cost report - the track-specific
 * metrics `evaluation.services.run_eval` (`manage.py eval run`) produces.
 * Structurally cloned from GuardrailPage's loading/error/ready pattern.
 */
export default function EvaluationPage() {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });

    getLatestEvalRun()
      .then((response) => {
        if (!cancelled) setState({ status: "ready", evalRun: response.eval_run });
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
          <h1 className="page-title">Evaluation results</h1>
          <p className="page-subtitle">
            The most recent held-out scoring pass from the evaluation harness (
            <code>manage.py eval run</code>) &mdash; precision/recall/F1 against ground-truth
            labels, severity calibration, and the false-positive/false-negative cost report.
          </p>
        </div>
      </div>

      {state.status === "loading" && <LoadingState label="Loading the latest evaluation run..." />}

      {state.status === "error" && (
        <ErrorState message={state.message} onRetry={() => setReloadToken((n) => n + 1)} />
      )}

      {state.status === "ready" && state.evalRun === null && (
        <div className="state-block empty-block card" data-testid="empty-state">
          <span className="state-block-icon" aria-hidden="true">
            <Icon name="inbox" size={20} />
          </span>
          <p className="state-block-title">No evaluation run yet</p>
          <p className="state-block-detail">
            Run <code>manage.py eval generate-dataset</code> and then{" "}
            <code>manage.py eval run</code> to produce one.
          </p>
        </div>
      )}

      {state.status === "ready" && state.evalRun !== null && (
        <EvalRunSummary evalRun={state.evalRun} />
      )}
    </>
  );
}

function EvalRunSummary({ evalRun }: { evalRun: EvalRun }) {
  const risk = evalRun.precision_recall_f1.risk_severity;
  const mismatch = evalRun.precision_recall_f1.mismatch_present;
  const cost = evalRun.cost_report;

  return (
    <>
      <dl className="audit-meta-grid document-meta-grid" data-testid="eval-run-meta">
        <div className="audit-meta-item">
          <dt>Dataset version</dt>
          <dd>
            <code>{evalRun.dataset_version}</code>
          </dd>
        </div>
        <div className="audit-meta-item">
          <dt>Fixture version</dt>
          <dd>
            <code>{evalRun.fixture_version}</code>
          </dd>
        </div>
        <div className="audit-meta-item">
          <dt>Run at</dt>
          <dd>{formatDateTime(evalRun.run_at)}</dd>
        </div>
        <div className="audit-meta-item">
          <dt>Pipeline version</dt>
          <dd>
            <code>{evalRun.pipeline_version}</code>
          </dd>
        </div>
      </dl>

      <div className="section">
        <h2 className="section-title">Risk severity scoring</h2>
        <div className="stat-grid" data-testid="risk-severity-stats">
          <div className="card stat-tile">
            <p className="stat-tile-label">Precision</p>
            <p className="stat-tile-value font-numeric">{formatPercent(risk.precision)}</p>
          </div>
          <div className="card stat-tile">
            <p className="stat-tile-label">Recall</p>
            <p className="stat-tile-value font-numeric">{formatPercent(risk.recall)}</p>
          </div>
          <div className="card stat-tile">
            <p className="stat-tile-label">F1</p>
            <p className="stat-tile-value font-numeric">{formatPercent(risk.f1)}</p>
          </div>
          <div className="card stat-tile">
            <p className="stat-tile-label">Severity calibration</p>
            <p className="stat-tile-value font-numeric">
              {formatPercent(evalRun.severity_calibration_score)}
            </p>
            <p className="stat-tile-hint">1.0 = exact severity match</p>
          </div>
          <div className="card stat-tile">
            <p className="stat-tile-label">Human-review recall</p>
            <p className="stat-tile-value font-numeric">
              {formatPercent(risk.human_review_recall)}
            </p>
          </div>
        </div>
        <p className="empty-note">
          {risk.true_positives} true positives, {risk.false_positives} false positives,{" "}
          {risk.false_negatives} false negatives across {risk.scored_clause_count} scored clauses
          ({risk.human_review_clause_count} held out as needs_human_review).
        </p>
      </div>

      <div className="section">
        <h2 className="section-title">Mismatch-flag scoring</h2>
        <div className="stat-grid" data-testid="mismatch-stats">
          <div className="card stat-tile">
            <p className="stat-tile-label">Precision</p>
            <p className="stat-tile-value font-numeric">{formatPercent(mismatch.precision)}</p>
          </div>
          <div className="card stat-tile">
            <p className="stat-tile-label">Recall</p>
            <p className="stat-tile-value font-numeric">{formatPercent(mismatch.recall)}</p>
          </div>
        </div>
        <p className="empty-note">
          {mismatch.true_positives} true positives, {mismatch.false_positives} false positives,{" "}
          {mismatch.false_negatives} false negatives against the Razorpay fixture matrix.
        </p>
      </div>

      <div className="section">
        <h2 className="section-title">Cost report</h2>
        <div className="stat-grid" data-testid="cost-report-stats">
          <div className="card stat-tile">
            <p className="stat-tile-label">False positives</p>
            <p className="stat-tile-value font-numeric">{cost.fp_count}</p>
          </div>
          <div className="card stat-tile">
            <p className="stat-tile-label">False negatives</p>
            <p className="stat-tile-value font-numeric">{cost.fn_count}</p>
          </div>
          <div className="card stat-tile">
            <p className="stat-tile-label">FP cost (reviewer-min)</p>
            <p className="stat-tile-value font-numeric">{cost.fp_cost.toFixed(1)}</p>
          </div>
          <div className="card stat-tile">
            <p className="stat-tile-label">FN cost (reviewer-min)</p>
            <p className="stat-tile-value font-numeric">{cost.fn_cost.toFixed(1)}</p>
          </div>
          <div className="card stat-tile">
            <p className="stat-tile-label">FN &divide; FP cost ratio</p>
            <p className="stat-tile-value font-numeric">
              {cost.fn_to_fp_cost_ratio !== null ? cost.fn_to_fp_cost_ratio.toFixed(2) : "N/A"}
            </p>
          </div>
        </div>

        <div className="upload-cost-notice" data-testid="cost-report-note">
          <span className="upload-cost-notice-icon" aria-hidden="true">
            <Icon name="info" size={16} />
          </span>
          <p>{evalRun.false_positive_cost_note}</p>
        </div>

        <CostBreakdown title="By clause type" data-testid="cost-breakdown-clause-type" entries={cost.by_clause_type} />
        <CostBreakdown
          title="By mismatch type"
          data-testid="cost-breakdown-mismatch-type"
          entries={cost.by_mismatch_type}
        />
      </div>
    </>
  );
}

function CostBreakdown({
  title,
  entries,
  "data-testid": dataTestId,
}: {
  title: string;
  entries: Record<string, CostBucketEntry>;
  "data-testid": string;
}) {
  const keys = Object.keys(entries);

  return (
    <div style={{ marginTop: "var(--space-4)" }}>
      <p className="reasoning-stage-label">{title}</p>
      {keys.length === 0 ? (
        <p className="empty-note">No entries.</p>
      ) : (
        <ul className="mismatch-list" data-testid={dataTestId}>
          {keys.map((key) => {
            const entry = entries[key];
            return (
              <li key={key} className="mismatch-item">
                <div className="mismatch-item-head">
                  <code>{key}</code>
                </div>
                <span>
                  {entry.fp_count} FP ({entry.fp_cost.toFixed(1)} min) &middot; {entry.fn_count} FN
                  ({entry.fn_cost.toFixed(1)} min)
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
