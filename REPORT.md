# Computer-Use Banking Automation — reviewer report

**Reviewer entry point:** start with `README.md`, then
`evidence/RUN_SUMMARY.md`, `evidence/manifest.json`, and the cited live/offline
event folders. Live records cover genuine-provider discovery, deterministic replay,
and same-browser handoff/resume; offline records are explicitly simulated or
hand-authored.

The latest local full suite passed 158 tests on Python 3.12.10 in 450.97 seconds,
and full Ruff passed; `evidence/test-verification-f545648.json` records the exact
commit, environment and command. The primary benchmark is
`evidence/repeatability-matrix-1419e92-both-workflows.json`: 324/324 distinct
balance/transaction combinations, 36 verified extractions, 240 expected business
outcomes, 24 expected interventions, 24 expected permission denials, and zero
unexpected mismatches. Non-extraction outcomes are reported separately and are
not described as successful extractions.

## 1. Architecture

The target is a separate FastAPI application with Jinja screens and SQLite; the automation is one Python process using asynchronous Playwright. There are no queues, agents-as-services, or orchestration frameworks. The app provides an intentionally modest legacy surface: an iframe, server-rendered forms, dense account tables, and repeated “View” links. Labels and table relationships remain usable to staff and automation alike.

The automation imports no banking business code. Its surface adapter observes visible headings, labeled controls, table rows and definition-list fields; it never queries the database, calls banking business endpoints, or reads scenario controls. Setup and tests are explicitly independent harnesses permitted to seed/configure and verify the app. The database stores integer cents, hashed passwords, server-side sessions, holds, transactions and audit events.

Discovery receives a natural-language goal and typed invocation. A configurable OpenAI-compatible adapter returns schema-validated actions referring to the current sanitized control catalog. The controller chooses no banking workflow steps itself. The same surface, action executor, policy and recovery logic are used in discovery and replay. A static, vendor-specific observation adapter is the trade-off: narrow and reviewable rather than falsely claiming arbitrary-web generality.

## 2. Artifact schema

A strict Pydantic capability specifies schema/capability versions, application compatibility, typed input/output contracts, preconditions, stable step IDs, explicit frame context, ordered locator strategies, row constraints, checks, final success conditions, business outcomes, recovery limits, policy requirements, and discovery provenance. Credentials, member values, URLs, session handles, raw transcripts and observed balances are absent.

Dynamic values are `input_ref` bindings. A search-result row binds its Member ID to `member_id`; an account row binds Product to `product_name` and Status to Active. Recording never infers parameterization by replacing arbitrary matching strings. The compiler resolves transient observation references into supported stable targets; missing or unsupported references stop for review. The final checkpoint and declared contract cannot be weakened through artifact fields. Tenant entry URL and iframe binding remain outside the reusable artifact.

## 3. Determinism & error handling

Replay is deterministic only for a fixed artifact, tenant, policy, browser surface, and application state; it is not a claim that model discovery or external systems are deterministic. Replay imports no provider. It validates inputs/artifact, resolves declared exact locators in order, requires one visible match, and verifies postconditions. A duplicate match stops immediately; it never falls through to an arbitrary first element. Table headers identify columns, row constraints select the intended record, and only then is the repeated View link resolved. The adapter waits for classified server-rendered navigation to finish, avoiding checks against an old iframe document.

Completion independently verifies member, product, active status, and the declared workflow outputs. Balances additionally require currency, monetary fields and a timezone-aware timestamp; available balance must equal current balance minus active holds, an explicit demo assumption. Transactions require the expected table headers, valid dates and decimal amounts, newest-first order, and at most five rows. The LLM saying “finish” is insufficient.

Missing members, invalid IDs and no eligible account are business outcomes. Permission denial is a hard failure, never a prompt to switch roles. A visible temporary error has one safe read-link retry by default; timeouts never trigger blind re-execution. Slow loads use bounded navigation waits. Discovery limits steps, repeated action/state pairs, total time and malformed responses. A run returns success, business_outcome, intervention_required, or failure, with stable error codes and sanitized state/evidence references. Tests independently exercise wrong-member, wrong-product, missing/malformed outputs and inconsistent balances.

## 4. Heterogeneity & multi-tenant

`SurfaceAdapter` separates observe/resolve/execute/verify/extract from control logic. A desktop implementation would supply accessibility-role/window-scoped targets and equivalent state checks; a screenshot adapter would need explicit confidence, coordinate validity and ambiguity rules. Neither is implemented. Only the browser adapter and this vendor UI are supported.

Capabilities identify vendor/product/version; a separate versioned tenant binding supplies origin and frame name. Visible branding/version checks run at startup, before actions and on resume. Incompatible versions stop. There is no live multi-tenant override system. A future approved override would be versioned, tied to artifact step IDs and product compatibility, schema-validated, reviewed and regression-tested. It could specialize targets only; the independent policy service/object would still intersect permissions and retain the immutable prohibition on banking writes. Overrides must never become a way to expand allowed destinations or suppress success checks.

