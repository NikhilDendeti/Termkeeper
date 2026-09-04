/**
 * Small typed fetch wrapper talking to the Django backend's JSON API.
 *
 * No shared code generation with the backend (see design.md - Non-Goals) -
 * this is a hand-written client. Every exported function throws a typed
 * `ApiError` on a non-2xx response or a network failure, so pages can
 * render the error-state requirement from the spec rather than crash. See
 * openspec/changes/add-react-frontend/specs/frontend/contract-dashboard/
 * spec.md - "Network and error states are handled visibly".
 */

import type {
  ClauseReasoningChain,
  ContractCreatePayload,
  ContractCreateResponse,
  ContractDocument,
  ContractReport,
  ContractSummary,
  GuardrailScanResult,
  AuditLogEntry,
  LatestEvalRunResponse,
} from "./types";

const BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000";

/** Thrown by every client function on a non-2xx response or network failure. */
export class ApiError extends Error {
  /** HTTP status code, or 0 when the request never reached the server (network failure). */
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string): Promise<T> {
  const url = `${BASE_URL}${path}`;
  let response: Response;
  try {
    response = await fetch(url);
  } catch (cause) {
    const detail = cause instanceof Error ? cause.message : String(cause);
    throw new ApiError(`Network error while requesting ${path}: ${detail}`, 0);
  }

  if (!response.ok) {
    throw new ApiError(
      `Request to ${path} failed with status ${response.status} ${response.statusText}`,
      response.status,
    );
  }

  return (await response.json()) as T;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/**
 * Turns a parsed JSON error body into a human-readable message, honoring
 * this project's two write-endpoint error shapes: the pipeline analyze
 * endpoint's `{error, detail, partial_progress, contract_id}` (see
 * pipeline/views.py) and DRF's default per-field validation shape,
 * `{field: [messages, ...]}` (see contracts/views.py, which returns
 * `serializer.errors` or a `ValidationError.message_dict` as-is). Returns
 * null when the body doesn't match either shape, so the caller falls back
 * to a generic status-based message instead.
 */
function extractErrorMessage(payload: unknown): string | null {
  if (!isRecord(payload)) return null;

  const detail = typeof payload.detail === "string" ? payload.detail : null;
  const error = typeof payload.error === "string" ? payload.error : null;
  if (detail && error) return `${detail} (${error})`;
  if (detail) return detail;
  if (error) return error;

  const parts: string[] = [];
  for (const [field, value] of Object.entries(payload)) {
    if (Array.isArray(value) && value.every((entry) => typeof entry === "string")) {
      parts.push(`${field}: ${value.join(" ")}`);
    } else if (typeof value === "string") {
      parts.push(`${field}: ${value}`);
    }
  }
  return parts.length > 0 ? parts.join("; ") : null;
}

/**
 * POST wrapper counterpart to `request` above - used by the two write
 * endpoints this change adds. Unlike `request`, it always reads the
 * response body (even on failure) so a structured error - a DRF field
 * error, or the analyze endpoint's partial-progress detail - reaches the
 * caller as a specific `ApiError.message` rather than a bare status code.
 */
async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const url = `${BASE_URL}${path}`;
  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (cause) {
    const detail = cause instanceof Error ? cause.message : String(cause);
    throw new ApiError(`Network error while requesting ${path}: ${detail}`, 0);
  }

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    const message =
      extractErrorMessage(payload) ??
      `Request to ${path} failed with status ${response.status} ${response.statusText}`;
    throw new ApiError(message, response.status);
  }

  return payload as T;
}

/**
 * POST /contracts/create/ - creates a Contract from submitted text and
 * engagement/Razorpay metadata. Thin wrapper over
 * `contracts.services.create_contract`; on a 400 the thrown `ApiError`
 * names the invalid field(s). See specs/contracts/upload-api/spec.md.
 */
export function createContract(payload: ContractCreatePayload): Promise<ContractCreateResponse> {
  return postJson<ContractCreateResponse>("/contracts/create/", payload);
}

/**
 * POST /contracts/<id>/analyze/ - runs the existing pipeline synchronously
 * against an already-created contract and returns its aggregate report.
 * This can take from under a minute to several minutes (real model calls
 * per clause) - callers should show a distinct, explanatory loading state
 * for the duration, not a generic spinner. On a mid-run failure the backend
 * returns a 502 naming the contract id and stating that partial progress
 * was saved; the thrown `ApiError.message` carries that detail (see
 * `extractErrorMessage` above). See specs/pipeline/analyze-api/spec.md.
 */
export function analyzeContract(contractId: string): Promise<ContractReport> {
  return postJson<ContractReport>(`/contracts/${contractId}/analyze/`);
}

/** GET /contracts/ - every ingested contract's summary, newest first. */
export function getContracts(): Promise<ContractSummary[]> {
  return request<ContractSummary[]>("/contracts/");
}

/** GET /contracts/<id>/report/ - a contract's aggregate risk report. */
export function getContractReport(contractId: string): Promise<ContractReport> {
  return request<ContractReport>(`/contracts/${contractId}/report/`);
}

/** GET /contracts/<id>/reasoning-chain/ - a contract's full per-clause reasoning chain. */
export function getContractReasoningChain(contractId: string): Promise<ClauseReasoningChain[]> {
  return request<ClauseReasoningChain[]>(`/contracts/${contractId}/reasoning-chain/`);
}

/** GET /contracts/<id>/document/ - a contract's full original text, unsegmented. */
export function getContractDocument(contractId: string): Promise<ContractDocument> {
  return request<ContractDocument>(`/contracts/${contractId}/document/`);
}

/** GET /contracts/<id>/audit-trail/ - a contract's full audit trail, in stage order. */
export function getContractAuditTrail(contractId: string): Promise<AuditLogEntry[]> {
  return request<AuditLogEntry[]>(`/contracts/${contractId}/audit-trail/`);
}

/** GET /guardrail-verification/ - the live Razorpay write-call guardrail scan result. */
export function getGuardrailStatus(): Promise<GuardrailScanResult> {
  return request<GuardrailScanResult>("/guardrail-verification/");
}

/**
 * GET /eval-runs/latest/ - the evaluation harness's most recently persisted
 * EvalRun, wrapped as `{ eval_run }` (explicitly null when none has ever
 * been persisted - not an error). See evaluation/views.py::LatestEvalRunAPIView.
 */
export function getLatestEvalRun(): Promise<LatestEvalRunResponse> {
  return request<LatestEvalRunResponse>("/eval-runs/latest/");
}
