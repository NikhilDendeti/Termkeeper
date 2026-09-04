import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { EvalRun, LatestEvalRunResponse } from "../api/types";
import EvaluationPage from "./EvaluationPage";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    getLatestEvalRun: vi.fn(),
  };
});

import { getLatestEvalRun } from "../api/client";

const mockedGetLatestEvalRun = vi.mocked(getLatestEvalRun);

const SAMPLE_EVAL_RUN: EvalRun = {
  id: "11111111-1111-1111-1111-111111111111",
  run_at: "2026-01-01T00:00:00Z",
  dataset_version: "v1",
  fixture_version: "v1",
  precision_recall_f1: {
    risk_severity: {
      precision: 0.9,
      recall: 0.8,
      f1: 0.847,
      human_review_recall: 1.0,
      true_positives: 9,
      false_positives: 1,
      false_negatives: 2,
      scored_clause_count: 12,
      human_review_clause_count: 2,
    },
    mismatch_present: {
      precision: 1.0,
      recall: 0.75,
      true_positives: 3,
      false_positives: 0,
      false_negatives: 1,
    },
  },
  severity_calibration_score: 0.875,
  cost_report: {
    minutes_per_dismissed_flag: 5.0,
    fp_count: 1,
    fn_count: 1,
    fp_cost: 5.0,
    fn_cost: 3.0,
    fn_to_fp_cost_ratio: 0.6,
    by_clause_type: {
      termination: { fp_count: 1, fn_count: 0, fp_cost: 5.0, fn_cost: 0.0 },
    },
    by_mismatch_type: {
      cadence_mismatch: { fp_count: 0, fn_count: 1, fp_cost: 0.0, fn_cost: 3.0 },
    },
  },
  false_positive_cost_note: "5.0 reviewer-minutes assumed per dismissed flag.",
  pipeline_version: "abc1234",
  prompt_version: "clause-segmentation-v1,risk-scoring-v1",
};

describe("EvaluationPage", () => {
  beforeEach(() => {
    mockedGetLatestEvalRun.mockReset();
  });

  it("shows loading, then the metrics for the latest eval run", async () => {
    const response: LatestEvalRunResponse = { eval_run: SAMPLE_EVAL_RUN };
    mockedGetLatestEvalRun.mockResolvedValueOnce(response);

    render(<EvaluationPage />);

    expect(screen.getByTestId("loading-state")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByTestId("eval-run-meta")).toBeInTheDocument());

    expect(screen.getByTestId("eval-run-meta")).toHaveTextContent("v1");
    expect(screen.getByTestId("risk-severity-stats")).toHaveTextContent("90.0%");
    expect(screen.getByTestId("risk-severity-stats")).toHaveTextContent("80.0%");
    expect(screen.getByTestId("mismatch-stats")).toHaveTextContent("100.0%");
    expect(screen.getByTestId("cost-report-stats")).toHaveTextContent("5.0");
    expect(screen.getByTestId("cost-breakdown-clause-type")).toHaveTextContent("termination");
    expect(screen.getByTestId("cost-breakdown-mismatch-type")).toHaveTextContent(
      "cadence_mismatch",
    );
    expect(screen.queryByTestId("empty-state")).not.toBeInTheDocument();
  });

  it("color-codes quality metrics by how good the score is, not by the risk severity ramp", async () => {
    const response: LatestEvalRunResponse = { eval_run: SAMPLE_EVAL_RUN };
    mockedGetLatestEvalRun.mockResolvedValueOnce(response);

    render(<EvaluationPage />);
    await waitFor(() => expect(screen.getByTestId("risk-severity-stats")).toBeInTheDocument());

    // F1 of 0.847 is a good score (>=0.625) - should read as a "medium"-or-better
    // band, i.e. NOT the same red "critical" a 0.847 *risk* score would be.
    const stats = screen.getByTestId("risk-severity-stats");
    const values = stats.querySelectorAll(".stat-tile-value");
    const classNames = Array.from(values).map((el) => el.className);
    expect(classNames.some((c) => c.includes("stat-tile-value--critical"))).toBe(false);
  });

  it("shows an explicit empty state, not a spinner or error, when no eval run exists yet", async () => {
    const response: LatestEvalRunResponse = { eval_run: null };
    mockedGetLatestEvalRun.mockResolvedValueOnce(response);

    render(<EvaluationPage />);

    await waitFor(() => expect(screen.getByTestId("empty-state")).toBeInTheDocument());

    expect(screen.getByTestId("empty-state")).toHaveTextContent("No evaluation run yet");
    expect(screen.queryByTestId("loading-state")).not.toBeInTheDocument();
    expect(screen.queryByTestId("error-state")).not.toBeInTheDocument();
    expect(screen.queryByTestId("eval-run-meta")).not.toBeInTheDocument();
  });

  it("shows an error state when the request fails", async () => {
    mockedGetLatestEvalRun.mockRejectedValueOnce(new Error("boom"));

    render(<EvaluationPage />);

    await waitFor(() => expect(screen.getByTestId("error-state")).toBeInTheDocument());
    expect(screen.queryByTestId("empty-state")).not.toBeInTheDocument();
  });
});
