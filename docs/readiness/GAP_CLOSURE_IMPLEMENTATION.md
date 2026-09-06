# V8 source-gap closure implementation

## Scope

The candidate branch `codex/hepta-v8-gap-closure-20260905` consolidates the
canonical V8.2 readiness head with bounded implementations for objective
compilation, NDU utility, causal learning ledgers, immutable learning artifacts,
Bellman targets, independent evaluation, temporal neuron signals, calibrated
intuition, governed prompt factors, prompt portfolios, plasticity proposals,
inference receipt validation, the read-only control UI, and engineering work
envelopes.

## Closed source roots

The closed-world inventory is recorded in
`qualification/gap-closure/MANIFEST.json` and verified by
`scripts/hepta-gap-closure.py`. Every Rust root inherits workspace package
metadata, opts into workspace lints, forbids unsafe code, has focused tests and
is included in the selected exact-head Cargo qualification.

The source verifier also executes the complete forty-module document check.
`scripts/hepta_module_doc_metadata.py` checks guide hashes, sizes, word counts
and source-status projections without writing. Explicit developer regeneration
uses `--write`; neither existence of a directory nor regenerated metadata
advances a module's source, runtime or capability status. The compact module
index preserves the same schema, contracts, ownership and authority fields.

## Implemented audit remediation boundaries

The CNS reference revalidates fused body-state age immediately at dispatch,
using a required maximum-age budget in the same monotonic clock domain. Future
observations, expired deadlines, invalid ranges and stale generations fail
closed. Physical calibration, clock-domain attestation, cryptographic authority
and hardware stop behavior still require their production adapters and evidence.

The reference loads all twenty-four registered organ manifests. Dependency and
fallback graphs are validated separately. A fallback cannot transitively depend
on the failed organ, and fallback cycles are rejected. HNMF failure degrades to
current body-state observation, not historical recall: requests needing memory
must abstain or seek takeover. This graph check is not a claim that twenty-four
production organs or physical controllers have been implemented.

Engineering integration evidence binds source commit/tree, base commit and a
distinct synthetic-merge commit/tree with ordered base/source parents. Both
execution lanes are required. The resulting decision is only eligibility for
independent review; structural consistency of supplied hashes is not signature
verification or permission to merge.

`codex-hepta-intelligence-eval::estimate_ope` now computes bounded fixed-point
IPS, SNIPS, doubly robust point estimates, effective sample size and maximum
importance weight. It rejects incomplete candidate sets, unsupported actions,
duplicate decisions, pending outcomes, watermark violations and invalid
probability distributions. Tests include `OPE-GV-001`, nonzero outcome-model
correction and tiny-weight ESS preservation. These in-process core types are
not a new external wire protocol or an acceptance interface.

The point estimator is separate from the existing conservative single-holdout
cluster intervals and preregistered temporal validation. These bounded analyses
do not establish general cross-fitting, authenticated evaluator independence,
production selection or future-time retention. The remaining requirements of
`LEARNING_EVALUATION_EXECUTION.md` keep the whole `LRN-2-CAUSAL-EVALUATION`
package and longitudinal capability claims open.

The OPE point estimator enforces the preregistered importance-weight ceiling
on the exact probability ratio before fixed-point rounding. A ratio above the
ceiling is rejected even when rounding would produce the ceiling itself.

Local memory retrieval rejects tombstone candidates before scoring or top-k
truncation. A deleted candidate invalidates the request; it cannot be returned
as evidence or concealed as an ordinary omitted result. The additive native
`retrieve_v2` API binds the query, snapshot, result limit and complete supplied
candidate set in canonical order, including the identities, record digests and
scores of omitted candidates. Its separate receipt digest also covers the
omission count. The existing V1 result digest keeps its original byte scope.
Consumers compare `request_binding_digest` with the binding of their expected
input. This is an owner-local integrity API, not an admitted external protocol,
source authentication or proof of completeness beyond the supplied candidates.

The actual cognitive owner now exposes `CognitiveStore::observe_memory_retrieval`.
It generates and revalidates at most 128 candidates in one SQLite read
transaction, preserving the legacy retrieval API and top-four ranking. Its
candidate observation records bind source revisions and scores without raw
memory or citation bodies. The final top-four omission count is exact for the
observed candidates. Per-channel `Exhausted` or `LimitReached` records distinguish
an exhausted bounded generator from a reached query/output cap; they do not
count unseen rows or prove global coverage, including beyond graph seed limits.
This owner observation does not bind a complete C1 objective/profile or establish
delivery-time freshness.

Matrix runtime accepts the typed `m.mentions` metadata serialized by the SDK
after ingress applies its explicit-mention policy. Only the message body is
submitted as user input. Unknown content or mention fields, invalid Matrix
user identifiers and malformed mention types remain rejected. The native
regression traverses SDK serialization, ingress persistence and runtime queue
admission, including duplicate delivery; its bridge is an isolated fixture.

