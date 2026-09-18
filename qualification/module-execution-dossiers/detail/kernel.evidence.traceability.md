# kernel.evidence qualification traceability

This matrix separates source/test coverage from execution and independent
acceptance. A test identity is never treated as a pass receipt, and CI is never
treated as an independent reviewer.

| Requirement | Source implementation | Native test / oracle | Exact execution receipt | Independent receipt | Current claim |
| --- | --- | --- | --- | --- | --- |
| QUAL-API-01 signed append | \`codex-rs/hepta-evidence/src/qualification.rs::HeptaEvidenceStore::append_receipt\` | \`target_append_and_query_are_exact_candidate_and_claim_class_bound\` | Lane A \`lane-a-source-native-<head>\` and synthetic-merge artifact | not required for API existence | source implemented |
| QUAL-API-02 bounded claim query | \`qualification.rs::query_claim\` | \`target_append_and_query_are_exact_candidate_and_claim_class_bound\` | Lane A exact-source/native receipt | not required for API existence | source implemented |
| QUAL-API-03 role/chain verification | \`qualification.rs::verify_chain\` | principal collision, expiry and revocation tests below | Lane A exact-source/native receipt | required before acceptance claim | source implemented |
| EVID-01 principal independence | \`qualification.rs::verify_chain\` principal/key separation | \`one_principal_cannot_satisfy_two_independent_roles\` | Lane A exact-source and merge-native receipts | external \`IndependentDecisionReceiptV1\` | implemented; external decision pending |
| EVID-02 exact tree / expiry | exact candidate SQL binding + validity windows | \`target_append_and_query_are_exact_candidate_and_claim_class_bound\`; \`expired_candidate_evidence_is_not_supported\` | Lane A exact-source and merge-native receipts | external decision consumes exact candidate | implemented |
| EVID-03 corrupt payload / lineage after reopen | \`verify_qualification_evidence_rows\`, FK lineage, immutable triggers | \`corrupted_qualification_payload_fails_closed_after_reopen\` | Lane A exact-source/native receipt | independent reviewer consumes recovery evidence | implemented |
| EVID-04 claim-class substitution | enum + exact claim-class query predicate | fixture query returns data while hardware query is empty in \`target_append_and_query_are_exact_candidate_and_claim_class_bound\` | Lane A exact-source/native receipt | external decision cannot upgrade fixture class | implemented |
| INDEP-01 registered independent decision | \`codex-hepta-contracts::IndependentDecisionReceiptV1\`; \`append_independent_decision_receipt\` | \`independent_decision_projection_binds_authenticated_signing_identity\` | Lane A contract/evidence test receipt | distinct authorized reviewer signature | admission implemented; acceptance pending |
| REVOC-01 issuer revocation | \`append_issuer_key_revocation\`; persisted revocation lookup | \`durable_key_revocation_invalidates_previous_independent_evidence\` | Lane A exact-source/native receipt | external revocation head remains host input | implemented |
| PROD-01 authenticated product writer/reader/observer | \`codex-rs/ext/hepta-governance/src/state.rs\` | \`governance_product_host_composes_authenticated_writer_reader_and_terminal_observer\` | blocking Bazel CI for exact PR candidate | operator acceptance remains external | product composed |
| CKPT-01 rollback/replacement frontier | \`codex-rs/hepta-evidence/src/checkpoint.rs\`; \`CHECKPOINT_V1.md\` | \`external_checkpoint_rejects_complete_database_rollback\` | Lane A exact-source/native receipt | externally retained checkpoint | implementation complete; external retention required |
| DOC-01 registry/manual ownership consistency | \`docs/modules/kernel.evidence/TECHNICAL.md\` | development-docs / registry projection verifier | Hepta development documents CI | not applicable | aligned |
| EXACT-01 source + synthetic merge | \`.github/workflows/lane-a-foundation.yml\` | \`verify_lane_a_foundation.py\` + \`run_lane_a_native_qualification.sh\` | \`lane-a-source-native-<sha>\`, \`lane-a-merge-native-<sha>\` | consumed by independent reviewer | generated per candidate |
| ACCEPT-01 independent exact-candidate acceptance | \`qualification/kernel-evidence/INDEPENDENT_ACCEPTANCE.md\` | store rejects identity/digest/expiry mismatch | exact candidate receipts above | signed external \`IndependentDecisionReceiptV1\` | external gate open |
| RELEASE-01 operator/promotion/release separation | TECHNICAL section 15 / P0.9 external gates | authority nonclaims and denied-capability checks | repository CI does not grant these states | operator/promotion/release authorities | external gate open |

## Eighteen-field implementation packet

The module-execution dossier's eighteen fields map as follows for this closure
candidate. Exact commit/tree and CI run identities are supplied by Lane A
receipts rather than hard-coded into this document.

| Field | Repository-controlled binding |
| --- | --- |
| 1. source receipt | Lane A exact-source receipt |
| 2. guide digest | development-docs registry projection / exact TECHNICAL bytes |
| 3. source roots | \`codex-rs/hepta-evidence\` |
| 4. entrypoints | \`append_receipt\`, \`verify_chain\`, \`query_claim\`, independent-decision/revocation/checkpoint operations |
| 5. consumer callsites | \`codex-rs/ext/hepta-governance/src/state.rs\` |
| 6. host runtime identity | existing \`codex-hepta-governance::GovernanceState\` product extension |
| 7. binary/artifact digest | exact-source/native CI receipt |
| 8. configuration/body generation | immutable issuer certificate, trust-root and external revocation-head inputs |
| 9. physical state | \`hepta_evidence_2.sqlite\`, migration 0011 |
| 10. schema/migration | SQLx migration ledger 0001..0011 plus schema manifest |
| 11. writer fence | authenticated issuer binding + BEGIN IMMEDIATE + idempotency conflict |
| 12. terminal observer | registered \`terminal_observer\` role through GovernanceState |
| 13. revocation source | external certificate revocation head plus durable issuer/receipt revocations |
| 14. fault results | EVID-01..04, corruption/reopen and rollback checkpoint tests |
| 15. resource measurements | registered 256 KiB receipt / 64 asset / 256 edge / 512 result limits; measurements remain candidate CI/host evidence |
| 16. fallback | missing/conflicting/expired disposition; corruption and rollback fail closed |
| 17. rollback predecessor | external checkpoint frontier plus exact Git candidate predecessor |
| 18. external-gate disposition | independent acceptance, physical target/operator acceptance, trust-root ceremony, promotion and release remain external |

## Closure rule

Repository-controlled source completion requires the source and merge-candidate
execution receipts to pass for the exact PR candidate. Independent acceptance
can move to true only after a distinct authorized actor supplies and the store
admits the signed decision described in
\`qualification/kernel-evidence/INDEPENDENT_ACCEPTANCE.md\`. No repository edit
may substitute for that actor.
