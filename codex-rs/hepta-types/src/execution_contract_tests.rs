use super::*;

fn id(raw: &str) -> StableId {
    StableId::new(raw).expect("bounded stable id")
}

fn digest(raw: &str) -> Digest32 {
    Digest32::of_bytes(raw.as_bytes())
}

fn intent() -> RuntimeToolIntentV1 {
    let generation = Generation::new(7).expect("generation");
    let organ = id("organ:native");
    RuntimeToolIntentV1 {
        cell: CellExecutionIntentV1 {
            operation_id: id("operation:7"),
            cell_id: id("cell:7"),
            organ_id: organ.clone(),
            generation,
            kind: ExecutionIntentKindV1::RuntimeTool,
            codex_binding: None,
            input_digest: digest("input"),
            final_payload: FinalPayloadDigestV1 {
                scope_id: organ,
                generation,
                payload_kind: id("tool.arguments"),
                digest: digest("arguments"),
            },
            deadline_ms: 1000,
        },
        tool_id: id("runtime.read"),
        arguments_digest: digest("arguments"),
        idempotency_key: id("operation:7"),
        host_scope: id("host:local"),
    }
}

fn successful_receipt(intent: &RuntimeToolIntentV1) -> RuntimeReceiptV1 {
    let outcome = ToolOutcomeV1 {
        terminal_observed: true,
        exit_code: Some(0),
        stdout_digest: Some(digest("readback")),
        stderr_digest: None,
        retryable: false,
    };
    RuntimeReceiptV1 {
        execution: ExecutionReceiptV1 {
            operation_id: intent.cell.operation_id.clone(),
            intent_digest: intent.cell.intent_digest(),
            generation: intent.cell.generation,
            final_payload_digest: intent.cell.final_payload.clone(),
            outcome_digest: Some(outcome.outcome_digest()),
            status: ExecutionStatusV1::Completed,
            recovery: RecoveryDispositionV1::None,
            authority: AuthorityPosture::DENY_ALL,
        },
        runtime_intent_digest: intent.intent_digest(),
        tool_outcome: outcome,
    }
}

#[test]
fn pure_native_contract_binds_all_effect_identities() {
    let baseline = intent();
    let receipt = successful_receipt(&baseline);
    assert_eq!(receipt.validate_against(&baseline), Ok(()));

    let mut changed = baseline.clone();
    changed.host_scope = id("host:other");
    assert_eq!(
        receipt.validate_against(&changed),
        Err(ExecutionContractError::ReceiptBindingMismatch),
    );
    changed = baseline.clone();
    changed.idempotency_key = id("operation:other");
    assert_eq!(
        receipt.validate_against(&changed),
        Err(ExecutionContractError::ReceiptBindingMismatch),
    );
    changed = baseline.clone();
    changed.tool_id = id("runtime.write");
    assert_eq!(
        receipt.validate_against(&changed),
        Err(ExecutionContractError::ReceiptBindingMismatch),
    );
    changed = baseline;
    changed.cell.generation = Generation::new(8).expect("next generation");
    changed.cell.final_payload.generation = changed.cell.generation;
    assert_eq!(
        receipt.validate_against(&changed),
        Err(ExecutionContractError::ReceiptBindingMismatch),
    );
}

#[test]
fn pure_native_contract_denies_payload_drift_and_unsafe_retry() {
    let original = intent();
    let mut changed = original.clone();
    changed.arguments_digest = digest("substituted");
    assert_eq!(
        changed.validate(),
        Err(ExecutionContractError::ToolPayloadMismatch),
    );

    let mut receipt = successful_receipt(&original);
    receipt.execution.status = ExecutionStatusV1::Indeterminate;
    receipt.execution.recovery = RecoveryDispositionV1::RetryBeforeAdmission;
    assert_eq!(
        receipt.validate_against(&original),
        Err(ExecutionContractError::StatusRecoveryMismatch),
    );
    receipt.execution.recovery = RecoveryDispositionV1::ReconcileSameOperation;
    receipt.tool_outcome.terminal_observed = false;
    receipt.tool_outcome.exit_code = None;
    receipt.tool_outcome.stdout_digest = None;
    receipt.execution.outcome_digest = Some(receipt.tool_outcome.outcome_digest());
    assert_eq!(receipt.validate_against(&original), Ok(()));
}

