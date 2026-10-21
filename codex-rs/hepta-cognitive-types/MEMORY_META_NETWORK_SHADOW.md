# Memory Meta-Network V1: frozen stem and typed Cell routing (SHADOW_ONLY)

## Ownership and non-goals

This experimental seam combines the reviewed typed MemoryCell source of PR #2688 and the shared Encoder, per-Cell Head, multimodal stem, and Group NDU source of PR #2695 on top of the dependency/Objective/UI convergence source of PR #2944. File blobs imported from those PRs remain independently attributable; this branch does **not** supersede them or merge into main.

A MemoryCell is a rebuildable, bounded projection. The existing source/revision ledger, knowledge graph, evidence and forget/tombstone frontiers remain the only owners of factual truth. Adapter/head/encoder weights, local state, associations and compressed indexes are **never** the system of record. Parameterized memory alone cannot satisfy exact forgetting or evidentiary citation requirements.

The imported \`SharedEncoderOwnerV1\` attests a single immutable Encoder driver call per input shared across accepted Cell heads. A production driver, selected model/weights, signed artifact loader, actual GPU execution and perf scaling are **not** supplied by this source integration.

## Meta-Network shadow routing

The pure \`route_memory_cells_v1\` accepts a bounded policy and a complete set of typed Cell candidates. Every candidate carries:

- an immutable typed manifest with shared base/Encoder digests and model/graph generation;
- the original tick input and receipt, including exact snapshot, source/forget frontier, logical sequence and checkpoint predecessor;
- one shared Encoder feature digest, an external evidence-ledger digest, optional support digest and independent assessment reference;
- bounded relevance, uncertainty/OOD and compute-resource claims, plus optional association/contradiction groups.

All source/generation mismatches and duplicate Cell identities **fail closed**. No unsupported or abstained Cell can be selected. A conflict group with multiple eligible candidates suppresses all contenders, rather than electing a high-scoring unproven fact. Remaining candidates are ranked deterministically, capacity-limited and charged against a global resource budget; matching selected association groups emit only cross-Cell reference pairs, never synthetic claims. A versioned receipt binds the complete candidate set, route decisions, accounting, associations, evidence/frontiers and policy into a deterministic digest.

Output authority is sealed \`DENY_ALL\`. The receipt asserts \`current_snapshot_immutable=true\` and \`production_activation_allowed=false\`. These digests are **references**, not independent cryptographic signatures or proof of inclusion in the ledger. The caller must verify source citations, retention/deletion completeness, evaluator identity and safety before using any routed information.

## Learning and topology

\`MemoryCellNextSnapshotCandidateV1\` is an **offline proposal** binding predecessor generations, frozen Encoder identity, source/forget frontiers, Replay snapshot/receipt, candidate Adapter and Head Artifacts, independent Evaluation, optional Topology Proposal and rollback plan.

A proposed model update must advance exactly one generation. A topology change requires a proposal reference and the next graph generation; otherwise the graph stays unchanged. No-op, stale-frontier, stale-Encoder, wrong-generation and production-authorizing candidates reject. The type **never** writes the new weights, publishes a snapshot, activates a split or grants authority. Existing \`MemoryCellSplitProposalV1\`, plasticity, immutable source ledger, CAS artifact owner and architecture approval gates remain authoritative.

## Verification

From \`codex-rs\`, on the exact candidate head:

\`\`\`bash
cargo test -p codex-hepta-cognitive-types --locked
cargo test -p codex-hepta-memory-retrieval --locked
cargo test -p codex-hepta-neuron --locked
cargo test -p codex-hepta-ndu --locked
\`\`\`

Also require the unmodified repository-required blocking CI, architecture source-head/base-merge/required, cargo-deny, Rustfmt/Clippy, full Bazel on Linux/macOS/Windows, V8 actual build as applicable. Queued, skipped, cancelled, old-head or fixture-only results are not qualification.

## Remaining blockers before any promotion

1. Bind a real signed Encoder driver and CAS loader to the actual owner, benchmark 64/256/1024/4096 Cells (RSS/GPU/latency/throughput/WAL), and demonstrate frozen/shared execution.
2. Resolve all dependency security and Bazel/Cargo lock blockers; obtain terminal exact-head platform tests with no gate relaxation.
3. Produce independent source-citation and tombstone/deletion-rebuild witnesses, conflict/negative-transfer/OOD/calibration evaluation and two genuinely future observation windows, compared against a strong RAG baseline.
4. Verify separately authenticated Replay/Evaluation/Artifact/Topology proposals, 3 independent snapshots, rollover/recovery, governance, rollback, and external FinalUse authorization.

Until then: \`SHADOW_ONLY / DENY_ALL / HOLD_NO_GO\`.

## Executable shadow batch adapter

`codex-hepta-memory-retrieval::run_memory_meta_batch_shadow_v1` runs the existing typed MemoryCell tick for several Cells against a **single immutable** cue and engram snapshot, then routes the actual tick receipts through the new Meta-Network. It preflights Cell identities, shared Encoder and evidence frontiers before tick work; duplicate IDs or stale inputs reject. The adapter does **not** instantiate an Encoder, perform pre-inference sparse scheduling, inspect external ledger membership, or persist a winner. Its budget is an auditable post-tick route bound, not evidence that a physical GPU invocation was avoided.

The unit tests exercise two typed Cells over real deterministic retrieval/engram fixtures, empty-support abstention and stale-frontier/duplicate preflight.
