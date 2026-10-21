# Memory Meta-Network V1: frozen stem and typed Cell routing (SHADOW_ONLY)

## Ownership and non-goals

This experimental seam combines the reviewed typed MemoryCell source of PR #2688 and the shared Encoder, per-Cell Head, multimodal stem, and Group NDU source of PR #2695 on top of the dependency/Objective/UI convergence source of PR #2944. File blobs imported from those PRs remain independently attributable; this branch does **not** supersede them or merge into main.

A MemoryCell is a rebuildable, bounded projection. The existing source/revision ledger, knowledge graph, evidence and forget/tombstone frontiers remain the only owners of factual truth. Adapter/head/encoder weights, local state, associations and compressed indexes are **never** the system of record. Parameterized memory alone cannot satisfy exact forgetting or evidentiary citation requirements.

The imported `SharedEncoderOwnerV1` attests a single immutable Encoder driver call per input shared across accepted Cell heads. A production driver, selected model/weights, signed artifact loader, actual GPU execution and perf scaling are **not** supplied by this source integration.

## Meta-Network shadow routing

The pure `route_memory_cells_v1` accepts a bounded policy and a complete set of typed Cell candidates. Every candidate carries:

- an immutable typed manifest with shared base/Encoder digests and model/graph generation;
- the original tick input and receipt, including exact snapshot, source/forget frontier, logical sequence and checkpoint predecessor;
- one shared Encoder feature digest, an external evidence-ledger digest, optional support digest and independent assessment reference;
- bounded relevance, uncertainty/OOD and compute-resource claims, plus optional association/contradiction groups.

All source/generation mismatches and duplicate Cell identities **fail closed**. No unsupported or abstained Cell can be selected. A conflict group with multiple eligible candidates suppresses all contenders, rather than electing a high-scoring unproven fact. Remaining candidates are ranked deterministically, capacity-limited and charged against a global resource budget; matching selected association groups emit only cross-Cell reference pairs, never synthetic claims. A versioned receipt binds the complete candidate set, route decisions, accounting, associations, evidence/frontiers and policy into a deterministic digest.

Output authority is sealed `DENY_ALL`. The receipt asserts `current_snapshot_immutable=true` and `production_activation_allowed=false`. These digests are **references**, not independent cryptographic signatures or proof of inclusion in the ledger. The caller must verify source citations, retention/deletion completeness, evaluator identity and safety before using any routed information.

## Learning and topology

`MemoryCellNextSnapshotCandidateV1` is an **offline proposal** binding predecessor generations, frozen Encoder identity, source/forget frontiers, Replay snapshot/receipt, candidate Adapter and Head Artifacts, independent Evaluation, optional Topology Proposal and rollback plan.

A proposed model update must advance exactly one generation. A topology change requires a proposal reference and the next graph generation; otherwise the graph stays unchanged. No-op, stale-frontier, stale-Encoder, wrong-generation and production-authorizing candidates reject. The type **never** writes the new weights, publishes a snapshot, activates a split or grants authority. Existing `MemoryCellSplitProposalV1`, plasticity, immutable source ledger, CAS artifact owner and architecture approval gates remain authoritative.

## Verification

From `codex-rs`, on the exact candidate head:

```bash
cargo test -p codex-hepta-cognitive-types --locked
cargo test -p codex-hepta-memory-retrieval --locked
cargo test -p codex-hepta-neuron --locked
cargo test -p codex-hepta-ndu --locked
```

Also require the unmodified repository-required blocking CI, architecture source-head/base-merge/required, cargo-deny, Rustfmt/Clippy, full Bazel on Linux/macOS/Windows, V8 actual build as applicable. Queued, skipped, cancelled, old-head or fixture-only results are not qualification.

## Remaining blockers before any promotion

1. Bind a real signed Encoder driver and CAS loader to the actual owner, benchmark 64/256/1024/4096 Cells (RSS/GPU/latency/throughput/WAL), and demonstrate frozen/shared execution.
2. Resolve all dependency security and Bazel/Cargo lock blockers; obtain terminal exact-head platform tests with no gate relaxation.
3. Produce independent source-citation and tombstone/deletion-rebuild witnesses, conflict/negative-transfer/OOD/calibration evaluation and two genuinely future observation windows, compared against a strong RAG baseline.
4. Verify separately authenticated Replay/Evaluation/Artifact/Topology proposals, 3 independent snapshots, rollover/recovery, governance, rollback, and external FinalUse authorization.

