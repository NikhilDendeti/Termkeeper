/**
 * TypeScript mirrors of every `reporting` app DRF serializer, field-for-field.
 *
 * Field names and nesting here match `reporting/serializers.py` and the
 * dataclasses in `reporting/selectors.py` (see openspec/changes/
 * add-react-frontend/design.md - Decisions, "frontend/src/api/types.ts").
 * Two serializers already exist on disk today (`ContractReportSerializer`,
 * `AuditLogEntrySerializer`); the rest are new endpoints this change adds
 * to the backend in parallel - their shapes below follow the same flat,
 * snake_case, dataclass-mirroring convention the existing serializers use.
 */

// ---------------------------------------------------------------------------
// Fixed taxonomies (mirrored from the Django model TextChoices - see
// contracts/models.py, pipeline/models.py, risk_scoring/models.py,
// razorpay_integration/models.py). Hardcoded here per design.md - no
// taxonomy-fetching endpoint exists or is needed for five/eight constants.
// ---------------------------------------------------------------------------

export type Severity = "low" | "medium" | "high" | "critical" | "needs_human_review";

export type ScoredSeverity = Exclude<Severity, "needs_human_review">;

export type ClauseType =
  | "payment_schedule"
  | "termination"
  | "penalty_late_fee"
  | "dispute_resolution"
  | "auto_renewal"
  | "indemnity"
  | "other"
  | "needs_human_review";

export type RazorpayReferenceType = "payout" | "subscription";

// razorpay_integration.models.PlatformRecordType - the three kinds of raw
// Razorpay resource that app fetches via GET.
export type PlatformRecordType = "payout" | "subscription" | "token";

export type TermType =
  | "payout_frequency"
  | "milestone_trigger"
  | "penalty_amount"
  | "notice_period"
  | "auto_renewal_term";

export type MismatchType =
  | "cadence_mismatch"
  | "amount_mismatch"
  | "missing_platform_evidence"
  | "trigger_condition_unverifiable";

// ---------------------------------------------------------------------------
// api/contract-listing (ContractSummarySerializer)
// ---------------------------------------------------------------------------

export interface ContractSummary {
  contract_id: string;
  engagement_id: string;
  razorpay_reference_type: RazorpayReferenceType;
  overall_risk_score: number | null;
  needs_human_review_count: number;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Existing: GET /contracts/<id>/report/ (ContractReportSerializer)
// ---------------------------------------------------------------------------

export interface FlaggedClause {
  clause_id: string;
  sequence_index: number;
  clause_type: ClauseType | null;
  clause_text: string;
  severity: ScoredSeverity;
  asymmetry_score: number;
  explanation: string;
  suggested_rewrite: string | null;
  linked_mismatch_flag_ids: string[];
}

export interface PlatformMismatch {
  mismatch_id: string;
  mismatch_type: MismatchType;
  clause_id: string;
  sequence_index: number;
  expected_value: unknown;
  actual_value: unknown;
  description: string;
}

export interface NeedsHumanReviewClause {
  clause_id: string;
  sequence_index: number;
  clause_type: ClauseType | null;
  clause_text: string;
  explanation: string;
}

// Per-clause-type entry of `ContractReport.severity_breakdown_by_clause_type`
// - mirrors `reporting.selectors._compute_clause_type_breakdown`'s per-group
// shape (task group 1 / spec: reporting/clause-type-breakdown). Keyed by
// `ClauseType` (or "unknown" as a defensive fallback - see the selector's
// docstring), so the map itself is a plain `Record<string, ...>` rather than
// `Record<ClauseType, ...>`.
export interface ClauseTypeSeverityBreakdown {
  count: number;
  mean_asymmetry_score: number;
}

export interface ContractReport {
  contract_id: string;
  overall_risk_score: number | null;
  flagged_clauses: FlaggedClause[];
  platform_mismatches: PlatformMismatch[];
  needs_human_review_clauses: NeedsHumanReviewClause[];
  severity_breakdown_by_clause_type: Record<string, ClauseTypeSeverityBreakdown>;
}

// ---------------------------------------------------------------------------
// Existing: GET /contracts/<id>/audit-trail/ (AuditLogEntrySerializer)
// ---------------------------------------------------------------------------

export interface AuditLogEntry {
  id: string;
  contract_id: string;
  clause_id: string | null;
  stage: number;
  prompt_version: string;
  llm_response_raw: unknown;
  model_name: string;
  latency_ms: number;
  created_at: string;
}

// ---------------------------------------------------------------------------
// api/reasoning-chain (ClauseReasoningChainSerializer)
// ---------------------------------------------------------------------------

export interface ExtractedTermEntry {
  id: string;
  term_type: TermType;
  value_raw: string;
  value_structured: Record<string, unknown>;
  extraction_confidence: number;
  needs_human_review: boolean;
  created_at: string;
}

// razorpay_integration.models.PlatformRecord, as exposed by
// reporting.serializers.PlatformRecordSerializer - only these 5 fields
// (the model's `contract` FK and `fetched_at` are not exposed). Used for
// `ClauseReasoningChain.verified_platform_records` - a clause's *confirmed*
// platform evidence (checked, no mismatch found), distinct from
// `platform_evidence`'s flagged-deviation evidence. See
// specs/reporting/confirmed-platform-evidence/spec.md
// (add-confirmed-platform-evidence).
export interface PlatformRecord {
  id: string;
  record_type: PlatformRecordType;
  razorpay_id: string;
  payload: unknown;
  razorpay_created_at: string;
}

export interface RiskAssessmentEntry {
  id: string;
  severity: Severity;
  asymmetry_score: number;
  explanation: string;
  suggested_rewrite: string | null;
  linked_mismatch_flag_ids: string[];
  created_at: string;
}

export interface ClauseReasoningChain {
  clause_id: string;
  sequence_index: number;
  clause_type: ClauseType | null;
  clause_text: string;
  classification_confidence: number | null;
  classification_rationale: string | null;
  classification_needs_human_review: boolean;
  extracted_terms: ExtractedTermEntry[];
  // Platform evidence for this clause - PlatformMismatchSerializer-shaped.
  // The wire field is `platform_evidence`, not the underlying
  // `ClauseReasoningChain.mismatch_flags` Python attribute name -
  // `MismatchFlagSerializer` is declared as
  // `platform_evidence = MismatchFlagSerializer(source="mismatch_flags", ...)`
  // in reporting/serializers.py, and DRF's `source=` only controls which
  // Python attribute is read, not the outer JSON key. See
  // specs/api/reasoning-chain/spec.md.
  platform_evidence: PlatformMismatch[];
  // Confirmed platform evidence: non-empty only when this clause has at
  // least one extracted term, zero linked mismatch flags, and the contract
  // has relevant platform records. Always present as a list (possibly
  // empty), never omitted or null - same convention as `extracted_terms`
  // and `platform_evidence`. Mutually exclusive with `platform_evidence`
  // being non-empty by construction on the backend - a mismatch always
  // wins, so this field and `platform_evidence` are never both non-empty
  // for the same clause. See
  // specs/reporting/confirmed-platform-evidence/spec.md.
  verified_platform_records: PlatformRecord[];
  risk_assessment: RiskAssessmentEntry | null;
}

// ---------------------------------------------------------------------------
// api/guardrail-verification (GuardrailScanResultSerializer)
// ---------------------------------------------------------------------------

export interface GuardrailViolation {
  file: string;
  line: number;
  matched_call: string;
}

export interface GuardrailScanResult {
  passed: boolean;
  scanned_files: string[];
  violations: GuardrailViolation[];
}