## 5. Escalation & handoff

Ownership is explicit: automation → paused → human → automation → completed. The runner awaits/settles the interrupted action before requesting intervention. A terminal operator claims the run and directly uses the existing visible browser. There is no replacement browser/context/page and no stored browser session snapshot. Authentication rotates the app cookie normally while retaining the intended account destination.

During human ownership, automated actions are rejected, while browser events continue flowing. Static document hooks record event categories/tags across navigations and frames without values or key contents. Resume checks the existing application and the requested active account's outputs. Early/wrong resumes are rejected. A verified human-completed account lookup finishes without repeating the interrupted step. Arbitrary intermediate checkpoints and compilation of human actions into artifacts are not supported; a human-completed discovery requires review/re-recording.

The noninteractive path returns an intervention request and closes the browser; it does not pretend to preserve a remotely resumable session. Hooks cannot observe OS dialogs or browser chrome and do not provide a complete semantic action history. Simulated operator tests prove ownership and session preservation but do not count as a real person's demonstration.

## 6. Safety

Trusted origin/route/action policy is separate from untrusted model decisions, app text and artifacts. Sensitive fills bind only to the authorized sign-in labels/routes. Actual link/form destinations are inspected before acting. Requests are intercepted context-wide; a Chromium response-stage gate validates redirects before following them, addressing the limitation of relying on initial-navigation checks alone. Popups and downloads are rejected, WebSockets blocked and service workers disabled. Human takeover cannot weaken network policy or bypass permission denial.

No arbitrary model code is executed. Structured observations contain public labels, symbolic input references and boolean matches, excluding credentials, member names/IDs and financial values. Persisted action rationales are concise normalized descriptions, not private reasoning or raw model payloads. Diagnostics use allowlisted event fields and sanitized structured snapshots; output values are returned only to the caller. The application's synthetic database is ordinary business storage, separate from diagnostic evidence. This is a reviewed sandbox policy, not a claim of universal isolation against a compromised browser or an operator modifying trusted code.

## 7. Cuts

Implemented depth centers on two typed read-only workflows on one vendor UI. No transfers, account changes, desktop adapter, general web crawler, tenant-override service, persistent browser restoration, remote co-browsing UI, or model-based replay recovery is included. Name search/pagination is available to staff; automation demonstrates exact-ID and product selection. The recorded live run demonstrates validated OpenAI-compatible discovery, deterministic replay, and same-browser human handoff/resume; provider token, cost, and API-latency metrics are not recorded.

`BrowserSurface.frame()` has a genuine registration-race branch: an attached iframe
can temporarily return no `content_frame()` before Playwright registers its named
frame. The focused regression test forces that condition and verifies the bounded
`frameattached` fallback. Duplicate matching frames and registration timeout are
defensive fail-closed branches, covered by focused tests without fallback to an
arbitrary frame.

The original assignment PDF was read. The checked-in evidence now includes genuine discovery, replay of its artifact with a different invocation, and a real human takeover/resume; simulated-provider runs remain separately labeled under `evidence/offline/`. The live handoff evidence records event categories and ownership transitions but no screenshots or raw browser trace. Before submission, review the sanitized evidence and publish only after explicit authorization. A production successor would add organizational authentication, approved artifact signing/review, richer vendor adapters and operational controls rather than unnecessary distributed infrastructure.

Artifact lifecycle is now explicit: discovery emits `draft`; the qualification
command executes an approved copy in fresh subprocess/browser contexts and writes
a sanitized hash-bound approval sidecar. Normal CLI replay rejects draft,
qualifying, rejected, or stale/mismatched approved discovery artifacts. The
caller now declares the workflow (`balances` or `transactions`) at discovery
time; the goal is model input and never selects the artifact type. The historical
transaction-goal attempts compiled `read_account_balances` capabilities.
The new `transactions/attempt-4-capability.json` was genuinely discovered with
`--workflow transactions`; it declares `read_recent_transactions`, a
`transaction_list` output, and transaction final/resume checkpoints.

Coverage status: the existing scenario matrix covers normal, missing/invalid
member, absent/closed/restricted accounts, permission denial, session expiry,
slow loading, bounded retry, and blocking-dialog intervention in the app/tests,
and the qualification matrix now declares independent balance and transaction
expectations for identity, product/status, ordering, count, dates, and decimal
amounts. The new transaction artifact passed its four-case qualification suite;
the separate two-workflow replay matrix covers 324 selected combinations. Adversarial safety coverage is substantial and includes forbidden routes/redirects/popups,
ambiguous locators, sensitive-evidence redaction, ownership dispatch blocking,
and resume checks. Two controlled tenant bindings are implemented
(`tenant.json` and `tenant-secondary.json`); capability reuse requires a
separate approval per tenant, and tenant, policy, or compatibility changes
invalidate that approval. Both bindings target the same local UI build (same
entry URL, frame, product, UI version, and adapter), so the secondary binding
demonstrates separately bound approvals rather than a different UI variant.
Tenant overrides cannot broaden the trusted
read-only policy.

