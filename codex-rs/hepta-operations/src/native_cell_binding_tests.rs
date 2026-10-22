use super::*;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::CellExecutionIntentV1;
use codex_hepta_types::ExecutionIntentKindV1;
use codex_hepta_types::ExecutionReceiptV1;
use codex_hepta_types::ExecutionStatusV1;
use codex_hepta_types::FinalPayloadDigestV1;
use codex_hepta_types::Generation;
use codex_hepta_types::RecoveryDispositionV1;
use codex_hepta_types::ToolOutcomeV1;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn digest(bytes: &[u8]) -> Digest32 {
    Digest32::of_bytes(bytes)
}

fn fixture() -> (RuntimeToolIntentV1, &'static [u8]) {
    let bytes = b"{\"op\":\"status\"}";
    let generation = Generation::new(7).expect("generation");
    let scope = id("organ:ops");
    (
        RuntimeToolIntentV1 {
            cell: CellExecutionIntentV1 {
                operation_id: id("operation:7"),
                cell_id: id("cell:status"),
                organ_id: scope.clone(),
                generation,
                kind: ExecutionIntentKindV1::RuntimeTool,
                codex_binding: None,
                input_digest: digest(b"input"),
                final_payload: FinalPayloadDigestV1 {
                    scope_id: scope,
                    generation,
                    payload_kind: id("runtime.arguments"),
                    digest: digest(bytes),
                },
                deadline_ms: 15_000,
            },
            tool_id: id("runtime.status"),
            arguments_digest: digest(bytes),
            idempotency_key: id("effect:7"),
            host_scope: id("host:one"),
        },
        bytes,
    )
}

fn claim(intent: &RuntimeToolIntentV1, bytes: &[u8]) -> DispatchClaim {
    DispatchClaim {
        intent: bind_native_cell_to_durable_outbox_v1(10_000, intent, bytes)
            .expect("valid durable intent"),
        worker_id: id("worker:one"),
        owner_generation: intent.cell.generation,
        fence: 1,
        attempts: 1,
        expires_at_unix_ms: 12_000,
    }
}

#[test]
fn exact_bytes_host_tool_idempotency_and_generation_change_outbox_identity() {
    let (base, bytes) = fixture();
    let durable = bind_native_cell_to_durable_outbox_v1(10_000, &base, bytes)
        .expect("exact durable binding");
    assert_eq!(durable.payload_digest, base.intent_digest());
    let mut variants = Vec::new();

    let mut tool = base.clone();
    tool.tool_id = id("runtime.other");
    variants.push(tool);
    let mut host = base.clone();
    host.host_scope = id("host:two");
    variants.push(host);
    let mut idempotency = base.clone();
    idempotency.idempotency_key = id("effect:8");
    variants.push(idempotency);
    let mut generation = base.clone();
    generation.cell.generation = Generation::new(8).expect("generation");
    generation.cell.final_payload.generation = generation.cell.generation;
    variants.push(generation);

    for variant in variants {
        let altered = bind_native_cell_to_durable_outbox_v1(10_000, &variant, bytes)
            .expect("altered durable intent");
        assert_ne!(altered.semantic_digest(), durable.semantic_digest());
    }
    assert_eq!(
        bind_native_cell_to_durable_outbox_v1(10_000, &base, b"wrong"),
        Err(NativeCellBindingError::ArgumentBytesMismatch)
    );
}

#[test]
fn expired_or_invalid_cell_request_cannot_enter_outbox() {
    let (base, bytes) = fixture();
    assert_eq!(
        bind_native_cell_to_durable_outbox_v1(15_000, &base, bytes),
        Err(NativeCellBindingError::DeadlineExpired)
    );
    let mut altered = base;
    altered.arguments_digest = digest(b"wrong digest");
    assert_eq!(
        bind_native_cell_to_durable_outbox_v1(10_000, &altered, bytes),
        Err(NativeCellBindingError::InvalidIntent(
            ExecutionContractError::ToolPayloadMismatch
        ))
    );
}

