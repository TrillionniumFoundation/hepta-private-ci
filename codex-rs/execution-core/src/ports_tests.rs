//! Source-only contract tests; no physical model, tool or FinalUse authority.

use super::ports::*;
use super::*;

fn dig(n: u8) -> String {
    format!("{n:064x}")
}

fn binding() -> ExecutionBinding {
    ExecutionBinding {
        schema_version: EXECUTION_SCHEMA_VERSION,
        run_id: "run-abc".into(),
        turn_id: "turn-abc".into(),
        cell_id: Some("cell-abc".into()),
        organ_id: None,
        operation_id: "operation-abc".into(),
        principal: "agent-abc".into(),
        objective_digest: dig(1),
        policy_digest: dig(2),
        candidate_digest: dig(3),
        host: "host-abc".into(),
        generation: 1,
        idempotency_key: "idem-abc".into(),
        predecessor: None,
        currentness: Currentness::Current,
        final_use: FinalUse::NotGranted,
        rollback_reference: Some("rollback-abc".into()),
    }
}

struct Deny;

impl ExecutionVerifier for Deny {
    fn verify_start(
        &self,
        _reservation: &ExecutionReservation,
        _started: &ExecutionStarted,
        _class: ExecutionClass,
    ) -> Result<(), ExecutionError> {
        Err(ExecutionError::AuthorizationDenied)
    }
}

fn prepared() -> (ExecutionJournal, ExecutionStarted) {
    let mut journal = ExecutionJournal::new();
    let original = binding();
    let head = journal
        .append(ExecutionRecord::ExecutionIntent(ExecutionIntent {
            binding: original.clone(),
            class: ExecutionClass::FileRead,
            payload_digest: dig(4),
        }))
        .unwrap();
    let mut reserved_binding = original.clone();
    reserved_binding.predecessor = Some(head);
    let reservation = ExecutionReservation {
        binding: reserved_binding,
        lease_digest: dig(5),
        expires_at_unix_ms: 200,
    };
    let reservation_digest = ExecutionRecord::ExecutionReservation(reservation.clone())
        .digest()
        .unwrap();
    let head = journal
        .append(ExecutionRecord::ExecutionReservation(reservation))
        .unwrap();
    let mut started_binding = original;
    started_binding.predecessor = Some(head);
    (journal, ExecutionStarted {
        binding: started_binding,
        reservation_digest,
        approval_receipt_digest: None,
        started_at_unix_ms: 100,
    })
}

#[test]
fn checked_start_cannot_be_forged_by_serialized_claim_or_denied_verifier() {
    let (mut journal, started) = prepared();
    assert!(matches!(
        CheckedStartHandleV1::admit(&mut journal, started, &Deny),
        Err(ExecutionError::AuthorizationDenied)
    ));
    assert_eq!(journal.events().len(), 2);
}

#[test]
fn model_request_and_observation_preserve_exact_binding() {
    let request = ModelInvocationV1 {
        binding: binding(),
        model_artifact_digest: dig(10),
        input_digest: dig(11),
        max_input_tokens: 1024,
        max_output_tokens: 128,
        deadline_unix_ms: 100,
    };
    let receipt = ModelObservationV1 {
        request_digest: request.digest().unwrap(),
        model_artifact_digest: dig(10),
        status: PortTerminal::Succeeded,
        output_digest: Some(dig(12)),
        input_tokens: 300,
        output_tokens: 25,
        provider_receipt_digest: Some(dig(13)),
    };
    assert_eq!(receipt.validate_against(&request), Ok(()));
    let mut bad = receipt.clone();
    bad.output_tokens = 129;
    assert!(bad.validate_against(&request).is_err());
    bad = receipt;
    bad.provider_receipt_digest = None;
    assert!(bad.validate_against(&request).is_err());
}

#[test]
fn step_budget_cannot_be_reopened_by_model_claim() {
    let request = AgentStepRequestV1 {
        binding: binding(),
        step: 3,
        max_steps: 4,
        state_digest: dig(20),
        deadline_unix_ms: 200,
    };
    let response = AgentStepObservationV1 {
        request_digest: request.digest().unwrap(),
        disposition: AgentStepDisposition::ProposeTool,
        next_state_digest: Some(dig(21)),
        action_digest: Some(dig(23)),
        observation_digest: dig(22),
    };
    assert!(response.validate_against(&request).is_err());
    let response = AgentStepObservationV1 {
        disposition: AgentStepDisposition::Completed,
        next_state_digest: None,
        action_digest: None,
        ..response
    };
    assert_eq!(response.validate_against(&request), Ok(()));
    let missing_action = AgentStepObservationV1 {
        disposition: AgentStepDisposition::InvokeModel,
        next_state_digest: Some(dig(21)),
        action_digest: None,
        ..response
    };
    assert!(missing_action.validate_against(&AgentStepRequestV1 {
        step: 1,
        ..request
    }).is_err());
}

