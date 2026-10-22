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
fn codex_binding_rejects_unsupported_protocol_and_noncanonical_version() {
    let mut cell = intent().cell;
    cell.kind = ExecutionIntentKindV1::CodexTurn;
    cell.codex_binding = Some(CodexTurnBindingV1 {
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
    assert_eq!(cell.validate(), Ok(()));

    cell.codex_binding.as_mut().expect("binding").protocol_id = id("codex.app-server.v1");
    assert_eq!(
        cell.validate(),
        Err(ExecutionContractError::UnsupportedCodexProtocol)
    );

    cell.codex_binding.as_mut().expect("binding").protocol_id = id("codex.app-server.v2");
    cell.codex_binding
        .as_mut()
        .expect("binding")
        .app_server_version = "v2\n".to_owned();
    assert_eq!(
        cell.validate(),
        Err(ExecutionContractError::InvalidAppServerVersion)
    );

    cell.codex_binding
        .as_mut()
        .expect("binding")
        .app_server_version = "v".repeat(crate::MAX_APP_SERVER_VERSION_BYTES + 1);
    assert_eq!(
        cell.validate(),
        Err(ExecutionContractError::InvalidAppServerVersion)
    );
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

    let mut missing = base.clone();
    missing.predecessor_generation = None;
    assert_eq!(
        missing.validate(),
        Err(ExecutionContractError::NonSuccessorGeneration)
    );
    let mut invented_initial_handoff = base.clone();
    invented_initial_handoff.generation = generation(1);
    invented_initial_handoff.predecessor_generation = None;
    assert_eq!(
        invented_initial_handoff.validate(),
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
fn completion_and_unknown_admission_enforce_recovery_posture() {
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
    assert_eq!(receipt.validate_against(&value.cell), Ok(()));

    receipt.recovery = RecoveryDispositionV1::RetryBeforeAdmission;
    assert_eq!(
        receipt.validate_against(&value.cell),
        Err(ExecutionContractError::StatusRecoveryMismatch)
    );
    receipt.status = ExecutionStatusV1::Indeterminate;
    receipt.outcome_digest = None;
    for invalid in [
        RecoveryDispositionV1::None,
        RecoveryDispositionV1::RetryBeforeAdmission,
        RecoveryDispositionV1::RollbackToPredecessor,
    ] {
        receipt.recovery = invalid;
        assert_eq!(
            receipt.validate_against(&value.cell),
            Err(ExecutionContractError::StatusRecoveryMismatch)
        );
    }
    for safe in [
        RecoveryDispositionV1::ReconcileSameOperation,
        RecoveryDispositionV1::Quarantine,
    ] {
        receipt.recovery = safe;
        assert_eq!(receipt.validate_against(&value.cell), Ok(()));
    }
}

#[test]
fn execution_receipt_status_recovery_matrix_is_fail_closed() {
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
        (ExecutionStatusV1::Failed, RecoveryDispositionV1::ReconcileSameOperation),
        (ExecutionStatusV1::Failed, RecoveryDispositionV1::Quarantine),
        (ExecutionStatusV1::Failed, RecoveryDispositionV1::RollbackToPredecessor),
        (ExecutionStatusV1::Indeterminate, RecoveryDispositionV1::ReconcileSameOperation),
        (ExecutionStatusV1::Indeterminate, RecoveryDispositionV1::Quarantine),
        (ExecutionStatusV1::Rejected, RecoveryDispositionV1::None),
        (ExecutionStatusV1::Rejected, RecoveryDispositionV1::RetryBeforeAdmission),
        (ExecutionStatusV1::Rejected, RecoveryDispositionV1::Quarantine),
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
