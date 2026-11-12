# Exact native format repair of the integrated same-actor candidate

This commit applies the actual formatter output retained by the failed V36 run of `b4960fe4a0577bd69a5341934bb38cb2715601d8`. It changes 76 Rust files only as produced by that original formatter, adjusts CALLERS to those exact layouts, updates the existing CALLERS size-exception hash, and corrects two descriptions of the A handoff. Future CLI, daemon coordination and completion-protocol source are outside this repair.

## What the evidence establishes

The original V36 formatter child exited 0 but changed the fixed source. The original executor and harness exited 1. Compilation, the full caller checker, QA and native tests were not reached. The complete original failure is preserved at [f9d82d4](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/f9d82d4831fe40e46a21e2ada77e66a1e062e735/qualification/ordinary-owner-assembly-20261111/native-components-b4960fe-seven/v11).

Root fetched the complete 407,063-byte native full-index patch and verified its original hash. All 76 files and 327 hunks reproduce exact preimage and postimage Git hashes, byte lengths and SHA256; reverse application recovers every original file. All 76 reconstructed postimages were CREATE/GET byte-verified. Hunk coordinates and full-file hashes disambiguate repeated context; textual uniqueness of every hunk is not asserted.

Independent source review accounts for every formatting delta, including optional commas, single-expression block layout and 15 import/module reorderings with their original attributes attached. It preserves all 1,016 comments, 2,288 value literals, 627 function names and 234 assertion/refusal macro occurrences. It finds no confirmed semantic blocker. This is source review, not compilation or test execution.

CALLERS changes through 65 exact, reversible whole-row replacements directly from `dbb7b662` to `5259882c`. Its 638 required/declared boundaries and 440 protected rows remain unchanged. All caller/receiver/ID sets and non-layout constraints are preserved. Of 168 marker strings, 157 change only whitespace; the remaining 11 reflect actual optional trailing commas, including one marker that now retains the native call's closing parenthesis. The original algorithms, checker and typed helper are unchanged. Independent metadata review found no weakening or local marker blocker and matched the actual changed source functions; 342 protected rows were not re-executed by this bounded projection. The complete original checker remains a required gate.

The existing single CALLERS size exception is rebound to SHA256 `9f4b62111b5cbf7c632fa4bb47f0253165bc0a64a783af2ac1e976405d3473da`. No path exception or size threshold is broadened. The evidence files here stay under the original 500 KiB threshold.

## A handoff and completion scope

The A handoff authenticates a task-local durable journal drain, awaits the original A Direct-owner loop, and releases its active owners before the second phase ACK. Root then validates and consumes the original Initial CURRENT owner before Learning/Model. The outer blocking task and Root service continue. Neither their physical join nor daemon/Root OS termination is inferred from task drain or an ACK.

The original generic-success refusal remains until the final owner-join protocol is implemented and qualified. Real ordinary task inputs and authenticated Outcomes, independent B holdout and executed cost/evidence journals, trusted Root approval material, actual Selector input and ordinary consumer owners are still required. The ordinary deployment entry remains future work. New sockets, readers, data notifications or callbacks cannot supply those missing authorities or resources by themselves.

## Qualification at this source freeze

The new fixed source has not yet run the original full qualification. V36 remains failed, and no V34 or other predecessor PASS is inherited. The next original entrance must retain the exact checker `7a6709691c372504ca11b5d2a74e14ba819fca8f`, typed helper `e23bb8aa42241b429ef5dbce5a4660853b66eb2f`, and harness `096b5b69c1295560f3a6c9e0da51e2708a0c996c` (50,167 bytes; SHA256 `1c9990189dde8cbf06ef4b234ada73376f8032d2f5dc40584ec2f3e53cd6e8a2`). The seven ordinary packages, exact 17 Root parents, retries 0, caller limit 3,600 s and overall limit 27,000 s remain fixed. Freshness is still 500 ms from the original request_started_ns; later events never renew it.

| Original business acceptance axis | Accepted |
|---|---:|
| Ordinary complete chain | 0 |
| Positive adoption chain | 0 |
| Genuine NoUpdate or rollback chain | 0 |

Independent ordinary C and actual daemon-plus-Root OS termination/restart remain unaccepted. A failed or unfinished system path is not NoUpdate. This is staged Draft work; main is not merged.

SOURCE_INVENTORY.json lists every one of the original 121 source paths and its exact parent/final bytes. The parent retains the original 40 assembly operation packets. The native patch, exact CALLERS operations, complete independent reviews, Root byte/structure checks and precise allowlist/wording operations in this directory make this repair reconstructible.
