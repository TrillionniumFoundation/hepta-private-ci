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
        arguments_digest: digest("payload"),
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

    let mut different_arguments = value.clone();
    different_arguments.arguments_digest = digest("different-arguments");
    assert_ne!(value.intent_digest(), different_arguments.intent_digest());
    assert_eq!(
        receipt.validate_against(&different_arguments),
        Err(ExecutionContractError::ToolPayloadMismatch)
    );
}

#[test]
fn runtime_tool_requires_exact_final_use_payload() {
    let mut value = intent();
    assert_eq!(value.validate(), Ok(()));

    value.cell.final_payload.digest = digest("changed-final-use");
    assert_eq!(
        value.validate(),
        Err(ExecutionContractError::ToolPayloadMismatch)
    );
}

#[test]
fn nonterminal_outcome_cannot_claim_a_process_exit() {
    let value = ToolOutcomeV1 {
        terminal_observed: false,
        exit_code: Some(0),
        stdout_digest: None,
        stderr_digest: None,
        retryable: true,
    };
    assert_eq!(
        value.validate(),
        Err(ExecutionContractError::StatusOutcomeMismatch)
    );
}

#[test]
fn rejected_runtime_receipt_cannot_claim_observed_effect_termination() {
    let intent = intent();
    let outcome = ToolOutcomeV1 {
        terminal_observed: true,
        exit_code: Some(0),
        stdout_digest: Some(digest("observed-effect")),
        stderr_digest: None,
        retryable: true,
    };
    let receipt = RuntimeReceiptV1 {
        execution: ExecutionReceiptV1 {
            operation_id: intent.cell.operation_id.clone(),
            intent_digest: intent.cell.intent_digest(),
            generation: intent.cell.generation,
            final_payload_digest: intent.cell.final_payload.clone(),
            outcome_digest: Some(outcome.outcome_digest()),
            status: ExecutionStatusV1::Rejected,
            recovery: RecoveryDispositionV1::RetryBeforeAdmission,
            authority: AuthorityPosture::DENY_ALL,
        },
        runtime_intent_digest: intent.intent_digest(),
        tool_outcome: outcome,
    };
    assert_eq!(
        receipt.validate_against(&intent),
        Err(ExecutionContractError::StatusOutcomeMismatch)
    );
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

    // A fabricated handoff without a predecessor must never pass solely
    // because its digests and observed booleans look complete.
    let mut missing_predecessor = base.clone();
    missing_predecessor.predecessor_generation = None;
    assert_eq!(
        missing_predecessor.validate(),
        Err(ExecutionContractError::NonSuccessorGeneration)
    );

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
fn terminal_execution_receipt_requires_nonzero_outcome_evidence() {
    let value = intent();
    let mut receipt = ExecutionReceiptV1 {
        operation_id: value.cell.operation_id.clone(),
        intent_digest: value.cell.intent_digest(),
        generation: value.cell.generation,
        final_payload_digest: value.cell.final_payload.clone(),
        outcome_digest: None,
        status: ExecutionStatusV1::Completed,
        recovery: RecoveryDispositionV1::None,
        authority: AuthorityPosture::DENY_ALL,
    };
    for status in [ExecutionStatusV1::Completed, ExecutionStatusV1::Failed] {
        receipt.status = status;
        assert_eq!(
            receipt.validate_against(&value.cell),
            Err(ExecutionContractError::MissingTerminalOutcome)
        );
    }
    receipt.outcome_digest = Some(Digest32::ZERO);
    assert_eq!(
        receipt.validate_against(&value.cell),
        Err(ExecutionContractError::ZeroDigest("execution outcome"))
    );
    receipt.status = ExecutionStatusV1::Indeterminate;
    receipt.outcome_digest = None;
    receipt.recovery = RecoveryDispositionV1::ReconcileSameOperation;
    assert_eq!(receipt.validate_against(&value.cell), Ok(()));
}

#[test]
fn failed_runtime_receipt_requires_observed_terminal() {
    let value = intent();
    let outcome = ToolOutcomeV1 {
        terminal_observed: false,
        exit_code: None,
        stdout_digest: None,
        stderr_digest: None,
        retryable: false,
    };
    let mut receipt = RuntimeReceiptV1 {
        execution: ExecutionReceiptV1 {
            operation_id: value.cell.operation_id.clone(),
            intent_digest: value.cell.intent_digest(),
            generation: value.cell.generation,
            final_payload_digest: value.cell.final_payload.clone(),
            outcome_digest: Some(outcome.outcome_digest()),
            status: ExecutionStatusV1::Failed,
            recovery: RecoveryDispositionV1::ReconcileSameOperation,
            authority: AuthorityPosture::DENY_ALL,
        },
        runtime_intent_digest: value.intent_digest(),
        tool_outcome: outcome,
    };
    assert_eq!(
        receipt.validate_against(&value),
        Err(ExecutionContractError::StatusOutcomeMismatch)
    );
    receipt.execution.status = ExecutionStatusV1::Indeterminate;
    assert_eq!(receipt.validate_against(&value), Ok(()));
}

#[test]
fn receipt_recovery_posture_never_authorizes_unsafe_replay() {
    let value = intent();
    let mut receipt = ExecutionReceiptV1 {
        operation_id: value.cell.operation_id.clone(),
        intent_digest: value.cell.intent_digest(),
        generation: value.cell.generation,
        final_payload_digest: value.cell.final_payload.clone(),
        outcome_digest: Some(digest("observed-terminal-or-rejection")),
        status: ExecutionStatusV1::Completed,
        recovery: RecoveryDispositionV1::None,
        authority: AuthorityPosture::DENY_ALL,
    };

    // No terminal effect may be described as a pre-admission retry, and
    // an unknown effect may not be silently rolled back or replayed.
    for (status, recovery) in [
        (
            ExecutionStatusV1::Completed,
            RecoveryDispositionV1::RetryBeforeAdmission,
        ),
        (
            ExecutionStatusV1::Completed,
            RecoveryDispositionV1::ReconcileSameOperation,
        ),
        (
            ExecutionStatusV1::Completed,
            RecoveryDispositionV1::RollbackToPredecessor,
        ),
        (
            ExecutionStatusV1::Failed,
            RecoveryDispositionV1::RetryBeforeAdmission,
        ),
        (
            ExecutionStatusV1::Indeterminate,
            RecoveryDispositionV1::None,
        ),
        (
            ExecutionStatusV1::Indeterminate,
            RecoveryDispositionV1::RetryBeforeAdmission,
        ),
        (
            ExecutionStatusV1::Indeterminate,
            RecoveryDispositionV1::RollbackToPredecessor,
        ),
        (
            ExecutionStatusV1::Rejected,
            RecoveryDispositionV1::ReconcileSameOperation,
        ),
        (
            ExecutionStatusV1::Rejected,
            RecoveryDispositionV1::RollbackToPredecessor,
        ),
    ] {
        receipt.status = status;
        receipt.recovery = recovery;
        assert_eq!(
            receipt.validate_against(&value.cell),
            Err(ExecutionContractError::StatusRecoveryMismatch),
            "{status:?} must reject {recovery:?}"
        );
    }

    for (status, recovery) in [
        (ExecutionStatusV1::Completed, RecoveryDispositionV1::None),
        (ExecutionStatusV1::Failed, RecoveryDispositionV1::None),
        (
            ExecutionStatusV1::Failed,
            RecoveryDispositionV1::ReconcileSameOperation,
        ),
        (ExecutionStatusV1::Failed, RecoveryDispositionV1::Quarantine),
        (
            ExecutionStatusV1::Failed,
            RecoveryDispositionV1::RollbackToPredecessor,
        ),
        (
            ExecutionStatusV1::Indeterminate,
            RecoveryDispositionV1::ReconcileSameOperation,
        ),
        (
            ExecutionStatusV1::Indeterminate,
            RecoveryDispositionV1::Quarantine,
        ),
        (ExecutionStatusV1::Rejected, RecoveryDispositionV1::None),
        (
            ExecutionStatusV1::Rejected,
            RecoveryDispositionV1::RetryBeforeAdmission,
        ),
        (
            ExecutionStatusV1::Rejected,
            RecoveryDispositionV1::Quarantine,
        ),
    ] {
        receipt.status = status;
        receipt.recovery = recovery;
        assert_eq!(receipt.validate_against(&value.cell), Ok(()));
    }
}

#[test]
fn native_success_requires_zero_exit_and_no_retry_signal() {
    let value = intent();
    let outcome = ToolOutcomeV1 {
        terminal_observed: true,
        exit_code: Some(0),
        stdout_digest: Some(digest("stdout")),
        stderr_digest: None,
        retryable: false,
    };
    let mut receipt = RuntimeReceiptV1 {
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

    receipt.tool_outcome.exit_code = Some(17);
    receipt.execution.outcome_digest = Some(receipt.tool_outcome.outcome_digest());
    assert_eq!(
        receipt.validate_against(&value),
        Err(ExecutionContractError::StatusOutcomeMismatch)
    );

    receipt.tool_outcome.exit_code = Some(0);
    receipt.tool_outcome.retryable = true;
    receipt.execution.outcome_digest = Some(receipt.tool_outcome.outcome_digest());
    assert_eq!(
        receipt.validate_against(&value),
        Err(ExecutionContractError::StatusOutcomeMismatch)
    );

    receipt.tool_outcome.retryable = false;
    receipt.tool_outcome.exit_code = None;
    receipt.execution.outcome_digest = Some(receipt.tool_outcome.outcome_digest());
    assert_eq!(receipt.validate_against(&value), Ok(()));
}

#[test]
fn execution_status_recovery_matrix_is_exhaustively_fail_closed() {
    let value = intent();
    let mut receipt = ExecutionReceiptV1 {
        operation_id: value.cell.operation_id.clone(),
        intent_digest: value.cell.intent_digest(),
        generation: value.cell.generation,
        final_payload_digest: value.cell.final_payload.clone(),
        outcome_digest: Some(digest("outcome")),
        status: ExecutionStatusV1::Completed,
        recovery: RecoveryDispositionV1::None,
        authority: AuthorityPosture::DENY_ALL,
    };
    let statuses = [
        ExecutionStatusV1::Completed,
        ExecutionStatusV1::Failed,
        ExecutionStatusV1::Indeterminate,
        ExecutionStatusV1::Rejected,
    ];
    let recoveries = [
        RecoveryDispositionV1::None,
        RecoveryDispositionV1::RetryBeforeAdmission,
        RecoveryDispositionV1::ReconcileSameOperation,
        RecoveryDispositionV1::Quarantine,
        RecoveryDispositionV1::RollbackToPredecessor,
    ];
    let allowed = [
        (ExecutionStatusV1::Completed, RecoveryDispositionV1::None),
        (ExecutionStatusV1::Failed, RecoveryDispositionV1::None),
        (
            ExecutionStatusV1::Failed,
            RecoveryDispositionV1::ReconcileSameOperation,
        ),
        (ExecutionStatusV1::Failed, RecoveryDispositionV1::Quarantine),
        (
            ExecutionStatusV1::Failed,
            RecoveryDispositionV1::RollbackToPredecessor,
        ),
        (
            ExecutionStatusV1::Indeterminate,
            RecoveryDispositionV1::ReconcileSameOperation,
        ),
        (
            ExecutionStatusV1::Indeterminate,
            RecoveryDispositionV1::Quarantine,
        ),
        (ExecutionStatusV1::Rejected, RecoveryDispositionV1::None),
        (
            ExecutionStatusV1::Rejected,
            RecoveryDispositionV1::RetryBeforeAdmission,
        ),
        (
            ExecutionStatusV1::Rejected,
            RecoveryDispositionV1::Quarantine,
        ),
    ];
    for &status in &statuses {
        for &recovery in &recoveries {
            receipt.status = status;
            receipt.recovery = recovery;
            let expected = if allowed.contains(&(status, recovery)) {
                Ok(())
            } else {
                Err(ExecutionContractError::StatusRecoveryMismatch)
            };
            assert_eq!(
                receipt.validate_against(&value.cell),
                expected,
                "status={status:?} recovery={recovery:?}"
            );
        }
    }
}

struct StubNativeAdapter {
    calls: std::sync::atomic::AtomicUsize,
    receipt: RuntimeReceiptV1,
}

impl NativeExecutionAdapter for StubNativeAdapter {
    async fn execute(
        &self,
        _intent: RuntimeToolIntentV1,
    ) -> Result<RuntimeReceiptV1, RuntimeExecutionError> {
        self.calls.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        Ok(self.receipt.clone())
    }
}

fn valid_native_receipt(value: &RuntimeToolIntentV1) -> RuntimeReceiptV1 {
    let tool_outcome = ToolOutcomeV1 {
        terminal_observed: true,
        exit_code: Some(0),
        stdout_digest: Some(digest("output")),
        stderr_digest: None,
        retryable: false,
    };
    RuntimeReceiptV1 {
        execution: ExecutionReceiptV1 {
            operation_id: value.cell.operation_id.clone(),
            intent_digest: value.cell.intent_digest(),
            generation: value.cell.generation,
            final_payload_digest: value.cell.final_payload.clone(),
            outcome_digest: Some(tool_outcome.outcome_digest()),
            status: ExecutionStatusV1::Completed,
            recovery: RecoveryDispositionV1::None,
            authority: AuthorityPosture::DENY_ALL,
        },
        runtime_intent_digest: value.intent_digest(),
        tool_outcome,
    }
}

fn ready_native<F: std::future::Future>(future: F) -> F::Output {
    let mut future = std::pin::pin!(future);
    let mut context = std::task::Context::from_waker(std::task::Waker::noop());
    match future.as_mut().poll(&mut context) {
        std::task::Poll::Ready(result) => result,
        std::task::Poll::Pending => panic!("stubbed native adapter must resolve immediately"),
    }
}

#[test]
fn native_gate_rejects_invalid_or_expired_intent_without_dispatch() {
    let value = intent();
    let adapter = StubNativeAdapter {
        calls: std::sync::atomic::AtomicUsize::new(0),
        receipt: valid_native_receipt(&value),
    };

    assert_eq!(
        ready_native(execute_native_tool_intent(
            &adapter,
            value.cell.deadline_ms,
            value.clone(),
        )),
        Err(RuntimeExecutionError::InvalidIntent(
            ExecutionContractError::ExpiredDeadline
        ))
    );
    let mut wrong_scope = value.clone();
    wrong_scope.cell.final_payload.scope_id = id("organ:foreign");
    assert_eq!(
        ready_native(execute_native_tool_intent(&adapter, 99, wrong_scope)),
        Err(RuntimeExecutionError::InvalidIntent(
            ExecutionContractError::PayloadScopeMismatch
        ))
    );
    assert_eq!(adapter.calls.load(std::sync::atomic::Ordering::SeqCst), 0);
}

#[test]
fn native_gate_rejects_forged_backend_receipts() {
    let value = intent();
    let mut adapter = StubNativeAdapter {
        calls: std::sync::atomic::AtomicUsize::new(0),
        receipt: valid_native_receipt(&value),
    };

    adapter.receipt.runtime_intent_digest = digest("different-native-operation");
    assert_eq!(
        ready_native(execute_native_tool_intent(&adapter, 99, value.clone())),
        Err(RuntimeExecutionError::InvalidReceipt(
            ExecutionContractError::ReceiptBindingMismatch
        ))
    );

    adapter.receipt = valid_native_receipt(&value);
    adapter.receipt.execution.status = ExecutionStatusV1::Rejected;
    adapter.receipt.execution.recovery = RecoveryDispositionV1::RetryBeforeAdmission;
    adapter.receipt.tool_outcome.retryable = true;
    adapter.receipt.execution.outcome_digest = Some(adapter.receipt.tool_outcome.outcome_digest());
    assert_eq!(
        ready_native(execute_native_tool_intent(&adapter, 99, value)),
        Err(RuntimeExecutionError::InvalidReceipt(
            ExecutionContractError::StatusOutcomeMismatch
        ))
    );
    assert_eq!(adapter.calls.load(std::sync::atomic::Ordering::SeqCst), 2);
}

#[test]
fn native_gate_forwards_only_a_validated_receipt() {
    let value = intent();
    let receipt = valid_native_receipt(&value);
    let adapter = StubNativeAdapter {
        calls: std::sync::atomic::AtomicUsize::new(0),
        receipt: receipt.clone(),
    };
    assert_eq!(
        ready_native(execute_native_tool_intent(&adapter, 99, value)),
        Ok(receipt)
    );
    assert_eq!(adapter.calls.load(std::sync::atomic::Ordering::SeqCst), 1);
}
