import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { GuardrailScanResult } from "../api/types";
import GuardrailPage from "./GuardrailPage";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    getGuardrailStatus: vi.fn(),
  };
});

import { getGuardrailStatus } from "../api/client";

const mockedGetGuardrailStatus = vi.mocked(getGuardrailStatus);

describe("GuardrailPage", () => {
  beforeEach(() => {
    mockedGetGuardrailStatus.mockReset();
  });

  it("shows loading, then an unambiguous PASS for a passing scan", async () => {
    const result: GuardrailScanResult = {
      passed: true,
      scanned_files: ["razorpay_integration/client.py", "razorpay_integration/services.py"],
      violations: [],
    };
    mockedGetGuardrailStatus.mockResolvedValueOnce(result);

    render(<GuardrailPage />);

    expect(screen.getByTestId("loading-state")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByTestId("guardrail-result")).toBeInTheDocument());

    expect(screen.getByTestId("guardrail-result")).toHaveTextContent(/PASS/);
    expect(screen.getByTestId("guardrail-result")).toHaveClass(
      "guardrail-result-banner--pass",
    );
    expect(screen.getByTestId("scanned-files").children).toHaveLength(2);
    expect(screen.queryByTestId("violation-list")).not.toBeInTheDocument();
  });

  it("shows an unambiguous FAIL with violation evidence for a failing scan", async () => {
    const result: GuardrailScanResult = {
      passed: false,
      scanned_files: ["razorpay_integration/client.py"],
      violations: [
        { file: "razorpay_integration/client.py", line: 42, matched_call: "sdk_client.post" },
      ],
    };
    mockedGetGuardrailStatus.mockResolvedValueOnce(result);

    render(<GuardrailPage />);

    await waitFor(() => expect(screen.getByTestId("guardrail-result")).toBeInTheDocument());

    expect(screen.getByTestId("guardrail-result")).toHaveTextContent(/FAIL/);
    expect(screen.getByTestId("guardrail-result")).toHaveClass(
      "guardrail-result-banner--fail",
    );
    expect(screen.getByTestId("violation-list")).toHaveTextContent("sdk_client.post");
    expect(screen.getByTestId("violation-list")).toHaveTextContent(
      "razorpay_integration/client.py:42",
    );
  });

  it("shows an error state when the guardrail request fails", async () => {
    mockedGetGuardrailStatus.mockRejectedValueOnce(new Error("boom"));

    render(<GuardrailPage />);

    await waitFor(() => expect(screen.getByTestId("error-state")).toBeInTheDocument());
  });
});