Until then: `SHADOW_ONLY / DENY_ALL / HOLD_NO_GO`.

## Executable shadow batch adapter

`codex-hepta-memory-retrieval::run_memory_meta_batch_shadow_v1` runs the existing typed MemoryCell tick for several Cells against a **single immutable** cue and engram snapshot, then routes the actual tick receipts through the new Meta-Network. It preflights Cell identities, shared Encoder and evidence frontiers before tick work; duplicate IDs or stale inputs reject. The adapter does **not** instantiate an Encoder, perform pre-inference sparse scheduling, inspect external ledger membership, or persist a winner. Its budget is an auditable post-tick route bound, not evidence that a physical GPU invocation was avoided.

The unit tests exercise two typed Cells over real deterministic retrieval/engram fixtures, empty-support abstention and stale-frontier/duplicate preflight.

## Pre-tick sparse admission candidate (shadow only)

`codex-hepta-memory-retrieval::plan_memory_meta_pre_ticks_shadow_v1` and
`run_memory_meta_preselected_shadow_v1` now offer a separately callable
**pre-tick admission** path. It is not silently substituted for the original
`run_memory_meta_batch_shadow_v1` full-batch baseline.

- The entire submitted Cell set is checked against one frozen Encoder,
  immutable snapshot, source/forget frontiers, and manifest/tick generation
  before **any** Cell tick.
  Candidate resource costs must also fit each Cell's own declared tick
  budget; a low-ranked/deferred Cell with impossible local accounting
  rejects before any other Cell tick (synthetic regression coverage). Even a low-priority or non-admitted Cell with invalid
  input/cue/objective is a hard rejection rather than a hidden omission.
- Claimed external support, typed contradiction groups, relevance, the maximum
  active-Cell count and a cumulative **reserved** compute budget are used
  deterministically; ties resolve by cost and stable Cell identity. An unresolved
  contradiction group is conservatively excluded before retrieval.
- Only admitted Cells have actual `run_memory_cell_tick` called. The original
  post-tick Meta-Network independently routes their real typed receipts and
  can still abstain due to confidence/OOD/conflict. Deferred Cell results are
  **not** fabricated.
- The plan retains ordered admitted/deferred identities, reserved cost,
  a SHA-256 commitment to the full **selection-metadata** input set and a
  separate decision digest. This internal, exact-source Debug-framed shadow
  digest is **not** a canonical wire schema, cryptographic signature, proof
  of ledger membership, or evidence that a generated payload was valid.
- The plan is `current_snapshot_immutable=true` and
  `production_activation_allowed=false`; it grants no writer, artifact
  selector, topology activation, model serving or FinalUse authority.

Focused tests cover order-independent plans, genuinely skipped invalid
non-admitted generated candidates, all-conflicted abstention, changed-metadata
digest binding, and stale-forget/forged-cue fail-closed behavior.

**Still blocked:** relevance/cost are caller-supplied estimates, not
independently authenticated or calibrated predictions. A single shared
Encoder feature digest is provided, not a running signed Encoder model.
No measured GPU FLOP reduction, corpus-backed citation, exact deletion proof,
future-time transfer superiority, replay/evaluation approval, or durable
generation promotion is claimed. Full exact-head CI remains mandatory.

## External evidence-owner admission seam (shadow only)

`run_memory_meta_preselected_evidence_checked_shadow_v1` is an additive,
opt-in wrapper around the deterministic pre-tick plan. Before the first
admitted Cell tick, it passes every admitted Cell's exact
`cell_id / support_digest / evidence_ledger_digest / snapshot_digest /
source_frontier_digest / forget_frontier_digest` to a caller-supplied
`FnMut(&MemoryMetaEvidenceLookupV1) -> bool` verifier. The wrapper fails the
**entire** batch on any rejection; it never falls back to the unverified
path. No deferred Cell runs or receives a fabricated evidence certificate.
Three focused tests cover late-Cell denial before an invalid retrieval,
tuple binding on acceptance, and empty-support abstention.

**Trust boundary:** that callback must be implemented by an independently
authenticated external ledger owner using a stable, pinned snapshot and
exact tombstone/forget membership checking. A callback returning `true`
is *not* a cryptographic signature, ledger inclusion proof, audit report or
consistency guarantee. The ordinary unverified shadow control remains
available for paired comparison and must never be promoted because of
this seam. No persistent writer, FinalUse permission or production route
has been added.

