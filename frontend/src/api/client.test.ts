import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  getContractAuditTrail,
  getContractReasoningChain,
  getContractReport,
  getContracts,
  getGuardrailStatus,
} from "./client";
import type {
  AuditLogEntry,
  ClauseReasoningChain,
  ContractReport,
  ContractSummary,
  GuardrailScanResult,
} from "./types";

function jsonResponse(body: unknown, init?: { ok?: boolean; status?: number; statusText?: string }) {
  return {
    ok: init?.ok ?? true,
    status: init?.status ?? 200,
    statusText: init?.statusText ?? "OK",
    json: () => Promise.resolve(body),
  } as Response;
}

describe("api/client", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  describe("getContracts", () => {
    it("returns the parsed contract summary list on success", async () => {
      const summaries: ContractSummary[] = [
        {
          contract_id: "c1",
          engagement_id: "ENG-1",
          razorpay_reference_type: "payout",
          overall_risk_score: 0.5,
          needs_human_review_count: 0,
          created_at: "2026-01-01T00:00:00Z",
        },
      ];
      fetchMock.mockResolvedValueOnce(jsonResponse(summaries));

      const result = await getContracts();

      expect(result).toEqual(summaries);
      expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/contracts/");
    });

    it("throws a typed ApiError on a non-2xx response", async () => {
      fetchMock.mockResolvedValueOnce(
        jsonResponse(null, { ok: false, status: 500, statusText: "Internal Server Error" }),
      );

      await expect(getContracts()).rejects.toMatchObject({
        name: "ApiError",
        status: 500,
      });
    });

    it("throws a typed ApiError on a network failure", async () => {
      fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));

      const error = await getContracts().catch((e: unknown) => e);

      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).status).toBe(0);
    });
  });

  describe("getContractReport", () => {
    it("requests the per-contract report endpoint", async () => {
      const report: ContractReport = {
        contract_id: "c1",
        overall_risk_score: null,
        flagged_clauses: [],
        platform_mismatches: [],
        needs_human_review_clauses: [],
        severity_breakdown_by_clause_type: {},
      };
      fetchMock.mockResolvedValueOnce(jsonResponse(report));

      const result = await getContractReport("c1");

      expect(result).toEqual(report);
      expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/contracts/c1/report/");
    });

    it("throws ApiError on failure", async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse(null, { ok: false, status: 404 }));
      await expect(getContractReport("missing")).rejects.toBeInstanceOf(ApiError);
    });
  });

  describe("getContractReasoningChain", () => {
    it("requests the reasoning-chain endpoint", async () => {
      const chain: ClauseReasoningChain[] = [];
      fetchMock.mockResolvedValueOnce(jsonResponse(chain));

      const result = await getContractReasoningChain("c1");

      expect(result).toEqual(chain);
      expect(fetchMock).toHaveBeenCalledWith(
        "http://localhost:8000/contracts/c1/reasoning-chain/",
      );
    });

    it("throws ApiError on failure", async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse(null, { ok: false, status: 404 }));
      await expect(getContractReasoningChain("missing")).rejects.toBeInstanceOf(ApiError);
    });
  });

  describe("getContractAuditTrail", () => {
    it("requests the audit-trail endpoint", async () => {
      const entries: AuditLogEntry[] = [];
      fetchMock.mockResolvedValueOnce(jsonResponse(entries));

      const result = await getContractAuditTrail("c1");

      expect(result).toEqual(entries);
      expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/contracts/c1/audit-trail/");
    });

    it("throws ApiError on failure", async () => {
      fetchMock.mockRejectedValueOnce(new Error("boom"));
      await expect(getContractAuditTrail("c1")).rejects.toBeInstanceOf(ApiError);
    });
  });

  describe("getGuardrailStatus", () => {
    it("requests the guardrail-verification endpoint", async () => {
      const scan: GuardrailScanResult = { passed: true, scanned_files: [], violations: [] };
      fetchMock.mockResolvedValueOnce(jsonResponse(scan));

      const result = await getGuardrailStatus();

      expect(result).toEqual(scan);
      expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/guardrail-verification/");
    });

    it("throws ApiError on failure", async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse(null, { ok: false, status: 503 }));
      await expect(getGuardrailStatus()).rejects.toBeInstanceOf(ApiError);
    });
  });
});