The product SDK sync path now normalizes the processed response into one V2
durable decision. It handles joined and left rooms, state-before/state-after
ordering, redactions including nested redaction evidence, own leave/ban and
tombstones. Mutations and the authoritative checkpoint commit atomically. A
failed or dropped attempt keeps that SDK instance fenced because the SDK's
internal cursor may already have advanced. Startup completes the first durable
sync, takes the recovery snapshot, resumes current threads and recovers pending
work before starting runtime tasks. These are source integration changes;
real-Synapse and independent qualification remain separate.

## Remaining integration requirements

The C1 contract in
`qualification/module-execution-dossiers/C1_EXECUTION.md` still requires a named
product-host composition with structured objective/profile binding, the actual
tokenizer/template/payload, delivery-time revocation checks, durable
provider-attempt correlation, independent task outcomes, learning-ledger
integration, selected new-process load and rollback. The owner retrieval
observation, standalone module tests and reference round-trip do not establish
these product observations.

Canonical objective admission also needs an explicit native adapter and
registered baseline/classification profile. The canonical envelope cannot by
itself recover native constraint class/axis, principal scope or a selected soft
weight; resource, risk and evidence requirements must retain their semantics.
Plain turn text and attribution metadata cannot supply this missing binding.

The owner-local `ObjectiveSourceEnvelopeV1` representation now preserves every
canonical input field and integer/enum alternative. Its `validate_structure`
checks raw UTF-8 field sizes, collection counts and within-array semantic keys.
It neither admits a wire message nor converts a trust label into authority.
Canonical encoding and aggregate encoded bounds, NFC, identifier/time syntax,
digest/profile verification and the actual compiler adapter remain separate
prerequisites. The existing scalar compiler API and digest scope are preserved.

The separate `decode_source_envelope_json_v1` input decoder now checks the
specified JSON field grammar through private DTOs. Nested structs must be
objects, enums must be strings, and duplicate decoded keys, unknown or missing
required fields, explicit nulls, wrong integer widths and malformed digest
strings fail closed. Optional deadline omission is allowed; a present deadline
must be a string. The raw JSON ingress guard is 262144 bytes including whitespace
and escapes, separately from canonical or nested aggregate encoded bounds.
Errors expose only safe structural details. The decoder preserves source
spelling and supplied trust/digest values; it does not publish canonical bytes,
verify profiles, normalize identities, admit authority or connect the compiler
to the product host. The owner-local models gain no public serde wire surface.

The private Matrix gap-page accumulator is qualification-only. It binds an
explicit room/session/filter plan and opaque token interval, enforces cumulative
page/event/byte bounds, and requires exact target-token continuity. Empty pages
with a continuation are not exhaustion; a visibility boundary before the target
does not establish coverage. It does not issue HTTP requests, clear `limited`,
write a coverage anchor or advance a cursor. Its transcript is owner-local
integrity evidence, not authenticated server completeness.

Matrix still needs automatic timeline gap fill with persisted coverage anchors
and a bound on raw HTTP receive bytes. The current 512-event and 16 MiB limits
apply after SDK processing, not to transport reception or decoding. Incomplete
timelines fail closed. Conflicts with active dispatch stop processing; they do
not grant cancellation authority over an admitted effect. An unchanged-token
empty response now requires a distinct fresh owner checkpoint/capacity
observation under the writer transaction. It leaves journal and checkpoint
timestamps unchanged, still rejects exhausted capacity, and is not a durable
V2 commit or operation-replay receipt. New-token or nonempty responses continue
to commit V2 decisions. Their finite journal still requires retention/compaction,
and recovery after rejoining remains required. Evaluator-history
enforcement of holdout reuse, retention/unlearning qualification and independently
observed future windows also remain open.

Windows CI exposed both an MSVC/GNU native-library ABI mismatch and a real
legacy sandbox outside-delete regression. The local Windows build fallback now
selects an explicitly MSVC-scoped native C toolchain for host macros, preserving
GNU target compilation and compiler hardening. Actual Windows linking remains
a separate gate from lock reconciliation. At
`c9df068321d698e61fd026b263542329aa0eb122`, Windows shard two compiled
host MSVC `sqlx-macros` and the State library that invokes those macros. This
resolves that observed compiler blocker, not all native runtime qualification.

At `94f906ab0ba0802135f41aac6daf4691278f07df`, all seven Windows
build jobs stopped at the LLVM header parser's POSIX-only `unistd.h` include;
the four test shards executed no tests. A scoped LLVM patch adds MSVC file and
process APIs with explicit argument quoting and compiler exit-status propagation.
The real patched helper passed six Linux behavior tests. The Windows CI smoke
builds the actual helper for the MSVC platform and runs those same tests before
shard one. A zero-context patch variant misplaced the conditional under Bazel;
the source-anchored correction produces the intended C bytes under both patch
implementations. Its native MSVC smoke step passed at
`c9df068321d698e61fd026b263542329aa0eb122`. Downstream linker and sandbox
runtime results, and each later source head's required checks, remain separate.

