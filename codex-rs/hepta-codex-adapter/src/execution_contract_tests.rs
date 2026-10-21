use super::*;
use crate::adapt_codex_cell_intent;
use crate::AdapterStatus;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid stable id")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("valid generation")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn intent() -> RuntimeToolIntentV1 {
    let organ = id("organ:build");
    let generation = generation(3);
    RuntimeToolIntentV1 {
        cell: CellExecutionIntentV1 {
            operation_id: id("operation:1"),
            cell_id: id("cell:compile"),
            organ_id: organ.clone(),
            generation,
            kind: ExecutionIntentKindV1::RuntimeTool,
            codex_binding: None,
            input_digest: digest("input"),
            final_payload: FinalPayloadDigestV1 {
                scope_id: organ,
                generation,
                payload_kind: id("tool.arguments"),
                digest: digest("payload"),
            },
            deadline_ms: 100,
        },
        tool_id: id("runtime.exec"),
        arguments_digest: digest("arguments"),
        idempotency_key: id("operation:1"),
        host_scope: id("host:local"),
    }
}

#[test]
fn intent_digest_is_deterministic_and_generation_bound() {
    let first = intent();
    let second = intent();
    assert_eq!(first.cell.intent_digest(), second.cell.intent_digest());

    let mut successor = second;
    successor.cell.generation = generation(4);
    successor.cell.final_payload.generation = generation(4);
    assert_ne!(first.cell.intent_digest(), successor.cell.intent_digest());
}

#[test]
fn codex_cell_intent_enters_existing_adapter_spine() {
    let mut value = intent();
    value.cell.kind = ExecutionIntentKindV1::CodexTurn;
    value.cell.codex_binding = Some(CodexTurnBindingV1 {
        source_admission_digest: digest("admission"),
        session_id: id("session:1"),
        thread_id: id("thread:1"),
        client_user_message_id: id("message:1"),
        user_input_digest: digest("input"),
        protocol_id: id("codex.app-server.v2"),
        app_server_version: "v2".to_owned(),
        codex_home_digest: digest("codex-home"),
        connection_id: 1,
    });
    let receipt = adapt_codex_cell_intent(1, value.cell).expect("cell admission");
    assert_eq!(receipt.status, AdapterStatus::Indeterminate);
}

#[test]
fn runtime_intent_rejects_codex_kind() {
    let mut value = intent();
    value.cell.kind = ExecutionIntentKindV1::CodexTurn;
    assert_eq!(
        value.validate(),
        Err(ExecutionContractError::WrongIntentKind)
    );
}

#[test]
fn codex_intent_requires_turn_binding() {
    let mut value = intent();
    value.cell.kind = ExecutionIntentKindV1::CodexTurn;
    assert_eq!(
        value.validate(),
        Err(ExecutionContractError::MissingCodexBinding)
    );
    value.cell.codex_binding = Some(CodexTurnBindingV1 {
        source_admission_digest: digest("admission"),
        session_id: id("session:1"),
        thread_id: id("thread:1"),
        client_user_message_id: id("message:1"),
        user_input_digest: digest("input"),
        protocol_id: id("codex.app-server.v2"),
        app_server_version: "v2".to_owned(),
        codex_home_digest: digest("codex-home"),
        connection_id: 1,
    });
    assert_eq!(value.validate(), Ok(()));
}

#[test]
fn receipt_requires_exact_payload_and_generation() {
    let value = intent();
    let receipt = ExecutionReceiptV1 {
        operation_id: value.cell.operation_id.clone(),
        intent_digest: value.cell.intent_digest(),
        generation: value.cell.generation,
        final_payload_digest: value.cell.final_payload.clone(),
        outcome_digest: Some(digest("outcome")),
        status: ExecutionStatusV1::Completed,
        recovery: RecoveryDispositionV1::None,
        authority: AuthorityPosture::DENY_ALL,
    };
    assert_eq!(receipt.validate_against(&value.cell), Ok(()));

    let mut no_terminal = receipt.clone();
    no_terminal.outcome_digest = None;
    assert_eq!(
        no_terminal.validate_against(&value.cell),
        Err(ExecutionContractError::MissingTerminalOutcome)
    );

    let mut wrong_recovery = receipt.clone();
    wrong_recovery.recovery = RecoveryDispositionV1::RetryBeforeAdmission;
    assert_eq!(
        wrong_recovery.validate_against(&value.cell),
        Err(ExecutionContractError::StatusOutcomeMismatch)
    );

    let mut unknown = receipt.clone();
    unknown.status = ExecutionStatusV1::Indeterminate;
    unknown.outcome_digest = None;
    assert_eq!(
        unknown.validate_against(&value.cell),
        Err(ExecutionContractError::StatusOutcomeMismatch)
    );
    unknown.recovery = RecoveryDispositionV1::ReconcileSameOperation;
    assert_eq!(unknown.validate_against(&value.cell), Ok(()));

    let mut stale = value.cell.clone();
    stale.final_payload.digest = digest("different-payload");
    assert_eq!(
        receipt.validate_against(&stale),
        Err(ExecutionContractError::ReceiptBindingMismatch)
    );
}

