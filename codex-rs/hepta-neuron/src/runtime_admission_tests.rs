//! Owner admission/recovery regressions; these use the existing durable stores.
use super::*;
use pretty_assertions::assert_eq;

#[test]
fn rejected_scope_does_not_leave_a_durable_pending_operation() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        fixture.operations(),
        native,
        scope(),
        /*max_records*/ 16,
        /*max_operations*/ 16,
        config,
        MemoryWitness::default(),
    ));
    let mut model = FakeModel::new();
    let mut wrong = input(1, Digest32::ZERO);
    wrong.subject_id = checked(StableId::new("another-subject"));
    assert_eq!(
        runtime.tick(&mut model, wrong).err(),
        Some(NeuronRuntimeError::Journal(JournalError::ContextMismatch))
    );
    assert_eq!(model.calls, 0);
    assert_eq!(checked(runtime.operations.pending()), None);
    checked(runtime.tick(&mut model, input(1, Digest32::ZERO)));
    assert_eq!(model.calls, 1);
}

#[test]
fn full_segment_rejects_before_model_or_prepare_and_can_roll_over() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        fixture.operations(),
        native,
        scope(),
        /*max_records*/ 1,
        /*max_operations*/ 16,
        config,
        MemoryWitness::default(),
    ));
    let mut model = FakeModel::new();
    let first = checked(runtime.tick(&mut model, input(1, Digest32::ZERO)));
    let second = input(2, first.tick.checkpoint_after);
    assert_eq!(
        runtime.tick(&mut model, second.clone()).err(),
        Some(NeuronRuntimeError::Journal(JournalError::Capacity))
    );
    assert_eq!(model.calls, 1);
    assert_eq!(checked(runtime.operations.pending()), None);
    checked(runtime.rollover(fixture.named_file("segment-2"), /*max_records*/ 1));
    checked(runtime.tick(&mut model, second));
    assert_eq!(model.calls, 2);
}

#[test]
fn bootstrapped_owner_reopens_before_its_first_tick() {
    for chain in [false, true] {
        let fixture = Fixture::new();
        let native = native_config();
        let config = runtime_config(&native);
        let witness = MemoryWitness::default();
        drop(checked(NeuronRuntime::bootstrap(
            fixture.file(),
            fixture.operations(),
            native.clone(),
            scope(),
            /*max_records*/ 16,
            /*max_operations*/ 16,
            config.clone(),
            witness.clone(),
        )));
        let result = if chain {
            NeuronRuntime::recover_chain_root(
                fixture.file(),
                fixture.operations(),
                native,
                scope(),
                /*max_records*/ 16,
                /*max_operations*/ 16,
                config,
                witness,
            )
        } else {
            NeuronRuntime::recover(
                fixture.file(),
                fixture.operations(),
                native,
                scope(),
                /*max_records*/ 16,
                /*max_operations*/ 16,
                config,
                witness,
            )
        };
        let mut recovered = checked(result);
        assert_eq!(checked(recovered.current_anchor()), None);
        let mut model = FakeModel::new();
        checked(recovered.tick(&mut model, input(1, Digest32::ZERO)));
        assert_eq!(model.calls, 1);
    }
}

struct CountingGuard {
    checks: usize,
    reject_at: usize,
    error: crate::NeuronAdmissionError,
}
impl crate::NeuronAdmissionGuard for CountingGuard {
    fn check(
        &mut self,
        _: &NeuronRuntimeConfigV1,
        _: &NeuronTickInputV1,
    ) -> Result<(), crate::NeuronAdmissionError> {
        self.checks += 1;
        if self.checks == self.reject_at {
            Err(self.error)
        } else {
            Ok(())
        }
    }
}

#[test]
fn revoked_cancelled_and_expired_admission_never_prepares_a_result() {
    use crate::NeuronAdmissionError;
    for error in [
        NeuronAdmissionError::Revoked,
        NeuronAdmissionError::Cancelled,
        NeuronAdmissionError::DeadlineExceeded,
    ] {
        for reject_at in [1, 2] {
            let fixture = Fixture::new();
            let native = native_config();
            let config = runtime_config(&native);
            let mut runtime = checked(NeuronRuntime::bootstrap(
                fixture.file(),
                fixture.operations(),
                native,
                scope(),
                /*max_records*/ 16,
                /*max_operations*/ 16,
                config,
                MemoryWitness::default(),
            ));
            let mut model = FakeModel::new();
            let mut guard = CountingGuard {
                checks: 0,
                reject_at,
                error,
            };
            assert_eq!(
                runtime
                    .tick_guarded(&mut model, input(1, Digest32::ZERO), &mut guard)
                    .err(),
                Some(NeuronRuntimeError::Admission(error))
            );
            assert_eq!(model.calls, reject_at - 1);
            assert_eq!(checked(runtime.current_anchor()), None);
            assert_eq!(checked(runtime.operations.is_empty()), true);
            checked(runtime.tick_guarded(&mut model, input(1, Digest32::ZERO), &mut guard));
        }
    }
}

