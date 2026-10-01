use super::*;

use pretty_assertions::assert_eq;

fn assert_context_rejections_preserve_state(
    runtime: &mut NeuronRuntime<MemoryWitness>,
    witness: &MemoryWitness,
    fixture: &Fixture,
    model: &mut FakeModel,
) {
    let anchor = checked(runtime.current_anchor()).expect("committed checkpoint");
    let before_journal = checked(fs::read(fixture.0.join("journal")));
    let before_witness = checked(witness.current());
    let before_calls = model.calls;
    let before_writes = witness.compare_and_swap_calls.load(Ordering::SeqCst);
    let mut equal_clock = input(/*sequence*/ 2, anchor.checkpoint_digest);
    equal_clock.monotonic_time_micros = 1000;
    let mut older_clock = equal_clock.clone();
    older_clock.monotonic_time_micros = 999;
    let mut different_body = input(/*sequence*/ 2, anchor.checkpoint_digest);
    different_body.body_generation = Some(2);
    for (rejected, error) in [
        (equal_clock, crate::SparseError::Clock),
        (older_clock, crate::SparseError::Clock),
        (different_body, crate::SparseError::ScopeDrift),
    ] {
        assert_eq!(
            runtime.tick(model, rejected).err(),
            Some(NeuronRuntimeError::Journal(JournalError::Mechanism(error)))
        );
        assert_eq!(model.calls, before_calls);
        assert_eq!(checked(fs::read(fixture.0.join("journal"))), before_journal);
        assert_eq!(checked(witness.current()), before_witness);
        assert_eq!(
            witness.compare_and_swap_calls.load(Ordering::SeqCst),
            before_writes
        );
        assert!(runtime.pending.is_none());
    }
}

#[test]
fn body_and_clock_drift_are_rejected_before_model_execution_and_after_recovery() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let witness = MemoryWitness::default();
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        native.clone(),
        scope(),
        /*max_records*/ 4,
        config.clone(),
        witness.clone(),
    ));
    let mut model = FakeModel::new();
    let first = checked(runtime.tick(&mut model, input(/*sequence*/ 1, Digest32::ZERO)));
    assert_context_rejections_preserve_state(&mut runtime, &witness, &fixture, &mut model);
    let anchor = checked(runtime.current_anchor()).expect("committed checkpoint");
    drop(runtime);
    let mut recovered = checked(NeuronRuntime::recover(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 4,
        config,
        anchor,
        witness.clone(),
    ));
    assert_context_rejections_preserve_state(&mut recovered, &witness, &fixture, &mut model);
    checked(recovered.tick(
        &mut model,
        input(/*sequence*/ 2, first.tick.checkpoint_after),
    ));
    assert_eq!(model.calls, 2);
}

fn assert_checkpoint_saturation_is_bound(
    runtime: &NeuronRuntime<MemoryWitness>,
    committed: &NeuronTickReceiptV1,
) {
    let published = checked(runtime.canonical_checkpoint(committed, /*expires_unix_ms*/ 10_000));
    let mut forged = committed.clone();
    forged.resource_receipt.saturation_count += 1;
    assert_eq!(
        runtime.canonical_checkpoint(&forged, /*expires_unix_ms*/ 10_000),
        Err(crate::NeuronProtocolError::BindingMismatch(
            "checkpoint lineage"
        ))
    );
    assert_eq!(
        checked(runtime.canonical_checkpoint(committed, /*expires_unix_ms*/ 10_000)),
        published
    );
}

#[test]
fn canonical_checkpoint_binds_replayed_saturation_count_without_changing_the_journal() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let witness = MemoryWitness::default();
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        native.clone(),
        scope(),
        /*max_records*/ 4,
        config.clone(),
        witness.clone(),
    ));
    let output =
        checked(runtime.tick(&mut FakeModel::new(), input(/*sequence*/ 1, Digest32::ZERO)));
    let journal = checked(fs::read(fixture.0.join("journal")));
    assert_checkpoint_saturation_is_bound(&runtime, &output.tick);
    let anchor = checked(runtime.current_anchor()).expect("committed checkpoint");
    drop(runtime);
    let recovered = checked(NeuronRuntime::recover(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 4,
        config,
        anchor,
        witness,
    ));
    assert_checkpoint_saturation_is_bound(&recovered, &output.tick);
    assert_eq!(checked(fs::read(fixture.0.join("journal"))), journal);
}

