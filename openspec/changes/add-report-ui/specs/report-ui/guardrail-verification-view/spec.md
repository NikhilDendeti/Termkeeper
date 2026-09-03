## Purpose

Gives a reviewer a page that proves, through a live static scan rather than an assertion, that the Razorpay integration layer's production code path issues no write calls against live data.

## ADDED Requirements

### Requirement: Production-path source is scanned for write calls
The system SHALL statically scan every production-path source file in the Razorpay integration layer for HTTP write operations (POST, PUT, PATCH, DELETE, or an equivalent SDK write call), excluding any file designated as test-mode fixture or demo-seeding code.

#### Scenario: Scan covers production files and excludes fixtures
- **WHEN** the guardrail verification page (or its underlying command) is invoked
- **THEN** the scan includes every production-path source file in the Razorpay integration layer and excludes the module designated as test-mode fixture/demo-seeding code

### Requirement: Scanned file list is disclosed
The system SHALL display the exact list of files that were included in the scan, so a reviewer can independently confirm coverage rather than trust a summary claim.

#### Scenario: File list visible to the reviewer
- **WHEN** a reviewer opens the guardrail verification page
- **THEN** the page lists every file path that was included in that scan

### Requirement: Pass/fail result is explicit and evidence-backed
The system SHALL render an explicit pass or fail result. A pass SHALL be shown only when zero write-call matches were found across all scanned files. A fail SHALL list every violation found, identified by file, line number, and matched call.

#### Scenario: Clean scan renders a pass
- **WHEN** a scan of the current source finds zero write-call matches in any scanned file
- **THEN** the page renders an explicit pass result

#### Scenario: A violation renders a fail with evidence
- **WHEN** a scan finds at least one write-call match in a scanned file
- **THEN** the page renders an explicit fail result and lists the file, line number, and matched call for every violation found

### Requirement: Result reflects the current state of the source, not a cached claim
The system SHALL run the scan against the current state of the source files on each invocation of the page or its underlying command, rather than displaying a stored or cached prior result.

#### Scenario: A fixed violation no longer appears on the next scan
- **WHEN** a previously flagged write call is removed from a scanned file and the guardrail verification page is requested again
- **THEN** the new scan result no longer lists that violation
