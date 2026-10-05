# kernel.evidence integration guide

## Library composition

Use typed `codex_hepta_evidence` APIs. Do not construct digest/value pairs
independently and do not bypass verified trust capabilities. Qualification
writers use `QualificationEvidenceStore`; recovery callers use V2 frontier,
backend and acceptance types. `classify_frontier_merge` must run before any
frontier write or external effect. A `RepairRequired` result is not permission;
it requires a valid `FrontierRepairAuthorizationV1` for the exact transition.

## Agentd composition

Development and production profiles are explicit and non-degradable. Production
requires owner-controlled issuer and signer trust, exact source and merge
receipts, governed executable identity, backup publication/restore binding,
external backend identity and the current accepted frontier. Missing, stale,
revoked or mismatched inputs enter `recovery_required`; there is no compatibility
fallback.

## Publication sequence

1. Reload current owner controls and trust.
2. Read the accepted predecessor from authenticated external history.
3. Prepare one durable fenced batch from one authenticated database snapshot.
4. Validate the proposed frontier and classify the transition.
5. Verify signatures, freshness, source/build/qualification and backup bindings.
6. Persist the exact dispatch identity before external CAS.
7. CAS the strict successor or recover its durable acknowledgement.
8. Revalidate authority after external I/O.
9. Atomically acknowledge the same batch/frontier locally.
10. Leave unknown outcomes indeterminate for a newly authorized reconciler.

## Readiness integration

`.github/workflows/kernel-evidence-readiness.yml` runs exact-source and
deterministic-merge suites, produces named crash receipts and emits one
`READINESS_MANIFEST.json`. Consumers must verify all hashes and candidate IDs;
they must not parse historical prose or aggregate receipts from different SHAs.
A main-branch post-merge run is required before a real merge can be considered.
