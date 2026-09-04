## MODIFIED Requirements

### Requirement: Verbatim clause extraction
The system SHALL split a Contract's raw text into an ordered sequence of clauses, each reproduced
character-for-character from the source text, except that runs of whitespace (spaces, tabs, newlines)
SHALL be collapsed to a single space, with leading/trailing whitespace stripped, before a clause's text
is compared against the source — so that formatting artifacts introduced by copying a line-wrapped or
table-extracted document into raw_text (a table cell's line breaks, hard-wrapped paragraphs) do not, on
their own, cause a genuinely-present clause to fail verbatim matching. Any other divergence — a
substituted, omitted, or added word or character — SHALL still fail verbatim matching exactly as before.

#### Scenario: Clause text matches source exactly
- **WHEN** segmentation completes for a Contract
- **THEN** every resulting clause's text is found verbatim within the Contract's raw_text, comparing
  with internal whitespace runs collapsed to a single space

#### Scenario: Whitespace-only divergence does not block a match
- **WHEN** a proposed clause's text differs from its span in the Contract's raw_text only in whitespace
  — for example the source has a line break where the proposed clause has a single space, as happens
  when a payment-milestone table's cells are copied onto separate lines
- **THEN** the clause is still treated as verbatim and segmentation persists it, rather than escalating
  the Contract to needs_human_review
