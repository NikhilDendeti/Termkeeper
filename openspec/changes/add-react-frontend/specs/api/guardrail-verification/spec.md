## Purpose

Exposes the live Razorpay-integration write-call guardrail scan as JSON, so a browser-based frontend can display proof — not just an assertion — that the production cross-check path never issues a write call against live data.

## ADDED Requirements

### Requirement: Guardrail-verification endpoint
The system SHALL expose a read-only endpoint that runs the guardrail scan live on every request and returns the pass/fail result together with the scanned file list and any violation evidence (file, line, matched call).

#### Scenario: Passing scan
- **WHEN** a caller requests the guardrail-verification endpoint and the current source contains no write-verb calls on the scanned production-path files
- **THEN** the response reports passed=true, the full list of scanned files, and an empty violation list

#### Scenario: Result reflects current source, not a cached claim
- **WHEN** the guardrail-verification endpoint is requested twice in a row with no change to the scanned source in between
- **THEN** both responses report identical results, each independently computed by scanning the files fresh (not served from a stored value)
