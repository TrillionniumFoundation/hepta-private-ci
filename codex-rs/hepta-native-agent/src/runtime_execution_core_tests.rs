use codex_execution_core::CheckedStartHandleV1;
use codex_execution_core::Currentness;
use codex_execution_core::EXECUTION_SCHEMA_VERSION;
use codex_execution_core::ExecutionBinding;
use codex_execution_core::ExecutionClass;
use codex_execution_core::ExecutionError;
use codex_execution_core::ExecutionIntent;
use codex_execution_core::ExecutionJournal;
use codex_execution_core::ExecutionRecord;
use codex_execution_core::ExecutionReservation;
use codex_execution_core::ExecutionStarted;
use codex_execution_core::ExecutionVerifier;
use codex_execution_core::FinalUse;
use codex_hepta_types::CellExecutionIntentV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::ExecutionIntentKindV1;
use codex_hepta_types::FinalPayloadDigestV1;
use codex_hepta_types::Generation;
use codex_hepta_types::RuntimeToolIntentV1;
use codex_hepta_types::StableId;

use super::canonical_runtime_intent_v1;

fn fixture() -> (ExecutionBinding, RuntimeToolIntentV1) {
    let generation = Generation::new(3).unwrap();
    let organ = StableId::new("organ:build").unwrap();
    let final_payload = Digest32::of_bytes(b"compiled process request with host and limits");
    let operation = RuntimeToolIntentV1 {
        cell: CellExecutionIntentV1 {
            operation_id: StableId::new("operation:build-1").unwrap(),
            cell_id: StableId::new("cell:compile").unwrap(),
            organ_id: organ.clone(),
            generation,
            kind: ExecutionIntentKindV1::RuntimeTool,
            codex_binding: None,
            input_digest: Digest32::of_bytes(b"model tool arguments"),
            final_payload: FinalPayloadDigestV1 {
                scope_id: organ,
                generation,
                payload_kind: StableId::new("runtime.process-start.v1").unwrap(),
                digest: final_payload,
            },
            deadline_ms: 4_000,
        },
        tool_id: StableId::new("runtime.process_start").unwrap(),
        arguments_digest: final_payload,
        idempotency_key: StableId::new("operation:build-1").unwrap(),
        host_scope: StableId::new("host:main").unwrap(),
    };
    let binding = ExecutionBinding {
        schema_version: EXECUTION_SCHEMA_VERSION,
        run_id: "run-1".into(),
        turn_id: "turn-1".into(),
        cell_id: Some(operation.cell.cell_id.as_str().to_owned()),
        organ_id: None,
        operation_id: operation.cell.operation_id.as_str().to_owned(),
        principal: "owner:original".into(),
        objective_digest: Digest32::of_bytes(b"objective").to_string(),
        policy_digest: Digest32::of_bytes(b"policy").to_string(),
        candidate_digest: operation.intent_digest().to_string(),
        host: operation.host_scope.as_str().to_owned(),
        generation: generation.get(),
        idempotency_key: operation.idempotency_key.as_str().to_owned(),
        predecessor: None,
        currentness: Currentness::Current,
        final_use: FinalUse::NotGranted,
        rollback_reference: Some("rollback:original".into()),
    };
    (binding, operation)
}

#[test]
fn projection_preserves_owner_binding_and_compiled_payload_without_a_grant() {
    let (binding, operation) = fixture();
    let expected = ExecutionIntent {
        binding: binding.clone(),
        class: ExecutionClass::NonDestructiveBuild,
        payload_digest: operation.cell.final_payload.digest.to_string(),
    };
    let projected =
        canonical_runtime_intent_v1(binding, &operation, ExecutionClass::NonDestructiveBuild)
            .unwrap();
    assert_eq!(projected, expected);
    assert_ne!(
        projected.payload_digest,
        operation.cell.input_digest.to_string()
    );
    assert_eq!(
        ExecutionRecord::ExecutionIntent(projected)
            .digest()
            .unwrap(),
        ExecutionRecord::ExecutionIntent(expected).digest().unwrap()
    );
}

#[test]
fn organ_projection_retains_the_cell_in_the_complete_candidate_digest() {
    let (mut binding, operation) = fixture();
    binding.cell_id = None;
    binding.organ_id = Some(operation.cell.organ_id.as_str().to_owned());
    assert!(
        canonical_runtime_intent_v1(binding.clone(), &operation, ExecutionClass::FileRead,).is_ok()
    );
    let mut other_cell = operation;
    other_cell.cell.cell_id = StableId::new("cell:another").unwrap();
    assert!(canonical_runtime_intent_v1(binding, &other_cell, ExecutionClass::FileRead).is_err());
}

