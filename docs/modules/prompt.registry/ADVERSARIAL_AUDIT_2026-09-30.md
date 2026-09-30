# prompt.registry adversarial audit — 2026-09-30

Source baseline: `a126987b84737dbc2ee2592442a314117bddb4a2` on `main`.
Scope: native registry, authenticated mutation seams, V1–V3 recovery, optimizer
read semantics, intelligence compilation and Agentd staging. This is a source
audit and remediation record, not independent product acceptance or release.

## Completion assessment

| Layer | Observed implementation | Completion boundary |
| --- | --- | --- |
| Development documentation | Technical guide, implementation dossier, profiles and map exist | Original dossier/map omitted implemented persistence and delivery; synchronized in this revision |
| Native deterministic owner | Factor lifecycle, exact model profiles, payloads, supersession, snapshots, graph-source reads, canonical codecs | Implemented; adversarial validation repaired in this revision |
| Durable owner | Unix exclusive lock, V3 immutable extents, migration, lifecycle replay, atomic metadata selection | Implemented; malformed-state and startup recovery repaired |
| Source consumers | Canonical optimizer, intelligence compiler, Agentd owner bootstrap and runtime host | Implemented source seams; actual optimization/staging turn ingress remains absent |
| Production writer | Final-use admission/payload/retire/revoke methods exist | No named authenticated product ingress or independently provisioned trust configuration |
| Live delivery | Sealed compiler output and bounded exact-model staging | Current revocation must also be revalidated at physical dispatch before live mutation activation |
| Production recovery | Internal image checks and exact-image backup tests | No external monotonic frontier rejects a complete older valid backup |
| Acceptance/release | Separate governance gates | Unproved; all production/activation/release claims remain false |

There is substantial native implementation, but the entire module is not
production-complete. A percentage would hide the missing integration gates.

## Reproduced defects and repairs

| Priority | Defect | Repair and regression coverage |
| --- | --- | --- |
| P0 source boundary | Public compiled delivery fields could be replaced and public digests recomputed, allowing forged instruction bytes into staging | Private compiler provenance seal; exact candidate/source/payload/role/token/profile/snapshot/serialized-byte cross-links; forged output regression |
| P1 | Compatible sets accepted rehashed invalid bindings, mixed model tuples, duplicate identities/profiles and missing required factors | Semantic closure and bounded required-factor filters before snapshot work; adversarial V2 tests |
| P1 | Admission grant retry ignored changed reviewer/evidence/scope and cross-factor reuse | Exact recorded admission semantics and unique grant identity; atomic conflict tests |
| P1 | Restore collapsed duplicate JSON members through `Value` | Bounded schema probe followed by strict typed decoding directly from bytes; four duplicate-member levels |
| P1 | Restore uniqueness omitted model ID/version although registration included them | Same complete profile semantics at registration and reopen; distinct-profile restart fixture |
| P1 | Rehashed lifecycle history could contain impossible owner events | Historical trust/event-shape, grant uniqueness and migration ordering validation; table of forged lifecycle images |
| P1 | FIFO state files blocked before regular-file validation | Nonblocking, descriptor-relative opening followed by private regular-file checks; FIFO rejection fixture |
| P1 | Invalid capacity or a known first-publication failure could strand a fresh owner marker | Validate configuration before storage effects; bounded initial-publication recovery while preserving uncertain/deleted-state rejection |
| P1 | Agentd accepted a different model label and could extend the selected portfolio horizon | Exact model ID and minimum of requested/portfolio/realization deadline; mismatch and expiry tests |
| P2 | Supersession restore rescanned every chain suffix | Memoized validated paths; 512-link recovery and rehashed-cycle rejection |
| P2 | Fresh owner directory name was not synchronized in its parent | Synchronize new directory publication before first owner commit |
| P2 | Relation-bearing memory state had no representable durable schema | Fail closed before publishing an image that would silently lose relations |

