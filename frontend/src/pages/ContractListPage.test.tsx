import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

  const mixedSummaries: ContractSummary[] = [
    {
      contract_id: "c1",
      engagement_id: "ENG-CRITICAL",
      razorpay_reference_type: "payout",
      overall_risk_score: 0.95,
      needs_human_review_count: 2,
      created_at: "2026-01-02T00:00:00Z",
    },
    {
      contract_id: "c2",
      engagement_id: "ENG-UNSCORED",
      razorpay_reference_type: "subscription",
      overall_risk_score: null,
      needs_human_review_count: 0,
      created_at: "2026-01-01T00:00:00Z",
    },
  ];

  it("renders the stat row's label/value pairs as a definition list", async () => {
    mockedGetContracts.mockResolvedValueOnce(mixedSummaries);

    renderPage();

    await waitFor(() => expect(screen.getByTestId("contract-list")).toBeInTheDocument());

    const totalTile = screen.getByText("Total contracts").closest("dl") as HTMLElement;
    expect(totalTile.tagName).toBe("DL");
    expect(totalTile.querySelector("dt")).toHaveTextContent("Total contracts");
    expect(totalTile.querySelector("dd")).toHaveTextContent("2");
    expect(within(screen.getByTestId("contract-list")).getByText("Not yet scored")).toBeInTheDocument();
  });

  it("filters the list by search text", async () => {
    mockedGetContracts.mockResolvedValueOnce(mixedSummaries);
    const user = userEvent.setup();

    renderPage();
    await waitFor(() => expect(screen.getByTestId("contract-list")).toBeInTheDocument());

    await user.type(screen.getByLabelText(/search contracts/i), "unscored");

    expect(screen.queryByText("ENG-CRITICAL")).not.toBeInTheDocument();
    expect(screen.getByText("ENG-UNSCORED")).toBeInTheDocument();
  });

  it("filters the list by status band and offers a way to clear filters when nothing matches", async () => {
    mockedGetContracts.mockResolvedValueOnce(mixedSummaries);
    const user = userEvent.setup();

    renderPage();
    await waitFor(() => expect(screen.getByTestId("contract-list")).toBeInTheDocument());

    await user.selectOptions(screen.getByLabelText(/filter by status/i), "unscored");
    expect(screen.queryByText("ENG-CRITICAL")).not.toBeInTheDocument();
    expect(screen.getByText("ENG-UNSCORED")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText(/filter by status/i), "medium");
    expect(screen.getByTestId("empty-filter-state")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /clear filters/i }));
    expect(screen.getByText("ENG-CRITICAL")).toBeInTheDocument();
    expect(screen.getByText("ENG-UNSCORED")).toBeInTheDocument();
  });
});