#[test]
fn lost_witness_success_response_returns_the_cached_output_without_another_cas() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let witness = MemoryWitness::default();
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 4,
        config,
        witness.clone(),
    ));
    witness
        .lose_next_response
        .store(/*val*/ true, Ordering::SeqCst);
    let mut model = FakeModel::new();
    let request = input(/*sequence*/ 1, Digest32::ZERO);
    let error = runtime.tick(&mut model, request.clone()).err();
    let pending = runtime
        .pending
        .as_ref()
        .expect("pending acknowledgement")
        .clone();
    assert_eq!(
        error,
        Some(NeuronRuntimeError::WitnessAfterCommit {
            anchor: pending.next,
            error: WitnessStoreError::Indeterminate,
        })
    );
    assert_eq!(checked(witness.current()), Some(pending.next));
    let journal = checked(fs::read(fixture.0.join("journal")));
    assert_eq!(checked(runtime.tick(&mut model, request)), pending.output);
    assert_eq!(model.calls, 1);
    assert_eq!(witness.compare_and_swap_calls.load(Ordering::SeqCst), 1);
    assert_eq!(checked(fs::read(fixture.0.join("journal"))), journal);
    assert!(runtime.pending.is_none());
    checked(runtime.canonical_checkpoint(&pending.output.tick, /*expires_unix_ms*/ 10_000));
    checked(runtime.tick(
        &mut model,
        input(/*sequence*/ 2, pending.next.checkpoint_digest),
    ));
    assert_eq!(model.calls, 2);
    assert_eq!(witness.compare_and_swap_calls.load(Ordering::SeqCst), 2);
}

#[test]
fn pending_retry_rejects_foreign_or_ahead_witness_and_recovers_only_its_exact_anchor() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let witness = MemoryWitness::default();
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        native,
        scope(),
        /*max_records*/ 4,
        config,
        witness.clone(),
    ));
    let mut model = FakeModel::new();
    let first = checked(runtime.tick(&mut model, input(/*sequence*/ 1, Digest32::ZERO)));
    witness.fail_next_compare_and_swap();
    let request = input(/*sequence*/ 2, first.tick.checkpoint_after);
    assert!(matches!(
        runtime.tick(&mut model, request.clone()),
        Err(NeuronRuntimeError::WitnessAfterCommit { .. })
    ));
    let pending = runtime
        .pending
        .as_ref()
        .expect("pending acknowledgement")
        .clone();
    let journal = checked(fs::read(fixture.0.join("journal")));
    let before_writes = witness.compare_and_swap_calls.load(Ordering::SeqCst);
    for foreign in [
        Some(JournalAnchor {
            sequence: pending.next.sequence,
            checkpoint_digest: Digest32::of_bytes(b"foreign checkpoint"),
        }),
        Some(JournalAnchor {
            sequence: pending.next.sequence + 1,
            checkpoint_digest: Digest32::of_bytes(b"ahead checkpoint"),
        }),
        None,
    ] {
        *checked(witness.current.lock()) = foreign;
        assert_eq!(
            runtime.tick(&mut model, request.clone()).err(),
            Some(NeuronRuntimeError::WitnessAfterCommit {
                anchor: pending.next,
                error: WitnessStoreError::Conflict,
            })
        );
        assert_eq!(checked(witness.current()), foreign);
        assert!(runtime.pending.is_some());
    }
    witness.fail_current.store(/*val*/ true, Ordering::SeqCst);
    assert_eq!(
        runtime.tick(&mut model, request.clone()).err(),
        Some(NeuronRuntimeError::WitnessAfterCommit {
            anchor: pending.next,
            error: WitnessStoreError::Unavailable,
        })
    );
    witness.fail_current.store(/*val*/ false, Ordering::SeqCst);
    assert_eq!(model.calls, 2);
    assert_eq!(
        witness.compare_and_swap_calls.load(Ordering::SeqCst),
        before_writes
    );
    assert_eq!(checked(fs::read(fixture.0.join("journal"))), journal);
    *checked(witness.current.lock()) = pending.expected;
    assert_eq!(checked(runtime.tick(&mut model, request)), pending.output);
    assert_eq!(checked(witness.current()), Some(pending.next));
    assert_eq!(model.calls, 2);
    assert_eq!(
        witness.compare_and_swap_calls.load(Ordering::SeqCst),
        before_writes + 1
    );
    assert_eq!(checked(fs::read(fixture.0.join("journal"))), journal);
    assert!(runtime.pending.is_none());
}
