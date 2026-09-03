import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuditLogEntry, ClauseReasoningChain } from "../api/types";
import ContractDetailPage from "./ContractDetailPage";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    getContractReasoningChain: vi.fn(),
    getContractAuditTrail: vi.fn(),
  };
});

import { getContractAuditTrail, getContractReasoningChain } from "../api/client";

const mockedGetChain = vi.mocked(getContractReasoningChain);
const mockedGetAuditTrail = vi.mocked(getContractAuditTrail);

function renderPage(contractId = "c1") {
  return render(
    <MemoryRouter initialEntries={[`/contracts/${contractId}`]}>
      <Routes>
        <Route path="/contracts/:id" element={<ContractDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

const scoredClause: ClauseReasoningChain = {
  clause_id: "clause-1",
  sequence_index: 1,
  clause_type: "payment_schedule",
  clause_text: "Payments occur monthly.",
  classification_confidence: 0.95,
  classification_rationale: "Clear payment cadence language.",
  classification_needs_human_review: false,
  extracted_terms: [
    {
      id: "term-1",
      term_type: "payout_frequency",
      value_raw: "monthly",
      value_structured: { numeric_value: null, unit: "month" },
      extraction_confidence: 0.88,
      needs_human_review: false,
      created_at: "2026-01-01T00:00:00Z",
    },
  ],
  platform_evidence: [],
  verified_platform_records: [],
  risk_assessment: {
    id: "risk-1",
    severity: "low",
    asymmetry_score: 0.1,
    explanation: "Balanced payment terms.",
    suggested_rewrite: null,
    linked_mismatch_flag_ids: [],
    created_at: "2026-01-01T00:00:00Z",
  },
};

const unscoredClause: ClauseReasoningChain = {
  clause_id: "clause-2",
  sequence_index: 2,
  clause_type: "termination",
  clause_text: "Either party may terminate with notice.",
  classification_confidence: 0.7,
  classification_rationale: null,
  classification_needs_human_review: false,
  extracted_terms: [],
  platform_evidence: [],
  verified_platform_records: [],
  risk_assessment: null,
};

const auditEntry: AuditLogEntry = {
  id: "audit-1",
  contract_id: "c1",
  clause_id: "clause-1",
  stage: 2,
  prompt_version: "v1",
  llm_response_raw: { classification: "payment_schedule", confidence: 0.95 },
  model_name: "claude-test",
  latency_ms: 512,
  created_at: "2026-01-01T00:05:00Z",
};

describe("ContractDetailPage", () => {
  beforeEach(() => {
    mockedGetChain.mockReset();
    mockedGetAuditTrail.mockReset();
  });

  it("shows loading, then the reasoning chain in sequence order", async () => {
    mockedGetChain.mockResolvedValueOnce([scoredClause, unscoredClause]);
    mockedGetAuditTrail.mockResolvedValueOnce([]);

    renderPage();

    expect(screen.getByTestId("loading-state")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByTestId("clause-chain")).toBeInTheDocument());

    const items = screen.getAllByText(/^Clause \d$/);
    expect(items[0]).toHaveTextContent("Clause 1");
    expect(items[1]).toHaveTextContent("Clause 2");
  });

  it("shows an explicit 'no platform evidence' state for a clause with no linked mismatch", async () => {
    mockedGetChain.mockResolvedValueOnce([scoredClause]);
    mockedGetAuditTrail.mockResolvedValueOnce([]);

    renderPage();

    await waitFor(() => expect(screen.getByTestId("clause-chain")).toBeInTheDocument());

    expect(screen.getByTestId("no-platform-evidence")).toHaveTextContent(
      "No platform evidence available",
    );
  });

  it("shows a distinct 'confirmed' state for a clause with verified platform records and no mismatch", async () => {
    const confirmedClause: ClauseReasoningChain = {
      ...scoredClause,
      platform_evidence: [],
      verified_platform_records: [
        {
          id: "record-1",
          record_type: "payout",
          razorpay_id: "pout_000001",
          payload: { id: "pout_000001", amount: 500000 },
          razorpay_created_at: "2026-01-01T00:00:00Z",
        },
      ],
    };
    mockedGetChain.mockResolvedValueOnce([confirmedClause]);
    mockedGetAuditTrail.mockResolvedValueOnce([]);

    renderPage();

    await waitFor(() => expect(screen.getByTestId("clause-chain")).toBeInTheDocument());

    expect(screen.getByTestId("confirmed-platform-evidence")).toHaveTextContent(
      "Confirmed - matches platform data",
    );
    expect(screen.getByTestId("confirmed-record-list")).toHaveTextContent("pout_000001");
    expect(screen.queryByTestId("no-platform-evidence")).not.toBeInTheDocument();
    expect(screen.queryByTestId("mismatch-list")).not.toBeInTheDocument();
  });

  it("shows the mismatch, not confirmed evidence, for a clause with both a linked mismatch and verified platform records", async () => {
    const mismatchedClause: ClauseReasoningChain = {
      ...scoredClause,
      platform_evidence: [
        {
          mismatch_id: "mismatch-1",
          mismatch_type: "amount_mismatch",
          clause_id: "clause-1",
          sequence_index: 1,
          expected_value: { amount: 500000 },
          actual_value: { amount: 400000 },
          description: "Payout amount does not match the contract's payment schedule.",
        },
      ],
      // Backend guarantees these are mutually exclusive, but the component
      // must not re-derive that itself - the mismatch branch must win even
      // if `verified_platform_records` were somehow non-empty too.
      verified_platform_records: [
        {
          id: "record-1",
          record_type: "payout",
          razorpay_id: "pout_000001",
          payload: { id: "pout_000001", amount: 400000 },
          razorpay_created_at: "2026-01-01T00:00:00Z",
        },
      ],
    };
    mockedGetChain.mockResolvedValueOnce([mismatchedClause]);
    mockedGetAuditTrail.mockResolvedValueOnce([]);

    renderPage();

    await waitFor(() => expect(screen.getByTestId("clause-chain")).toBeInTheDocument());

    expect(screen.getByTestId("mismatch-list")).toBeInTheDocument();
    expect(screen.queryByTestId("confirmed-platform-evidence")).not.toBeInTheDocument();
  });

  it("shows an explicit 'not yet assessed' state for a clause with a null risk_assessment", async () => {
    mockedGetChain.mockResolvedValueOnce([unscoredClause]);
    mockedGetAuditTrail.mockResolvedValueOnce([]);

    renderPage();

    await waitFor(() => expect(screen.getByTestId("clause-chain")).toBeInTheDocument());

    expect(screen.getByTestId("not-yet-assessed")).toHaveTextContent("Not yet assessed");
  });

  it("visibly distinguishes a needs_human_review clause from a scored clause", async () => {
    const reviewClause: ClauseReasoningChain = {
      ...unscoredClause,
      clause_id: "clause-3",
      sequence_index: 3,
      clause_type: "needs_human_review",
      classification_needs_human_review: true,
    };
    mockedGetChain.mockResolvedValueOnce([scoredClause, reviewClause]);
    mockedGetAuditTrail.mockResolvedValueOnce([]);

    renderPage();

    await waitFor(() => expect(screen.getByTestId("clause-chain")).toBeInTheDocument());

    const badges = screen.getAllByTestId("severity-badge");
    const reviewBadges = badges.filter((b) => b.classList.contains("severity-badge--needs_human_review"));
    expect(reviewBadges.length).toBeGreaterThan(0);
  });

  it("shows the audit trail with stage, prompt version, model, and latency, and lets the raw response be inspected without navigating away", async () => {
    mockedGetChain.mockResolvedValueOnce([]);
    mockedGetAuditTrail.mockResolvedValueOnce([auditEntry]);

    const user = userEvent.setup();
    renderPage();

    await waitFor(() => expect(screen.getByRole("tab", { name: /audit trail/i })).toBeInTheDocument());
    await user.click(screen.getByRole("tab", { name: /audit trail/i }));

    const list = screen.getByTestId("audit-list");
    expect(within(list).getByText("v1")).toBeInTheDocument();
    expect(within(list).getByText("claude-test")).toBeInTheDocument();
    expect(within(list).getByText("512")).toBeInTheDocument();

    // Raw response is not visible until the <details> is opened...
    expect(within(list).getByTestId("raw-response")).not.toBeVisible();

    await user.click(within(list).getByText("Raw model response"));

    // ...and is inspectable in place, without leaving the page.
    expect(within(list).getByTestId("raw-response")).toBeVisible();
    expect(within(list).getByTestId("raw-response").textContent).toContain("payment_schedule");
  });

  it("shows an error state when either request fails", async () => {
    mockedGetChain.mockRejectedValueOnce(new Error("boom"));
    mockedGetAuditTrail.mockResolvedValueOnce([]);

    renderPage();

    await waitFor(() => expect(screen.getByTestId("error-state")).toBeInTheDocument());
  });
});
