# learning.plasticity current implementation status

This file separates **implemented source**, **product composition**, **host responsibility**, and **external gates**. It is intentionally stricter than target architecture prose in `TECHNICAL.md`.

## Status legend

- **Implemented source**: native code exists in the declared source roots and has focused tests or a named test surface.
- **Product composed**: a named product-workspace caller exists in source. This does **not** mean the path is activated in a deployment.
- **Host responsibility**: correctness depends on state/trust owned outside `learning.plasticity`.
- **Externally gated**: cannot be truthfully closed by this module's source code alone.

## Current source state

| Capability | State | Evidence / boundary |
| --- | --- | --- |
| Parameter V2 canonicalization, trust-region verification and digest binding | Implemented source | `codex-rs/hepta-plasticity/src/parameter_v2.rs` |
| Deterministic parameter candidate generation | Implemented source | `generator_v3.rs`; candidates are generated from the complete admitted signal surface rather than supplied by the caller |
| Artifact/current-lineage validation | Implemented source | `governed_v3.rs` consumes `learning.artifacts::ArtifactRegistry` and requires an eligible `Parameters` artifact |
| Evidence material existence and integrity | Implemented source + host responsibility | `PlasticityEvidenceResolverV3` must return the actual bytes for every named window/update/modulator/eligibility/norm/per-parameter digest; admission recomputes every digest and fails closed |
| Generator/observer/evaluator authentication | Implemented source + host responsibility | existing `learning.ledger` signed-evidence verifier, immutable host trust snapshot, revocation window and controller IDs |
| Independent evaluation | Implemented source + externally gated evidence | `learning.eval` signed independent evaluation is consumed; ineligible/insufficient evidence rejects proposal admission |
| Parameter proposal persistence | Implemented source | append-only checksum-chain registry |
| Production anti-rollback persistence | Implemented source + host responsibility | `ProductionProposalRegistryV1` requires a host-owned external anchor for every non-empty history and compare-and-store acknowledgement after every durable append |
| Named product caller | Product composed in source | `codex-rs/hepta-intelligence/src/plasticity_product.rs` |
| Topology proposal construction | Implemented source | `topology_v2.rs` emits one exact-successor, typed, authority-free structural proposal |
| Topology graph mutation / writer handoff | Externally gated / not implemented | deliberately no mutation API; requires separate migration, ownership handoff, canary and rollback implementation |
| Weight training / installation | Externally gated / not implemented | proposal engine remains next-generation only |
| Selection / acceptance / promotion / activation / release | Externally gated | no source path in this module grants those authorities |

## Trust boundary

A governed parameter proposal is admitted only when all of the following are true at admission time:

1. the selected parameter artifact exists in the current artifact registry and its full predecessor lineage remains eligible;
2. the dataset receipt recomputes and its producer principal remains valid;
3. every evidence digest named by the proposal resolves to actual bounded bytes and recomputes exactly;
4. the artifact-bound norm-profile evidence resolves to the exact canonical norm payload for the selected artifact;
5. the deterministic generator output recomputes from the complete admitted signal surface;
6. a trusted generator signs the generator input/output binding;
7. an independent trusted observer signs the complete evidence manifest;
8. a trusted evaluator signs the independent evaluation bundle;
9. generator, observer and evaluator pass principal and controller-level role separation;
10. the independent evaluation result is `EligibleForIndependentSelection`;
11. the final V2 proposal still carries `RequiresIndependentAcceptance` and `DENY_ALL` authority.

The signatures authenticate attestations and identities; they do not turn an evaluation into scientific truth or grant selection/activation authority.

## Production writer rule

`DurableProposalRegistry::open` remains a lower-level storage API for qualification and controlled bootstrap. A production-composed caller MUST use `ProductionProposalRegistryV1` or an equivalent stronger wrapper.

For a non-empty proposal file, an external `DurableRegistryAnchorV1` is mandatory. The anchor store MUST be in a rollback domain independent from the proposal file and MUST implement atomic compare-and-store for `(registry_scope_digest, writer_fence)`. If a proposal frame reaches durable storage but anchor acknowledgement fails, the handle is poisoned and no further writes are permitted until reconciliation/reopen.

## Non-claims

Source composition is not deployment activation. This branch does not claim production traffic, operator acceptance, independent acceptance, canary completion, promotion or release. Those claims require exact-head execution evidence from the selected host and the external governance gates described in `TECHNICAL.md` and `RUNBOOK.md`.
