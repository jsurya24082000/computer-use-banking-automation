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

`manifest.json` links the actual offline and live run folders and statuses. `test-summary.json` is produced from pytest's real XML report, retaining only counts and timing. The live handoff evidence records a real operator interaction in the same browser process/context/page; simulated-operator tests remain separately labeled and do not substitute for that live run.

An earlier failed app-connectivity attempt is retained in `offline/e32067593416/`. It is not counted as a successful demonstration. No successful result was substituted for that failed attempt.

Run diagnostics omit invocation values and declared financial outputs. Failure evidence is a sanitized structured snapshot rather than raw HTML, traces or unmasked screenshots. Test XML and captured output are temporary and are not included. The expected balances in the README are explicitly published synthetic sample values, separate from diagnostics.

To regenerate offline evidence, start the bank and run `python tools/collect_offline_evidence.py`. To regenerate verification counts, run `python tools/verify.py`. Review live run folders before public submission; provider token/cost/latency metrics are not recorded, and no screenshots or raw browser traces are retained.
