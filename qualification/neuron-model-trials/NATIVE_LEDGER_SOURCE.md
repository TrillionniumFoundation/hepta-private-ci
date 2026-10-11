# Native LedgerWriter-bound Neuron trial source handoff

This additive entrypoint is **diagnostic and read-only**. It does not create a
second Ledger writer, model runner, independent Evaluator, objective, or
promotion path.

The existing `codex_hepta_learning_ledger::LedgerWriter` owns the durable event
log, root-activated trust and independently retained commit witness. To build a
Neuron trial source join, an approved owner must retain four existing native
values from the original signed data freeze:

1. `LedgerSnapshot` actually read at freeze (not a reconstructed digest).
2. `DatasetFreezePlanV2` used at freeze.
3. Original `SignedLearningEvidenceV1` with the Evaluator role.
4. `DatasetSnapshotReceiptV3` returned by `LedgerWriter::freeze_dataset`.

Then use the **same current owner** to call:

```rust,ignore
let source = ledger.read_neuron_trial_source_v1(
    &frozen_snapshot,
    &freeze_plan,
    &evaluator_freeze_signature,
    &dataset_receipt,
    now,
)?;
assert!(source.validate_integrity());
// Only metadata: source.terminal_joins has canonical decision/outcome
// record IDs and event digests, not the observer's private labels.
```

The API checks that the frozen snapshot is a valid prefix of the *current*
ledger, that the current ledger head has an independently acknowledged witness,
that the source signature verifies using the **owner's** activated Evaluator
trust, and that the issued frozen receipt exactly equals a recomputation from
that frozen snapshot and verified actor. It then calls the owner's existing
`read_dataset_records` to revalidate active source membership against current
corrections, revocations and unlearning before joining authenticated V2 Decision
and Outcome events. Pending and censored episodes remain explicit exclusions.

The result is a digest-bound diagnostic with `AuthorityPosture::DENY_ALL`.
It never exports terminal reward values, raw questions, correct answers,
credentials or private source text to an inference worker. No caller-supplied
JSON event list can substitute for the native durable read. The result's
`diagnostic_digest` is an integrity checksum, **not** an independent signature
or proof of production data collection.

### Remaining independently owned gates

- **Observation Owner:** authorize and bind the actual question/state/features
  and permissible source uses to these native event identities. Ledger event
  hashes cannot reconstruct private text.
- **Production Cell Owner:** capture the *actually selected* no-change policy,
  current generation, model/weight or deterministic code identity, route,
  checkpoint and feature/runtime receipts. Laya is only an external A/B arm.
- **Evaluator + Observer:** join genuine terminal labels in private storage;
  freeze a plan before two *elapsed* future windows; use native
  `ProductEvaluationRunnerV1` and signed `LongitudinalTimeEvidenceV1`.
- **Operator/Authority:** independently verify target-host source access,
  revocation/currentness, recovery/fences, NDU net gain and production choice.

The new native method does not claim it has these external inputs and cannot
select, canary, promote, release, dispatch effects or make a self-certified
longitudinal learning claim. Unit tests use synthetic, locally signed facts,
not production data.
