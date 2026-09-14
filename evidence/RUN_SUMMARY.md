# Measured run summary

**Scope:** repository evidence already present at audit time. This document does not
claim any run, interaction, model call, or metric that is not recorded in the cited
files. Banking data is synthetic only; the live discovery used a real configured
provider.

## Genuine discovery

| Item | Status | Evidence | Audit note |
|---|---|---|---|
| Genuine LLM discovery | Success | `evidence/live-discovery/77525c9151e2/events.jsonl` | `llm_discovery`, provider `openai-compatible/gpt-4o`, run `SUCCESS`; duration measured from recorded events: 23.217 seconds. |
| Genuine discovery artifact | Recorded and linked | `evidence/live-discovery/77525c9151e2/capability.json`; `artifacts/read-account-balances.json` | Both files have the same SHA-256 (`090515FF...1739CE3`); artifact provenance identifies run `77525c9151e2`. No credentials, cookies, raw member identifiers, or financial outputs are present. |

## Deterministic replay

| Run | Status | Evidence | Measured result |
|---|---|---|---|
| Replay of the checked-in simulated capability with a different invocation | Success | `evidence/offline/03f645c07c91/events.jsonl`; `evidence/manifest.json` | The event log records `deterministic_replay`, ordered actions through `finish`, and `SUCCESS`. No output values are reproduced here. |
| Replay of the genuinely discovered artifact with a different invocation | Success | `evidence/live-replay/19744e6936e7/events.jsonl`; `artifacts/read-account-balances.json` | `deterministic_replay`, `SUCCESS`, and recorded duration of 2.896 seconds. |

The live discovery and replay are comparable single-run executions of the same
capability workflow: 23.217 seconds versus 2.896 seconds, a measured difference of
20.321 seconds (about 8.0x elapsed-time ratio). This is not a causal benchmark and
does not include model token or cost data.

## Runtime scenarios

| Scenario/evidence class | Status | Evidence | Recorded behavior |
|---|---|---|---|
| Simulated discovery in real Chromium | Success | `evidence/offline/5156ceafab4e/events.jsonl`; `evidence/offline/5156ceafab4e/capability.json` | `simulated_discovery`; artifact compiled; run finished `SUCCESS`. This is not genuine LLM evidence. |
| Business outcome | Recorded | `evidence/offline/63695471525e/events.jsonl`; `evidence/offline/63695471525e/failure-snapshot.json` | Run finished with `business_outcome` / `MEMBER_NOT_FOUND`; snapshot is sanitized and contains no raw member identifier or financial output. |
| Recoverable read failure | Success | `evidence/offline/225308a6b01c/events.jsonl` | One recorded `RETRY_VISIBLE_READ_LINK` recovery, followed by account-details verification and `SUCCESS`. |
| Intervention request without operator | Recorded | `evidence/offline/2659d4cad2b9/events.jsonl`; `evidence/offline/2659d4cad2b9/intervention.json`; `evidence/offline/2659d4cad2b9/failure-snapshot.json` | Ownership transitions to paused; run finishes `intervention_required` / `OPERATOR_UNAVAILABLE`. |
| Live human takeover and resume | Success | `evidence/live-handoff/35587b0655e5/events.jsonl`; `evidence/live-handoff/35587b0655e5/intervention.json` | `automation → paused → human → automation`; 14 sanitized human interaction events; resume verification and final `SUCCESS`; recorded duration 51.489 seconds. |
| Earlier app-connectivity attempt | Not a successful run | `evidence/offline/e32067593416/events.jsonl`; `evidence/README.md` | Retained as a failed attempt and excluded from successful demonstrations. |

## Human takeover and resume

| Item | Status | Evidence | Audit note |
|---|---|---|---|
| Real human takeover | Recorded | `evidence/live-handoff/35587b0655e5/events.jsonl`; `evidence/live-handoff/35587b0655e5/intervention.json` | Ownership changes to human and sanitized click/input/change/submit/navigation categories are recorded. |
| Real human resume | Recorded | `evidence/live-handoff/35587b0655e5/events.jsonl` | `resume_verified` records the requested checkpoint, followed by automation ownership and successful completion. |
| Simulated operator test coverage | Recorded, not human evidence | `evidence/test-summary.json`; `REPORT.md` | The test summary explicitly says takeover tests use a simulated operator and do not establish a real-person demonstration. |

## Tests

| Check | Recorded result | Evidence | Notes |
|---|---:|---|---|
| Pytest suite | 83 tests, 0 failures, 0 errors, 0 skipped | `evidence/test-summary.json` | Latest `tools/verify.py` execution; Python 3.14.0 and Playwright Chromium. |
| Test duration | 230.272 seconds | `evidence/test-summary.json` | Latest documented verification output; not used as a discovery/replay speed comparison. |
| Genuine-provider test | Not part of suite | `evidence/test-summary.json`; `evidence/live-discovery/77525c9151e2/events.jsonl` | The test suite uses a fake provider; the separate live run records genuine provider discovery. |

## Evidence handling and unavailable metrics

- Evidence references above are repository-relative and point to the checked-in
  artifacts inspected for this summary.
- This summary intentionally omits credentials, API keys, cookies, session tokens,
  raw member IDs, banking output values, raw DOM, screenshots, and provider payloads.
- No token usage, cost, provider API latency, or model billing data is recorded.
- Event-derived elapsed durations are recorded for the three live runs; human action
  duration is not isolated from browser/runtime time.
- No new discovery or model call was performed for this documentation update.

## Repeatability sample

| Sample | Result | Evidence | Measured result |
|---|---|---|---|
| Ten alternating model-free replays of the genuine artifact | 10 success, 0 failure | `evidence/repeatability-final.json` | Slots A/B alternate the two documented normal members; outputs were verified in memory and aggregate evidence contains no output values or member IDs. Command elapsed time: min 3.875s, median 4.037s, max 5.144s. |

This is a local ten-run sample, not a production benchmark. No model access was
used, and no financial output values are persisted in the repeatability evidence.

## Traceability and CI

New replay runs emit `replay_started` with the SHA-256 of the validated capability's
canonical JSON (`model_dump(mode="json")`, recursively sorted keys, compact JSON
separators, UTF-8 encoded, SHA-256). The hash covers the full capability and no
invocation values, credentials, or financial outputs; historical event logs were
not rewritten. The CI workflow is `.github/workflows/verify.yml` and runs pinned
dependencies, Chromium, pytest, and Ruff on Ubuntu and Windows without model
credentials. No hosted CI result is claimed here because it was not run in this
audit.
