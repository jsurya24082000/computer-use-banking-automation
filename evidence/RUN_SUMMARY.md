# Measured run summary

**Scope:** repository evidence already present at audit time. This document does not
claim any run, interaction, model call, or metric that is not recorded in the cited
files. The dataset is synthetic only.

## Genuine discovery

| Item | Status | Evidence | Audit note |
|---|---|---|---|
| Genuine LLM discovery | **Not recorded / not run** | `evidence/README.md`; `evidence/manifest.json`; `REPORT.md` | The repository explicitly records that model credentials were unavailable. No provider response, model transcript, credential, cookie, raw member identifier, or banking output value is included. |
| Genuine discovery artifact | **Not recorded / not run** | `evidence/manifest.json` | `evidence/offline/5156ceafab4e/capability.json` is labeled `simulated_discovery`; it is not genuine discovery evidence. |

## Deterministic replay

| Run | Status | Evidence | Measured result |
|---|---|---|---|
| Replay of the checked-in simulated capability with a different invocation | Success | `evidence/offline/03f645c07c91/events.jsonl`; `evidence/manifest.json` | The event log records `deterministic_replay`, ordered actions through `finish`, and `SUCCESS`. No output values are reproduced here. |
| Replay of a genuinely discovered artifact | **Not recorded / not run** | `evidence/README.md`; `evidence/manifest.json` | Depends on the unrecorded genuine discovery deliverable. |

The replay event log records timestamps for each event, but this audit does not claim
a comparative speedup: no paired baseline and replay duration measurement was
provided for a single comparable workflow.

## Runtime scenarios

| Scenario/evidence class | Status | Evidence | Recorded behavior |
|---|---|---|---|
| Simulated discovery in real Chromium | Success | `evidence/offline/5156ceafab4e/events.jsonl`; `evidence/offline/5156ceafab4e/capability.json` | `simulated_discovery`; artifact compiled; run finished `SUCCESS`. This is not genuine LLM evidence. |
| Business outcome | Recorded | `evidence/offline/63695471525e/events.jsonl`; `evidence/offline/63695471525e/failure-snapshot.json` | Run finished with `business_outcome` / `MEMBER_NOT_FOUND`; snapshot is sanitized and contains no raw member identifier or financial output. |
| Recoverable read failure | Success | `evidence/offline/225308a6b01c/events.jsonl` | One recorded `RETRY_VISIBLE_READ_LINK` recovery, followed by account-details verification and `SUCCESS`. |
| Intervention request without operator | Recorded | `evidence/offline/2659d4cad2b9/events.jsonl`; `evidence/offline/2659d4cad2b9/intervention.json`; `evidence/offline/2659d4cad2b9/failure-snapshot.json` | Ownership transitions to paused; run finishes `intervention_required` / `OPERATOR_UNAVAILABLE`. |
| Earlier app-connectivity attempt | Not a successful run | `evidence/offline/e32067593416/events.jsonl`; `evidence/README.md` | Retained as a failed attempt and excluded from successful demonstrations. |

## Human takeover and resume

| Item | Status | Evidence | Audit note |
|---|---|---|---|
| Real human takeover | **Not recorded / not run** | `evidence/README.md`; `evidence/manifest.json`; `evidence/test-summary.json` | The intervention evidence stops at operator unavailability. |
| Real human resume | **Not recorded / not run** | Same as above | No real operator, browser handback, or verified resume event is included. |
| Simulated operator test coverage | Recorded, not human evidence | `evidence/test-summary.json`; `REPORT.md` | The test summary explicitly says takeover tests use a simulated operator and do not establish a real-person demonstration. |

## Tests

| Check | Recorded result | Evidence | Notes |
|---|---:|---|---|
| Pytest suite | 72 tests, 0 failures, 0 errors, 0 skipped | `evidence/test-summary.json` | Recorded execution used Python 3.12.14 and Playwright Chromium. |
| Test duration | 81.573 seconds | `evidence/test-summary.json` | This is the only aggregate timing recorded in the repository. It is not used as a discovery/replay speed comparison. |
| Genuine-provider test | **Not recorded / not run** | `evidence/test-summary.json`; `evidence/README.md` | Discovery tests use a fake provider. |

## Evidence handling and unavailable metrics

- Evidence references above are repository-relative and point to the checked-in
  artifacts inspected for this summary.
- This summary intentionally omits credentials, API keys, cookies, session tokens,
  raw member IDs, banking output values, raw DOM, screenshots, and provider payloads.
- No cost, token usage, model latency, genuine-discovery duration, human-action
  duration, or comparable single-run speedup is recorded in the cited evidence.
- No discovery, model call, publish, push, or external upload was performed for this
  audit.