#[test]
fn runtime_receipt_rechecks_tool_outcome_digest() {
    let value = intent();
    let outcome = ToolOutcomeV1 {
        terminal_observed: true,
        exit_code: Some(0),
        stdout_digest: Some(digest("stdout")),
        stderr_digest: None,
        retryable: false,
    };
    let receipt = RuntimeReceiptV1 {
        execution: ExecutionReceiptV1 {
            operation_id: value.cell.operation_id.clone(),
            intent_digest: value.cell.intent_digest(),
            generation: value.cell.generation,
            final_payload_digest: value.cell.final_payload.clone(),
            outcome_digest: Some(outcome.outcome_digest()),
            status: ExecutionStatusV1::Completed,
            recovery: RecoveryDispositionV1::None,
            authority: AuthorityPosture::DENY_ALL,
        },
        runtime_intent_digest: value.intent_digest(),
        tool_outcome: outcome,
    };
    assert_eq!(receipt.validate_against(&value), Ok(()));

    let mut unsuccessful_exit = receipt.clone();
    unsuccessful_exit.tool_outcome.exit_code = Some(42);
    unsuccessful_exit.execution.outcome_digest =
        Some(unsuccessful_exit.tool_outcome.outcome_digest());
    assert_eq!(
        unsuccessful_exit.validate_against(&value),
        Err(ExecutionContractError::StatusOutcomeMismatch)
    );
    // A nonzero exit is a valid observed failure, not a success.
    unsuccessful_exit.execution.status = ExecutionStatusV1::Failed;
    assert_eq!(unsuccessful_exit.validate_against(&value), Ok(()));

    let mut retryable_success = receipt.clone();
    retryable_success.tool_outcome.retryable = true;
    retryable_success.execution.outcome_digest =
        Some(retryable_success.tool_outcome.outcome_digest());
    assert_eq!(
        retryable_success.validate_against(&value),
        Err(ExecutionContractError::StatusOutcomeMismatch)
    );

    for mutated in [
        RuntimeToolIntentV1 {
            tool_id: id("runtime.other"),
            ..value.clone()
        },
        RuntimeToolIntentV1 {
            arguments_digest: digest("different-arguments"),
            ..value.clone()
        },
        RuntimeToolIntentV1 {
            idempotency_key: id("operation:reused"),
            ..value.clone()
        },
        RuntimeToolIntentV1 {
            host_scope: id("host:other"),
            ..value.clone()
        },
    ] {
        assert_ne!(value.intent_digest(), mutated.intent_digest());
        assert_eq!(
            receipt.validate_against(&mutated),
            Err(ExecutionContractError::ReceiptBindingMismatch)
        );
    }
}

#[test]
fn fence_requires_old_writer_and_route_cutover() {
    let base = GenerationFenceWitnessV1 {
        scope_id: id("organ:build"),
        generation: generation(3),
        predecessor_generation: Some(generation(2)),
        old_writer_id: id("writer:old"),
        new_writer_id: id("writer:new"),
        fence_digest: digest("fence"),
        migration_digest: digest("migration"),
        old_writer_fenced: true,
        route_cutover_observed: true,
    };
    assert_eq!(base.validate(), Ok(()));

    let mut skipped = base.clone();
    skipped.generation = generation(5);
    assert_eq!(
        skipped.validate(),
        Err(ExecutionContractError::NonSuccessorGeneration)
    );

    let mut backwards = base.clone();
    backwards.generation = generation(1);
    assert_eq!(
        backwards.validate(),
        Err(ExecutionContractError::NonSuccessorGeneration)
    );

    let mut incomplete = base;
    incomplete.route_cutover_observed = false;
    assert_eq!(
        incomplete.validate(),
        Err(ExecutionContractError::FenceNotComplete)
    );
}

#[test]
fn terminal_tool_outcome_has_a_nonzero_digest() {
    let outcome = ToolOutcomeV1 {
        terminal_observed: true,
        exit_code: Some(0),
        stdout_digest: Some(digest("stdout")),
        stderr_digest: None,
        retryable: false,
    };
    outcome.validate().expect("valid terminal outcome");
    assert!(!outcome.outcome_digest().is_zero());
}