#[test]
fn final_use_rejection_preserves_history_but_does_not_publish_success() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        fixture.operations(),
        native,
        scope(),
        /*max_records*/ 16,
        /*max_operations*/ 16,
        config,
        MemoryWitness::default(),
    ));
    let mut model = FakeModel::new();
    let request = input(1, Digest32::ZERO);
    let mut guard = CountingGuard {
        checks: 0,
        reject_at: 3,
        error: crate::NeuronAdmissionError::Revoked,
    };
    assert_eq!(
        runtime
            .tick_guarded(&mut model, request.clone(), &mut guard)
            .err(),
        Some(NeuronRuntimeError::Admission(
            crate::NeuronAdmissionError::Revoked
        ))
    );
    let stored = checked(runtime.operations.find_tick(&request.tick_id)).expect("committed result");
    assert_eq!(checked(runtime.operations.pending()), None);
    let retry = checked(runtime.tick_guarded(&mut model, request.clone(), &mut guard));
    assert_eq!(retry, stored.output);
    assert_eq!(model.calls, 1);
    guard.reject_at = guard.checks + 1;
    assert!(
        runtime
            .tick_guarded(&mut model, request, &mut guard)
            .is_err()
    );
    assert_eq!(model.calls, 1);
}

#[test]
fn lost_empty_journal_is_not_reinitialized_by_recovery() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let witness = MemoryWitness::default();
    drop(checked(NeuronRuntime::bootstrap(
        fixture.file(),
        fixture.operations(),
        native.clone(),
        scope(),
        /*max_records*/ 16,
        /*max_operations*/ 16,
        config.clone(),
        witness.clone(),
    )));
    checked(fs::write(fixture.0.join("journal"), []));
    assert_eq!(
        NeuronRuntime::recover(
            fixture.file(),
            fixture.operations(),
            native,
            scope(),
            /*max_records*/ 16,
            /*max_operations*/ 16,
            config,
            witness
        )
        .err(),
        Some(NeuronRuntimeError::Journal(
            JournalError::AcknowledgedHistoryMissing
        ))
    );
    assert_eq!(checked(fixture.file().metadata()).len(), 0);
}

#[test]
fn full_operation_store_rejects_before_model_execution() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        fixture.operations(),
        native,
        scope(),
        /*max_records*/ 16,
        /*max_operations*/ 1,
        config,
        MemoryWitness::default(),
    ));
    let mut model = FakeModel::new();
    let first = checked(runtime.tick(&mut model, input(1, Digest32::ZERO)));
    assert_eq!(
        runtime
            .tick(&mut model, input(2, first.tick.checkpoint_after))
            .err(),
        Some(NeuronRuntimeError::Operation(OperationStoreError::Capacity))
    );
    assert_eq!(model.calls, 1);
    assert_eq!(
        checked(runtime.tick(&mut model, input(1, Digest32::ZERO))),
        first
    );
}

#[test]
fn canonical_publication_requires_the_exact_completed_operation_receipt() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let witness = MemoryWitness::default();
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        fixture.operations(),
        native,
        scope(),
        /*max_records*/ 16,
        /*max_operations*/ 16,
        config,
        witness.clone(),
    ));
    let mut model = FakeModel::new();
    witness.fail_next_compare_and_swap();
    assert!(runtime.tick(&mut model, input(1, Digest32::ZERO)).is_err());
    let pending = checked(runtime.operations.pending()).expect("pending");
    assert!(
        runtime
            .canonical_checkpoint(&pending.output.tick, 1_900_000_000_000)
            .is_err()
    );
    let result = checked(runtime.tick(&mut model, input(1, Digest32::ZERO)));
    for field in ["identity", "confidence", "resource"] {
        let mut changed = result.tick.clone();
        match field {
            "identity" => changed.tick_id = checked(StableId::new("forged-tick")),
            "confidence" => changed.confidence_ppm ^= 1,
            "resource" => changed.resource_receipt.queue_age_micros += 1,
            _ => unreachable!(),
        }
        assert!(
            runtime
                .canonical_checkpoint(&changed, 1_900_000_000_000)
                .is_err()
        );
    }
    checked(runtime.canonical_checkpoint(&result.tick, 1_900_000_000_000));
    assert_eq!(
        checked(runtime.query_result(
            &result.tick.tick_id,
            checked(input(1, Digest32::ZERO).semantic_digest())
        )),
        Some(result)
    );
}

#[test]
fn owner_result_metadata_must_match_the_independently_replayed_native_receipt() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        fixture.operations(),
        native,
        scope(),
        /*max_records*/ 16,
        /*max_operations*/ 16,
        config,
        MemoryWitness::default(),
    ));
    let mut model = FakeModel::new();
    let result = checked(runtime.tick(&mut model, input(1, Digest32::ZERO)));
    let original = checked(runtime.operations.find_tick(&result.tick.tick_id)).expect("record");
    for field in ["clock", "error", "projection"] {
        let mut changed = original.clone();
        match field {
            "clock" => changed.sparse_tick.monotonic_micros += 1,
            "error" => changed.output.tick.prediction_error_q24 += 1,
            "projection" => changed.output.tick.resource_receipt.saturation_count += 1,
            _ => unreachable!(),
        }
        assert!(runtime.validate_committed_operation(&changed).is_err());
    }
    checked(runtime.rollover(fixture.named_file("next-segment"), /*max_records*/ 16));
    checked(runtime.validate_committed_operation(&original));
}
