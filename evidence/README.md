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
| Genuine LLM discovery and resulting artifact | Included under `live-discovery/77525c9151e2/`; provenance is `llm_discovery` |
| Replay of a genuinely discovered artifact | Included under `live-replay/19744e6936e7/`; uses the discovered artifact |
| Real human takeover and resume | Included under `live-handoff/35587b0655e5/`; ownership and sanitized human events are recorded |
| Repeatability sample | Included under `repeatability-final/` and `repeatability-final.json`; ten alternating model-free replays |

`manifest.json` links the actual offline and live run folders and statuses. `test-summary.json` is produced from pytest's real XML report, retaining only counts and timing. The live handoff evidence records a real operator interaction in the same browser process/context/page; simulated-operator tests remain separately labeled and do not substitute for that live run.

An earlier failed app-connectivity attempt is retained in `offline/e32067593416/`. It is not counted as a successful demonstration. No successful result was substituted for that failed attempt.

Run diagnostics omit invocation values and declared financial outputs. Failure evidence is a sanitized structured snapshot rather than raw HTML, traces or unmasked screenshots. Test XML and captured output are temporary and are not included. The expected balances in the README are explicitly published synthetic sample values, separate from diagnostics.

To regenerate offline evidence, start the bank and run `python tools/collect_offline_evidence.py`. To measure ten model-free replays of the genuine artifact, start the bank in the normal scenario and run `python tools/repeatability.py --runs 10 --out evidence/repeatability-final.json`; it resets the synthetic database, blocks provider imports, writes aggregate metadata only, and preserves failures. To regenerate verification counts, run `python tools/verify.py`. Review live run folders before public submission; provider token/cost/latency metrics are not recorded, and no screenshots or raw browser traces are retained. New replay runs include a canonical capability SHA-256 in `replay_started`; historical logs retain their original format.

## Latest owner-run validation

The latest owner-run evidence was collected from source revision `659d6f4`.
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
zero unexpected mismatches: primary/secondary tenant crossed with the two
attempt directories. Because every retained artifact is a `read_account_balances`
capability, all four reports exercised balance extraction; the reports labeled
transactions did not verify transaction outputs. The reports preserve category
counts and per-attempt expected/observed status. They do not record
first-attempt/recovery counts or
p95 duration because the current runner does not measure those fields.

Stage 6 preserves both actual-person handoff attempts. The failed run
`246101e0d773` ends with `INVALID_CREDENTIALS` before intervention. The
successful run `5c4f9a6d4fe9` records
`automation -> paused -> human -> automation`, sanitized human interaction
events, a rejected early resume, `resume_verified`, and final `SUCCESS`.
