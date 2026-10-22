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