#[test]
fn ports_are_object_safe_for_runtime_backend_selection() {
    struct Unavailable;
    impl ModelPort for Unavailable {
        fn infer<'a>(&'a self, _: &'a CheckedModelInvocationV1) -> PortFuture<'a, ModelObservationV1> {
            Box::pin(async { Err(PortError::Unavailable) })
        }
    }
    impl ExecutionPort for Unavailable {
        fn dispatch<'a>(&'a self, _: &'a CheckedStartHandleV1) -> PortFuture<'a, ExecutionObservationV1> {
            Box::pin(async { Err(PortError::Denied) })
        }
        fn cancel<'a>(&'a self, _: &'a ExecutionBinding) -> PortFuture<'a, ExecutionObservationV1> {
            Box::pin(async { Err(PortError::Indeterminate) })
        }
        fn reconcile<'a>(&'a self, _: &'a ExecutionBinding) -> PortFuture<'a, ExecutionObservationV1> {
            Box::pin(async { Err(PortError::Indeterminate) })
        }
    }
    impl AgentLoopPort for Unavailable {
        fn step<'a>(&'a self, _: &'a AgentStepRequestV1) -> PortFuture<'a, AgentStepObservationV1> {
            Box::pin(async { Err(PortError::Unavailable) })
        }
    }
    let object = Unavailable;
    let _: &dyn ModelPort = &object;
    let _: &dyn ExecutionPort = &object;
    let _: &dyn AgentLoopPort = &object;
}


struct Allow;

impl ExecutionVerifier for Allow {
    fn verify_start(
        &self,
        _reservation: &ExecutionReservation,
        _started: &ExecutionStarted,
        _class: ExecutionClass,
    ) -> Result<(), ExecutionError> {
        Ok(())
    }
}

#[test]
fn checked_handle_retains_verified_start_identity_without_granting_effect() {
    let (mut journal, started) = prepared();
    let operation_id = started.binding.operation_id.clone();
    let checked = CheckedStartHandleV1::admit(&mut journal, started, &Allow).unwrap();
    let last_digest = journal.events().last().unwrap().digest().unwrap();
    assert_eq!(checked.start_record_digest(), last_digest);
    assert_eq!(checked.binding().operation_id, operation_id);
    let observation = ExecutionObservationV1 {
        operation_id: operation_id.clone(),
        start_record_digest: last_digest,
        status: PortTerminal::Succeeded,
        terminal_observation_digest: Some(dig(23)),
    };
    assert_eq!(observation.validate_against(&checked), Ok(()));
    let forged = ExecutionObservationV1 {
        operation_id: "different-operation".into(),
        ..observation
    };
    assert!(forged.validate_against(&checked).is_err());
}

struct DenyModel;

impl ModelStartVerifier for DenyModel {
    fn verify_model_start(&self, _: &ModelInvocationV1) -> Result<(), PortError> {
        Err(PortError::Denied)
    }
}

struct TestOnlyAllowModel;

impl ModelStartVerifier for TestOnlyAllowModel {
    fn verify_model_start(&self, _: &ModelInvocationV1) -> Result<(), PortError> {
        Ok(())
    }
}

#[test]
fn model_port_requires_checked_final_use_and_independent_verifier() {
    let request = ModelInvocationV1 {
        binding: binding(),
        model_artifact_digest: dig(10),
        input_digest: dig(11),
        max_input_tokens: 100,
        max_output_tokens: 20,
        deadline_unix_ms: 1234,
    };
    assert!(matches!(
        CheckedModelInvocationV1::admit(request.clone(), &TestOnlyAllowModel),
        Err(PortError::Denied)
    ));
    let mut authorized = request;
    authorized.binding.final_use = FinalUse::Verified {
        grant_digest: dig(14),
        verifier_receipt_digest: dig(15),
    };
    assert!(matches!(
        CheckedModelInvocationV1::admit(authorized.clone(), &DenyModel),
        Err(PortError::Denied)
    ));
    let checked = CheckedModelInvocationV1::admit(authorized, &TestOnlyAllowModel).unwrap();
    assert_eq!(checked.request_digest(), checked.request().digest().unwrap());
    assert!(matches!(checked.request().binding.final_use, FinalUse::Verified { .. }));
    // A unit-test-only accepting verifier does not constitute production authority.
}
