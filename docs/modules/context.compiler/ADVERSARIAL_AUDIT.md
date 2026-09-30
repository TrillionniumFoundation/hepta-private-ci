# context.compiler adversarial audit — 2026-09-30

## Scope and source interpretation

Reviewed main at `a126987b84737dbc2ee2592442a314117bddb4a2` and the existing V3
candidate PR #1157 at `c2d044272bcf106f6fd9e5aa40656cdc7069a702` before this
follow-up. Main and the unmerged candidate have different completion states.
The candidate's previous PR description named an older source object; source
assessment here follows its actual branch contents. This report is design/audit
evidence, not an immutable CI execution receipt or independent acceptance.

Detailed technical development documentation exists: the retained
`design-baseline/` describes the compiler model and contracts; `TECHNICAL.md`,
`CURRENT_PRODUCT_PATH.md`, `IMPLEMENTATION_MAP.json` and `MODULE_MANIFEST.json`
project the canonical `CURRENT_STATE.json`. `SECURITY_BOUNDARY.md` and
`RECOVERY_AND_RELEASE_RUNBOOK.md` describe authority and recovery limits.
Retained design must be read together with current source and qualification
receipts: source existence, product reachability, execution and acceptance are
separate claims.

## Findings and changes

| Finding | Concrete trigger / consequence | Follow-up |
|---|---|---|
| Empty-selection domain bypass | Revalidation iterated only selected admissions; an empty compilation could attach against a foreign scope/domain. | Check the compilation receipt domain before iterating, including empty contexts. |
| Independently verified revocation rollback | A caller could supply a newer root-verified snapshot omitting an earlier unrelated revocation; selected admissions remained individually valid. | Retain the immutable cumulative frontier on verified admissions and attachments; reject time/epoch rollback, same-epoch changes and higher-epoch resurrection at actual attachment/preparation consumers. |
| Intervening attachment frontier loss | Preparation could preserve the admission baseline while dropping a revocation introduced at attachment time, including for empty context. | Validate preparation against the attachment frontier as well as the admission frontier. |
| Path-directed durable storage | Ordinary path opens could follow state/next/lock links; root or lock replacement could detach the single writer from its visible identity. | On Unix pin the private directory, open relative descriptors with no-follow/nonblocking flags, check ownership/mode/type/link count before truncation, verify publication inode and permanently fence identity drift. |
| Dormant tests counted as available source | Storage regression source existed without module registration; settlement tests reference an absent implementation. | Register six storage tests and require their exact names in qualification. Mark settlement source dormant; do not count it as coverage. |
| Stale qualification source inventory | Current capacity regression bytes differed from the registered blob; both source and synthetic-merge CI stopped before native tests. | Refresh registered source objects and generated projections, including the changed compiler and storage sources. |
| Dependency lock drift | The candidate declared agentd's libc dependency without its Cargo.lock dependency edge. | Synchronize the lock entry and attempt the prescribed Bazel lock update. |

The frontier is shared with `Arc` rather than copied per admission. Attachment
revalidation scans each distinct admission snapshot once; the snapshot digest
already binds the retained frontier, so these checks do not change wire/digest
schemas. Storage's deterministic pre-publication rejection leaves an otherwise
valid owner usable; uncertainty after publication or owner identity loss requires
reopening. Existing owned directory initialization tightens mode through its pinned
descriptor; permissive state files fail closed without changing their permissions.

## Position in the project and completion assessment

The intended path is registry authority → intelligence V3 compilation and
canonical serialization → Agentd exact-delivery owner → provider body/terminal
evidence. Compiler-local invariants are necessary, but the physical effect and
durable authorization belong to the delivery owner. This is why this follow-up
repairs actual consumer seams and delivery storage rather than introducing a
second provider owner or a parallel V3 implementation.

| Layer | Source assessment | Remaining completion requirement |
|---|---|---|
| Compiler core | Implemented, with added domain/frontier adversarial regressions. | Final immutable source/merge execution and qualified real tokenizer semantics. |
| Registry/intelligence composition | Typed construction-closed authority and canonical V3 profile are source-composed. | Independent authority/provider qualification. |
| Agentd exact delivery | Named owner entrypoint and bounded recovery protocol are source-composed; Unix storage defenses strengthened. | Authenticated ordinary App Server ingress, target-host durability and cancellation authority. |
| Security capabilities | External lease/journal/generation/custody/attestation interfaces are defined. | Consume those capabilities in the actual owner; a local consistency verifier cannot attest provider truth. |
| Long-lived operation | Raw-content retirement and bounded capacity defenses exist. | History rollover/checkpoint/archive migration preserving tombstones and anchored frontiers; current limits remain 1024 runtime dispatch / 4096 exact pre-send records. |
| Release | No source-generated acceptance or activation. | Independent security acceptance and operator-controlled release. |

## Verification and further work

Local core tests passed (55), including the three added frontier/domain tests.
Strict compiler all-targets Clippy passed with `-D warnings` after repairing five
findings. The regenerated source/docs Python suite passed (61). A standalone Unix storage
harness compiled the unchanged production store methods and storage module and
ran all six storage tests successfully; schema migration/validation and metrics
were substituted in that harness, so this is storage-only evidence, not an
agentd crate or product pass. Full consumer builds twice stopped with disk
exhaustion before executing tests. Bazel batch mode bypassed the container
process-discovery failure, but dependency fetching then failed certificate
validation. Neither failed check is a pass. Consumer native execution,
strict lint, pinned dependency policy, source-head and synthetic-merge results
must be reported from their actual run outcomes; local source navigation or this
report does not transfer qualification to a later commit.

Further adversarial review must cover real tokenizer custody and accuracy,
privileged rollback/replace-and-restore attacks, Windows storage parity,
power-loss recovery, post-authorization cancellation, non-developer provider
slots, cross-holder redaction and named-host latency/memory/backlog measurements.
These are concrete unresolved integration/qualification tasks, not a claim that
all optimization opportunities have been exhausted. Do not raise bounded limits
or delete replay history to make capacity tests pass.
