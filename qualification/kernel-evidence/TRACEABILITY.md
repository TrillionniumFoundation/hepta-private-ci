# kernel.evidence closure traceability

This matrix is the canonical human-readable closure view for the current
`kernel.evidence` source candidate. Source/test references prove implementation
presence; GitHub Actions execution records prove only that exact commands ran
successfully on a bound object; the final column remains external when true
independence cannot be manufactured by repository CI.

| Requirement | Source | Test / oracle | Exact execution receipt | Independent receipt |
|---|---|---|---|---|
| Native `append_receipt` authenticates exact envelope and atomically advances replay + append | `codex-rs/hepta-evidence/src/qualification.rs`, migration `0011_qualification_evidence.sql` | `exact_authenticated_retry_is_idempotent_but_payload_drift_conflicts`, `replay_sequence_is_consumed_atomically_with_insert` | `kernel-evidence-source-<SHA>` / `evidence-tests.json` | external acceptance required |
| `query_claim` is exact candidate/tree + class and bounded | `qualification.rs` | EVID-02, EVID-04 | same source/merge artifact | external semantic review required |
| `verify_chain` enforces expiry, lineage, role coverage and distinct principals | `qualification.rs` | EVID-01..04, correction/revocation test | same source/merge artifact | external architecture/durability review required |
| `IndependentDecisionReceiptV1` binds candidate, principal, key identity, evidence set, role and expiry | `qualification.rs` | `independent_decision_binds_candidate_principal_key_role_and_evidence_set` | `evidence-tests.json` | **must be supplied by an external principal; CI cannot self-sign** |
| Canonical row/projection corruption fails closed on reopen | `qualification.rs`, `store.rs`, `schema_validation.rs` | EVID-03 payload/projection + broken predecessor | `evidence-tests.json` | durable-role review required |
| Product caller/writer is real Agentd composition, not a library-only seam | `hepta-agentd/src/evidence_host.rs`, `evidence_trust.rs`, control/client routing | `tests/kernel_evidence_product.rs` | `agentd-product-test.json` | external product/physical review still required for activation |
| Current revocation is checked immediately before physical evidence append | `evidence_trust.rs`, `evidence_host.rs` | product test rewrites issuer as revoked and requires server rejection | `agentd-product-test.json` | security review required |
| Terminal observation can be recorded by a separate terminal-observer principal | Agentd evidence trust/host + qualification role model | product test persists provider-effect terminal observation from third principal | `agentd-product-test.json` | real provider terminal evidence remains environment-specific |
| Migration/schema/immutable lineage is closed-world and reopen-verified | migration `0001..0011`, `schema_validation.rs`, Lane-A verifier | Lane-A truth verifier + native store tests | `lane-a-truth.json`, dedicated workflow artifacts | independent durability review |
| Exact PR head is tested | dedicated workflow source-head job + `hepta_ci_exec.py` | evidence package, Agentd product test, docs/Lane-A gates | `kernel-evidence-source-<SOURCE_SHA>` | external exact-candidate decision required |
| Deterministic synthetic merge is tested | `.github/actions/hepta-synthetic-merge` + dedicated workflow | same command set on two-parent merge | `kernel-evidence-merge-<MERGE_SHA>` | external decision binds final merge candidate where required |
| Backup/restore never treats a valid stale SQLite image as fresh evidence | `RECOVERY_FRONTIER_V1.md` | required fault matrix specified there | no production receipt until a concrete external backend is qualified | external durability/operator receipt required |
| Complete-database replacement is detectable against an independent rollback domain | `RECOVERY_FRONTIER_V1.md` | replacement/behind-frontier fault required | external-backend qualification pending | external durability/operator receipt required |
| Manual TECHNICAL contract/data truth matches canonical generated registry projection | `docs/modules/kernel.evidence/TECHNICAL.md` | docs closed-world verifier | `docs.json` | documentation/architecture review required |

## Claim boundary

On this PR the intended repository-controlled closure is:

- target/native qualification contract: source implemented;
- named Agentd product caller/writer: source composed and product-tested;
- terminal-observer role/path: source implemented and product-tested;
- exact-source + synthetic-merge execution: required by workflow before merge;
- external monotonic checkpoint backend: specified, not activated;
- independent external acceptance: not self-issued and remains pending;
- operator acceptance, promotion and release: unchanged external gates.

A green CI run does not change the last four bullets by inference.
