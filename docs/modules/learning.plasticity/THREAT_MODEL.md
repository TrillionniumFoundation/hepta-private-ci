# learning.plasticity threat model

This document defines mandatory source/host controls for the proposal engine. It is normative for any production composition of `learning.plasticity`.

## Protected assets

- selected artifact and selected graph identity;
- proposal lineage, window and exact predecessor;
- evidence provenance/freshness and evaluator independence;
- trust-region constraints and canonical proposal bytes;
- durable proposal history and external acknowledgement sequence;
- deny-all authority posture of proposal records.

## Trust boundaries

### Evidence producer boundary

A digest is an integrity identifier, not proof of provenance. Production composition MUST authenticate every required evidence claim through a registered `EvidenceVerifier`. Verification MUST bind producer identity, subject digest, selected artifact/graph scope, window scope, freshness and revocation state. Unknown or unavailable critical verification fails closed.

### Independent evaluator boundary

Unequal proposer/evaluator strings are not proof of independence. Production composition MUST authenticate evaluator identity and an independent-evaluation attestation through `IndependentEvaluatorVerifier`. The verifier MUST reject self-evaluation, shared/revoked identity where policy forbids it, stale attestations and scope/evaluation-digest mismatch.

### Durable anti-rollback boundary

A checksum/hash chain proves internal consistency of the bytes that are present; it cannot prove that the file was not replaced with an older valid prefix. Therefore:

- after any frame is externally acknowledged, production reopen MUST use `ProductionProposalRegistry::open_anchored`;
- the external anchor MUST be retained outside the rollback domain of the registry file and ordinary backups;
- the host MUST NOT silently lower or discard an acknowledged anchor;
- anchor mismatch or acknowledged history missing MUST block writes and trigger incident handling;
- unanchored `DurableProposalRegistry::open` is compatibility/bootstrap/test surface and MUST NOT be used to reopen acknowledged production history.

## Threats and controls

| Threat | Required control |
| --- | --- |
| Caller supplies arbitrary candidates and claims generator completeness | Product caller uses native deterministic generator; composed request requires empty candidate list. |
| Forged non-zero evidence digest | Authenticated `EvidenceVerifier`; non-zero digest alone is insufficient. |
| Fake independent evaluator label | Authenticated `IndependentEvaluatorVerifier`; ID inequality alone is insufficient. |
| Stale/replayed evidence | issued/expires window + verifier revocation/freshness checks + artifact/window binding. |
| Cross-artifact/window evidence replay | exact artifact/window scope match before verifier grant. |
| Proposal mutation/tamper | canonical digest verification and deny-all authority check. |
| Parameter delta escapes trust region | per-layer and global exact squared-ratio limits. |
| Duplicate/conflicting proposal | artifact/window slot conflict + proposal-ID conflict + exact replay idempotency. |
| Durable suffix partial write | poisoned handle + anchored reopen + incomplete-tail repair only after anchor reconciliation. |
| Rollback to old valid prefix | independent external anchor MUST match recovered acknowledged sequence/digest. |
| Topology self-activation | topology V2 contains candidates only and always deny-all; no runtime graph mutation API exists. |
| Structural migration without rollback design | every topology mutation binds non-zero migration and rollback digests. |
| Proposal acknowledgement mistaken for acceptance | API/docs explicitly separate durable append from selection/acceptance/activation. |

## Forbidden shortcuts

Production composition MUST NOT:

- implement an `EvidenceVerifier` that returns success without checking registered trust material;
- implement an evaluator verifier that accepts based only on string inequality;
- reopen acknowledged history through the unanchored raw registry API;
- treat a valid proposal digest as proof that external evidence is true;
- treat a durable append receipt as independent acceptance or selection;
- apply parameter or topology changes directly from this crate;
- reduce trust-region or capacity limits via unchecked configuration.

## Residual external dependencies

Repository source cannot prove target-host key custody, external anchor independence, operator procedure compliance, deployed telemetry, or independent acceptance. Those remain external qualification gates and MUST be evidenced separately before activation/release claims change.
