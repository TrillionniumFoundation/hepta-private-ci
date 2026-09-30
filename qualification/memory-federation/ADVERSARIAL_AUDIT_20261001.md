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
cannot qualify this changed source. The implementation map binds the new source snapshot in a subsequent metadata-only commit. The repository verifier passes with the registry scoped read-only to memory.federation (one map, productionImplementationProved=false). The full repository verifier fails on pre-existing drift in kernel.operations, memory.retrieval and knowledge.graph and unavailable historical objects in other module maps; it is not a passing full-repository acceptance result.

## Follow-up audit on PR #1298

The preceding local results belong to the first source revision. Its hosted
canonical suite (31), wire suite (93) and compile-fail doctests (3) passed,
but all three federation jobs then failed strict Clippy under Rust 1.98.0:
two test fixtures manually implemented an empty waker. Replace them with
`Waker::noop()`, retaining the strict lint policy.

Three additional regressions fail on source revision
`93ad6c77b558a4ca786189d71c2a39a2b38db90a` and pass after the follow-up fix:

- an outgoing query exceeds the selected packet-size profile, but still commits
  pending intent;
- an outgoing owner response exceeds that profile, but still commits terminal
  state;
- owner response content has already expired at completion, but is still sealed
  and committed as terminal.

Crate-private validation hooks now check the fully encoded authenticated frame
plus body and fixed packet header before the existing wire owner's transaction
commits. Public wire entrypoints retain their existing semantics. This is not
a new persistence owner or a compensating write after failure.

A fourth regression covers cancellation replies: the incoming cancellation
fits its profile but its larger acknowledgement does not. Rejection preserves
the exact durable snapshot and replay slot; the original request then succeeds
with adequate reply capacity. The client also reuses the response shape/digest
validation already completed by body decoding, removing one redundant
clone/hash pass without bypassing authenticated admission.

Follow-up verification:

- Rust 1.95: 96 wire tests passed before adding the cancellation-reply regression;
- Rust 1.98.0: 97 wire tests passed, zero skipped;
- Rust 1.98.0 package-scoped `just fix` and all-target strict Clippy passed;
- 12 existing module-registry/projection tests passed;
- strict package registry is aligned (52 packages bound, none unclaimed);
- generated module-source projection check passes.

The hosted development-doc check exposed another module-owned omission:
the wire crate was unclaimed in the explicit Cargo registry. Bind both the
canonical and wire roots to memory.federation and refresh its source projection.
This does not upgrade production/composition/acceptance flags. Rebind the
implementation map only after committing the changed source and guide.
The product workflow now checks out and asserts the exact event source SHA,
and retains capacity diagnostics under that source identity. New final-source
hosted checks must be evaluated separately from the prior run.

## Completion assessment and remaining implementation gates

| Layer | Assessment |
| --- | --- |
| Canonical one-peer V2 checked adapter | Implemented; new adversarial regressions locally pass |
| Local-owner product composition | Present; #1280 fixes scope-before-ranking, exhaustion, peer failure isolation and final-use validity; production qualification remains separate |
| Authenticated wire, replay and durable recovery | Source candidates present; 97 follow-up local tests pass |
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
