import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    createContract: vi.fn(),
    analyzeContract: vi.fn(),
  };
});

import { ApiError, analyzeContract, createContract } from "../api/client";
import type { ContractReport } from "../api/types";
import UploadPage from "./UploadPage";

const mockedCreateContract = vi.mocked(createContract);
const mockedAnalyzeContract = vi.mocked(analyzeContract);

function ContractDetailStub() {
  const { id } = useParams<{ id: string }>();
  return <p>Contract detail page for {id}</p>;
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/upload"]}>
      <Routes>
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/contracts/:id" element={<ContractDetailStub />} />
      </Routes>
    </MemoryRouter>,
  );
}

const sampleReport: ContractReport = {
  contract_id: "c1",
  overall_risk_score: 0.3,
  flagged_clauses: [],
  platform_mismatches: [],
  needs_human_review_clauses: [],
  severity_breakdown_by_clause_type: {},
};

describe("UploadPage", () => {
  beforeEach(() => {
    mockedCreateContract.mockReset();
    mockedAnalyzeContract.mockReset();
  });

  it("pre-fills the engagement id and Razorpay reference fields with sensible, editable defaults", () => {
    renderPage();

    const engagementInput = screen.getByLabelText(/engagement id/i) as HTMLInputElement;
    const razorpayTypeSelect = screen.getByLabelText(/razorpay reference type/i) as HTMLSelectElement;
    const razorpayIdInput = screen.getByLabelText(/razorpay reference id/i) as HTMLInputElement;

    expect(engagementInput.value).toMatch(/^upload-\d+$/);
    expect(razorpayTypeSelect.value).toBe("payout");
    expect(razorpayIdInput.value).toMatch(/^manual-upload-\d+$/);

    // All three are ordinary editable fields, not read-only.
    expect(engagementInput).not.toBeDisabled();
    expect(razorpayTypeSelect).not.toBeDisabled();
    expect(razorpayIdInput).not.toBeDisabled();
  });

  it("states up front that analysis calls a real AI provider per clause and is not instantaneous", () => {
    renderPage();

    const notice = screen.getByTestId("upload-cost-notice");
    expect(notice).toHaveTextContent(/model calls? per clause/i);
    expect(notice).toHaveTextContent(/minute/i);
  });

  it("does not submit when the contract text is empty", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: /submit for analysis/i }));

    expect(mockedCreateContract).not.toHaveBeenCalled();
  });

  it("shows a visible message and does not submit when the contract text is whitespace-only", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText(/contract text/i), "   ");
    await user.click(screen.getByRole("button", { name: /submit for analysis/i }));

    expect(mockedCreateContract).not.toHaveBeenCalled();
    expect(screen.getByTestId("error-state")).toHaveTextContent(/contract text cannot be blank/i);
  });

  it("shows the field-labeled version of a raw backend validation error", async () => {
    const user = userEvent.setup();
    mockedCreateContract.mockRejectedValueOnce(
      new ApiError("raw_text: This field may not be blank.", 400),
    );

    renderPage();
    await user.type(screen.getByLabelText(/contract text/i), "1. PAYMENT. Pays monthly.");
    await user.click(screen.getByRole("button", { name: /submit for analysis/i }));

    await waitFor(() => expect(screen.getByTestId("error-state")).toBeInTheDocument());
    expect(screen.getByText(/^contract text: this field may not be blank\.$/i)).toBeInTheDocument();
  });

  it("shows a phase-specific button label while creating and while analyzing", async () => {
    const user = userEvent.setup();
    mockedCreateContract.mockResolvedValueOnce({ contract_id: "c1" });
    let resolveAnalyze!: (report: ContractReport) => void;
    mockedAnalyzeContract.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveAnalyze = resolve;
      }),
    );

    renderPage();
    await user.type(screen.getByLabelText(/contract text/i), "1. PAYMENT. Pays monthly.");
    await user.click(screen.getByRole("button", { name: /submit for analysis/i }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Analyzing..." })).toBeInTheDocument());

    resolveAnalyze(sampleReport);
    await waitFor(() => expect(screen.getByText("Contract detail page for c1")).toBeInTheDocument());
  });

  it("shows a specific, explanatory loading state while analysis is in progress", async () => {
    const user = userEvent.setup();
    mockedCreateContract.mockResolvedValueOnce({ contract_id: "c1" });
    let resolveAnalyze!: (report: ContractReport) => void;
    mockedAnalyzeContract.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveAnalyze = resolve;
      }),
    );

    renderPage();
    await user.type(screen.getByLabelText(/contract text/i), "1. PAYMENT. Pays monthly.");
    await user.click(screen.getByRole("button", { name: /submit for analysis/i }));

    await waitFor(() => expect(screen.getByTestId("loading-state")).toBeInTheDocument());
    expect(screen.getByText(/analyzing your contract/i)).toBeInTheDocument();
    expect(screen.getByText(/can take a few minutes/i)).toBeInTheDocument();

    resolveAnalyze(sampleReport);
    await waitFor(() => expect(screen.getByText("Contract detail page for c1")).toBeInTheDocument());
  });

  it("routes to the contract's detail page automatically when analysis completes successfully", async () => {
    const user = userEvent.setup();
    mockedCreateContract.mockResolvedValueOnce({ contract_id: "c1" });
    mockedAnalyzeContract.mockResolvedValueOnce(sampleReport);

    renderPage();
    await user.type(screen.getByLabelText(/contract text/i), "1. PAYMENT. Pays monthly.");
    await user.click(screen.getByRole("button", { name: /submit for analysis/i }));

    await waitFor(() => expect(screen.getByText("Contract detail page for c1")).toBeInTheDocument());

    expect(mockedCreateContract).toHaveBeenCalledWith(
      expect.objectContaining({ raw_text: "1. PAYMENT. Pays monthly." }),
    );
    expect(mockedAnalyzeContract).toHaveBeenCalledWith("c1");
  });

  it("shows the error plainly and links to the partial result when analysis fails partway through", async () => {
    const user = userEvent.setup();
    mockedCreateContract.mockResolvedValueOnce({ contract_id: "c1" });
    mockedAnalyzeContract.mockRejectedValueOnce(
      new ApiError(
        "Pipeline stopped partway through. Whatever was already analyzed has been saved. (rate limit exceeded)",
        502,
      ),
    );

    renderPage();
    await user.type(screen.getByLabelText(/contract text/i), "1. PAYMENT. Pays monthly.");
    await user.click(screen.getByRole("button", { name: /submit for analysis/i }));

    await waitFor(() => expect(screen.getByTestId("error-state")).toBeInTheDocument());
    expect(screen.getByText(/pipeline stopped partway through/i)).toBeInTheDocument();

    const link = screen.getByRole("link", { name: /view partial result/i });
    expect(link).toHaveAttribute("href", "/contracts/c1");
  });

  it("shows the error without a partial-result link when contract creation itself fails", async () => {
    const user = userEvent.setup();
    mockedCreateContract.mockRejectedValueOnce(
      new ApiError("raw_text: This field may not be blank.", 400),
    );

    renderPage();
    await user.type(screen.getByLabelText(/contract text/i), "1. PAYMENT. Pays monthly.");
    await user.click(screen.getByRole("button", { name: /submit for analysis/i }));

    await waitFor(() => expect(screen.getByTestId("error-state")).toBeInTheDocument());
    expect(screen.getByText(/this field may not be blank/i)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /view partial result/i })).not.toBeInTheDocument();
    expect(mockedAnalyzeContract).not.toHaveBeenCalled();
  });

  it("reads a selected .txt file client-side into the contract text field", async () => {
    const user = userEvent.setup();
    renderPage();

    const file = new File(["1. PAYMENT. From a file."], "contract.txt", { type: "text/plain" });
    const fileInput = screen.getByLabelText(/choose a \.txt file/i);

    await user.upload(fileInput, file);

    await waitFor(() =>
      expect((screen.getByLabelText(/contract text/i) as HTMLTextAreaElement).value).toBe(
        "1. PAYMENT. From a file.",
      ),
    );
    expect(screen.getByText("contract.txt")).toBeInTheDocument();
  });

  it("marks the loaded filename as edited once the textarea is changed by hand", async () => {
    const user = userEvent.setup();
    renderPage();

    const file = new File(["1. PAYMENT. From a file."], "contract.txt", { type: "text/plain" });
    await user.upload(screen.getByLabelText(/choose a \.txt file/i), file);
    await waitFor(() => expect(screen.getByText("contract.txt")).toBeInTheDocument());

    await user.type(screen.getByLabelText(/contract text/i), " Extra.");

    expect(screen.getByText("contract.txt (edited)")).toBeInTheDocument();
  });

  it("warns when a selected .txt-named file reports a non-text MIME type", async () => {
    const user = userEvent.setup();
    renderPage();

    // Same extension the accept filter requires, but a binary-looking
    // declared type - e.g. a renamed or misidentified file.
    const file = new File(["%PDF-1.4 binary..."], "contract.txt", {
      type: "application/octet-stream",
    });
    await user.upload(screen.getByLabelText(/choose a \.txt file/i), file);

    await waitFor(() =>
      expect(screen.getByText(/doesn't look like a plain-text file/i)).toBeInTheDocument(),
    );
  });

  it("surfaces a message instead of failing silently when the file can't be read", async () => {
    const originalFileReader = globalThis.FileReader;
    class ErroringFileReader {
      onerror: (() => void) | null = null;
      onload: (() => void) | null = null;
      result: string | ArrayBuffer | null = null;
      readAsText() {
        setTimeout(() => this.onerror?.(), 0);
      }
    }
    // @ts-expect-error - deliberately minimal stub for this one test
    globalThis.FileReader = ErroringFileReader;

    try {
      const user = userEvent.setup();
      renderPage();

      const file = new File(["1. PAYMENT."], "contract.txt", { type: "text/plain" });
      await user.upload(screen.getByLabelText(/choose a \.txt file/i), file);

      await waitFor(() => expect(screen.getByText(/could not read/i)).toBeInTheDocument());
    } finally {
      globalThis.FileReader = originalFileReader;
    }
  });
});