#[test]
fn pure_cell_intent_requires_explicit_backend_binding() {
    let mut value = intent();
    value.cell.kind = ExecutionIntentKindV1::CodexTurn;
    assert_eq!(
        value.cell.validate(),
        Err(ExecutionContractError::MissingCodexBinding),
    );
}

#[test]
fn pure_codex_binding_rejects_unbounded_and_control_character_versions() {
    let mut cell = intent().cell;
    cell.kind = ExecutionIntentKindV1::CodexTurn;
    cell.codex_binding = Some(CodexTurnBindingV1 {
        source_admission_digest: digest("source-admission"),
        session_id: id("session:1"),
        thread_id: id("thread:1"),
        client_user_message_id: id("message:1"),
        user_input_digest: digest("user-input"),
        protocol_id: id("codex.app-server.v2"),
        app_server_version: "v2".to_owned(),
        codex_home_digest: digest("codex-home"),
        connection_id: 1,
    });

    assert_eq!(cell.validate(), Ok(()));
    let binding = cell.codex_binding.as_mut().expect("Codex binding");
    binding.app_server_version = "v".repeat(128);
    assert_eq!(cell.validate(), Ok(()), "the existing 128-byte bound is inclusive");

    cell.codex_binding.as_mut().expect("Codex binding").app_server_version = "v".repeat(129);
    assert_eq!(
        cell.validate(),
        Err(ExecutionContractError::InvalidText("app server version")),
    );

    cell.codex_binding.as_mut().expect("Codex binding").app_server_version =
        "v2\nforged-header".to_owned();
    assert_eq!(
        cell.validate(),
        Err(ExecutionContractError::InvalidText("app server version")),
    );

    cell.codex_binding.as_mut().expect("Codex binding").app_server_version.clear();
    assert_eq!(
        cell.validate(),
        Err(ExecutionContractError::EmptyText("app server version")),
    );

    // Matching the old adapter also means rejecting an unsupported v1
    // dispatch protocol instead of accepting any well-formed StableId.
    let binding = cell.codex_binding.as_mut().expect("Codex binding");
    binding.app_server_version = "v2".to_owned();
    binding.protocol_id = id("unregistered.protocol");
    assert_eq!(
        cell.validate(),
        Err(ExecutionContractError::UnsupportedProtocol),
    );
}

#[test]
fn pre_admission_rejection_cannot_claim_observed_native_output() {
    let value = intent();
    let outcome = ToolOutcomeV1 {
        terminal_observed: false,
        exit_code: None,
        stdout_digest: None,
        stderr_digest: None,
        retryable: true,
    };
    let mut receipt = RuntimeReceiptV1 {
        execution: ExecutionReceiptV1 {
            operation_id: value.cell.operation_id.clone(),
            intent_digest: value.cell.intent_digest(),
            generation: value.cell.generation,
            final_payload_digest: value.cell.final_payload.clone(),
            outcome_digest: Some(outcome.outcome_digest()),
            status: ExecutionStatusV1::Rejected,
            recovery: RecoveryDispositionV1::RetryBeforeAdmission,
            authority: AuthorityPosture::DENY_ALL,
        },
        runtime_intent_digest: value.intent_digest(),
        tool_outcome: outcome,
    };
    // A refusal before dispatch has no native output, and remains retry-safe.
    assert_eq!(receipt.validate_against(&value), Ok(()));

    // Partial native output contradicts pre-admission rejection even without
    // a process exit. Bind each forged output to its matching digest so the
    // security gate, not the digest-integrity gate, rejects it.
    for (stdout, stderr) in [
        (Some(digest("stdout")), None),
        (None, Some(digest("stderr"))),
        (Some(digest("stdout")), Some(digest("stderr"))),
    ] {
        receipt.tool_outcome.stdout_digest = stdout;
        receipt.tool_outcome.stderr_digest = stderr;
        receipt.execution.outcome_digest = Some(receipt.tool_outcome.outcome_digest());
        assert_eq!(
            receipt.validate_against(&value),
            Err(ExecutionContractError::StatusOutcomeMismatch)
        );

        // The same partial bytes may be genuine indeterminate evidence: they
        // require same-operation reconciliation, never a new retry admission.
        receipt.execution.status = ExecutionStatusV1::Indeterminate;
        receipt.execution.recovery = RecoveryDispositionV1::ReconcileSameOperation;
        assert_eq!(receipt.validate_against(&value), Ok(()));
        receipt.execution.status = ExecutionStatusV1::Rejected;
        receipt.execution.recovery = RecoveryDispositionV1::RetryBeforeAdmission;
    }
}