## Historical owner-run validation

The owner-run stages were performed from source revision `659d6f4` and are
separate from the historical evidence above. Six genuine OpenAI discovery
attempts were recorded in `evidence/discovery-attempts-balances.json` and
`evidence/discovery-attempts-transactions.json`: four succeeded and two failed;
the failed attempts remain represented in the aggregates and were not
reclassified or rerun. Four successful capability artifacts were retained under
`evidence/discovery-attempts/`.

Each successful capability was approved for both `config/tenant.json` and
`config/tenant-secondary.json`, producing eight approved sidecars. All four
retained artifacts are `read_account_balances` capabilities; the
transaction-goal attempts compiled balance-workflow artifacts because the
typed `--workflow` discriminator did not exist at that revision. After the
workflow schema change, the eight sidecars were regenerated through real
qualification runs; they record `source_revision` `26dbf9d5`, the base commit —
the workflow fixes were still uncommitted at that point and are now committed
as `b99c91a` (`source_revision` is informational only and does not affect
approval matching). Artifact bytes were unchanged; the
approved hashes are `6b352786...b7ffe9a` and `ccdb2b9f...0e01855` under
`balances/`, and `e26ed1b2...eb7e047` and `f67d96f3...ff81c56` under
`transactions/` — the latter two are still balance-workflow capabilities.
Approval records use distinct tenant digests, so this is
capability reuse with separate tenant-bound approvals, not an unbound override.

The four historical primary/secondary reports contain 100 model-free executions
each (400 total): 72 extractions, 256 expected business outcomes, 48 expected
interventions, and 24 expected permission denials. They report zero mismatches,
but every report lists two artifacts while exercising only attempt 2; attempt 3
is uncovered. All four exercised balance workflows, including the reports labeled
transactions. These records are secondary historical evidence, not the primary
benchmark. Separately, `repeatability-final.json` and the adjacent
`repeatability-final/` directory have disjoint run-ID sets and cannot corroborate
a single ten-run sample.

The real handoff evidence is preserved in
`evidence/live-handoff-stage6/246101e0d773/` and
`evidence/live-handoff-stage6-retry/5c4f9a6d4fe9/`. The first ends with
`INVALID_CREDENTIALS` and is not counted as a successful handoff. The retry
records sanitized human interaction events, `automation -> paused -> human ->
automation`, `resume_verified`, and final `SUCCESS`.

## Typed transaction validation after the fixes

- Code commits: `b99c91adf5274e1f821eadc4388ab6ded84d8fde` adds typed workflows;
  `a398d503e883f84681cb8deeb2247e65ae7390aa` repairs cleanup/diagnostic handling
  and strengthens matrix verification; `1419e92fb162c8ce08014a5cf9e20cf11f13f02e`
  fixes retained evidence path conversion.
- Genuine OpenAI-compatible/gpt-4o discovery: `live-discovery/fb5619a7967f/`.
  The draft copy remains there; qualification approved
  `discovery-attempts/transactions/attempt-4-capability.json` through all four
  declared cases. Its sidecar records source revision `b99c91a` and canonical
  artifact hash `c2d4a19cb04de890f42415e5bd184f324c50b7b8862bf81efd307688e9099330`.
- Different-member replay with the model key removed succeeded in
  `live-replay/3e2895258655/`, using that same approved artifact.
- The first 324-case matrix at `b99c91a` failed at iterations 33, 78 and 79;
  `repeatability-matrix-b99c91a-both-workflows.json` is retained unchanged.
  Its temporary per-run logs were deleted by the old harness, so the precise
  original runtime cause is unproven. Tests independently reproduced abandoned
  cleanup tasks and unbounded failure snapshots; those defects were repaired.
  The `a398d50` retry stopped before browser startup due to a Path/string
  regression, fixed and regression-tested in `1419e92`. Its empty progress
  journal is retained, not counted as a completed matrix.
- `repeatability-matrix-1419e92-both-workflows.json` records clean source and
  all 324 distinct requested combinations: 36 verified extractions, 240
  expected business outcomes, 24 expected permission denials and 24 expected
  noninteractive interventions. Zero mismatches, rejected artifacts, unverified
  outputs or missing combinations; exit 0. Sanitized per-run diagnostics and a
  flushed progress journal remain in the matching `-runs/` directory.
- `test-verification-f545648.json` records the latest 158-test run on the final
  pre-submission commit. `clean-checkout-verification-f545648.json` records a
  fresh locked install, full Ruff, bank startup, and successful approved balance
  and transaction replays with model access removed.
- Real operator transaction takeover: `live-handoff-transactions/592ded6b14be/`
  records `SESSION_EXPIRED`, `automation -> paused -> human -> automation`,
  manual browser interactions, `resume_verified`, and final `SUCCESS`.
  The intervention identifies `read_recent_transactions`; the operator entered
  claim/resume in a visible terminal and performed sign-in in the same browser.

All evidence paths in this section are under `evidence/`. The secondary binding
still targets the same UI; these runs do not establish a second UI variant.
