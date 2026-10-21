# Shared Encoder / typed MemoryCell / Meta-Network candidate contract

Status: **SHADOW_ONLY / DENY_ALL / HOLD_NO_GO**. This is an implementation
and qualification contract, not a production memory writer or a claim that a
learning benchmark has passed.

## Owner topology

1. The external source/revision ledger owns facts, citations, revocations and
   forget frontiers. A MemoryCell is a rebuildable projection; neither a head
   weight nor an association edge is a replacement for source evidence.
2. One frozen or slowly updated shared Encoder, identified by its immutable
   artifact digest and generation, produces a shared feature snapshot.
   codex-hepta-neuron::SharedEncoderOwnerV1 retains physical forward ownership;
   a MemoryCell never owns another 421M-class backbone.
3. Typed MemoryCells (codex-hepta-cognitive-types::memory_cell) retain only
   adapter/head artifact refs, bounded state, lineage and compressed engram
   indices. codex-hepta-memory-retrieval::run_memory_cell_tick remains the
   generation-bound shadow recall seam; facts are never written by it.
4. The Meta-Network candidate planner (meta_network.rs) checks the declared
   current evidence root, source/forget frontiers, shared base/Encoder digest and
   graph/model generation before computing an **advisory** sparse route.
   It does not bypass hepta-ndu owner decisions or its explicit no-change path.
5. Actual scheduling, model execution, App Server tool turns and durable state
   remain with existing Hepta/Codex owners. This module creates none of them.

## Meta-Network V1

MetaNetworkPlanV1 carries a full bounded candidate set:

- MetaNetworkCellBidV1 includes a validated MemoryCellManifestV1, its
  canonical contract digest, a ledger-evidence receipt reference, estimated
  benefit, estimated resource cost, risk and OOD. The supplied numbers are
  *estimates* and are not measured performance claims.
- MetaNetworkLinkV1 is an evidence-referenced associate or conflict relation
  between ordered distinct Cell IDs. Duplicate, dangling and non-canonical
  links fail closed. Conflict takes precedence over association strength.
- MetaNetworkPolicyV1 bounds selection to 64 active Cells, 256 links and
  1,000,000 estimated resource units at most, and defines max OOD and minimum
  net benefit. All arithmetic is integer based and deterministic.
- MetaNetworkLedgerWitnessV1 must be supplied by the **original ledger owner**
  at the latest snapshot. The pure planner checks equality with the candidate's
  exact ledger, source, forget and admission receipt digests.
  A matching caller-supplied digest is **not cryptographic authentication**;
  the surrounding owner still must prove identity, ACL and revocation freshness.

The algorithm deterministically ranks by estimated benefit minus cost minus
risk, breaking ties by canonical Cell ID, and admits only policy-compliant
bids that fit the remaining budget. Conflicting Cell pairs cannot co-exist;
selected association edges remain only when both endpoints are selected and
are capped separately. The empty set is always an abstention. Every full
plan, including rejected candidates and link evidence, is digest-bound in
MetaNetworkRouteReceiptV1. Recompute the route against the current witness
to detect altered receipts.

Externally transferable contracts use the existing strict cognitive wire:
MetaNetworkPlanV1, MetaNetworkRouteReceiptV1 and
MetaNetworkNextSnapshotCandidateV1. Unknown fields, alternate schema labels,
non-canonical JSON, floats or a production posture are rejected.

## Ledger receipt coverage (V1 supplement)

The route-plan/ledger-root equality check alone cannot establish that each
Cell bid and graph edge still references an admissible live receipt. The
additive MetaNetworkEvidenceCatalogV1 is a **bounded, query-scoped projection**
of the original source/forget owner's live and revoked receipt identities.
The propose_meta_network_route_with_evidence_v1 gate requires every bid and
every link (including OOD/omitted bids and edges that would suppress another
Cell) to resolve to a live receipt. A missing, revoked or overlapping receipt,
stale ledger/source/forget frontier, or changed admission receipt fails closed.
The catalog has its own strict canonical cognitive wire identity.

Catalog membership is not a source signature, ACL decision, fact-grounding
proof or global deletion guarantee. The runtime must retrieve this catalog
and witness from the **authenticated current evidence ledger owner**, using
the existing authorization, source revision and revocation mechanisms.
Caller-provided matching digests do not authenticate their own provenance.
This contract introduces no second writer, ledger or retrieval owner.

MetaNetworkNextSnapshotCandidateV1::validate_against_live_evidence recomputes
the exact evidence-covered route before validating the successor. Independent
Replay, immutable Artifact, held-out Evaluation and Topology Proposal owners
must still authenticate their own referenced artifacts before any future
snapshot admission. All new tests use synthetic receipt identifiers: they
do not qualify a real evidence-owner integration, unlearning, learning gain
or FinalUse.

## Learning is next-generation only

MetaNetworkNextSnapshotCandidateV1 cannot execute or mutate anything.
It binds the exact route receipt, ledger/source/forget roots, replay receipt,
adapter/head artifact, **independent evaluation** and topology proposal by
digest. Graph generation must advance by exactly one; model generation may
be unchanged or advance by exactly one. The caller must still:

1. Retrieve/verify replay rows and provenance from the original source/forget
   frontiers; exclude revoked sources and stale facts.
2. Produce an immutable learning artifact in the existing artifact owner,
   declaring training source-family and temporal boundaries.
3. Evaluate on frozen independent held-out source families/future windows;
   include strong RAG and frozen shared-Encoder controls, OOD, privacy,
   deletion, negative transfer, latency, RSS, fairness and resource cost.
4. Verify the existing typed TopologyProposalV1 and retain the original owner
   and independent acceptance/rejection receipts; a digest is not approval.
5. After separate approved admission, use the already-defined next-snapshot,
   migration, old-writer fence, rollback and canary lifecycle. This contract
   performs none of those steps and does not authorize FinalUse.

## Negative controls and open blockers

The current tests use synthetic manifests and estimates; they do not
demonstrate real neural memory gain, citation precision, independent source
adjudication, exact unlearning or product readiness. The integration parent
and new child must earn real Cargo/Rustfmt/Clippy, Bazel Linux/macOS/Windows
and cargo-deny gates on the exact head; unrun checks are not passes.
A verified source owner/witness is still required for authenticated ledger
freshness, and independent evaluation remains uncompleted.

Any stale ledger witness, Encoder/generation drift, mutated manifest,
replay-evaluation mismatch, invalid relation or budget violation must fail
closed. The system remains **SHADOW_ONLY / DENY_ALL / HOLD_NO_GO**.
