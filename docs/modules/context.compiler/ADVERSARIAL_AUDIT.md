# Context compiler adversarial audit and integration boundaries

Detailed technical development documentation exists. Read
[V3_DEVELOPMENT.md](V3_DEVELOPMENT.md) for the active contracts and development
procedure, the generated current source/consumer maps for navigation,
`design-baseline/` for the detailed proof model, and `SECURITY_BOUNDARY.md` /
`RECOVERY_AND_RELEASE_RUNBOOK.md` for authority and recovery limits.

Source existence, ordinary product reachability, native execution and independent
acceptance are separate claims. Current candidates, run results and approvals
belong to exact PR/workflow receipts. This document records invariant findings
and design boundaries; it is not a copied qualification receipt.

## Adversarial findings and defenses

| Finding | Trigger / consequence | Implemented defense |
|---|---|---|
| Empty-selection domain bypass | A loop over selected admissions skipped scope/domain verification when there were none. | Validate the compilation receipt domain before iterating, including empty V2 contexts. |
| Independent-root revocation rollback | A newer independently verified snapshot could omit an earlier unrelated revocation while selected items stayed valid. | Retain the immutable cumulative frontier and reject time/epoch rollback, same-epoch changes and higher-epoch resurrection at attachment/preparation consumers. |
| Intervening attachment frontier loss | Preparation could retain the admission baseline but drop a revocation introduced at attachment time. | Check the attachment frontier as well as admission baselines, including empty context. |
| Path-directed durable storage | State/next/lock links or root/lock replacement could redirect IO or detach the visible writer identity. | Unix descriptor-relative no-follow/nonblocking IO; owner/mode/type/link checks before truncation; publication inode validation; permanent fencing on identity drift. |
| Dormant tests mistaken for coverage | Source files without module registration cannot execute; future settlement tests reference an absent implementation. | Register storage and diagnostic tests and require exact native names. Mark settlement source dormant. |
| Dynamic error disclosure | Pipeline/runtime Debug and Display exposed registry, adapter or compiler error strings; the public pipeline enum referenced a private internal error type. | Stable raw-free reason codes and an opaque public exact-delivery diagnostic; preserve recovery classification without exposing internal details. |
| Stale source navigation | Registered source blobs and shared workspace-input observations could lag actual source, stopping qualification before native execution. | Bind current registered bytes, regenerate projections and refresh only affected navigation observations. Navigation never grants execution/acceptance. |
| Resource failure mistaken for semantic failure | A full 257-turn fsync/tokenizer fixture needs a different harness budget from a single turn; combined Cargo debug/incremental output and Bazel extraction can exhaust a runner. | Preserve the complete workload under a bounded dedicated watchdog and disk-workload group; reduce temporary CI debug/incremental artifacts and record those inputs. Keep failures and all security gates visible. |

Frontiers are shared with `Arc` instead of copied per admission. Revalidation
scans each distinct admission snapshot once. The existing snapshot digest binds
its frontier, so the consumer checks do not change wire/digest schemas.
Deterministic pre-publication storage rejection can leave a valid owner usable;
uncertain publication or root/lock identity loss requires reopen. Owned directory
initialization tightens permissions through its descriptor, while unsafe state
file permissions are rejected without chmod through a replaceable path.

## Project position and completion assessment

The registry issues context authority, intelligence composes the V3 compiler,
and the existing exact-delivery/provider spine owns final request use. Compiler
proofs are necessary but do not independently establish provider truth or grant
a model call. Fix actual consumer seams rather than introducing a second owner.

| Layer | Source assessment | Remaining completion requirement |
|---|---|---|
| Compiler core | Implemented with domain/frontier regressions. | Exact candidate execution and qualified real tokenizer semantics. |
| Registry/intelligence | Typed authority and canonical V3 profile are source-composed. | Independent authority/provider qualification. |
| Agentd exact delivery | Named owner entrypoint and bounded recovery protocol are source-composed; Unix storage and error boundaries strengthened. | Authenticated ordinary App Server ingress, selected-host durability and cancellation authority. |
| Security capabilities | External lease/journal/generation/custody/attestation interfaces exist. | Consume them in the actual owner; a local verifier cannot attest provider truth. |
| Long-lived operation | Raw-content retirement and bounded capacity defenses exist. | Journal/checkpoint/archive migration preserving tombstones and anchored frontiers; limits remain 1024 runtime dispatch / 4096 exact pre-send records. |
| Release | Source generation grants no acceptance or activation. | Independent security acceptance and operator-controlled release. |

## Required verification

Inspect exact source-head and synthetic-merge receipts for actual command exits,
required fully qualified native test names, fixture profiles, strict lint,
dependency policy and immutable source checks. A successful `cargo check` profile
is compilation evidence. An isolated harness is only evidence for its declared
scope. Neither is an ordinary authenticated product run or target-host acceptance.

Further adversarial work must cover tokenizer custody/accuracy, privileged
rollback and replace-and-restore, Windows parity, power-loss recovery,
post-authorization cancellation, remaining provider slots, cross-holder redaction
and named-host latency/memory/backlog. These are unresolved integration tasks;
do not claim universal completeness, raise limits, delete replay history or
ignore dependency security errors to report closure.