The sandbox source candidate propagates required ACL setup errors and closes
the token before aborting launch. Legacy workspace tokens restrict writes to
their actual root capabilities; private desktops grant those same restricted
SIDs without changing the shared station or default desktop ACL. Such tokens
now require a private desktop. Readonly and elevated token policies remain
unchanged. Native regressions cover failed ACL installation, broad parent ACLs,
outside deletion and private desktop isolation. The local Linux package run
passed its twelve portable tests; it does not compile or execute these new
Windows-only paths. Native Windows isolation, process startup, PowerShell and
ConPTY compatibility remain required before this repair is qualified.
The later native run at `c9df068321d698e61fd026b263542329aa0eb122`
executed the sandbox library and failed: two delete operations escaped the
restricted-token boundary, and an ACL-denial fixture did not reject capture
startup. Subsequent poisoned-mutex failures are secondary. `WRITE_RESTRICTED`
does not cover the file deletion rights; the capability-only SID change is
therefore insufficient to close the deletion gap. These failures remain open
and must not be replaced by portable-test or compiler success claims.

Native CI also exposed an overlong `process_wrapper.exe` command before rustc
started. The wrapper candidate transports its own arguments through a separate
multiline response file without expanding the child's argument files. Its full
upstream harness passed 18 local tests, including five new regressions; the
actual Bazel-applied sources match that harness byte for byte. Native Windows
execution and an exact-head lock diagnostic remain required.

Other native repairs retain their platform boundaries: concrete Supervisord
process hosting rejects non-Unix before fleet access, and unsupported UDS peer
identity remains an error even where raw socket transport works. Operator file
verification now has a Windows handle-based hardlink/reparse candidate, while
the original hardlink rejection test stays enabled. The shadow oracle's exact
LF checkout rule preserves its existing byte pin. Parent-directory durability
on Windows remains unresolved; no successful fsync receipt is inferred from a
no-op or from flushing only the file.

## Safety and authority boundary

The implementation deliberately does not grant runtime, production-writer,
model-provider, physical-effect, selection, promotion, merge or release
authority. A successful source qualification means only that the bounded source
candidate passed its declared checks. Independent acceptance, production
activation, longitudinal efficacy and physical-safety evidence remain separate
governed states and may not be inferred from fixture success.

## Verification

The inherited feature-removal migration left qualification-only Rust code,
required-feature test targets and CI commands without their manifest entries.
The bounded migration exception in the workspace manifest verifier preserves
only the exact legacy feature mappings for Contracts, TaskFlow, Agentd, Matrix
SDK/daemon and the Supervisor signer. Every default feature set remains empty.
Unknown features, altered forwarding, optional dependencies and unregistered
internal feature activation remain rejected. This temporary declaration bridge
does not itself make Bazel run the feature-gated integration tests. TaskFlow now
has two explicit Bazel targets in `//codex-rs/hepta-automation`:
`hepta-automation-taskflow-kernel-qualification-test` and
`hepta-automation-taskflow-step-qualification-test`. They enable the structural
feature only in a private test-only library and the two existing fixture
binaries, using the shared native test launcher. The product library remains
unchanged. Exact-source execution of their four kernel and three step tests is
required; target declaration alone is not execution evidence. Extraction of
the other qualification suites and independent governance review remain open.
The signer and real-Synapse test stay opt-in and are not activated by source
qualification.
Windows run `34055640287`, job `101546918698`, reports the TaskFlow step
qualification target passed at `5ec6d0db2ef24bf545a18eeba1814dfa6e449ff2`.
Run `34056311823`, job `101548741807`, also reports that target and the
Contracts B3 adapter qualification target passed at
`e16208a8d490e72006f60eb002a220eb5cb174dc`. These are observed target-level
results; the logs do not include successful inner case counts. Both shards
failed overall on other targets, so these receipts do not establish green CI.

The Matrix SDK marker helper has an isolated Bazel target,
`//codex-rs/hepta-matrix-sdk:hepta-matrix-sdk-qualification-marker-test`.
It compiles the existing helper source directly and exercises one temporary
directory test for exact payload binding, one-time consumption and receipt
creation. The SDK product library keeps its transport failpoint disabled.
This local file test does not prove a real Synapse response was lost or that
the production retry path reuses its transaction ID.

