## 1. Architecture

The target is a separate FastAPI application with Jinja screens and SQLite; the automation is one Python process using asynchronous Playwright. There are no queues, agents-as-services, or orchestration frameworks. The app provides an intentionally modest legacy surface: an iframe, server-rendered forms, dense account tables, and repeated “View” links. Labels and table relationships remain usable to staff and automation alike.

The automation imports no banking business code. Its surface adapter observes visible headings, labeled controls, table rows and definition-list fields; it never queries the database, calls banking business endpoints, or reads scenario controls. Setup and tests are explicitly independent harnesses permitted to seed/configure and verify the app. The database stores integer cents, hashed passwords, server-side sessions, holds, transactions and audit events.

Discovery receives a natural-language goal and typed invocation. A configurable OpenAI-compatible adapter returns schema-validated actions referring to the current sanitized control catalog. The controller chooses no banking workflow steps itself. The same surface, action executor, policy and recovery logic are used in discovery and replay. A static, vendor-specific observation adapter is the trade-off: narrow and reviewable rather than falsely claiming arbitrary-web generality.

## 2. Artifact schema

A strict Pydantic capability specifies schema/capability versions, application compatibility, typed input/output contracts, preconditions, stable step IDs, explicit frame context, ordered locator strategies, row constraints, checks, final success conditions, business outcomes, recovery limits, policy requirements, and discovery provenance. Credentials, member values, URLs, session handles, raw transcripts and observed balances are absent.

Dynamic values are `input_ref` bindings. A search-result row binds its Member ID to `member_id`; an account row binds Product to `product_name` and Status to Active. Recording never infers parameterization by replacing arbitrary matching strings. The compiler resolves transient observation references into supported stable targets; missing or unsupported references stop for review. The final checkpoint and declared contract cannot be weakened through artifact fields. Tenant entry URL and iframe binding remain outside the reusable artifact.

## 3. Determinism & error handling

Replay imports no provider. It validates inputs/artifact, resolves declared exact locators in order, requires one visible match, and verifies postconditions. A duplicate match stops immediately; it never falls through to an arbitrary first element. Table headers identify columns, row constraints select the intended record, and only then is the repeated View link resolved. The adapter waits for classified server-rendered navigation to finish, avoiding checks against an old iframe document.

Completion independently verifies member, product, active status, currency, all monetary fields and a timezone-aware timestamp. Decimal strings are parsed with Decimal; available balance must equal current balance minus active holds, an explicit demo assumption. The LLM saying “finish” is insufficient.

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

Implemented depth centers on one read-only capability. No transfers, account changes, desktop adapter, general web crawler, tenant-override service, persistent browser restoration, remote co-browsing UI, or model-based replay recovery is included. Name search/pagination is available to staff; automation demonstrates exact-ID and product selection. Live provider responses are strictly validated but no claim is made that the untested provider run has succeeded.

The original assignment PDF was read. Its mandatory genuine LLM demonstration remains incomplete because no model API credentials were available. No real human operator was available either. Included evidence accurately labels simulated discovery, genuine browser execution, deterministic replays, business/recovery paths, tests and intervention requests. The README supplies exact commands to capture the missing genuine discovery/artifact/replay and human takeover. Before submission, run those demonstrations, review their sanitized evidence, and publish only after explicit authorization. A production successor would add organizational authentication, approved artifact signing/review, richer vendor adapters and operational controls rather than unnecessary distributed infrastructure.
