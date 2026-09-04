## Purpose

Defines what a person can do and see when submitting their own contract through the frontend, independent of implementation — the externally observable behavior a browser user relies on.

## ADDED Requirements

### Requirement: A person can submit contract text without backend access
The frontend SHALL provide a page where a user can enter contract text (by pasting it or by choosing a local `.txt` file, read client-side) along with engagement metadata, and submit it for analysis.

#### Scenario: Submission with sensible defaults
- **WHEN** a user opens the upload page
- **THEN** the engagement id and Razorpay reference fields are pre-filled with sensible, clearly-labeled defaults that the user may edit, so submission does not require the user to already have real Razorpay data

### Requirement: The cost and duration of analysis is stated up front, not hidden
The frontend SHALL tell the user, before they submit, that analysis calls a real AI provider per clause and can take from under a minute to several minutes depending on contract length.

#### Scenario: Expectation set before submission
- **WHEN** a user views the upload form before submitting
- **THEN** a visible note states that analysis is not instantaneous and explains why (real model calls per clause)

### Requirement: A long-running analysis shows a visible, specific progress state
The frontend SHALL show a clear loading state for the duration of analysis, distinct from a generic spinner with no explanation.

#### Scenario: User waits during analysis
- **WHEN** a submitted contract is being analyzed
- **THEN** the page shows a state explaining that analysis is in progress and may take some time, not an indefinite unlabeled spinner

### Requirement: A partial failure is shown plainly, with a path forward
The frontend SHALL show an explicit error state when analysis fails partway through, and SHALL still offer a way to view whatever partial result exists rather than a dead end.

#### Scenario: Analysis fails partway through
- **WHEN** the analyze request returns a partial-failure error
- **THEN** the frontend shows the error plainly and provides a link to the contract's (partial) detail page, not just an error message with no next step

### Requirement: Successful analysis leads directly to the result
The frontend SHALL route the user to the contract's detail page automatically when analysis completes successfully.

#### Scenario: Successful submission end to end
- **WHEN** a user submits valid contract text and analysis completes without error
- **THEN** the user is taken to that contract's detail page, showing its real reasoning chain
