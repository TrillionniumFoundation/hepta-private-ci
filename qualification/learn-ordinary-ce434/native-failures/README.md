# Retained original LEARN native failures

These are failed qualifications of two exact source candidates. Later fixture repairs do not change these outcomes.

| Source | Original native result | Fresh JUnit |
| --- | --- | --- |
| c7788fcb70e90ee887410df5abc4e840664ba088 | Compile failed: 12 E0659 ambiguous assert_eq! diagnostics; zero Rust test cases ran | None produced |
| 8f7cdf81c7e3a4a0c8921b63e3b64e73657e19cc | 1,330 cases actually executed: 1,325 passed / 5 failed; no retries | Original 1,330-case JUnit with all 5 failures |

Both sources passed their own 131 source-closure and 12 parser-control tests. Those checks did not establish native behavior. Source SHA/tree and clean state are bound in each original result.

## Exact 8f7 failure inventory

All original 1,305 baseline package/test identities are present exactly once and passed on 8f7. Material passed 6/6; C Observer passed 5/6; Selector passed 4/5. The native profile excluded 73 further cases; they are not passes. No case in the collected JUnit is marked skipped.

Three failures occurred in the original Training/Model lane fixture. Its synthetic evaluation clock issued evidence one second before the actual Training receipt, so the production timestamp check correctly rejected the material. Two failures occurred in positive C/Selector fixtures: the synthetic evidence peer had a 2-second idle wait and a 5-second session while the owner performed intervening physical CURRENT reads. The original raw diagnostics, rather than this interpretation, remain the authoritative observations.

The failed run did not proceed to its alias comparison. No later-source native pass is inferred here.

## Evidence identity

manifest.json lists each copied original path, byte length and SHA256. Original recorder-generated log basenames are unchanged. The execution record binds that exact log; JUnit and source/parser logs are copied without normalization. The missing c778 JUnit is not synthesized. runtime-terminal-readback.json records the original job service's terminal failed state, complete durable output, and absence of cancellation or timeout.

The 8f7 qualification driver is preserved as executed. Its same-source helper preparation and pinned V8 checks are included in the original result and helper logs. The older 73f20ed evidence is separately preserved at commit ab61d4ec6190125a11037ce6679895358871252d.

## Acceptance boundary

Complete ordinary positive adoption: **0**. Complete ordinary NoUpdate/fallback: **0**. Actual daemon plus Root cold restart of that complete chain: **0**. Component tests and original file reopen mechanisms do not satisfy those acceptance chains.
