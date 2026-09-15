# Computer-Use Banking Automation

A runnable, single-process Python automation engine and a separate **Demo Credit Union — Staff Console**. The model discovers a workflow through visible browser controls; a typed JSON capability records explicit input bindings; replay uses that capability without model decisions.

![Staff console sign-in, with empty credential fields](docs/staff-sign-in.png)

**Demo — Synthetic Data Only.** Never connect this project to a real bank.

## Delivery status and evidence honesty

Implemented: the FastAPI/SQLite banking app, iframe surface, reproducible scenarios, typed artifacts, a configurable real-model adapter, compiler, deterministic replay, policy enforcement, sanitized evidence, and terminal-driven same-browser takeover/resume.

The checked-in evidence demonstrates **real Chromium execution with a genuine LLM discovery**, replay of its artifact with different inputs, a business outcome, a recovered read failure, and a real human takeover/resume. Simulated-provider runs remain under `evidence/offline/` and are labeled separately. A hand-authored artifact is also included solely for executor testing.

The historical genuine discovery, deterministic replay, and human takeover/resume records are preserved under `evidence/live-discovery/`, `evidence/live-replay/`, and `evidence/live-handoff/`. The latest owner-run validation is separately preserved under `evidence/discovery-attempts/`, `evidence/repeatability-matrix-*.json`, and `evidence/live-handoff-stage6*/`; it includes four successful and two failed genuine discovery attempts, eight tenant-bound approvals, 400 model-free matrix executions, and one failed plus one successful real handoff attempt. All four retained artifacts are `read_account_balances` capabilities: the transaction-goal attempts ran before the typed `--workflow` discriminator existed, so they compiled balance-workflow artifacts. No genuine `read_recent_transactions` artifact is recorded yet. Provider token/cost metrics and raw browser traces are not recorded. Nothing has been emailed; publishing still requires explicit authorization.

See [evidence/README.md](evidence/README.md), [evidence/manifest.json](evidence/manifest.json), and [evidence/test-summary.json](evidence/test-summary.json) for what actually ran. [REPORT.md](REPORT.md) explains the design and limits.

**Reviewer entry point:** start with [REPORT.md](REPORT.md), then [evidence/RUN_SUMMARY.md](evidence/RUN_SUMMARY.md), [evidence/manifest.json](evidence/manifest.json), and the cited sanitized event folders. Live records are distinct from simulated runs under `evidence/offline/`.

## Install

Python 3.11+; tested with Python 3.12. Use an ordinary desktop session for human takeover.

```bash
python -m venv .venv
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
python -m playwright install chromium
# Linux CI missing system packages: python -m playwright install --with-deps chromium
```

`requirements.lock` pins runtime, test, and formatting dependencies. `pyproject.toml` also pins direct dependencies. The `.env.example` file is a reference only; variables are read from the process environment, not auto-loaded from that file.

## Seed and launch the bank

From the repository root:

```bash
python -m automation.cli seed
python -m automation.cli scenario normal
python -m automation.cli serve
```

Open <http://127.0.0.1:8000/>. Keep the server running in this terminal; use a second activated terminal for automation commands. `seed` intentionally resets the demo database, sessions, and audit history. Stop active runs before resetting it. Logical seed records and balances are deterministic; password salts and session tokens are securely generated.

Synthetic staff accounts:

| Username | Demo password | Role |
|---|---|---|
| `teller` | `DemoBank!2026` | Default teller; cannot access restricted accounts |
| `supervisor` | `DemoBank!2026` | Supervisor; for manual app testing |

The automation will prompt for credentials, or read them from these variables:

```bash
export BANK_STAFF_USER=teller
export BANK_STAFF_PASSWORD='DemoBank!2026'
# PowerShell: $env:BANK_STAFF_USER='teller'
# PowerShell: $env:BANK_STAFF_PASSWORD='DemoBank!2026'
```

