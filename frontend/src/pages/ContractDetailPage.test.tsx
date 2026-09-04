import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AuditLogEntry, ClauseReasoningChain, ContractDocument } from "../api/types";
import ContractDetailPage from "./ContractDetailPage";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    getContractReasoningChain: vi.fn(),
    getContractAuditTrail: vi.fn(),
    getContractDocument: vi.fn(),
  };
});

import { getContractAuditTrail, getContractDocument, getContractReasoningChain } from "../api/client";

const mockedGetChain = vi.mocked(getContractReasoningChain);
const mockedGetAuditTrail = vi.mocked(getContractAuditTrail);
const mockedGetDocument = vi.mocked(getContractDocument);

const sampleDocument: ContractDocument = {
  contract_id: "c1",
  engagement_id: "engagement-1",
  razorpay_reference_type: "payout",
  razorpay_reference_id: "pout_test_001",
  raw_text: "1. PAYMENT. Client pays Contractor INR 10,000 monthly.",
  source_filename: null,
  created_at: "2026-01-01T00:00:00Z",
  needs_human_review: false,
  human_review_reason: null,
};

/** The page defaults to the Document tab on load - open Reasoning chain explicitly. */
async function openReasoningChainTab(user: ReturnType<typeof userEvent.setup>) {
  await waitFor(() => expect(screen.getByRole("tab", { name: /reasoning chain/i })).toBeInTheDocument());
  await user.click(screen.getByRole("tab", { name: /reasoning chain/i }));
}

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
  overdue_statuses: [],
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
  overdue_statuses: [],
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
  prev_hash: null,
  entry_hash: null,
  chain_sequence: null,
};