The isolated Agentd target
`//codex-rs/hepta-agentd:hepta-agentd-cognitive-write-qualification-test`
uses the `runtime::tests::qualification_` filter for four existing local host
tests: unavailable-store rejection, exact replay, expired attempt takeover
without evidence, and quarantine when H7 evidence exists. These tests use
temporary registry and SQLite state; they do not start Agentd, an App Server
or a provider. The product feature remains disabled. This local qualification
does not replace the process-level cognitive E2E suite or production authority
evidence. Actual execution of these new Bazel targets remains required.
The admission-replay fixture explicitly withdraws its queued, unexecuted
occurrence before releasing the lease. Admission is not a completed-turn
observation, and unresolved occurrences must continue to block lease release.

Agentd also has the explicit Unix process-suite target
`//codex-rs/hepta-agentd:hepta-agentd-cognitive-product-qualification-test`.
Its dedicated binary uses the isolated qualification library; the test wrapper
resolves that binary through runfiles and runs the existing suite serially.
The eight active cases use local processes, temporary stores and mock services.
The four ignored comparisons/provider cases retain their existing guards.
This wiring does not activate the default writer, supply a real provider
receipt or establish production new-process recovery qualification.
The local process-suite attempt compiled and ran all eight active cases:
unavailable-store rejection passed and seven process cases timed out; four
ignored cases remained excluded. This is a failed qualification attempt.
Separate local UDS tests report socket creation denied by the environment,
but that observation alone does not prove the cause of every process timeout.
Successful native execution and diagnosis of any remaining timeout are required.

Contracts also has two explicit targets in `//codex-rs/hepta-contracts`:
`hepta-contracts-authbus-local-qualification-test` and
`hepta-contracts-authbus-b3-adapter-qualification-test`. Their private test-only
library enables only the local AuthBus qualification feature. The six B4/B5
and seven B3 adapter tests use in-memory models and scripted providers; their
recovery snapshots and secret-backend errors do not exercise real process
crashes, fsync, OpenBao or provider transport. The product library and existing
caller-manifest unit tests remain unchanged. These targets require actual
exact-source execution; they do not retire the Cargo migration exceptions or
satisfy independent acceptance and production integration gates.

The original `hepta-gap-closure.yml` workflow includes source normalization and
lockfile reconciliation. A result from a mutated checkout must not substitute
for exact-source qualification.

The dependency cleanup at `9e339cebaf0be6ee99c880251e809b9524b7b9d2`
has a verified Bazel lock diagnostic from workflow run `34045950601`, artifact
`9993629303`: before-check, update and after-check all exited zero. The candidate
lock has no diff and matches the retained `MODULE.bazel.lock` byte for byte.
This resolves that dependency change's lock reconciliation; it does not replace
the required source/merge checks or qualify later dependency changes.

The later SDK serde dev-dependency at
`ef723ae657196d60bb33246f65ac03c52e30903d` has its own matching result:
run `34049248997`, artifact `9994052918`, three zero exit codes and an unchanged
candidate lock. The earlier cleanup receipt was not substituted for this edge.

The native Windows compiler extension at
`b19625495ead1445854489923db6ae227ffe1874` also has its own verified diagnostic:
run `34052012269`, artifact `9994840015`, three zero exit codes and a candidate
lock byte-identical to the repository. This does not establish Windows linker
or sandbox runtime success.

The Objective structural decoder dependencies at
`bc851d2778e3ac5a753b5dce88b16865a56a3dd5` have a fourth exact-head
diagnostic: run `34054268307`, artifact `9995493305`, three zero exit codes
and an unchanged candidate lock. This receipt does not cover the later LLVM
helper patch or establish canonical Objective admission.

The initial LLVM helper patch at
`aa4013f2ff7bdcc3ca6f10b198460c4c460c0466` has a matching unchanged-lock
receipt from run `34054858120`, artifact `9995658610`; this did not make its
incorrect native patch placement pass. The source-anchored correction at
`c9df068321d698e61fd026b263542329aa0eb122` has its own run `34055332229`,
artifact `9995791034`. Both diagnostics contain three zero exit codes and
byte-identical candidate locks. Native smoke success for the correction is
distinct from production recovery or sandbox qualification.

`hepta-audit-remediation.yml` separately tests the immutable source head and a
synthetic merge with explicit parents. It uses read-only repository permission,
no retained checkout credentials and no automatic commit, push or merge. Both
lanes run affected Python/document gates, locked Rust all-target compilation,
selected-package regressions, strict Clippy and formatting checks. Formatting
suggestions are written outside the checkout and are diagnostic artifacts only.

CNS, engineering and metadata regressions remain independently runnable with
Python unittest discovery. Full module-document integrity is a required part
of source-gap verification, so stale metadata cannot be hidden by a narrower
source-inventory success. Real model use, durable closed-loop learning,
longitudinal efficacy, hardware safety, independent acceptance and production
rollout remain separate unclosed capabilities.