#[test]
fn projection_rejects_rebound_owner_correlations() {
    let (original, operation) = fixture();
    let mut mutations = Vec::new();
    let mut changed = original.clone();
    changed.operation_id = "operation:another".into();
    mutations.push(changed);
    let mut changed = original.clone();
    changed.cell_id = Some("cell:another".into());
    mutations.push(changed);
    let mut changed = original.clone();
    changed.host = "host:other".into();
    mutations.push(changed);
    let mut changed = original.clone();
    changed.generation += 1;
    mutations.push(changed);
    let mut changed = original.clone();
    changed.idempotency_key = "operation:retry".into();
    mutations.push(changed);
    let mut changed = original.clone();
    changed.candidate_digest = operation.cell.final_payload.digest.to_string();
    mutations.push(changed);
    let mut changed = original.clone();
    changed.currentness = Currentness::Stale;
    mutations.push(changed);
    let mut changed = original.clone();
    changed.currentness = Currentness::Unknown;
    mutations.push(changed);
    let mut changed = original;
    changed.organ_id = Some(operation.cell.organ_id.as_str().to_owned());
    mutations.push(changed);
    for binding in mutations {
        assert!(
            canonical_runtime_intent_v1(binding, &operation, ExecutionClass::FileRead).is_err()
        );
    }
}

#[test]
fn projection_rejects_unrepresented_source_drift_and_payload_substitution() {
    let (binding, original) = fixture();
    let mut mutations = Vec::new();
    let mut changed = original.clone();
    changed.tool_id = StableId::new("runtime.another_tool").unwrap();
    mutations.push(changed);
    let mut changed = original.clone();
    changed.cell.deadline_ms += 1;
    mutations.push(changed);
    let mut changed = original.clone();
    changed.cell.input_digest = Digest32::of_bytes(b"other model arguments");
    mutations.push(changed);
    let mut changed = original.clone();
    changed.cell.final_payload.payload_kind = StableId::new("runtime.another-payload.v1").unwrap();
    mutations.push(changed);
    // The substituted request is internally valid. Only the commitment to the
    // complete original intent prevents rebinding it under the old admission.
    let mut changed = original.clone();
    changed.arguments_digest = Digest32::of_bytes(b"different compiled request");
    changed.cell.final_payload.digest = changed.arguments_digest;
    changed.validate().unwrap();
    mutations.push(changed);
    let mut changed = original.clone();
    changed.cell.organ_id = StableId::new("organ:other").unwrap();
    changed.cell.final_payload.scope_id = changed.cell.organ_id.clone();
    mutations.push(changed);
    let mut changed = original;
    changed.arguments_digest = changed.cell.input_digest;
    mutations.push(changed);
    for operation in mutations {
        assert!(
            canonical_runtime_intent_v1(binding.clone(), &operation, ExecutionClass::FileRead,)
                .is_err()
        );
    }
}

#[test]
fn projected_durable_intent_does_not_become_a_checked_start_without_final_use() {
    struct UnexpectedVerifier;
    impl ExecutionVerifier for UnexpectedVerifier {
        fn verify_start(
            &self,
            _: &ExecutionReservation,
            _: &ExecutionStarted,
            _: ExecutionClass,
        ) -> Result<(), ExecutionError> {
            panic!("a missing FinalUse must be rejected before a verifier can authorize a start");
        }
    }

    let (binding, operation) = fixture();
    let projected =
        canonical_runtime_intent_v1(binding.clone(), &operation, ExecutionClass::DurableProcess)
            .unwrap();
    assert_eq!(projected.binding.final_use, FinalUse::NotGranted);
    let mut journal = ExecutionJournal::new();
    let intent_digest = journal
        .append(ExecutionRecord::ExecutionIntent(projected))
        .unwrap();
    let mut reserved_binding = binding.clone();
    reserved_binding.predecessor = Some(intent_digest);
    let reservation = ExecutionReservation {
        binding: reserved_binding,
        lease_digest: Digest32::of_bytes(b"qualification reservation reference").to_string(),
        expires_at_unix_ms: 2_000,
    };
    let reservation_digest = journal
        .append(ExecutionRecord::ExecutionReservation(reservation))
        .unwrap();
    let mut started_binding = binding;
    started_binding.predecessor = Some(reservation_digest.clone());
    let started = ExecutionStarted {
        binding: started_binding,
        reservation_digest,
        approval_receipt_digest: None,
        started_at_unix_ms: 1_000,
    };
    assert!(matches!(
        CheckedStartHandleV1::admit(&mut journal, started, &UnexpectedVerifier),
        Err(ExecutionError::AuthorizationDenied)
    ));
    assert_eq!(journal.events().len(), 2);
}
