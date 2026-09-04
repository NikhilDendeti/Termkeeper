import type { ScoredSeverity } from "../api/types";

/**
 * Buckets a contract's `overall_risk_score` (a 0-1 weighted average of its
 * scored clauses' severity - see reporting/selectors.py's
 * `_SEVERITY_WEIGHTS`: critical=1.0, high=0.75, medium=0.5, low=0.25) into
 * one of the four scored severity bands, purely for the list page's
 * at-a-glance color coding. This is a display-only derivation, distinct
 * from any single clause's own `severity` field.
 */
export function scoreToSeverityBand(score: number): ScoredSeverity {
  if (score >= 0.875) return "critical";
  if (score >= 0.625) return "high";
  if (score >= 0.375) return "medium";
  return "low";
}

/**
 * Buckets a 0-1 "higher is better" quality score (precision, recall, F1,
 * severity-calibration, human-review recall) into the same four severity
 * tiers `scoreToSeverityBand` uses for risk - but inverted, since a high
 * quality score is good (green/"low") and a low one is bad (red/"critical"),
 * the opposite direction from a risk score's own scale.
 */
export function qualityToSeverityBand(score: number): ScoredSeverity {
  if (score >= 0.875) return "low";
  if (score >= 0.625) return "medium";
  if (score >= 0.375) return "high";
  return "critical";
}
