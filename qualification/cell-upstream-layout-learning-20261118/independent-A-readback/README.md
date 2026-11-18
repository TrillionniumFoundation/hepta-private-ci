# A-panel original business readback (research only)

Observation on 2026-11-18, after the two frozen 32-update arms finished. This is a read-only independent recount of **the same original owner’s A executions**, not a new evaluation, independent controller, or prospective B3 experiment. Executing source: `78099aa6af4c70c00f26cb11888e20aa59510014`. Parent training source and original NoUpdate decisions retain their own identity. No models were generated or trained by this readback.

| Arm | Actual A current calls | Current task successes | Common-P-prefix calls | Prefix successes | Native verifier child runs | Current output-cap hits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| document_evidence control | 8 | **0/4** | 4 | **0/4** | **0** | 6 |
| native_feedback (prospectively designated main arm) | 8 | **0/4** | 4 | **0/4** | **0** | 7 |

All 24 calls have a recorded patch-admission rejection. The current-policy arms had 8/8 and 8/8 rejected attempts respectively; none reached the original native test child. The 24 exact original `VERIFICATION-*.json` bytes and SHA-256 digests are retained in `ORIGINAL_VERIFICATIONS.json` as base64 records. Their rejection categories include malformed/unterminated JSON, duplicate keys, old-text mismatch, and invalid edit fields. A response that reaches the output cap remains a failure; no retry was added.

Original source evidence retained here, copied byte-for-byte from the same owner directory:

- `document_RESULT.json`: 11,050 bytes, SHA-256 `2812be2feaf9526be114b2e7664fdca7f837b54db09241219cfc4dae5be91c32`
- `native_RESULT.json`: 11,028 bytes, SHA-256 `7845bb0f338d087c091bc8b46f412235046cd02558bcb867a953e2e805553191`
- `A_OWNER_COMPLETE.json`: 4,229 bytes, SHA-256 `94d57d3338f096fc3b99295372686f68f52b18a98ae218936a7374708bd86746`
- Frozen weights were read but not copied: 65,301 bytes, SHA-256 `2ab883c01843a4f29875f00b209ee9cc6ed7d4040fddd5ee297723bb5b276e63`; they already belong to the parent training evidence.

Exact per-arm tokens, disjoint runtime scopes, and rejection frequencies are in `READOUT.json`. The owner COMPLETE contains **130 whole-host RAPL samples**, about 66,502 J on CPU package 0 and 66,433 J on package 1 over the whole interval. These include unrelated host load and cannot be attributed to the model. GPU/network/storage energy, storage byte-seconds, provider charges and monetary cost remain **UNKNOWN**. Nested time and CPU scopes must not be added twice.

**Research decision:** The A panel demonstrates no learned executable repair success for either arm; it does not establish a causal feedback benefit. This cannot revise the earlier ResearchNoUpdate or qualify E1–E6. B3 remains separately committed, controlled by the original custodian and cannot be retroactively called independent controller custody; these A observations do not authorize changing B3 cases, budget, primary arm or hidden release order. No adoption, new C, cold fresh D, FinalUse or settlement is asserted.
