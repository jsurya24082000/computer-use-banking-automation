# Execution evidence — synthetic data only

Evidence status is explicit; no provider response, human interaction, test result or successful run is fabricated.

| Deliverable | Status |
|---|---|
| Hand-authored executor artifact | Included as `executor-test-capability.json`; not a discovery deliverable |
| Real Chromium execution with simulated provider | Included under `offline/`; provenance says `simulated_discovery` |
| Replay with different member and no model | Included; uses the artifact compiled from simulated decisions |
| Business outcome | Included: missing member |
| Recoverable error | Included: temporary account failure, bounded safe retry |
| Intervention request | Included: session expiry; no operator available |
| Genuine LLM discovery and resulting artifacts | Balance: `live-discovery/77525c9151e2/`; typed transactions: `live-discovery/fb5619a7967f/`; both provenance records say `llm_discovery` |
| Replay of genuinely discovered artifacts | Historical balance: `live-replay/19744e6936e7/`; typed transactions: `live-replay/3e2895258655/` |
| Actual-person takeover and resume | Balance: `live-handoff/35587b0655e5/`; typed transactions: `live-handoff-transactions/592ded6b14be/` |
| Primary repeatability benchmark | `repeatability-matrix-1419e92-both-workflows.json`; 324 combinations, 36 verified extractions, zero mismatches |
| Historical ten-run records | `repeatability-final.json` and `repeatability-final/`; their run-ID sets are disjoint and must not be joined as one sample |

`manifest.json` reconciles the current submission benchmark with the preserved historical records. `test-verification-f545648.json` records the latest 158-test run; `test-summary.json` remains the earlier 138-test XML-derived record. `clean-checkout-verification-f545648.json` records installation and approved-artifact replay checks from an isolated checkout. Actual-person handoff evidence is separate from simulated-operator tests.

An earlier failed app-connectivity attempt is retained in `offline/e32067593416/`. It is not counted as a successful demonstration. No successful result was substituted for that failed attempt.

Run diagnostics omit invocation values and declared financial outputs. Failure evidence is a sanitized structured snapshot rather than raw HTML, traces or unmasked screenshots. Test XML and captured output are temporary and are not included. The expected balances in the README are explicitly published synthetic sample values, separate from diagnostics.

To collect new evidence, always choose fresh output paths; do not rerun evidence tools over the historical paths in this directory. For a new ten-replay sample, start the bank in the normal scenario and run `python tools/repeatability.py --runs 10 --out evidence/repeatability-new.json`; it resets the synthetic database, blocks provider imports, and preserves failures in its new summary. To create a new verification count record, run the tests and save a new named record rather than replacing `test-summary.json`. Provider token/cost/latency metrics are not recorded, and no screenshots or raw browser traces are retained. New replay runs include a canonical capability SHA-256 in `replay_started`; historical logs retain their original format.

## Current typed transaction validation

- Genuine discovery: `live-discovery/fb5619a7967f/`, using OpenAI-compatible/gpt-4o
  on revision `b99c91a`. The draft artifact is preserved there.
- Qualification: `discovery-attempts/transactions/attempt-4-capability.json.approval.json`
  approves all four declared transaction cases, records `b99c91a`, and binds the
  approved transaction artifact. No approval hash was edited manually.
- Different-member replay without a model key: `live-replay/3e2895258655/`.
- Real transaction takeover/resume: `live-handoff-transactions/592ded6b14be/`.
  The operator claimed the run in a visible terminal, signed in in the same
  browser, and requested resume. Events record the ownership transitions,
  `resume_verified`, and `SUCCESS`; the intervention names the transaction workflow.
- Corrected matrix: `repeatability-matrix-1419e92-both-workflows.json` records
  clean revision `1419e92`, 324/324 distinct combinations, 36 verified
  extractions, 240 expected business outcomes, 24 expected permission denials,
  24 expected interventions, and zero unexpected mismatches. The matching
  `-runs/` directory retains sanitized per-run evidence and `iterations.jsonl`.
- Failed matrix: `repeatability-matrix-b99c91a-both-workflows.json` retains three
  mismatches. Its old harness deleted the temporary per-run logs; the exact
  original cause remains unproven. Regression tests reproduced cleanup and
  diagnostic-timeout defects that were subsequently fixed.
- Startup regression: `repeatability-matrix-a398d50-both-workflows-runs/iterations.jsonl`
  is empty because a Path/string validation error stopped execution before
  the first replay. The fix was committed as `1419e92`; this is not a completed run.

The latest local full suite passed 158 tests (450.97 seconds, Python 3.12.10),
and full Ruff passed; `test-verification-f545648.json` records the exact commit,
environment and command. `test-summary.json` is the preserved earlier 138-test
record. `manifest.json` now labels historical transaction-goal artifacts as
balance workflows and makes the 324-case report the primary benchmark.

## Historical owner-run validation

The historical owner-run evidence was collected from source revision `659d6f4`.
Stage 2 contains six genuine OpenAI discovery attempts: two successes and one
preserved failure for each of the balances and transactions goals. All four
successful attempts compiled `read_account_balances` capabilities — the
transaction-goal runs predated the typed `--workflow` discriminator, so the
artifacts preserved under `discovery-attempts/transactions/` are
balance-workflow capabilities, not transaction capabilities. The aggregate
records are `discovery-attempts-balances.json` and
`discovery-attempts-transactions.json`.

Stage 3 contains eight approved sidecars: the four successful capabilities were
qualified against both `config/tenant.json` and
`config/tenant-secondary.json`. The same capability hashes are reused across
tenants, while the tenant digests differ and bind each approval separately.
Both tenants bind the same local UI build, so the secondary binding proves
per-tenant approval scoping rather than a different UI variant. After the
workflow schema change, the sidecars were regenerated through real
qualification runs; they record `source_revision` `26dbf9d5`, which was the
base commit — the fixes themselves were uncommitted then and are now committed
as `b99c91a`. The artifact files themselves were
not modified.

Stage 4 contains four model-free reports, each with 100 recorded attempts and
zero reported mismatches. In total they contain 72 extractions, 256 expected
business outcomes, 48 expected interventions, and 24 expected permission
denials—not 400 successful extractions. All four reports exercised balance
workflows, including those labeled transactions. Each report lists two artifacts
but exercises only attempt 2, leaving attempt 3 uncovered. These historical
reports are not the primary benchmark. The historical ten-run summary and its
adjacent log directory also have zero overlapping run IDs.

Stage 6 preserves both actual-person handoff attempts. The failed run
`246101e0d773` ends with `INVALID_CREDENTIALS` before intervention. The
successful run `5c4f9a6d4fe9` records
`automation -> paused -> human -> automation`, sanitized human interaction
events, a rejected early resume, `resume_verified`, and final `SUCCESS`.
