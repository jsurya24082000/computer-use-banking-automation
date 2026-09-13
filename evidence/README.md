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
| Genuine LLM discovery and resulting artifact | **Not captured: model credentials unavailable** |
| Replay of a genuinely discovered artifact | **Not captured: depends on genuine discovery** |
| Real human takeover and resume | **Not captured: no real operator** |

`manifest.json` links the actual run folders and statuses. `test-summary.json` is produced from pytest's real XML report, retaining only counts and timing. Tests include a simulated operator in the same real browser process/context/page; those tests do not establish a real human demonstration.

An earlier failed app-connectivity attempt is retained in `offline/e32067593416/`. It is not counted as a successful demonstration. No successful result was substituted for that failed attempt.

Run diagnostics omit invocation values and declared financial outputs. Failure evidence is a sanitized structured snapshot rather than raw HTML, traces or unmasked screenshots. Test XML and captured output are temporary and are not included. The expected balances in the README are explicitly published synthetic sample values, separate from diagnostics.

To regenerate offline evidence, start the bank and run `python tools/collect_offline_evidence.py`. To regenerate verification counts, run `python tools/verify.py`. Use the README's real-provider and interactive commands to finish the missing demonstrations; review their sanitized run folders before copying them from the ignored `evidence/local/` directory for public submission.