The primary read-only run uses the teller. Permission denial stops execution; the engine never switches roles to bypass it.

## Genuine discovery and deterministic replay

Configure your own model endpoint and key. The default adapter uses the OpenAI-compatible Chat Completions API and requires JSON-schema structured output support.

```bash
export OPENAI_API_KEY='YOUR_API_KEY'
export LLM_MODEL='gpt-4o'
# Optional: export LLM_BASE_URL='https://api.openai.com/v1'
python -m automation.cli scenario normal
python -m automation.cli discover --provider openai \
  --member 10001 --product 'Primary Savings' --headed \
  --goal 'Find the member identified by input_ref member_id and return current and available balances for the active product identified by input_ref product_name.' \
  --artifact-out evidence/discovery-attempts/balances/new-candidate-capability.json
```

Success writes a draft candidate at
`evidence/discovery-attempts/balances/new-candidate-capability.json` and a
provenance-linked copy under `evidence/live-discovery/<run-id>/capability.json`
for the recorded live run. Qualify that candidate before replay; the measured
approved artifact used below is
`evidence/discovery-attempts/balances/attempt-2-capability.json`. A model's
`finish` response cannot create an artifact unless the final state and every
required output validate. Invalid model responses get at most two retries; the
run has a 25-step and 300-second live-run budget when invoked with `--timeout
300`.

Now replay **the same discovered artifact with a different member**, with model access disabled:

```bash
unset OPENAI_API_KEY
# PowerShell: Remove-Item Env:OPENAI_API_KEY
python -m automation.cli replay --artifact evidence/discovery-attempts/balances/attempt-2-capability.json \
  --member 10002 --product 'Primary Savings'
```

Replay never constructs a provider or imports the provider module. It returns typed JSON to the caller. Declared output values are not copied into diagnostic logs.

Discovery writes a `draft` artifact. Qualify it against fresh replay invocations
before normal replay:

```powershell
python -m automation.cli qualify --artifact evidence/discovery-attempts/balances/attempt-2-capability.json --members 10001,10002 --tenant config/tenant.json --policy config/policy.json
python -m automation.cli replay --artifact evidence/discovery-attempts/balances/attempt-2-capability.json --member 10002 --product 'Primary Savings' --tenant config/tenant.json --policy config/policy.json
```

Qualification writes a bound sanitized sidecar at
`<artifact>.approval.json`; the hash links records but does not protect against
an actor who can rewrite both artifact and approval files.

The second read-only goal uses the same visible account-details screen:
“Find the requested member and active account, then return its five most recent
transactions.” Discovery compiles a `read_recent_transactions` capability only
when invoked with `--workflow transactions`; the goal text is model input and
never selects the artifact type. The typed `surface.recent_transactions()` path
enforces the accessible table headers, ISO dates, decimal strings,
deterministic newest-first ordering supplied by the app, and a maximum of five
rows. A separate discovered transaction artifact/evidence bundle is not claimed
until a genuine provider run and qualification are performed.

For three independent genuine attempts (each starts a separate CLI/browser run),
use the owner’s private model environment. The `--workflow` flag selects the
typed capability to compile, the per-workflow artifact directory, and the
default goal:

```powershell
python tools/discovery_attempts.py --runs 3 --provider openai --workflow balances
```

The runner records successes and failures without provider payloads. It does not
claim genuine evidence when credentials or model access are unavailable.

For the second capability, declare the transactions workflow explicitly; the
goal is free text for the model and never selects the artifact type:

```powershell
python -m automation.cli discover --provider openai --member 10001 --product 'Primary Savings' --headed --timeout 300 --workflow transactions --goal 'Find the requested member and active account, then return its five most recent transactions.' --artifact-out evidence/discovery-attempts/transactions/new-candidate-capability.json
```

Run three independent attempts per workflow without substituting simulated
responses:

