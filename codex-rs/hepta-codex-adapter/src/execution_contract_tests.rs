use super::*;
use crate::AdapterStatus;
use crate::adapt_codex_cell_intent;

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

#[test]
fn runtime_receipt_rejects_false_success_and_unknown_failure() {
    let request = intent();
    let observed = ToolOutcomeV1 {
        terminal_observed: true,
        exit_code: Some(0),
        stdout_digest: Some(digest("stdout")),
        stderr_digest: None,
        retryable: false,
    };
    let mut receipt = RuntimeReceiptV1 {
        execution: ExecutionReceiptV1 {
            operation_id: request.cell.operation_id.clone(),
            intent_digest: request.cell.intent_digest(),
            generation: request.cell.generation,
            final_payload_digest: request.cell.final_payload.clone(),
            outcome_digest: Some(observed.outcome_digest()),
            status: ExecutionStatusV1::Completed,
            recovery: RecoveryDispositionV1::None,
            authority: AuthorityPosture::DENY_ALL,
        },
        runtime_intent_digest: request.intent_digest(),
        tool_outcome: observed,
    };
    assert_eq!(receipt.validate_against(&request), Ok(()));

    // A successful HTTP/JSONRPC observation is not successful tool execution.
    receipt.tool_outcome.exit_code = Some(7);
    receipt.execution.outcome_digest = Some(receipt.tool_outcome.outcome_digest());
    assert_eq!(
        receipt.validate_against(&request),
        Err(ExecutionContractError::StatusOutcomeMismatch)
    );

    receipt.tool_outcome.exit_code = Some(0);
    receipt.tool_outcome.retryable = true;
    receipt.execution.outcome_digest = Some(receipt.tool_outcome.outcome_digest());
    assert_eq!(
        receipt.validate_against(&request),
        Err(ExecutionContractError::StatusOutcomeMismatch)
    );

    receipt.tool_outcome.retryable = false;
    receipt.execution.outcome_digest = Some(receipt.tool_outcome.outcome_digest());
    receipt.execution.recovery = RecoveryDispositionV1::RetryBeforeAdmission;
    assert_eq!(
        receipt.validate_against(&request),
        Err(ExecutionContractError::StatusOutcomeMismatch)
    );

    receipt.execution.recovery = RecoveryDispositionV1::None;
    receipt.execution.status = ExecutionStatusV1::Failed;
    receipt.tool_outcome.terminal_observed = false;
    receipt.tool_outcome.exit_code = None;
    receipt.tool_outcome.stdout_digest = None;
    receipt.execution.outcome_digest = Some(receipt.tool_outcome.outcome_digest());
    assert_eq!(
        receipt.validate_against(&request),
        Err(ExecutionContractError::StatusOutcomeMismatch)
    );

    // A physical tool result may be failed, but must not be mislabeled as a
    // pre-admission rejection.
    receipt.execution.status = ExecutionStatusV1::Rejected;
    receipt.tool_outcome.terminal_observed = true;
    receipt.tool_outcome.stdout_digest = Some(digest("rejected-after-effect"));
    receipt.execution.outcome_digest = Some(receipt.tool_outcome.outcome_digest());
    assert_eq!(
        receipt.validate_against(&request),
        Err(ExecutionContractError::StatusOutcomeMismatch)
    );

    // Explicit rejection before admission can request a safe retry.
    receipt.tool_outcome.terminal_observed = false;
    receipt.tool_outcome.stdout_digest = None;
    receipt.tool_outcome.retryable = true;
    receipt.execution.outcome_digest = Some(receipt.tool_outcome.outcome_digest());
    receipt.execution.recovery = RecoveryDispositionV1::RetryBeforeAdmission;
    assert_eq!(receipt.validate_against(&request), Ok(()));

    receipt.execution.status = ExecutionStatusV1::Completed;
    receipt.execution.recovery = RecoveryDispositionV1::None;
    receipt.execution.outcome_digest = None;
    assert_eq!(
        receipt.execution.validate_against(&request.cell),
        Err(ExecutionContractError::StatusOutcomeMismatch)
    );

    receipt.execution.outcome_digest = Some(Digest32::ZERO);
    assert_eq!(
        receipt.execution.validate_against(&request.cell),
        Err(ExecutionContractError::ZeroDigest("execution outcome"))
    );
}

