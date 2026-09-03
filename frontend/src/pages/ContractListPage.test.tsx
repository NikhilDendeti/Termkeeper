import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import type { ContractSummary } from "../api/types";
import ContractListPage from "./ContractListPage";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    getContracts: vi.fn(),
  };
});

import { getContracts } from "../api/client";

const mockedGetContracts = vi.mocked(getContracts);

function renderPage() {
  return render(
    <MemoryRouter>
      <ContractListPage />
    </MemoryRouter>,
  );
}

describe("ContractListPage", () => {
  beforeEach(() => {
    mockedGetContracts.mockReset();
  });

  it("shows a loading state, then the contract list once data arrives", async () => {
    const summaries: ContractSummary[] = [
      {
        contract_id: "c1",
        engagement_id: "ENG-1",
        razorpay_reference_type: "payout",
        overall_risk_score: 0.9,
        needs_human_review_count: 1,
        created_at: "2026-01-01T00:00:00Z",
      },
    ];
    mockedGetContracts.mockResolvedValueOnce(summaries);

    renderPage();

    expect(screen.getByTestId("loading-state")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByTestId("contract-list")).toBeInTheDocument());

    expect(screen.getByText("ENG-1")).toBeInTheDocument();
    expect(screen.queryByTestId("loading-state")).not.toBeInTheDocument();
  });

  it("shows an explicit empty state when there are no contracts", async () => {
    mockedGetContracts.mockResolvedValueOnce([]);

    renderPage();

    await waitFor(() => expect(screen.getByTestId("empty-state")).toBeInTheDocument());
    expect(screen.getByText(/no contracts yet/i)).toBeInTheDocument();
  });

  it("shows a loading state, then an error state when the request fails", async () => {
    mockedGetContracts.mockRejectedValueOnce(new ApiError("Network error", 0));

    renderPage();

    expect(screen.getByTestId("loading-state")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByTestId("error-state")).toBeInTheDocument());
    expect(screen.getByText("Network error")).toBeInTheDocument();
  });
});
