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

Matrix still needs automatic timeline gap fill with persisted coverage anchors
and a bound on raw HTTP receive bytes. The current 512-event and 16 MiB limits
apply after SDK processing, not to transport reception or decoding. Incomplete
timelines fail closed. Conflicts with active dispatch stop processing; they do
not grant cancellation authority over an admitted effect. Every successful poll,
including an unchanged-token empty response, requires a V2 committed receipt;
idle polls therefore consume the finite decision journal. Retention/compaction
or an explicitly owner-validated no-op design, and recovery after rejoining,
remain required. Evaluator-history
enforcement of holdout reuse, retention/unlearning qualification and independently
observed future windows also remain open.

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
does not make Bazel run the feature-gated integration tests; their extraction
into explicit qualification targets and independent governance review remain
open. The signer and real-Synapse test stay opt-in and are not activated by
source qualification.

The original `hepta-gap-closure.yml` workflow includes source normalization and
lockfile reconciliation. A result from a mutated checkout must not substitute
for exact-source qualification.

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
