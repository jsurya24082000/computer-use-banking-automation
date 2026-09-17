Computer-Use Banking Automation

Discover a workflow with an LLM. Save it as a typed capability. Replay it with different inputs—without model decisions.

A runnable automation system for Demo Credit Union — Staff Console, a synthetic internal banking application. It demonstrates browser-only discovery, deterministic replay, policy enforcement, bounded recovery, and human takeover in the same browser session.

Quick start · Discover a workflow · Human takeover · Results · Technical report



What it does

The primary goal is to find a member's active account and return its current and available balances. Both the member ID and product name are invocation inputs.

Workflow

Capability

Output

Account balances

read_account_balances

Verified account metadata, currency, current balance, available balance, active holds, and ledger timestamp

Recent transactions

read_recent_transactions

Verified account metadata and up to five recent transactions, with validated dates and decimal amounts

Discovery chooses structured actions from current browser observations. The engine validates and authorizes each action, then checks the resulting state. A model's finish response is not proof of success.

A successful discovery produces a draft JSON capability. Qualification tests it against declared expectations. Normal CLI replay of a genuine-discovery artifact requires a matching approval and executes the declared workflow without importing the model provider.

Measured results

The latest verified PR revision, e25b69f, passed 165 tests per platform, with Ruff passing on both:

Platform

Tests

Test duration

Ubuntu

165 passed

297.60 seconds

Windows

165 passed

379.84 seconds

These results come from the PR verification run. The separate push verification run also passed on both platforms.

PR #3 merged into master at a2e2cc9. At this README update, its post-merge verification run was still in progress; the results above are for the PR revision, not a claimed post-merge result.

For historical comparison, merge eea76cf passed 158 tests per platform and Ruff in its post-merge CI run.

The primary replay benchmark covers 324 distinct combinations across two workflows, six members, three products, and nine scenarios:

Outcome

Count

Verified extractions

36

Expected business outcomes

240

Expected noninteractive interventions

24

Expected permission denials

24

Unexpected mismatches

0

Missing coverage / rejected artifacts

0 / 0

These are 324 expected outcomes, not 324 successful extractions. The matrix was recorded on clean revision 1419e92; it is separate from the final merge's CI results.

Genuine discovery, different-member replay, and actual-person takeover evidence are retained for both workflow types. The correctly typed transactions workflow has one recorded genuine discovery success; this is a demonstration, not a statistically established discovery success rate.

Start with the run summary, evidence manifest, and primary matrix. Historical limitations are listed below.

Quick start

Use Python 3.12, the tested setup, and a desktop session if you want to watch the browser or demonstrate takeover. Run commands from the repository root.

1. Install

git clone https://github.com/jsurya24082000/computer-use-banking-automation.git
cd computer-use-banking-automation
python -m venv .venv

Activate the environment:

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate

Then install the pinned dependencies and browser:

python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
python -m playwright install chromium

On Linux, use python -m playwright install --with-deps chromium if browser system dependencies are missing. The clean-checkout verification records installation and both approved replay demos at revision f545648.

2. Start the bank

In Terminal 1:

python -m automation.cli seed
python -m automation.cli scenario normal
python -m automation.cli serve

Open http://127.0.0.1:8000/ and leave this terminal running.

Demo username

Demo password

Role

teller

DemoBank!2026

Default automation role; restricted accounts remain inaccessible

supervisor

DemoBank!2026

Manual application testing

seed resets the synthetic database, sessions, and audit history. Stop active runs before using it. If port 8000 is occupied, check whether the bank is already running.

3. Run the approved demos—no model key needed

Open Terminal 2, enter the repository root, and activate the same virtual environment. The examples below use PowerShell. Set the synthetic staff credentials for automation:

$env:BANK_STAFF_USER = 'teller'
$env:BANK_STAFF_PASSWORD = [System.Net.NetworkCredential]::new('', (Read-Host 'Demo staff password' -AsSecureString)).Password
Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue

Replay the approved balances artifact for member 10002:

python -m automation.cli replay --artifact evidence/discovery-attempts/balances/attempt-2-capability.json --member 10002 --product 'Primary Savings' --tenant config/tenant.json --policy config/policy.json --headed

Replay the approved transactions artifact:

python -m automation.cli replay --artifact evidence/discovery-attempts/transactions/attempt-4-capability.json --member 10002 --product 'Primary Savings' --tenant config/tenant.json --policy config/policy.json --headed

Omit --headed for headless execution. Each command returns a structured result to the caller; financial outputs are not automatically copied into diagnostic logs.

Synthetic balance expectations:

Member / product

Current

Holds

Available

10001 / Primary Savings

4250.75

250.00

4000.75

10002 / Primary Savings

9123.45

123.45

9000.00