```powershell
python tools/discovery_attempts.py --runs 3 --provider openai --member 10001 --product 'Primary Savings' --workflow balances --out evidence/discovery-attempts-balances.json
python tools/discovery_attempts.py --runs 3 --provider openai --member 10001 --product 'Primary Savings' --workflow transactions --out evidence/discovery-attempts-transactions.json
```

Each attempt writes `evidence/discovery-attempts/<workflow>/attempt-N-capability.json`
so the same artifact path is used by the discovery, qualification, and replay
commands. Attempt numbering continues past existing files, so a new run never
overwrites a preserved artifact. Every attempt remains recorded, including
failures.

The varied approved-artifact matrix is owner-run only until a genuine
`--workflow transactions` artifact exists; the preserved artifacts under
`evidence/discovery-attempts/transactions/` are `read_account_balances`
capabilities, so replaying them exercises the balance workflow regardless of
directory name. Its intended command is:

```powershell
python tools/repeatability_matrix.py --runs 100 --artifacts evidence/discovery-attempts/balances/attempt-2-capability.json,evidence/discovery-attempts/transactions/attempt-4-capability.json --members 10001,10002,10004,10005,10006,10007 --products 'Primary Savings,Everyday Checking,Education Savings' --tenant config/tenant.json --policy config/policy.json --out evidence/repeatability-matrix-primary.json
```

This checkout does not claim that command was run; the matrix rejects
unapproved artifacts, omits model credentials, preserves every failure, and
reports expected business outcomes separately from extraction success. Inputs
from hand-authored or simulated artifacts are labeled as such and never count
as genuine-discovery evidence.

### Exact owner-run order

The following is the complete PowerShell sequence. **Terminal 1** runs only
the synthetic app; **Terminal 2** runs commands and keeps the model key
private. Set `BANK_STAFF_USER`, `BANK_STAFF_PASSWORD`, `OPENAI_API_KEY`, and
optionally `LLM_MODEL`/`LLM_BASE_URL` in Terminal 2 by private means; never
paste their values into logs or evidence.

**Terminal 1**

```powershell
python -m automation.cli seed
python -m automation.cli scenario normal
python -m automation.cli serve
```

Leave this process running. In **Terminal 2**, run each genuine workflow
three times independently. Each command starts its own browser/run and writes
an aggregate containing successes and failures:

```powershell
python tools/discovery_attempts.py --runs 3 --provider openai --member 10001 --product 'Primary Savings' --workflow balances --goal 'Find the member identified by input_ref member_id and return current and available balances for the active product identified by input_ref product_name.' --out evidence/discovery-attempts-balances.json
python tools/discovery_attempts.py --runs 3 --provider openai --member 10001 --product 'Primary Savings' --workflow transactions --goal 'Find the requested member and active account, then return its five most recent transactions.' --out evidence/discovery-attempts-transactions.json
```

The success signal is a zero exit status and a `status` of `success`; a
business outcome or failure is retained in the aggregate. If one attempt
fails, preserve its record and rerun only that command after correcting the
reported setup/model issue. For each successfully compiled artifact, qualify
against both normal members before replay. Substitute the successful attempt
numbers recorded in each aggregate; the preserved `attempt-2`/`attempt-3` files
under `transactions/` are historical `read_account_balances` artifacts from the
pre-workflow revision and are not transaction capabilities:

```powershell
python -m automation.cli qualify --artifact evidence/discovery-attempts/balances/attempt-2-capability.json --members 10001,10002 --product 'Primary Savings' --tenant config/tenant.json --policy config/policy.json
python -m automation.cli qualify --artifact evidence/discovery-attempts/transactions/attempt-4-capability.json --members 10001,10002 --product 'Primary Savings' --tenant config/tenant.json --policy config/policy.json
```

The success signal is `"status": "approved"` and a
`<artifact>.approval.json` sidecar. A rejected qualification must remain
rejected; do not manually edit the sidecar. Replay only after approval:

```powershell
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
python tools/repeatability_matrix.py --runs 100 --artifacts evidence/discovery-attempts/balances/attempt-2-capability.json,evidence/discovery-attempts/transactions/attempt-4-capability.json --members 10001,10002,10004,10005,10006,10007 --products 'Primary Savings,Everyday Checking,Education Savings' --tenant config/tenant.json --policy config/policy.json --out evidence/repeatability-matrix-primary.json
```

The matrix verifies each artifact against the expectations of its declared
capability name — a balance artifact can never satisfy the transaction suite
and vice versa. The matrix success signal is a completed sanitized output with
exactly 100 attempt records and a zero exit status; incorrect outputs, rejected
required artifacts, `outputs_verified_in_memory: false`, and incomplete
coverage all fail the run. It never imports or calls a provider. Failed
qualification, business outcomes, interventions, refusals, and extraction
failures remain separate categories. If the command stops before 100 records,
preserve the partial file and rerun with a new output path after fixing the
cause.

For an actual same-browser handoff, use **Terminal 2** after restoring the
approved artifact and keep **Terminal 1** running:

```powershell
python -m automation.cli scenario session_expiry
python -m automation.cli replay --artifact evidence/discovery-attempts/balances/attempt-2-capability.json --member 10001 --product 'Primary Savings' --tenant config/tenant.json --policy config/policy.json --headed --interactive --timeout 600 --evidence-dir evidence/live-handoff
```

The expected signal is an `intervention_required` result and a visible
ownership prompt. The human operator must type `claim`, reauthenticate in the
existing browser, verify the requested account, and type `resume`; only a
subsequent `status: success` with sanitized ownership events counts as a
completed handoff. If the operator aborts or times out, preserve that evidence
and rerun the same command; never simulate the interaction.

Synthetic expected results:

| Invocation | Current | Active holds | Available |
|---|---:|---:|---:|
| Member `10001`, Primary Savings | `4250.75` | `250.00` | `4000.75` |
| Member `10002`, Primary Savings | `9123.45` | `123.45` | `9000.00` |
| Member `10004`, Education Savings | `7000.00` | `0.00` | `7000.00` |

**Demo assumption:** available balance = current balance minus active holds. SQLite stores integer cents. Decimal parsing and decimal strings are used at the output boundary. No binary floating-point arithmetic is used for money. The displayed “As of” is the fixed synthetic ledger snapshot timestamp, not the time of the automation run.

The latest local repeatability sample ran the genuine artifact ten times with model access disabled, alternating the two documented normal members. All ten succeeded with in-memory output verification; see `evidence/repeatability-final.json` for run IDs and elapsed times.

To repeat that measured sample without calling a model, start the bank in `normal`
scenario and run:

```bash
python tools/repeatability.py --runs 10 --out evidence/repeatability-final.json
```

The command resets the synthetic bank with the existing seed command, requires the
genuine `llm_discovery` artifact, alternates members `10001` and `10002`, verifies
seeded outputs only in memory, blocks provider imports, writes aggregate metadata
only, and preserves failures in the summary rather than replacing them. Use
`--members 10001,10002 --product 'Primary Savings'` to state the defaults
explicitly.

## Offline executor and compiler demonstration

No model credentials are needed:

```bash
python -m automation.cli scenario normal
python -m automation.cli replay --artifact evidence/executor-test-capability.json \
  --member 10001 --product 'Primary Savings'

python -m automation.cli discover --provider fake \
  --member 10001 --product 'Primary Savings' \
  --artifact-out evidence/offline-capability.json
python -m automation.cli replay --artifact evidence/offline-capability.json \
  --member 10002 --product 'Primary Savings'
```

The fake provider is scripted and visibly labeled **SIMULATED**. It acts against the real browser and exercises the same compiler/executor as the real adapter. It does not count as genuine discovery. To regenerate the offline evidence bundle with the app already running:

```bash
python tools/collect_offline_evidence.py
```

This developer harness changes scenario configuration between runs. The automation packages never read that configuration or the banking database. Only the app and independent test harness do.

Replay events from new runs include a SHA-256 of the canonical validated capability; credentials, invocation values, and financial outputs are excluded from diagnostics. Historical evidence is preserved without rewriting.

## Runtime scenarios

Select a scenario before a run, in the second terminal. The app reads developer configuration from `var/scenario.json`; no scenario names or control flags appear in browser observations. Setting a scenario starts a new deterministic scenario epoch; it is never randomly chosen.

```bash
python -m automation.cli scenario fail_once
python -m automation.cli replay --artifact evidence/executor-test-capability.json \
  --member 10001 --product 'Primary Savings'
python -m automation.cli scenario normal
```

| Scenario | Visible behavior and engine outcome |
|---|---|
| `normal` | Normal UI; verify and return balances |
| `member_not_found` | Missing-record message; `MEMBER_NOT_FOUND` business outcome |
| `invalid_member_id` | Validation message; `INVALID_INPUT` business outcome |
| `no_matching_active_account` | Empty account table; `NO_ELIGIBLE_ACCOUNT` business outcome |
| `permission_denied` | Staff access denied; hard failure without role switching |
| `session_expiry` | Details request expires the session once; sign-in preserves the intended account destination |
| `slow_account_loading` | Details response delayed two seconds; bounded navigation wait |
| `fail_once` | First details request shows a temporary failure and safe retry link; one recorded retry |
| `blocking_dialog` | Visible service notice; intervention required |

Without injected scenarios: member `99999` is missing, `10005` has no savings account, `10006` has only closed savings, and `10007` is restricted. Members `10002` and `10003` share a fictional display name. The human UI supports paginated name search; the automation capability uses exact member-ID lookup.

## Real human takeover / resume demonstration

Use a computer with a visible desktop and the terminal in which you start the run. After genuine discovery, use its artifact; the executor-test artifact can be used to practice the mechanism.

```bash
python -m automation.cli scenario session_expiry
python -m automation.cli replay --artifact evidence/discovery-attempts/balances/attempt-2-capability.json \
  --member 10001 --product 'Primary Savings' \
  --headed --interactive --timeout 600
```

For the actual operator demonstration, do not automate the interaction:

```powershell
python -m automation.cli seed
python -m automation.cli scenario session_expiry
python -m automation.cli replay --artifact evidence/discovery-attempts/balances/attempt-2-capability.json --member 10001 --product 'Primary Savings' --tenant config/tenant.json --policy config/policy.json --headed --interactive --timeout 600
```

When the browser pauses, the operator must type `claim`, reauthenticate in the
existing browser window, confirm the requested account, and type `resume`.
The demonstration remains incomplete until a real operator performs those steps.

1. Automation reaches account details, encounters the expired session, and stops dispatching actions.
2. The same terminal prints the intervention/run ID. Type `claim`.
3. In the **existing browser window**, sign in with the demo teller credentials. Do not open a new window or restart the app. The bank rotates its authentication cookie normally but the browser process, context, and page are preserved.
4. The bank returns you to the intended account details. Verify the member and product, then type `resume` in the original terminal.
5. The engine checks origin, compatibility, member, product, status, currency, balances, and timestamp. It rejects an early or incorrect resume while leaving ownership with the human. Once verified, it finishes without repeating the account-opening step.

Type `abort` to end an intervention. The operator budget is five minutes; `--timeout` caps the whole run including browser startup and human time. A headless/noninteractive run returns `intervention_required` and closes the browser; it does not claim to preserve a remotely resumable session.

Human events record event category, element tag, frame category, and ownership transitions. Values, keystrokes, URLs, cookies, screenshots, and raw DOM are not recorded. Hooks cover document clicks/inputs/changes/submits and navigations in the instrumented page and its frames. They do not observe browser chrome, OS dialogs, or every semantic action. After an unknown mid-workflow state, the supported resume checkpoint is the fully verified requested account. Arbitrary intermediate resume/merging human actions into a reusable capability is deliberately unsupported.