#[test]
fn old_generation_or_foreign_outbox_claim_is_rejected() {
    let (request, bytes) = fixture();
    let valid = claim(&request, bytes);
    assert_eq!(
        check_native_cell_outbox_claim_v1(10_000, &request, bytes, &valid),
        Ok(())
    );
    let mut stale = valid.clone();
    stale.fence = 0;
    assert_eq!(
        check_native_cell_outbox_claim_v1(10_000, &request, bytes, &stale),
        Err(NativeCellBindingError::ForeignOrExpiredClaim)
    );
    stale = valid.clone();
    stale.owner_generation = Generation::new(8).expect("generation");
    assert_eq!(
        check_native_cell_outbox_claim_v1(10_000, &request, bytes, &stale),
        Err(NativeCellBindingError::ForeignOrExpiredClaim)
    );
    stale = valid.clone();
    stale.expires_at_unix_ms = 10_000;
    assert_eq!(
        check_native_cell_outbox_claim_v1(10_000, &request, bytes, &stale),
        Err(NativeCellBindingError::ForeignOrExpiredClaim)
    );
    stale = valid;
    stale.intent.payload_digest = digest(b"other");
    assert_eq!(
        check_native_cell_outbox_claim_v1(10_000, &request, bytes, &stale),
        Err(NativeCellBindingError::ForeignOrExpiredClaim)
    );
}

#[test]
fn terminal_receipt_must_match_exact_native_request_and_observation() {
    let (request, _) = fixture();
    let outcome = ToolOutcomeV1 {
        terminal_observed: true,
        exit_code: Some(0),
        stdout_digest: Some(digest(b"observed result")),
        stderr_digest: None,
        retryable: false,
    };
    let mut receipt = RuntimeReceiptV1 {
        execution: ExecutionReceiptV1 {
            operation_id: request.cell.operation_id.clone(),
            intent_digest: request.cell.intent_digest(),
            generation: request.cell.generation,
            final_payload_digest: request.cell.final_payload.clone(),
            outcome_digest: Some(outcome.outcome_digest()),
            status: ExecutionStatusV1::Completed,
            recovery: RecoveryDispositionV1::None,
            authority: AuthorityPosture::DENY_ALL,
        },
        runtime_intent_digest: request.intent_digest(),
        tool_outcome: outcome,
    };
    assert_eq!(check_native_cell_receipt_v1(&request, &receipt), Ok(()));
    receipt.tool_outcome.terminal_observed = false;
    receipt.tool_outcome.exit_code = None;
    receipt.tool_outcome.stdout_digest = None;
    receipt.execution.outcome_digest = Some(receipt.tool_outcome.outcome_digest());
    assert_eq!(
        check_native_cell_receipt_v1(&request, &receipt),
        Err(NativeCellBindingError::InvalidIntent(
            ExecutionContractError::StatusOutcomeMismatch
        ))
    );
}


#[test]
fn native_claim_cannot_extend_cell_deadline_or_durable_lease_budget() {
    let (intent, bytes) = fixture();
    let mut beyond_deadline = claim(&intent, bytes);
    beyond_deadline.expires_at_unix_ms = intent.cell.deadline_ms + 1;
    assert_eq!(
        check_native_cell_outbox_claim_v1(10_000, &intent, bytes, &beyond_deadline),
        Err(NativeCellBindingError::ForeignOrExpiredClaim)
    );

    let mut exhausted = claim(&intent, bytes);
    exhausted.attempts = MAX_DURABLE_OUTBOX_ATTEMPTS + 1;
    assert_eq!(
        check_native_cell_outbox_claim_v1(10_000, &intent, bytes, &exhausted),
        Err(NativeCellBindingError::ForeignOrExpiredClaim)
    );

    // With a sufficiently long Cell deadline, the durable-owner lease limit
    // is still independently enforced instead of being masked by the deadline.
    let mut long_cell = intent;
    long_cell.cell.deadline_ms = 100_000;
    let mut long_lease = claim(&long_cell, bytes);
    long_lease.expires_at_unix_ms = 10_000 + MAX_DURABLE_LEASE_MS + 1;
    assert_eq!(
        check_native_cell_outbox_claim_v1(10_000, &long_cell, bytes, &long_lease),
        Err(NativeCellBindingError::ForeignOrExpiredClaim)
    );
    long_lease.expires_at_unix_ms = 10_000 + MAX_DURABLE_LEASE_MS;
    assert_eq!(
        check_native_cell_outbox_claim_v1(10_000, &long_cell, bytes, &long_lease),
        Ok(())
    );
}