#[test]
fn nonzero_process_exit_cannot_be_a_successful_runtime_receipt() {
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

    // Non-process tools may have a terminal observation without an exit code.
    receipt.tool_outcome.exit_code = None;
    receipt.execution.outcome_digest = Some(receipt.tool_outcome.outcome_digest());
    assert_eq!(receipt.validate_against(&value), Ok(()));
}

#[test]
fn failed_receipt_never_retries_as_unadmitted() {
    let value = intent();
    let mut receipt = ExecutionReceiptV1 {
        operation_id: value.cell.operation_id.clone(),
        intent_digest: value.cell.intent_digest(),
        generation: value.cell.generation,
        final_payload_digest: value.cell.final_payload.clone(),
        outcome_digest: Some(digest("failed outcome")),
        status: ExecutionStatusV1::Failed,
        recovery: RecoveryDispositionV1::RetryBeforeAdmission,
        authority: AuthorityPosture::DENY_ALL,
    };
    assert_eq!(
        receipt.validate_against(&value.cell),
        Err(ExecutionContractError::StatusRecoveryMismatch)
    );
    receipt.recovery = RecoveryDispositionV1::ReconcileSameOperation;
    assert_eq!(receipt.validate_against(&value.cell), Ok(()));
}

#[test]
fn native_tool_exit_and_status_must_be_consistent() {
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

    // A successful native tool is not an unadmitted rejection.
    receipt.execution.status = ExecutionStatusV1::Rejected;
    assert_eq!(
        receipt.validate_against(&value),
        Err(ExecutionContractError::StatusOutcomeMismatch)
    );

    // A completed effect is not independently marked retryable.
    receipt.execution.status = ExecutionStatusV1::Completed;
    receipt.tool_outcome.retryable = true;
    receipt.execution.outcome_digest = Some(receipt.tool_outcome.outcome_digest());
    assert_eq!(
        receipt.validate_against(&value),
        Err(ExecutionContractError::StatusOutcomeMismatch)
    );

    // Even a digest-matching exit code is invalid without terminal observation.
    receipt.tool_outcome.retryable = false;
    receipt.tool_outcome.terminal_observed = false;
    receipt.execution.outcome_digest = Some(receipt.tool_outcome.outcome_digest());
    assert_eq!(
        receipt.tool_outcome.validate(),
        Err(ExecutionContractError::StatusOutcomeMismatch)
    );
    assert_eq!(
        receipt.validate_against(&value),
        Err(ExecutionContractError::StatusOutcomeMismatch)
    );

    // A genuine pre-admission rejection has no observed native tool exit.
    receipt.tool_outcome.exit_code = None;
    receipt.tool_outcome.stdout_digest = None;
    receipt.tool_outcome.retryable = true;
    receipt.execution.outcome_digest = Some(receipt.tool_outcome.outcome_digest());
    receipt.execution.status = ExecutionStatusV1::Rejected;
    receipt.execution.recovery = RecoveryDispositionV1::RetryBeforeAdmission;
    assert_eq!(receipt.validate_against(&value), Ok(()));
}

