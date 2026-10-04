# Topology V1 historical verification and V2 admission

Status: local source repair; exact candidate and authenticated product qualification required.

## Two explicit commitments

`RuntimeTopologyCandidateV1` retains its historical `hepta.plasticity.topology-candidate.v3` length framing. Its digest covers candidate ID, changed flag and input-ordered deltas. It does not bind proposal, evaluation, generation or selected/rollback topology fields. Existing V1 validation and digest behavior remain available for read/audit; validity supplies no current effect authority.

`RuntimeTopologyCandidateV2` uses HPTC encoding V1 with semantic schema 2 and the new `platform.types:runtime-topology-candidate-v2` identity. Its delta identity is `platform.types:runtime-topology-delta-v2`, also schema 2. Every candidate semantic field except derived `candidate_digest`, and every delta field, is committed. Delta/module sets must have canonical increasing order.

The intermediate audit candidate placed this stronger commitment beneath the existing public V1 name. That was a compatibility defect. Its HPTC-under-V1 digest is not a legacy fallback and neither final decoder accepts it. Inventory any locally retained intermediate candidates before upgrading; do not assume an unpublished/reviewed branch produced no retained evidence.

## Read, upgrade and effect boundary

Separate V1/V2 JSON discriminators, schemas, codecs and validated wrappers prevent version inference from a digest. V1 decoding is historical read/audit only. V2 decoding validates a current candidate, but still grants no selection or effect authority.

The existing Supervisor `register_selected_topology_candidate(V1, ...)` signature remains available for source compatibility and now refuses every V1 admission before state mutation. It returns the existing `MissingVerifiedSelection` variant without expanding the exhaustive error enum. This means no eligible current V2-bound selection exists for that V1 request; it does not claim the supplied historical signature was invalid.

Current admission is explicitly `register_selected_topology_candidate_v2(V2, ...)`. The independently verified selection must match the new candidate digest, ID, generations and current serving topology, and all existing ABI/dependency/lifecycle checks remain. Private pending topology state contains V2 values only. There is no API that rehashes an old receipt or converts an old selection token into V2 authority.

## Evaluation commitment and unresolved owner binding

The V2 `evaluation_digest` is a nonzero caller-supplied value included in the candidate commitment. `RuntimeTopologyCandidateV2::validate` verifies that commitment; it does not authenticate the evaluation or identify its digest domain. The existing `historical_unbound_fields_stay_historical_and_v2_binds_them` test demonstrates the distinction: substituting the field invalidates the old V2 digest, while recomputing the candidate digest validates the new data without issuing authority.

In `codex-rs/hepta-intelligence-eval/src/self_evolution_selection.rs`, `prepare_self_evolution_selection_v1` derives `receipt.evaluation_evidence_digest` from the authenticated longitudinal `evaluation.decision.evidence_digest`. It separately copies `request.candidate_artifact_digest`; it matches the evaluation candidate ID but does not inspect topology semantics. The selector signs the resulting receipt, which commits both values. In `codex-rs/hepta-supervisor/src/module_runtime.rs`, V2 admission compares the receipt's candidate artifact digest with the full V2 candidate digest. It does **not** compare the candidate's `evaluation_digest` with the receipt's `evaluation_evidence_digest` or verify a mapping between them.

The tracked source contains no production producer or conversion into `RuntimeTopologyCandidateV2` that defines that mapping. The related `TopologyProposalRequestV2` in `codex-rs/hepta-plasticity/src/topology_v2.rs` also accepts a caller-supplied `evaluation_digest`. This does not establish either equal domains or distinct domains; comparing those fields solely because of their names would invent a protocol rule.

This is an unresolved product-security qualification blocker inherited from the prior admission path. A signed receipt committing the candidate and an evaluation is not proof that the candidate's evaluation reference identifies that authenticated evaluation. Before claiming authenticated topology admission, the owner must specify the producer and evaluation identity/domain, enforce the specified equality or verified mapping before mutation, and run real issuance tests that accept a matching candidate and reject a substituted reference without owner-state changes. Those tests must use the authenticated dataset, ledger, evaluation and selector flow, including upgrade/rollback cases. This repair does not close that gap or demonstrate an authenticated exploit.

## Required upgrade qualification

For an upgrade:

1. Retain original V1 inputs and witnesses for historical verification.
2. Obtain trusted values for every field newly committed by V2. If unavailable, stop; do not infer authority from old digest equality.
3. Build a canonical V2 candidate and independently reevaluate/reselect it. Merely copying fields or hashing them does not qualify or authorize it.
4. Submit matching V2 ABIs and the fresh independent selection through the V2 admission entrypoint.

This is an intentional fail-closed effect-admission transition, while native V1 read/API compatibility remains. Product callers must migrate explicitly.

## Rollback and restart limits

No cross-version authority rollback is supported. Current runtime rollback continues to require its independently verified selection and rollback witness, with successor generation semantics. Do not convert a V2 commitment back into historical V1 and apply it as an upgrade rollback.

Supervisor pending topology maps are in-memory and initialized empty. This change does not add a durable topology migration or prove restart recovery. External ledgers/artifact stores must retain the version and original selection evidence, inventory old or intermediate records, and requalify affected product flows. Historical digest verification is not a filesystem migration receipt.

## Evidence and qualification boundary

The shared vectors include old/new golden commitments, both wrong-discriminator directions, both crossed-digest directions, and rejection of the superseded HPTC-under-V1 digest. Native type tests preserve legacy unbound-field behavior while proving the V2 commitment binds it. The version-policy test exercises the same immutable V1 barrier used by the public method without manufacturing an opaque selection token; it checks valid/invalid candidates and ABIs leave owner state unchanged.

These tests are not an authenticated end-to-end owner selection fixture. Existing Supervisor topology tests largely exercise pending-state/lifecycle internals; source markers do not prove complete signed upgrade, restart or rollback execution. Native full types/wire/Supervisor tests, exact-head/prospective CI, independent review and authenticated product qualification remain required. No previous 145/145/82 receipt transfers to this changed source.