The demo defines available balance = current balance − active holds. SQLite stores integer cents; outputs use decimal strings. The displayed “As of” timestamp identifies the fixed synthetic ledger snapshot, not the execution time.

Discover, qualify, and replay

Keep the bank running and use Terminal 2. A new discovery requires your own model credentials and may incur provider charges. The adapter uses an OpenAI-compatible Chat Completions endpoint with JSON-schema structured output support. .env.example documents configuration; .env is not loaded automatically.

Configure the provider privately

$env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new('', (Read-Host 'Model API key' -AsSecureString)).Password
$env:LLM_MODEL = 'gpt-4o'
$env:LLM_BASE_URL = 'https://api.openai.com/v1'
$runStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$candidate = "evidence/local/discovery-$runStamp/balances-capability.json"
python -m automation.cli scenario normal

Discover a balances capability

python -m automation.cli discover --provider openai --workflow balances --member 10001 --product 'Primary Savings' --goal 'Find the member identified by input_ref member_id and return current and available balances for the active product identified by input_ref product_name.' --headed --timeout 300 --evidence-dir "evidence/local/discovery-$runStamp" --artifact-out "$candidate"

Continue only after the result is success and the candidate exists. Discovery has bounded steps, elapsed time, invalid-response retries, and no-progress checks. Failed attempts remain failures; do not relabel them or substitute a simulated provider.

Qualify the same candidate

python -m automation.cli qualify --artifact "$candidate" --members 10001,10002 --tenant config/tenant.json --policy config/policy.json

Continue only after status: approved. Qualification checks the declared workflow's outputs and expected business outcomes using fresh worker invocations. It writes <artifact>.approval.json, bound to the artifact, tenant, policy, and compatibility information. Do not manually change a rejected approval.

Replay with different inputs

Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
python -m automation.cli replay --artifact "$candidate" --member 10002 --product 'Primary Savings' --tenant config/tenant.json --policy config/policy.json --headed

This executes the artifact you just discovered, not a separate sample workflow.

For a new transactions discovery, privately configure the model key again, choose a fresh output path, and run:

$transactionCandidate = "evidence/local/transactions-$(Get-Date -Format 'yyyyMMdd-HHmmss')/capability.json"
python -m automation.cli discover --provider openai --workflow transactions --member 10001 --product 'Primary Savings' --goal 'Find the requested member and active account, then return its five most recent transactions.' --headed --timeout 300 --artifact-out "$transactionCandidate"

Repeat qualification and different-member replay with $transactionCandidate. The explicit --workflow selects the typed contract; goal text alone does not change the artifact type.

Human takeover

This demonstration requires a real operator and a visible desktop. It uses the checked-in, approved transactions artifact and does not need a model key.

python -m automation.cli scenario session_expiry
python -m automation.cli replay --artifact evidence/discovery-attempts/transactions/attempt-4-capability.json --member 10002 --product 'Primary Savings' --tenant config/tenant.json --policy config/policy.json --headed --interactive --timeout 600 --evidence-dir evidence/local/handoff

The account-details request expires the session. Automation pauses and prints an intervention prompt.

Type claim in the original terminal. Automation stops dispatching actions while the human owns the session.

Sign in manually in the same browser window. The bank preserves the intended account destination.

Verify member 10002, Primary Savings, and active status. Type resume in the original terminal.

The engine validates the resume checkpoint before continuing. An incorrect or premature resume is rejected; the interrupted action is not blindly repeated.

Type abort to stop. The operator budget is five minutes, and the overall timeout includes human time. A headless, noninteractive intervention returns a structured outcome and closes the browser; it does not leave a remotely resumable session.

Restore normal behavior after the demonstration:

python -m automation.cli scenario normal

See the recorded actual-person transaction handoff. Human event logging records categories and ownership transitions, never password values or keystrokes. Browser chrome and OS dialogs are outside its observation scope.

Reproducible runtime scenarios

Developer configuration selects scenarios before a run. The automation sees their visible UI effects, not the scenario configuration.

Scenario

Visible behavior / expected handling

normal

Verify the requested account and extract outputs

member_not_found

Missing-record message → business outcome

invalid_member_id

Validation message → business outcome

no_matching_active_account

No eligible account → business outcome

permission_denied

Access denied → stop without switching roles

session_expiry

Sign-in required → human intervention

slow_account_loading

Delayed response → bounded wait

fail_once

Temporary read failure → bounded safe retry

blocking_dialog

Blocking service notice → intervention

For example, replace normal with fail_once, then run either approved replay command:

python -m automation.cli scenario fail_once

Restore normal afterward. The seeded application also includes duplicate display names, multiple savings products, missing or closed savings accounts, and role-restricted accounts. Human name search supports pagination; capabilities use exact member-ID lookup.

Architecture

The bank and automation are separate components. Only the bank and independent verification harness access synthetic seed data directly.

