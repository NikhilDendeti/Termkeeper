import type { ChangeEvent, FormEvent } from "react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, analyzeContract, createContract } from "../api/client";
import type { RazorpayReferenceType } from "../api/types";
import ErrorState from "../components/ErrorState";
import Icon from "../components/Icon";
import LoadingState from "../components/LoadingState";

type Phase =
  | { status: "form" }
  | { status: "creating" }
  | { status: "analyzing" }
  | { status: "error"; message: string; contractId: string | null };

function defaultEngagementId(): string {
  return `upload-${Date.now()}`;
}

function defaultRazorpayReferenceId(): string {
  return `manual-upload-${Date.now()}`;
}

/**
 * Lets a person submit their own contract text - pasted, or a local .txt
 * file read client-side - and watch the real, unmodified pipeline analyze
 * it, no backend CLI access required. See
 * specs/frontend/upload-page/spec.md (all five requirements) and
 * design.md - Decisions, "Frontend: new /upload page".
 */
export default function UploadPage() {
  const navigate = useNavigate();

  const [contractText, setContractText] = useState("");
  const [sourceFilename, setSourceFilename] = useState<string | null>(null);
  const [engagementId, setEngagementId] = useState(defaultEngagementId);
  const [razorpayReferenceType, setRazorpayReferenceType] =
    useState<RazorpayReferenceType>("payout");
  const [razorpayReferenceId, setRazorpayReferenceId] = useState(defaultRazorpayReferenceId);
  const [phase, setPhase] = useState<Phase>({ status: "form" });

  const busy = phase.status === "creating" || phase.status === "analyzing";

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = ""; // lets the same file be re-selected later
    if (!file) return;

    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") {
        setContractText(reader.result);
        setSourceFilename(file.name);
      }
    };
    reader.readAsText(file);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!contractText.trim() || !engagementId.trim() || !razorpayReferenceId.trim()) return;

    setPhase({ status: "creating" });
    let contractId: string;
    try {
      const created = await createContract({
        raw_text: contractText,
        engagement_id: engagementId,
        razorpay_reference_type: razorpayReferenceType,
        razorpay_reference_id: razorpayReferenceId,
        source_filename: sourceFilename,
      });
      contractId = created.contract_id;
    } catch (error: unknown) {
      const message =
        error instanceof ApiError
          ? error.message
          : "An unexpected error occurred while creating the contract.";
      setPhase({ status: "error", message, contractId: null });
      return;
    }

    setPhase({ status: "analyzing" });
    try {
      await analyzeContract(contractId);
      navigate(`/contracts/${contractId}`);
    } catch (error: unknown) {
      const message =
        error instanceof ApiError ? error.message : "An unexpected error occurred during analysis.";
      setPhase({ status: "error", message, contractId });
    }
  }

  return (
    <>
      <div className="page-header">
        <div className="page-header-text">
          <h1 className="page-title">Upload a contract</h1>
          <p className="page-subtitle">
            Submit your own contract text and watch the real pipeline analyze it - no backend
            access required.
          </p>
        </div>
      </div>

      <form className="card upload-form" onSubmit={handleSubmit} aria-busy={busy}>
        <div className="form-field">
          <label htmlFor="upload-contract-text" className="form-label">
            Contract text
          </label>
          <textarea
            id="upload-contract-text"
            className="form-textarea"
            rows={12}
            placeholder="Paste the full contract text here..."
            value={contractText}
            onChange={(event) => setContractText(event.target.value)}
            disabled={busy}
            required
          />
          <div className="form-file-row">
            <label htmlFor="upload-contract-file" className="form-file-label">
              <Icon name="file-text" size={14} />
              Or choose a .txt file
              <input
                id="upload-contract-file"
                type="file"
                accept=".txt"
                onChange={handleFileChange}
                disabled={busy}
              />
            </label>
            {sourceFilename && <span className="form-file-name">{sourceFilename}</span>}
          </div>
        </div>

        <div className="form-row">
          <div className="form-field">
            <label htmlFor="upload-engagement-id" className="form-label">
              Engagement id
            </label>
            <input
              id="upload-engagement-id"
              type="text"
              className="form-input"
              value={engagementId}
              onChange={(event) => setEngagementId(event.target.value)}
              disabled={busy}
              required
            />
          </div>

          <div className="form-field">
            <label htmlFor="upload-razorpay-type" className="form-label">
              Razorpay reference type
            </label>
            <select
              id="upload-razorpay-type"
              className="form-select"
              value={razorpayReferenceType}
              onChange={(event) =>
                setRazorpayReferenceType(event.target.value as RazorpayReferenceType)
              }
              disabled={busy}
            >
              <option value="payout">Payout</option>
              <option value="subscription">Subscription</option>
            </select>
          </div>

          <div className="form-field">
            <label htmlFor="upload-razorpay-id" className="form-label">
              Razorpay reference id
            </label>
            <input
              id="upload-razorpay-id"
              type="text"
              className="form-input"
              value={razorpayReferenceId}
              onChange={(event) => setRazorpayReferenceId(event.target.value)}
              disabled={busy}
              required
            />
          </div>
        </div>

        <div className="upload-cost-notice" data-testid="upload-cost-notice">
          <Icon name="info" size={16} className="upload-cost-notice-icon" />
          <p>
            Analysis runs the real, unmodified pipeline against a live AI provider - one or more
            model calls per clause - so this is not instantaneous. Expect anywhere from under a
            minute to several minutes depending on how many clauses your contract has, and it will
            consume real API quota.
          </p>
        </div>

        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? "Submitting..." : "Submit for analysis"}
        </button>

        {phase.status === "creating" && <LoadingState label="Creating your contract record..." />}

        {phase.status === "analyzing" && (
          <LoadingState label="Analyzing your contract... this can take a few minutes, since it makes real model calls per clause." />
        )}

        {phase.status === "error" && (
          <ErrorState
            message={phase.message}
            linkTo={phase.contractId ? `/contracts/${phase.contractId}` : undefined}
            linkLabel="View partial result"
          />
        )}
      </form>
    </>
  );
}
