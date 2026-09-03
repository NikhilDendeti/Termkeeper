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
  ContractReport,
  ContractSummary,
  GuardrailScanResult,
  AuditLogEntry,
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

/** GET /contracts/<id>/audit-trail/ - a contract's full audit trail, in stage order. */
export function getContractAuditTrail(contractId: string): Promise<AuditLogEntry[]> {
  return request<AuditLogEntry[]>(`/contracts/${contractId}/audit-trail/`);
}

/** GET /guardrail-verification/ - the live Razorpay write-call guardrail scan result. */
export function getGuardrailStatus(): Promise<GuardrailScanResult> {
  return request<GuardrailScanResult>("/guardrail-verification/");
}