An independent second pass found a regression in the initial delivery repair:
bounded lookup could return an earlier-sorting role instead of the optimizer's
cheaper selected realization. The compiler now reconstructs its compatible set
from the exact owner-dereferenced selected bindings, preserving canonical ordering
and omission semantics. A separate multi-role regression protects this behavior.
The next pass identified the known first-publication marker recovery defect and
triggered another repair. Its concurrency follow-up added directory-before-marker
locking and an unlinked-inode fence. The final independent read-only pass on
`04f544073bbe1a3dd0a6f4a602e03631c2d2fb75` found no additional actionable
source defect within this audited scope. This is scoped review convergence, not
a guarantee that future workloads or integration cannot expose new issues.

## Position in the project and remaining work

`prompt.registry` owns admitted semantic factors, realization bytes and lifecycle.
`knowledge.graph` owns rebuildable interactions; `prompt.optimizer` reads and
selects; `context.compiler` binds selected content; `learning.ledger` owns causal
exposure/outcome facts. Agentd owns host composition and actual turn staging.
Keeping these writers separate prevents learned scores or external page text
from becoming instruction authority.

The remaining work is concrete, not hidden by the repaired source:

1. Compose a named authenticated product mutation ingress and provision independent
   reviewer/final-use trust and scope configuration.
2. Connect enumeration/selection/compilation/staging to real turn ingress, with
   dispatch-time current registry/revocation checks and stop propagation.
3. Bind backup recovery to an independently retained monotonic owner frontier.
4. Define governed durable relation publication and migration, history retention
   and compaction, and exact-tokenizer token-cost attestation. Declared token cost
   is currently not a measured tokenizer certificate.
5. Supply target-host performance, non-Unix durable support if required, independent
   semantic/product acceptance, and later PIM-3 evolution/causal-ablation evidence.

None of these is replaced by a unit test or an internally generated digest.
`CALLERS.toml` now inventories the four registry mutation boundaries with empty
product callers, and reconciles five already-declared boundaries missing from its
closed inventory. It does not invent a production consumer.
The caller scanner also retains production-possible conditional code, excludes
build outputs before reading, rejects source aliases outside scanned roots or
into ignored directories, and compares markers at identifier boundaries.
Adversarial wrapper tests prevent an autodereferenced registry call from being
hidden by another type's conditional, associated or typed-receiver method.
This remains lexical source inventory with `authorityGranted=false`.

## Validation

The unchanged baseline passed all 50 native registry tests. The repaired native
registry passed all 67 tests, including malformed restoration, admission retry,
bounded semantic-set validation, long supersession chains and bootstrap recovery.
The focused intelligence prompt suite passed all 9 tests, including forged
compiler output and the multiple-role selection regression. Scoped registry
`just fix` and the dossier verifier passed. Intelligence `just fix` also passed.
Agentd's focused test build stopped in the existing `codex-core` dependency with
SIGKILL under shared memory pressure, including a retry with one build job; no
Agentd tests executed. Its metadata-only lint retry was also interrupted by
SIGKILL in `codex-app-server-protocol` after an initial capacity failure. There
was no consumer source diagnostic and no Agentd test or lint pass is claimed.

Repository `just fmt`, scoped Rust formatting for registry/intelligence/Agentd,
changed Python formatting and `git diff --check` passed. Unrelated baseline
Python formatter churn was restored. The adversarial caller self-test and full
caller proof passed for 49 boundaries, 27 protected files and 2,865 Rust source
files, with `authorityGranted=false`. Build-resource failures are not test passes.

Test source locations and commands are listed in the technical guide and
implementation dossier; stored navigation is not a pass receipt. CI now includes
the focused intelligence and Agentd prompt suites on exact source and synthetic
merge candidates. No target-host or independent acceptance is claimed.

Repository-wide map validation has separate baseline gaps: seven unrelated maps
refer to unavailable historical commits even after fetching full repository
history (`objective.compiler`, `learning.ledger`, `cognitive.read`,
`automation.taskflow`, `utility.ndu`, `learning.artifacts`, `control.engineering`).
Only source evidence for the six modules touched by this change is rebound; no
unrelated historical receipt or execution claim is promoted. The CI map gate
remains blocking, after the focused prompt suites so those checks can provide
exact-candidate evidence despite unrelated map-anchor failures.