## Frozen-stem cross-generation shadow continuity

`MemoryCellNextSnapshotCandidateV1::validate_after` rejects a next
proposal if its predecessor graph/model generation does not match the
previous candidate's proposed successor, its Cell/Base/Encoder identity
changes, or its source/forget frontier changes without a separately
reviewed ledger migration. It also rejects reuse of the same Replay
snapshot, Replay receipt or Evaluation digest across consecutive model
generations, and rejects an unchanged pair of Adapter/Head artifact
digests without a valid topology proposal. Tests exercise G1→G2→G3→G4
handoffs and fail-closed stale/replay/no-op inputs.

This checks the continuity and *non-reuse of references*, not proof that
three independent future observation windows were executed. It does not
train a model, authenticate evaluators, bind real artifact bytes or
authorize generation promotion; those remain mandatory external blockers.

## Whole-batch cue/objective preflight hardening

Both the full-recall shadow control and the preselected path now validate
**every** Cell's tick cue and objective against the immutable invocation
*before* executing any Cell retrieval. A later Cell with a forged or stale cue
or objective rejects the entire batch without even running a prior Cell's
invalid generated retrieval. The previously separate preselected check is
centralized in the common fail-closed preflight. This does not authenticate
external evidence or change the production DENY_ALL boundary.

Exact-head native regression multi_cell_shadow_preflight_rejects_late_forged_cue_and_objective_before_any_tick
and the unchanged real CI gates are required before marking this code qualified.

## Post-tick external evidence revalidation (shadow only)

The evidence-checked admission path now performs two distinct external
verifier passes over exactly the same immutable admitted-Cell tuples. All
Cell supports must be accepted before retrieval, and all must be accepted
again before returning any route. A late rejection (including a simulated
forget/revocation observed during Cell ticks) discards the whole outcome.
The callback is required to be idempotent; the existing unverified baseline
is unchanged. The plan digest must also match the recomputed execution plan.

This is **not** a transactional pinned ledger read, a signed inclusion or
tombstone proof, nor protection from a revocation occurring *after* the
second pass. Production still needs an authenticated snapshot-consistent
owner with complete exact-delete propagation. Full exact-head Rust and
cross-platform checks remain mandatory.

## Local budget and full-chain replay invariants (shadow only)

The common `MemoryMetaRoutingCandidateV1::validate` now rejects a
routing cost greater than the Cell's declared tick budget, not only
the global Meta-Network limit. The independent, deserializable
`MemoryMetaRouteReceiptV1::validate` rejects zero or out-of-range
per-Cell costs even when its route digest has been recomputed. This
keeps pure routing, pre-tick admission and receipt validation aligned
on nonzero bounded resource reservations; it does not establish that
the estimates correspond to GPU or wall-clock usage.

`MemoryCellNextSnapshotCandidateV1::validate_chain` checks a bounded
oldest-first sequence of 3 to 64 offline proposals. In addition to
pairwise model/topology continuity and frozen Base/Encoder/frontiers,
Replay snapshot, Replay receipt and independent Evaluation digests
must be unique across **the whole sequence**. Tests reject reuse
across nonadjacent generations even where a two-generation
`validate_after` check would pass. These are consistency checks
over untrusted references, not signed Replay, evaluation independence,
future-window performance, actual model training or activation authority.
The qualification state remains **SHADOW_ONLY / DENY_ALL / HOLD_NO_GO**.

## Rehydrated route and replay lineage checks (shadow only)

A deserialized `MemoryMetaRouteReceiptV1` can have internally consistent
accounting and a newly computed route digest while still misstating utility,
source support or selection. The new `validate_against(policy, candidates)`
replays deterministic routing over the **complete original candidate set**
(in arbitrary input order) and rejects every divergence from the receipt.
`validate()` remains a necessary **self-consistency** check only; callers
must independently authenticate the supplied policy, candidates and external
evidence ledger before treating a replay as an evidentiary claim.

`MemoryCellNextSnapshotCandidateV1::validate_chain_against(manifest, chain)`
now anchors the oldest proposal to the actual Cell manifest before checking
the whole 3–64-generation offline chain. The chain rejects reused topology
proposal digests even when the reuse is nonadjacent and per-hop replay and
evaluator references are otherwise distinct. None of these methods signs an
artifact, approves training, applies a graph change or authorizes production.
