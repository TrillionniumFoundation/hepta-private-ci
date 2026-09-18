# kernel.evidence qualification traceability

This matrix separates source implementation, execution receipts and independent
acceptance. A source test name is not treated as evidence that a current candidate
executed successfully.

| Requirement | Source | Native test / verifier | Exact-candidate execution receipt | Independent receipt |
| --- | --- | --- | --- | --- |
| target `append_receipt` with authenticated issuer and immutable idempotency | `codex-rs/hepta-evidence/src/qualification_store.rs` | `target_api_appends_queries_verifies_and_survives_reopen`; `changed_payload_under_reused_identity_conflicts` | required from PR/source-head CI for the candidate under review | not sufficient by itself |
| target `query_claim` with exact candidate and exact claim class | `qualification_store.rs` | `evid_02_different_tree_is_unavailable`; `evid_04_claim_class_substitution_is_rejected_by_query` | required | reviewed as part of the signed evidence set |
| target `verify_chain` with bounded traversal, expiry/revocation and role separation | `qualification_store.rs` | `target_api_appends_queries_verifies_and_survives_reopen`; `evid_01_same_controller_cannot_satisfy_independent_roles` | required | independent reviewer/operator must sign the exact evidence-set digest |
| EVID-01 principal/controller/key independence | `qualification_store.rs` | `evid_01_same_controller_cannot_satisfy_independent_roles` | required | pending external execution/acceptance |
| EVID-02 different tree / stale candidate unavailable | `qualification_store.rs` | `evid_02_different_tree_is_unavailable` | required | pending external execution/acceptance |
| EVID-03 corrupt payload / broken lineage fails closed on reopen | `qualification_store.rs`, migration `0011` | `evid_03_corrupted_payload_fails_integrity_on_reopen` plus store-open integrity checks | required | pending external execution/acceptance |
| EVID-04 claim-class substitution rejected | `qualification_store.rs` | `evid_04_claim_class_substitution_is_rejected_by_query` | required | pending external execution/acceptance |
| `IndependentDecisionReceiptV1` producer/domain registry consistency | `QualificationEvidenceEnvelopeV1::independent_decision_receipt` and `TECHNICAL.md` | protocol/document registry verification | required | receipt must originate from an independently authenticated principal |
| migration and immutable storage | `0011_qualification_evidence.sql`, `schema_validation.rs` | Lane A migration/schema verifier and reopen tests | required | not a substitute for independent semantic review |
| production caller / writer | qualification façade plus `PRODUCTION_COMPOSITION_HANDOFF.md` | integration test must name the real caller | pending until a named authenticated product host executes the API | pending |
| terminal outcome observer | provider-effect reconciliation and host-specific observer | provider-effect tests plus product integration | pending per provider/host | pending |
| external anti-rollback | `ANTI_ROLLBACK_V1.md` | repository can validate format/algorithm only | restore rehearsal receipt required | external checkpoint signer/store required |
| operator acceptance | `codex-rs/hepta-operator-acceptance` plus `INDEPENDENT_ACCEPTANCE_HANDOFF.md` | crate tests and formal environment checks | exact candidate/qualification receipt required | pending execution by an independent authorized operator |
| activation / promotion / release | external governance | repository gates | not claimed by this module | not claimed |

## Required module execution receipt fields

Every execution packet uses the canonical eighteen dossier fields:
`sourceReceipt`, `moduleGuideDigest`, `declaredSourceRoots`, `entrypoints`,
`consumerCallsites`, `hostRuntimeIdentity`, `binaryOrArtifactDigest`,
`configurationAndBodyGeneration`, `ownedPhysicalState`, `schemaAndMigration`,
`singleWriterFence`, `terminalObserver`, `revocationSource`, `faultResults`,
`resourceMeasurements`, `fallback`, `rollbackPredecessor`, and
`externalGateDisposition`.

For this change, repository CI may fill source/test fields only after it runs against
the exact candidate. The independent and operator fields remain missing until the
separate signer/operator actually performs the ceremony.