#[test]
fn failed_execution_requires_observed_error_digest() {
    let request = intent();
    let mut receipt = ExecutionReceiptV1 {
        operation_id: request.cell.operation_id.clone(),
        intent_digest: request.cell.intent_digest(),
        generation: request.cell.generation,
        final_payload_digest: request.cell.final_payload.clone(),
        outcome_digest: None,
        status: ExecutionStatusV1::Failed,
        recovery: RecoveryDispositionV1::None,
        authority: AuthorityPosture::DENY_ALL,
    };
    assert_eq!(
        receipt.validate_against(&request.cell),
        Err(ExecutionContractError::StatusOutcomeMismatch)
    );
    receipt.outcome_digest = Some(digest("observed-terminal-error"));
    assert_eq!(receipt.validate_against(&request.cell), Ok(()));
}

#[test]
fn rejected_native_tool_cannot_hide_partial_effect_as_safe_pre_admission_retry() {
    let request = intent();
    let outcome = ToolOutcomeV1 {
        terminal_observed: false,
        exit_code: None,
        stdout_digest: None,
        stderr_digest: None,
        retryable: true,
    };
    let clean_rejection = RuntimeReceiptV1 {
        execution: ExecutionReceiptV1 {
            operation_id: request.cell.operation_id.clone(),
            intent_digest: request.cell.intent_digest(),
            generation: request.cell.generation,
            final_payload_digest: request.cell.final_payload.clone(),
            outcome_digest: Some(outcome.outcome_digest()),
            status: ExecutionStatusV1::Rejected,
            recovery: RecoveryDispositionV1::RetryBeforeAdmission,
            authority: AuthorityPosture::DENY_ALL,
        },
        runtime_intent_digest: request.intent_digest(),
        tool_outcome: outcome,
    };
    assert_eq!(clean_rejection.validate_against(&request), Ok(()));

    // An effect may have emitted output before its completion notification
    // disappeared. Neither output nor a process exit can be a pre-start retry.
    for evidence in 0..3 {
        let mut altered = clean_rejection.clone();
        match evidence {
            0 => altered.tool_outcome.exit_code = Some(0),
            1 => altered.tool_outcome.stdout_digest = Some(digest("partial stdout")),
            2 => altered.tool_outcome.stderr_digest = Some(digest("partial stderr")),
            _ => unreachable!(),
        }
        altered.execution.outcome_digest = Some(altered.tool_outcome.outcome_digest());
        assert_eq!(
            altered.validate_against(&request),
            Err(ExecutionContractError::StatusOutcomeMismatch)
        );
    }

    // An unknown outcome cannot gain a retry capability by changing a flag.
    let mut unknown = clean_rejection.clone();
    unknown.execution.status = ExecutionStatusV1::Indeterminate;
    unknown.execution.recovery = RecoveryDispositionV1::ReconcileSameOperation;
    assert_eq!(
        unknown.validate_against(&request),
        Err(ExecutionContractError::StatusOutcomeMismatch)
    );

    // A native retry flag and the adapter recovery disposition must agree.
    let mut conflicting = clean_rejection;
    conflicting.tool_outcome.retryable = false;
    conflicting.execution.outcome_digest = Some(conflicting.tool_outcome.outcome_digest());
    assert_eq!(
        conflicting.validate_against(&request),
        Err(ExecutionContractError::StatusOutcomeMismatch)
    );

    // Partial output is still expressible as an indeterminate observation,
    // without granting fresh dispatch authority.
    let mut observed_unknown = unknown;
    observed_unknown.tool_outcome.retryable = false;
    observed_unknown.tool_outcome.stdout_digest = Some(digest("partial stdout"));
    observed_unknown.execution.outcome_digest = Some(observed_unknown.tool_outcome.outcome_digest());
    assert_eq!(observed_unknown.validate_against(&request), Ok(()));
}
