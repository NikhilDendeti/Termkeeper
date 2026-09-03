## Purpose

Renders a contract's clauses as an expandable, ordered reasoning chain — clause text through classification, extraction, platform evidence, and risk verdict — so a reviewer can inspect why the system produced a flag without querying the database directly.

## ADDED Requirements

### Requirement: Clauses listed in sequence order
The system SHALL render a contract's clauses as a list ordered by `sequence_index`, one entry per clause, with no clause omitted regardless of its `clause_type` or review state.

#### Scenario: All clauses rendered in order
- **WHEN** a reviewer opens the report page for a contract that has N clauses
- **THEN** all N clauses are listed on the page in ascending `sequence_index` order

### Requirement: Full reasoning chain shown per clause
Each clause entry SHALL, when expanded, present its reasoning chain in this order: clause text, classification (clause type and confidence), extracted term(s) if any (including the verbatim source span), platform evidence if any, and the final risk verdict if one exists. A stage that produced nothing for this clause SHALL render an explicit empty state naming that stage rather than being omitted from the layout.

#### Scenario: Fully processed clause shows every stage
- **WHEN** a reviewer expands a clause that has completed classification, term extraction, platform cross-check, and risk scoring
- **THEN** the expanded view shows, in order, the clause text, its classification, its extracted term with the verbatim value span it was extracted from, its platform evidence, and its risk verdict

#### Scenario: Clause with no platform evidence
- **WHEN** a reviewer expands a `payment_schedule` clause whose engagement has no matching platform record or mismatch flag
- **THEN** the expanded view displays an explicit "no platform evidence available" message in the platform-evidence position, rather than leaving that section blank or absent

#### Scenario: Clause not yet risk-scored
- **WHEN** a reviewer expands a clause that has an extracted term but no risk verdict has been produced for it yet
- **THEN** the expanded view displays an explicit "not yet assessed" message in the risk-verdict position, rather than leaving that section blank or absent

### Requirement: needs_human_review renders distinctly from every scored severity
The system SHALL render any clause, extracted term, or risk-verdict position flagged `needs_human_review` (or for which scoring was withheld pending review) using a visual treatment that is never applied to any scored severity level, at whichever stage the flag was raised, so a viewer cannot mistake an unreviewed item for one that was reviewed and found low-risk.

#### Scenario: needs_human_review clause never shown as a severity
- **WHEN** a clause, its extracted term, or its risk verdict has `needs_human_review = true`
- **THEN** the page renders that item with a treatment distinct from every severity-level treatment used elsewhere on the page, and that treatment is never reused to represent a low-severity or no-risk verdict

#### Scenario: Distinct treatment holds independent of later stages
- **WHEN** `needs_human_review` was raised at the classification stage for a clause that nonetheless proceeded to extraction and risk scoring
- **THEN** the classification stage's rendering still carries its own needs-human-review treatment regardless of what severity the risk verdict later received

### Requirement: needs-human-review state conveyed by text label, not color alone
The system SHALL always render an explicit text label identifying a `needs_human_review` item as such, independent of any color or styling used, so the state is verifiable from the page's text content alone.

#### Scenario: Label text present regardless of styling
- **WHEN** any item on the page is in a `needs_human_review` state
- **THEN** the rendered page's text content includes an explicit label identifying that item as needing human review