## Tests

```bash
python -m pytest -q
# Same real tests plus a sanitized evidence summary:
python tools/verify.py
python -m ruff check automation banking_app tests tools --select F
```

Tests launch a separate FastAPI server on an ephemeral local port with a private temporary database. They cover schemas, binding, member/product selection, balances, business outcomes, timeouts, retry bounds, ambiguous rows/controls, forbidden requests and redirects, popups, redaction, ownership, resume verification, simulated compiler execution, and replay without model credentials. Test operator actions are explicitly simulated; they are not human evidence. The latest recorded verification summary reports 138 passing tests with no failures, errors, or skips.

## Layout and configuration

- `banking_app/`: private database, seed data, authentication, server-rendered screens and scenarios.
- `automation/models.py`: contracts for inputs, actions, targets, capabilities and results.
- `automation/surface.py`: visible DOM perception, scoped iframe targeting, browser actions and output checks.
- `automation/policy.py`: trusted origin/route/action policy and read-only action classification.
- `automation/provider.py`, `discovery.py`, `compiler.py`: structured model decisions and verified compilation.
- `automation/runner.py`: model-free replay and shared bounded recovery.
- `automation/handoff.py`: terminal ownership and verified same-session handback.
- `automation/evidence.py`: allowlisted events and sanitized structured failure snapshots.
- `config/`: separate versioned tenant binding and trusted policy.
- `tests/`, `tools/`: independent verification and explicitly labeled offline evidence harness.

`BANK_DB` and `BANK_SCENARIO_FILE` configure only the app/setup harness. `BANK_SESSION_SECONDS` configures server-side expiry. `--tenant` and `--policy` select automation JSON configuration. `config/tenant.json` and `config/tenant-secondary.json` are the two validated controlled bindings; a capability can be qualified separately for either tenant, but approval is invalidated by any tenant, policy, or compatibility change. Both bindings currently target the same local UI build — the same entry URL, frame, product, UI version, and adapter — so the secondary binding demonstrates separately bound tenant approvals, not a different UI variant. Tenant bindings cannot alter the capability or remove policy checks. The approval hash is an integrity link, not protection against an actor who controls both artifact and sidecar files. Approved selector overrides and desktop adapters are not implemented.

## Safety and public-submission checklist

The primary capability cannot transfer money or modify bank accounts. The engine checks actual form/link destinations against trusted route metadata; credentials can only be filled into the correct sign-in fields. Context-wide request interception plus a Chromium response gate check destinations before redirects are followed. Popups, downloads and WebSockets are blocked; service workers are disabled. These controls continue during human ownership and resume. The read-only policy is defense in depth for this chosen sandbox, not a general-purpose security boundary for arbitrary hostile browsers or users editing trusted Python/configuration.

Evidence uses structured sanitized snapshots instead of screenshots or raw traces. Banking storage legitimately contains synthetic business records; automation diagnostics do not. `.gitignore` excludes environment files, local databases, browser/session state and local run evidence. Explicitly review and copy the sanitized genuine run folders into `evidence/` before public submission. The provided assignment PDF was read during development but is not redistributed here.

The app is bound to loopback. Its demo HTTP cookie has `HttpOnly` and `SameSite=Strict`; HTTPS plus `Secure` cookies, production identity management, operational hardening and a security review would be required for any real deployment. Do not publish the demo service as real banking software.

Reference documentation: [Playwright browser contexts](https://playwright.dev/python/docs/api/class-browsercontext), [Chromium Fetch interception](https://chromedevtools.github.io/devtools-protocol/tot/Fetch/), and [OpenAI structured outputs](https://platform.openai.com/docs/guides/structured-outputs).