Component

Responsibility

banking_app/

FastAPI/Jinja UI, SQLite records, authentication, sessions, and scenarios

automation/surface.py

Observe visible DOM, resolve unique contextual targets inside frames, act, extract, and verify

automation/discovery.py, provider.py

Bounded observe–decide–validate–authorize–act–verify loop and model adapter

automation/compiler.py, models.py

Typed actions, explicit input bindings, capability contracts, checkpoints, and provenance

automation/qualification.py

Workflow-specific qualification and bound approval records

automation/runner.py

Model-free replay using the shared executor and recovery rules

automation/policy.py

Trusted origin, route, and action restrictions

automation/handoff.py

Ownership transfer and verified same-browser resume

automation/evidence.py

Sanitized events and structured failure evidence

config/, tests/, tools/

Tenant/policy bindings and independent verification

The UI deliberately uses server-rendered forms, an iframe, and repeated View links. Targets require stable context and unique matches. The model cannot execute arbitrary Python, JavaScript, or shell commands.

Capabilities separate workflow structure from tenant entry URLs, credentials, invocation values, and transient browser handles. See REPORT.md for schema, compatibility, recovery, and adapter-extension decisions.

Safety and evidence

Both workflows are read-only. Trusted policy checks actual destinations; the model cannot declare an unsafe action safe.

Origin and route checks cover relevant requests and redirects. Popups, downloads, and WebSockets are blocked; service workers are disabled.

Policy remains active during discovery, replay, human ownership, and resume. Permission denials are not bypassed.

Automation evidence excludes credentials, cookies, raw member identifiers, financial outputs, raw model payloads, and browser traces. Failures use sanitized structured snapshots.

Synthetic records in the application database are separate from automation diagnostic evidence.

The approval hash links an artifact to its approval; it is not cryptographic attestation against someone who can rewrite both. The local HTTP demo would need production identity, HTTPS, secure-cookie configuration, operational hardening, and security review before any real deployment.

Run verification

python -m pytest -q
python -m ruff check automation banking_app tests tools

Tests use a separate bank server and temporary database. Coverage includes contract validation, parameter binding, account selection, typed extraction, recovery bounds, ambiguous targets, forbidden destinations, redaction, control ownership, resume checks, and replay without model access. Fake-provider and automated operator tests are explicitly simulated, not genuine discovery or human evidence.

To reproduce the full model-free matrix, keep the seeded bank running and use a fresh report path:

$matrixOut = "evidence/local/matrix-$(Get-Date -Format 'yyyyMMdd-HHmmss').json"
python tools/repeatability_matrix.py --skip-seed --runs 324 --artifacts evidence/discovery-attempts/balances/attempt-2-capability.json,evidence/discovery-attempts/transactions/attempt-4-capability.json --members 10001,10002,10004,10005,10006,10007 --products 'Primary Savings,Everyday Checking,Education Savings' --tenant config/tenant.json --policy config/policy.json --out "$matrixOut"
python -m automation.cli scenario normal

The harness blocks provider imports and retains sanitized run logs plus a progress journal. Incorrect outputs, unexpected outcomes, rejected required artifacts, or incomplete coverage fail verification. A shorter prefix cannot establish all 324 combinations.

tools/verify.py writes the historical fixed path evidence/test-summary.json. Use pytest directly and a fresh evidence filename when preserving that record.

Scope and known limitations

Intermittent Windows iframe startup failure. An earlier Windows PR run failed two transaction tests with FRAME_NOT_FOUND before workflow execution. Both tests passed when rerun locally, and the latest PR and push checks passed on both platforms. The root cause remains unresolved; passing runs do not establish that it is fixed. CI now retains existing sanitized event logs and failure snapshots when a job fails to support investigation. See the recorded failure. No test was skipped or timeout increased by that diagnostic change.

One UI implementation. Two tenant bindings demonstrate approval scoping against the same local UI, not different vendor interfaces. Desktop adapters and approved selector overrides are not implemented.

Limited genuine discovery sample. The typed transactions workflow has one recorded genuine discovery success. Model tokens, cost, and provider-only latency were not measured.

Bounded resume support. Human resume requires the verified requested account state. Arbitrary intermediate workflow merging is not supported.

Historical evidence has gaps. Earlier transactions-labeled artifacts actually declare balances. Older matrices omitted a listed artifact; the historical ten-run summary and adjacent logs have disjoint run IDs. They are not the primary benchmark.

History remains inspectable. Earlier failures are retained. Eight historical approval sidecars were regenerated after schema changes; prior versions remain in Git. Some historical runs lack complete source/dirty-state provenance.

The technical report explains trade-offs and deliberately omitted work. The evidence guide, run summary, and manifest distinguish genuine, simulated, current, and historical records.