describe("ContractDetailPage", () => {
  beforeEach(() => {
    mockedGetChain.mockReset();
    mockedGetAuditTrail.mockReset();
    mockedGetDocument.mockReset();
    mockedGetDocument.mockResolvedValue(sampleDocument);
  });

  it("shows loading, then the Document tab by default, with the original text", async () => {
    mockedGetChain.mockResolvedValueOnce([scoredClause, unscoredClause]);
    mockedGetAuditTrail.mockResolvedValueOnce([]);

    renderPage();

    expect(screen.getByTestId("loading-state")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByTestId("document-raw-text")).toBeInTheDocument());

    expect(screen.getByRole("tab", { name: /document/i })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("document-raw-text")).toHaveTextContent(sampleDocument.raw_text);
    expect(screen.getByText("engagement-1")).toBeInTheDocument();
    expect(screen.getByText("pout_test_001")).toBeInTheDocument();
  });

  it("shows a needs-human-review banner with the reason when the contract document is flagged", async () => {
    mockedGetChain.mockResolvedValueOnce([scoredClause, unscoredClause]);
    mockedGetAuditTrail.mockResolvedValueOnce([]);
    mockedGetDocument.mockReset();
    mockedGetDocument.mockResolvedValue({
      ...sampleDocument,
      needs_human_review: true,
      human_review_reason: "Stage-1 segmentation failed verbatim-matching twice.",
    });

    renderPage();

    await waitFor(() => expect(screen.getByTestId("document-raw-text")).toBeInTheDocument());

    expect(screen.getByTestId("needs-review-banner")).toBeInTheDocument();
    expect(screen.getByTestId("needs-review-reason")).toHaveTextContent(
      "Stage-1 segmentation failed verbatim-matching twice.",
    );
  });

  it("shows no needs-human-review banner when the contract document is not flagged", async () => {
    mockedGetChain.mockResolvedValueOnce([scoredClause, unscoredClause]);
    mockedGetAuditTrail.mockResolvedValueOnce([]);

    renderPage();

    await waitFor(() => expect(screen.getByTestId("document-raw-text")).toBeInTheDocument());

    expect(screen.queryByTestId("needs-review-banner")).not.toBeInTheDocument();
  });

  it("shows the reasoning chain in sequence order once that tab is selected", async () => {
    mockedGetChain.mockResolvedValueOnce([scoredClause, unscoredClause]);
    mockedGetAuditTrail.mockResolvedValueOnce([]);

    const user = userEvent.setup();
    renderPage();
    await openReasoningChainTab(user);

    await waitFor(() => expect(screen.getByTestId("clause-chain")).toBeInTheDocument());

    const items = screen.getAllByText(/^Clause \d$/);
    expect(items[0]).toHaveTextContent("Clause 1");
    expect(items[1]).toHaveTextContent("Clause 2");
  });

  it("shows an explicit 'no platform evidence' state for a clause with no linked mismatch", async () => {
    mockedGetChain.mockResolvedValueOnce([scoredClause]);
    mockedGetAuditTrail.mockResolvedValueOnce([]);

    const user = userEvent.setup();
    renderPage();
    await openReasoningChainTab(user);

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

    const user = userEvent.setup();
    renderPage();
    await openReasoningChainTab(user);

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

    const user1 = userEvent.setup();
    renderPage();
    await openReasoningChainTab(user1);

    await waitFor(() => expect(screen.getByTestId("clause-chain")).toBeInTheDocument());

    expect(screen.getByTestId("mismatch-list")).toBeInTheDocument();
    expect(screen.queryByTestId("confirmed-platform-evidence")).not.toBeInTheDocument();
  });

  it("shows an overdue warning banner for a term list_overdue_statuses reports as overdue", async () => {
    const overdueClause: ClauseReasoningChain = {
      ...scoredClause,
      overdue_statuses: [
        {
          term_id: "term-1",
          is_overdue: true,
          days_since_last_payout: 40,
          expected_interval_days: 30,
          latest_payout_date: "2026-01-01T00:00:00Z",
        },
      ],
    };
    mockedGetChain.mockResolvedValueOnce([overdueClause]);
    mockedGetAuditTrail.mockResolvedValueOnce([]);

    const user = userEvent.setup();
    renderPage();
    await openReasoningChainTab(user);

    await waitFor(() => expect(screen.getByTestId("clause-chain")).toBeInTheDocument());

    const banner = screen.getByTestId("overdue-banner");
    expect(banner).toHaveTextContent("Overdue");
    expect(banner).toHaveTextContent("expected every 30 days");
    expect(banner).toHaveTextContent("last payout was 40 days ago");
  });

  it("shows no overdue banner when the term's overdue status is not overdue", async () => {
    const notOverdueClause: ClauseReasoningChain = {
      ...scoredClause,
      overdue_statuses: [
        {
          term_id: "term-1",
          is_overdue: false,
          days_since_last_payout: 5,
          expected_interval_days: 30,
          latest_payout_date: "2026-01-01T00:00:00Z",
        },
      ],
    };
    mockedGetChain.mockResolvedValueOnce([notOverdueClause]);
    mockedGetAuditTrail.mockResolvedValueOnce([]);

    const user = userEvent.setup();
    renderPage();
    await openReasoningChainTab(user);

    await waitFor(() => expect(screen.getByTestId("clause-chain")).toBeInTheDocument());

    expect(screen.queryByTestId("overdue-banner")).not.toBeInTheDocument();
  });

  it("shows no overdue banner when overdue_statuses is empty", async () => {
    mockedGetChain.mockResolvedValueOnce([scoredClause]);
    mockedGetAuditTrail.mockResolvedValueOnce([]);

    const user = userEvent.setup();
    renderPage();
    await openReasoningChainTab(user);

    await waitFor(() => expect(screen.getByTestId("clause-chain")).toBeInTheDocument());

    expect(screen.queryByTestId("overdue-banner")).not.toBeInTheDocument();
  });

  it("shows an explicit 'not yet assessed' state for a clause with a null risk_assessment", async () => {
    mockedGetChain.mockResolvedValueOnce([unscoredClause]);
    mockedGetAuditTrail.mockResolvedValueOnce([]);

    const user2 = userEvent.setup();
    renderPage();
    await openReasoningChainTab(user2);

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

    const user3 = userEvent.setup();
    renderPage();
    await openReasoningChainTab(user3);

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

  it("isolates a failure to the tab that failed, leaving the other tabs usable", async () => {
    mockedGetChain.mockRejectedValueOnce(new Error("boom"));
    mockedGetAuditTrail.mockResolvedValueOnce([auditEntry]);

    const user = userEvent.setup();
    renderPage();

    // The default Document tab is unaffected by the reasoning-chain failure.
    await waitFor(() => expect(screen.getByTestId("document-raw-text")).toBeInTheDocument());

    await user.click(screen.getByRole("tab", { name: /reasoning chain/i }));
    await waitFor(() => expect(screen.getByTestId("error-state")).toBeInTheDocument());

    // Audit trail, unaffected by either other request, still works.
    await user.click(screen.getByRole("tab", { name: /audit trail/i }));
    await waitFor(() => expect(screen.getByTestId("audit-list")).toBeInTheDocument());
  });

  it("retries only the failed section, without disturbing an already-loaded tab", async () => {
    mockedGetChain.mockRejectedValueOnce(new Error("boom"));
    mockedGetChain.mockResolvedValueOnce([scoredClause]);
    mockedGetAuditTrail.mockResolvedValueOnce([]);

    const user = userEvent.setup();
    renderPage();

    await waitFor(() => expect(screen.getByTestId("document-raw-text")).toBeInTheDocument());

    await user.click(screen.getByRole("tab", { name: /reasoning chain/i }));
    await waitFor(() => expect(screen.getByTestId("error-state")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /retry/i }));
    await waitFor(() => expect(screen.getByTestId("clause-chain")).toBeInTheDocument());

    // The Document tab's already-fetched data was never touched by the retry.
    await user.click(screen.getByRole("tab", { name: /document/i }));
    expect(screen.getByTestId("document-raw-text")).toBeInTheDocument();
  });

  it("wires each tab button to its panel via ARIA (role=tabpanel, aria-controls/aria-labelledby)", async () => {
    mockedGetChain.mockResolvedValueOnce([scoredClause]);
    mockedGetAuditTrail.mockResolvedValueOnce([]);

    renderPage();

    const documentTab = await screen.findByRole("tab", { name: /document/i });
    const panel = screen.getByRole("tabpanel");
    expect(documentTab).toHaveAttribute("aria-controls", panel.id);
    expect(panel).toHaveAttribute("aria-labelledby", documentTab.id);
  });
});
