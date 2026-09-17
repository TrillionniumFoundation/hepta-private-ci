# learning.plasticity production operations

This runbook applies to a selected host that composes `learning.plasticity`. It does not itself activate the module.

## Ownership

- Module owner: `learning-platform`.
- Architecture deputy: `architecture`.
- The selected host owns file-path enrollment, filesystem permissions, backup/restore, deletion, writer-fence issuance and the external anti-rollback anchor store.
- The external anchor MUST live in a rollback domain independent from the proposal-registry file and its ordinary backup/restore path.
- Evidence and evaluator verifiers MUST use registered trust roots and MUST fail closed on unknown producer, expired/revoked credential, scope mismatch or unverifiable receipt.

## Required safe telemetry

A composed host MUST emit aggregate counters and terminal events without raw model parameters, credentials or secret-bearing evidence payloads:

- proposal generation attempts/success/rejection by rejection class;
- candidate count and delta count histograms;
- trust-region rejection counts;
- evidence-verification rejection counts by evidence kind;
- independent-evaluator verification failures;
- durable append inserted/unchanged/conflict/capacity/indeterminate/poisoned counts;
- registry open anchored-success/anchor-mismatch/history-missing/corrupt/busy counts;
- current durable sequence and last acknowledged external-anchor sequence;
- topology proposal attempts/rejections; topology application MUST remain zero until a separately admitted application path exists.

Telemetry MUST use proposal/window identifiers or digests only where those identifiers are approved for operations logs. Evidence bodies and credentials MUST NOT be logged.

## Initial service objectives

These are operational guardrails for pilot qualification, not historical measurements:

- `proposal_generation_error_rate`: < 1% excluding explicit policy/trust-region rejections over a 15-minute window.
- `durable_append_indeterminate_rate`: 0 tolerated; any occurrence pages the owner and poisons/reopens the writer.
- `anchor_mismatch_count`: 0 tolerated; any occurrence is a security incident and blocks writes.
- `acknowledged_history_missing_count`: 0 tolerated after first external acknowledgement; any occurrence blocks writes.
- `registry_corrupt_count`: 0 tolerated; any occurrence blocks writes and preserves the original bytes for investigation.
- `evaluator_verification_bypass_count`: 0 tolerated; no bypass mode is allowed on the composed product path.
- `evidence_verification_bypass_count`: 0 tolerated; no bypass mode is allowed on the composed product path.
- `topology_runtime_mutation_count`: 0 until topology application is separately implemented, admitted and accepted.

A selected host MAY choose stricter thresholds. Relaxation requires architecture review and a new host profile revision.

## Alerting

Page immediately on:

- `AnchorMismatch`, `AcknowledgedHistoryMissing`, `Corrupt`, `Indeterminate` or `Poisoned`;
- any externally acknowledged sequence greater than the locally recovered sequence;
- any use of an expired/revoked evidence or evaluator credential that reaches proposal construction;
- any attempt to use an unanchored reopen in a production caller;
- any runtime parameter/topology mutation attributable to this module.

Create a ticket and stop new generation on sustained capacity pressure > 90%, repeated registry `Busy`, or generator rejection caused by configuration drift.

## Startup procedure

1. Resolve the registered host profile, registry scope and writer fence.
2. If this is first enrollment, create a new file with exclusive creation and initialize `ProductionProposalRegistry::initialize_new`.
3. Otherwise read the independently retained external anchor and call `ProductionProposalRegistry::open_anchored`.
4. Refuse startup if the anchor is missing after prior acknowledgement, mismatched, ahead of local history, corrupt or associated with a different scope/fence/capacity header.
5. Load trust roots for evidence producers and independent evaluators.
6. Verify revocation/freshness sources are available before enabling proposal generation.
7. Run a no-change dry qualification before accepting normal generation traffic.

## Append and acknowledgement procedure

1. Generate candidates from bounded learning signals; the composed caller MUST NOT supply a preconstructed final candidate set.
2. Authenticate every required lineage/evidence digest and every parameter evidence digest.
3. Authenticate evaluator identity and independence.
4. Construct and verify the proposal.
5. Append using the exact predecessor frame digest.
6. Persist the returned frame anchor in the independent anchor store.
7. Only after external anchor acknowledgement may the host report the durable proposal as acknowledged.
8. Proposal acknowledgement MUST NOT be interpreted as selection, acceptance, activation, training, installation, promotion or release.

## Incident recovery

For `Indeterminate`/`Poisoned`:

1. Stop the writer and preserve logs/bytes.
2. Reopen only with the last externally acknowledged anchor.
3. Let the registry repair only an incomplete suffix after anchor reconciliation.
4. Replay the exact proposal; identical semantics may return `Unchanged`.
5. If reconciliation fails, quarantine the file and do not create a replacement at the same logical scope without explicit recovery authorization.

For `AnchorMismatch` or missing acknowledged history:

1. Treat as possible rollback/replacement/tamper.
2. Freeze all writes for the scope.
3. Preserve the suspect file and external anchor record.
4. Compare backup/restore and fence-issuance audit trails.
5. Recovery requires an independently reviewed predecessor and a new writer fence; never silently lower the external anchor.

## Capacity and retirement

- Registry maximum remains bounded by native limits.
- At 90% capacity, stop admitting new windows unless retention/archival policy has been explicitly approved.
- Retirement must preserve proposal and anchor interpretability for the required audit horizon.
- Deletion must cover file, indexes, caches and backups according to the owning retention policy and must not permit resurrection of revoked history.
