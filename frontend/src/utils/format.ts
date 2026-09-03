/**
 * Display-label lookups and small formatting helpers.
 *
 * The label text mirrors each Django `TextChoices`' human-readable label
 * (see contracts/models.py, pipeline/models.py, risk_scoring/models.py,
 * razorpay_integration/models.py) so the frontend reads the same as
 * report_ui's server-rendered templates, which call `get_FOO_display()`.
 */

import type {
  ClauseType,
  MismatchType,
  PlatformRecordType,
  RazorpayReferenceType,
  Severity,
  TermType,
} from "../api/types";

const CLAUSE_TYPE_LABELS: Record<ClauseType, string> = {
  payment_schedule: "Payment schedule",
  termination: "Termination",
  penalty_late_fee: "Penalty / late fee",
  dispute_resolution: "Dispute resolution",
  auto_renewal: "Auto-renewal",
  indemnity: "Indemnity",
  other: "Other",
  needs_human_review: "Needs human review",
};

const TERM_TYPE_LABELS: Record<TermType, string> = {
  payout_frequency: "Payout frequency",
  milestone_trigger: "Milestone trigger",
  penalty_amount: "Penalty amount",
  notice_period: "Notice period",
  auto_renewal_term: "Auto-renewal term",
};

const MISMATCH_TYPE_LABELS: Record<MismatchType, string> = {
  cadence_mismatch: "Cadence mismatch",
  amount_mismatch: "Amount mismatch",
  missing_platform_evidence: "Missing platform evidence",
  trigger_condition_unverifiable: "Trigger condition unverifiable",
};

const SEVERITY_LABELS: Record<Severity, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  critical: "Critical",
  needs_human_review: "Needs human review",
};

const RAZORPAY_REFERENCE_TYPE_LABELS: Record<RazorpayReferenceType, string> = {
  payout: "Payout",
  subscription: "Subscription",
};

const PLATFORM_RECORD_TYPE_LABELS: Record<PlatformRecordType, string> = {
  payout: "Payout",
  subscription: "Subscription",
  token: "Token",
};

// AuditLogEntry.stage is an unconstrained int - `pipeline.models.PipelineStage`
// only enumerates 1-3; stages 4 (razorpay_integration) and 5 (risk_scoring)
// are appended integers by design (see those apps' services.py comments,
// "additive by construction"). Labelled here for display only.
const PIPELINE_STAGE_LABELS: Record<number, string> = {
  1: "Segmentation",
  2: "Classification",
  3: "Extraction",
  4: "Platform cross-check",
  5: "Risk scoring",
};

export function clauseTypeLabel(clauseType: ClauseType | null): string {
  if (clauseType === null) return "Not yet classified";
  return CLAUSE_TYPE_LABELS[clauseType] ?? clauseType;
}

export function termTypeLabel(termType: TermType): string {
  return TERM_TYPE_LABELS[termType] ?? termType;
}

export function mismatchTypeLabel(mismatchType: MismatchType): string {
  return MISMATCH_TYPE_LABELS[mismatchType] ?? mismatchType;
}

export function severityLabel(severity: Severity): string {
  return SEVERITY_LABELS[severity] ?? severity;
}

export function razorpayReferenceTypeLabel(value: RazorpayReferenceType): string {
  return RAZORPAY_REFERENCE_TYPE_LABELS[value] ?? value;
}

export function platformRecordTypeLabel(value: PlatformRecordType): string {
  return PLATFORM_RECORD_TYPE_LABELS[value] ?? value;
}

export function pipelineStageLabel(stage: number): string {
  return PIPELINE_STAGE_LABELS[stage] ?? `Stage ${stage}`;
}

export function formatScore(score: number | null): string {
  if (score === null) return "N/A";
  return score.toFixed(2);
}

export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
