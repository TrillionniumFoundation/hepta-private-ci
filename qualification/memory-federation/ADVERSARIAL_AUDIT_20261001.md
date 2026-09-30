# memory.federation adversarial audit — 2026-10-01

## Source boundaries

- Main inspected: `a126987b84737dbc2ee2592442a314117bddb4a2`.
- Latest layered candidate inspected and used as patch parent: PR #1283,
  `869c0983fcef3937dec537d1cec5a4755de4e1c3`.
- Delivery chain: #1280 host-local correctness → #1281 authenticated protocol
  → #1282 durable recovery → #1283 canonical V2 product adapter.
- This audit is implementation evidence, not independent security acceptance,
  target-host qualification, activation, promotion or release approval.

## Findings and changes

| Finding | Reproduction/evidence | Resolution |
| --- | --- | --- |
| Stop checked after adapter factory invocation | Stopped preflight and dispatch regressions panic on the parent | Lazy stack-pinned transport/authority construction after stop check |
| Stop becoming ready during synchronous poll was ignored | Ready transport and post-I/O authority regressions accept a result on the parent | Re-poll stop before accepting every ready result |
| Product CI stops before tests | Hosted run 36744050464/job 109985577644 fails rustfmt | Format capacity probe and adapter fixture |
| Capacity CLI contract mismatch | Workflow supplies `--output`, binary reads `args_os().nth(1)` as output path | Supply positional path and verify a real nonempty JSON output |
| Dependent source changes omit product verification | Product workflow path filters include only its own wire crate | Include canonical federation/types/wire dependencies and test canonical engine |
| Latest layer docs omit implementation contract detail | Product-layer guide is only 18 lines; main guide says no wire schema | Add source/ownership/admission/recovery map and distinguish source codec registration from production selection |

## Executed local checks

Before the fix, 31 canonical tests ran: 27 passed and four new regressions failed.
The pending-transport drop regression passed and confirms actual started-future
cleanup, rather than merely cancelling before transport polling.

After the fix:

- canonical V2 default surface: 31 tests passed, zero skipped;
- canonical plus explicit `legacy-v1`: 35 tests passed, zero skipped;
- independent wire crate: 93 tests passed, zero skipped;
- standalone wire-manifest package selection for the canonical suite passed;
- package-scoped `just fix` and wire all-target strict Clippy passed;
- capacity probe with its positional output path completed successfully.

Tests use `just test`/nextest. Five new tests cover cancellation and deadline at
factory boundaries, ready-poll completion, preflight/post-I/O authority, and
exactly-once drop of an already polled pending transport. Lazy wrappers are
stack-pinned and add no outer heap allocation.

Local checks do not replace hosted checks on the final source and merge
candidate. Historical FINAL_V2_VERIFICATION.md remains historical/pending and
cannot qualify this changed source. The implementation map must bind the new
source snapshot in a subsequent metadata-only commit.

## Completion assessment and remaining implementation gates

| Layer | Assessment |
| --- | --- |
| Canonical one-peer V2 checked adapter | Implemented; new adversarial regressions locally pass |
| Local-owner product composition | Present; #1280 fixes scope-before-ranking, exhaustion, peer failure isolation and final-use validity; production qualification remains separate |
| Authenticated wire, replay and durable recovery | Source candidates present; 93 local tests pass |
| Cross-host model recall | Incomplete: response currently carries identity/digests, not model-visible memory payload and full remote revalidation material |
| Selected production service | Incomplete: channel selection, credential operations and Agentd network serving remain absent |
| Deployment acceptance | Unproved: independent two-host fault/SLO/restart/rollback qualification, canary and operator/security acceptance remain gates |

The next substantive implementation is an authenticated bounded evidence
payload and its owner/currentness binding, followed by selected transport and
Agentd composition. Do not add another scheduler, writable memory owner or
retry queue to the canonical checked adapter. Preserve explicit partial and
indeterminate coverage, externally governed fact/authority ownership, and
correction/deletion/final-use boundaries. Do not replace missing execution or
product behavior with completion flags.

The final review of this bounded patch found no additional defect in its stop
fences. This is not a claim that an entire cross-host federation product has no
remaining work or that security review can exhaust all possible findings.