#[test]
fn native_retry_hint_requires_exact_preadmission_recovery() {
    let value = intent();
    let outcome = ToolOutcomeV1 {
        terminal_observed: false,
        exit_code: None,
        stdout_digest: None,
        stderr_digest: None,
        retryable: true,
    };
    let mut receipt = RuntimeReceiptV1 {
        execution: ExecutionReceiptV1 {
            operation_id: value.cell.operation_id.clone(),
            intent_digest: value.cell.intent_digest(),
            generation: value.cell.generation,
            final_payload_digest: value.cell.final_payload.clone(),
            outcome_digest: Some(outcome.outcome_digest()),
            status: ExecutionStatusV1::Rejected,
            recovery: RecoveryDispositionV1::RetryBeforeAdmission,
            authority: AuthorityPosture::DENY_ALL,
        },
        runtime_intent_digest: value.intent_digest(),
        tool_outcome: outcome,
    };
    // Only this exact pre-admission state is eligible for a new attempt.
    assert_eq!(receipt.validate_against(&value), Ok(()));

    // A valid, digested backend hint cannot override reconciliation, a
    // quarantine or a rejected operation's explicit no-retry posture.
    for (status, recovery) in [
        (
            ExecutionStatusV1::Indeterminate,
            RecoveryDispositionV1::ReconcileSameOperation,
        ),
        (
            ExecutionStatusV1::Indeterminate,
            RecoveryDispositionV1::Quarantine,
        ),
        (ExecutionStatusV1::Rejected, RecoveryDispositionV1::None),
        (ExecutionStatusV1::Rejected, RecoveryDispositionV1::Quarantine),
    ] {
        receipt.execution.status = status;
        receipt.execution.recovery = recovery;
        assert_eq!(
            receipt.validate_against(&value),
            Err(ExecutionContractError::StatusOutcomeMismatch),
            "status={status:?} recovery={recovery:?}"
        );
    }

    // Likewise, the recovery instruction cannot authorize a retry if the
    // backend explicitly marks that same pre-admission result non-retryable.
    receipt.execution.status = ExecutionStatusV1::Rejected;
    receipt.execution.recovery = RecoveryDispositionV1::RetryBeforeAdmission;
    receipt.tool_outcome.retryable = false;
    receipt.execution.outcome_digest = Some(receipt.tool_outcome.outcome_digest());
    assert_eq!(
        receipt.validate_against(&value),
        Err(ExecutionContractError::StatusOutcomeMismatch)
    );

    // Admitted failures may be reconciled, but not repeated as fresh effects.
    receipt.execution.status = ExecutionStatusV1::Failed;
    receipt.execution.recovery = RecoveryDispositionV1::ReconcileSameOperation;
    receipt.tool_outcome.terminal_observed = true;
    receipt.tool_outcome.exit_code = Some(9);
    receipt.tool_outcome.stderr_digest = Some(digest("native error"));
    receipt.tool_outcome.retryable = true;
    receipt.execution.outcome_digest = Some(receipt.tool_outcome.outcome_digest());
    assert_eq!(
        receipt.validate_against(&value),
        Err(ExecutionContractError::StatusOutcomeMismatch)
    );

    receipt.tool_outcome.retryable = false;
    receipt.execution.outcome_digest = Some(receipt.tool_outcome.outcome_digest());
    assert_eq!(receipt.validate_against(&value), Ok(()));
    receipt.execution.status = ExecutionStatusV1::Indeterminate;
    receipt.execution.recovery = RecoveryDispositionV1::ReconcileSameOperation;
    assert_eq!(receipt.validate_against(&value), Ok(()));
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

#[test]
fn silent_native_process_exit_is_valid_terminal_evidence() {
    let value = intent();
    let mut receipt = valid_native_receipt(&value);
    // Empty stdout/stderr are normal for successful native commands.
    receipt.tool_outcome.stdout_digest = None;
    receipt.execution.outcome_digest = Some(receipt.tool_outcome.outcome_digest());
    assert_eq!(receipt.tool_outcome.validate(), Ok(()));
    assert_eq!(receipt.validate_against(&value), Ok(()));

    // Silent nonzero exits are terminal failures, never Completed successes.
    receipt.tool_outcome.exit_code = Some(21);
    receipt.execution.outcome_digest = Some(receipt.tool_outcome.outcome_digest());
    assert_eq!(
        receipt.validate_against(&value),
        Err(ExecutionContractError::StatusOutcomeMismatch),
    );
    receipt.execution.status = ExecutionStatusV1::Failed;
    receipt.execution.recovery = RecoveryDispositionV1::ReconcileSameOperation;
    assert_eq!(receipt.validate_against(&value), Ok(()));

    // No output AND no exit observation cannot be promoted into terminality.
    receipt.tool_outcome.exit_code = None;
    receipt.execution.outcome_digest = Some(receipt.tool_outcome.outcome_digest());
    assert_eq!(
        receipt.tool_outcome.validate(),
        Err(ExecutionContractError::MissingTerminalOutcome),
    );
    assert_eq!(
        receipt.validate_against(&value),
        Err(ExecutionContractError::MissingTerminalOutcome),
    );

    // An exit code cannot claim terminality if no terminal observation exists.
    receipt.tool_outcome.exit_code = Some(0);
    receipt.tool_outcome.terminal_observed = false;
    receipt.execution.outcome_digest = Some(receipt.tool_outcome.outcome_digest());
    assert_eq!(
        receipt.validate_against(&value),
        Err(ExecutionContractError::StatusOutcomeMismatch),
    );
}
