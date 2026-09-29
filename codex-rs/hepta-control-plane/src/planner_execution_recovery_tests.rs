//! Durable dispatch and recovery regressions.

use super::*;

#[test]
fn current_authority_claims_before_execution_and_records_terminal_receipt() {
    let directory = must(tempdir());
    let mut store = must(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    let request = request();
    let mut authority = authority(&request);
    let mut executor = executor(PlannerEffectDispositionV1::Succeeded);
    let receipt = must(execute_planner_request_v1(
        &request,
        1_000,
        &mut authority,
        &mut executor,
        &mut store,
    ));

    assert_eq!(executor.executions, 1);
    assert_eq!(executor.reconciliations, 0);
    assert_eq!(authority.authorizations, 1);
    assert_eq!(authority.revalidations, 1);
    assert!(!receipt.authority.grants_any());
    assert_eq!(store.records().len(), 2);
    assert_eq!(store.records()[0].kind, PlannerStoreRecordKindV1::Selection);
    assert_eq!(
        store.records()[1].kind,
        PlannerStoreRecordKindV1::TerminalReceipt
    );
}

#[test]
fn repeated_request_never_replays_after_a_durable_claim() {
    let request = request();
    let mut authority = authority(&request);
    authority.grant_digest = digest("grant-one");
    let mut executor = executor(PlannerEffectDispositionV1::Succeeded);
    executor.fail_next_execute = true;
    let mut sink = CollectSink::default();

    let first = must_err(execute_planner_request_v1(
        &request,
        1_000,
        &mut authority,
        &mut executor,
        &mut sink,
    ));
    assert!(matches!(first, PlannerExecutionError::Store(_)));
    assert_eq!(executor.executions, 1);
    assert_eq!(executor.reconciliations, 0);
    assert!(sink.receipts.is_empty());

    authority.grant_digest = digest("grant-two");
    let reconciled = must(execute_planner_request_v1(
        &request,
        1_001,
        &mut authority,
        &mut executor,
        &mut sink,
    ));
    assert_eq!(
        reconciled.disposition,
        PlannerEffectDispositionV1::Succeeded
    );
    assert_eq!(reconciled.grant_digest, digest("grant-one"));
    assert_eq!(executor.executions, 1);
    assert_eq!(executor.reconciliations, 1);
    assert_eq!(authority.authorizations, 1);
    assert_eq!(authority.revalidations, 1);

    let replay = must(execute_planner_request_v1(
        &request,
        1_002,
        &mut authority,
        &mut executor,
        &mut sink,
    ));
    assert_eq!(replay, reconciled);
    assert_eq!(executor.executions, 1);
    assert_eq!(executor.reconciliations, 1);
    assert_eq!(authority.authorizations, 1);
    assert_eq!(authority.revalidations, 1);
}

#[test]
fn conclusive_receipt_is_returned_after_request_expiry_without_new_authority() {
    let request = request();
    let mut authority = authority(&request);
    let mut executor = executor(PlannerEffectDispositionV1::Succeeded);
    let mut sink = CollectSink::default();

    let first = must(execute_planner_request_v1(
        &request,
        1_000,
        &mut authority,
        &mut executor,
        &mut sink,
    ));
    authority.payload_digest = digest("invalid-later-payload");
    authority.revalidation = PlannerAuthorityRevalidationV1::Revoked;

    let replay = must(execute_planner_request_v1(
        &request,
        request.expires_at_micros,
        &mut authority,
        &mut executor,
        &mut sink,
    ));
    assert_eq!(replay, first);
    assert_eq!(authority.authorizations, 1);
    assert_eq!(authority.revalidations, 1);
    assert_eq!(executor.executions, 1);
    assert_eq!(executor.reconciliations, 0);
}

#[test]
fn indeterminate_terminal_is_reconciled_instead_of_treated_as_complete() {
    let request = request();
    let mut authority = authority(&request);
    let mut executor = executor(PlannerEffectDispositionV1::Indeterminate);
    executor.reconciliation_disposition = PlannerEffectDispositionV1::Succeeded;
    let mut sink = CollectSink::default();

    let first = must(execute_planner_request_v1(
        &request,
        1_000,
        &mut authority,
        &mut executor,
        &mut sink,
    ));
    assert_eq!(first.disposition, PlannerEffectDispositionV1::Indeterminate);

    let second = must(execute_planner_request_v1(
        &request,
        1_001,
        &mut authority,
        &mut executor,
        &mut sink,
    ));
    assert_eq!(second.disposition, PlannerEffectDispositionV1::Succeeded);
    assert_eq!(executor.executions, 1);
    assert_eq!(executor.reconciliations, 1);
}

#[test]
fn durable_v2_claim_reopens_after_unknown_executor_without_timestamp_conflict() {
    let directory = must(tempdir());
    let request = request();
    let mut authority = authority(&request);
    authority.grant_digest = digest("original-grant");
    let mut executor = executor(PlannerEffectDispositionV1::Succeeded);
    executor.fail_next_execute = true;

    let mut store = must(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    must_err(execute_planner_request_v1(
        &request,
        1_000,
        &mut authority,
        &mut executor,
        &mut store,
    ));
    assert_eq!(store.records().len(), 1);
    drop(store);

    authority.grant_digest = digest("refreshed-grant");
    let mut reopened = must(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    let reconciled = must(execute_planner_request_v1(
        &request,
        1_500,
        &mut authority,
        &mut executor,
        &mut reopened,
    ));
    assert_eq!(
        reconciled.disposition,
        PlannerEffectDispositionV1::Succeeded
    );
    assert_eq!(reconciled.grant_digest, digest("original-grant"));
    assert_eq!(executor.executions, 1);
    assert_eq!(executor.reconciliations, 1);
    assert_eq!(authority.authorizations, 1);
    assert_eq!(authority.revalidations, 1);
    assert_eq!(reopened.records().len(), 2);
}

#[test]
fn legacy_v1_claim_reopens_into_reconciliation_without_redispatch() {
    let directory = must(tempdir());
    let request = request();
    let operation_identity_digest = super::super::super::codec::operation_identity_digest(&request);
    let request_digest = super::super::super::codec::request_digest(&request);
    let grant_digest = digest("legacy-grant");
    let claimed_at_micros = 900;
    let claim_digest = super::super::super::codec::dispatch_claim_digest_v1(
        operation_identity_digest,
        request_digest,
        grant_digest,
        request.final_payload_digest,
        claimed_at_micros,
    );
    let mut envelope = super::super::super::codec::DISPATCH_CLAIM_ENVELOPE_DOMAIN_V1.to_vec();
    envelope.extend_from_slice(operation_identity_digest.as_array());
    envelope.extend_from_slice(request_digest.as_array());
    envelope.extend_from_slice(grant_digest.as_array());
    envelope.extend_from_slice(request.final_payload_digest.as_array());
    envelope.extend_from_slice(&claimed_at_micros.to_be_bytes());
    envelope.extend_from_slice(claim_digest.as_array());

    let mut store = must(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    must(store.append_execution_record(
        PlannerStoreRecordKindV1::Selection,
        super::super::super::codec::dispatch_claim_identity(operation_identity_digest),
        claim_digest,
        &envelope,
    ));
    drop(store);

    let mut reopened = must(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    let mut authority = authority(&request);
    let mut executor = executor(PlannerEffectDispositionV1::Succeeded);
    let receipt = must(execute_planner_request_v1(
        &request,
        1_000,
        &mut authority,
        &mut executor,
        &mut reopened,
    ));
    assert_eq!(receipt.grant_digest, grant_digest);
    assert_eq!(executor.executions, 0);
    assert_eq!(executor.reconciliations, 1);
    assert_eq!(authority.authorizations, 0);
    assert_eq!(authority.revalidations, 0);
}

#[test]
fn durable_store_reopens_and_converges_without_redispatch() {
    let directory = must(tempdir());
    let request = request();
    let mut authority = authority(&request);
    let mut executor = executor(PlannerEffectDispositionV1::Indeterminate);
    executor.reconciliation_disposition = PlannerEffectDispositionV1::Succeeded;

    let mut store = must(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    let first = must(execute_planner_request_v1(
        &request,
        1_000,
        &mut authority,
        &mut executor,
        &mut store,
    ));
    assert_eq!(first.disposition, PlannerEffectDispositionV1::Indeterminate);
    drop(store);

    let mut reopened = must(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    let reconciled = must(execute_planner_request_v1(
        &request,
        1_001,
        &mut authority,
        &mut executor,
        &mut reopened,
    ));
    assert_eq!(
        reconciled.disposition,
        PlannerEffectDispositionV1::Succeeded
    );
    assert_eq!(executor.executions, 1);
    assert_eq!(executor.reconciliations, 1);
    assert_eq!(reopened.records().len(), 3);
    drop(reopened);

    let mut final_open = must(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    let replay = must(execute_planner_request_v1(
        &request,
        1_002,
        &mut authority,
        &mut executor,
        &mut final_open,
    ));
    assert_eq!(replay, reconciled);
    assert_eq!(executor.executions, 1);
    assert_eq!(executor.reconciliations, 1);
    assert_eq!(final_open.records().len(), 3);
}

#[test]
fn revocation_after_claim_stops_before_executor() {
    let request = request();
    let mut authority = authority(&request);
    authority.revalidation = PlannerAuthorityRevalidationV1::Revoked;
    let mut executor = executor(PlannerEffectDispositionV1::Succeeded);
    let mut sink = CollectSink::default();
    let error = must_err(execute_planner_request_v1(
        &request,
        1_000,
        &mut authority,
        &mut executor,
        &mut sink,
    ));

    assert_eq!(error, PlannerExecutionError::AuthorityRevoked);
    assert_eq!(executor.executions, 0);
    assert_eq!(executor.reconciliations, 0);
    assert_eq!(sink.claimed_operations.len(), 1);
    assert_eq!(sink.receipts.len(), 1);
    assert_eq!(
        sink.receipts[0].disposition,
        PlannerEffectDispositionV1::Failed
    );

    let terminal = must(execute_planner_request_v1(
        &request,
        1_001,
        &mut authority,
        &mut executor,
        &mut sink,
    ));
    assert_eq!(terminal, sink.receipts[0]);
    assert_eq!(authority.authorizations, 1);
    assert_eq!(authority.revalidations, 1);
    assert_eq!(executor.executions, 0);
    assert_eq!(executor.reconciliations, 0);
}

#[test]
fn final_payload_drift_is_rejected_before_claim_and_dispatch() {
    let request = request();
    let mut authority = authority(&request);
    authority.payload_digest = digest("changed-payload");
    let mut executor = executor(PlannerEffectDispositionV1::Succeeded);
    let mut sink = CollectSink::default();
    let error = must_err(execute_planner_request_v1(
        &request,
        1_000,
        &mut authority,
        &mut executor,
        &mut sink,
    ));

    assert_eq!(error, PlannerExecutionError::GrantMismatch);
    assert_eq!(executor.executions, 0);
    assert_eq!(executor.reconciliations, 0);
    assert!(sink.claimed_operations.is_empty());
    assert!(sink.receipts.is_empty());
}

#[test]
fn indeterminate_effect_is_reconciled_without_replaying_dispatch() {
    let request = request();
    let mut authority = authority(&request);
    let mut executor = executor(PlannerEffectDispositionV1::Succeeded);
    executor.fail_next_execute = true;
    let mut sink = CollectSink::default();
    must_err(execute_planner_request_v1(
        &request,
        1_000,
        &mut authority,
        &mut executor,
        &mut sink,
    ));

    executor.reconciliation_disposition = PlannerEffectDispositionV1::Indeterminate;
    let receipt = must(reconcile_planner_request_v1(
        &request,
        digest("grant"),
        &mut executor,
        &mut sink,
    ));

    assert_eq!(
        receipt.disposition,
        PlannerEffectDispositionV1::Indeterminate
    );
    assert_eq!(executor.executions, 1);
    assert_eq!(executor.reconciliations, 1);
    assert_eq!(sink.receipts, vec![receipt]);
}

#[test]
fn reconciliation_without_a_durable_claim_is_rejected() {
    let request = request();
    let mut executor = executor(PlannerEffectDispositionV1::Succeeded);
    let mut sink = CollectSink::default();
    let error = must_err(reconcile_planner_request_v1(
        &request,
        digest("grant"),
        &mut executor,
        &mut sink,
    ));
    assert!(matches!(
        error,
        PlannerExecutionError::Store(message)
            if message.contains("requires a durable dispatch claim")
    ));
    assert_eq!(executor.executions, 0);
    assert_eq!(executor.reconciliations, 0);
    assert!(sink.receipts.is_empty());
}

#[test]
fn reopened_terminal_without_claim_is_rejected_before_authority_or_effect() {
    let directory = must(tempdir());
    let request = request();
    let grant = PlannerExecutionGrantV1 {
        grant_digest: digest("orphan-grant"),
        final_payload_digest: request.final_payload_digest,
        revocation_frontier_digest: request.revocation_frontier_digest,
        expires_at_micros: request.expires_at_micros,
    };
    let receipt = must(super::super::terminal_receipt(
        &request,
        &grant,
        PlannerEffectObservationV1 {
            disposition: PlannerEffectDispositionV1::Succeeded,
            outcome_digest: digest("orphan-outcome"),
            observed_at_micros: 1_100,
        },
    ));
    let envelope = super::super::encode_terminal_receipt(&receipt);

    let mut store = must(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    must(store.append_execution_record(
        PlannerStoreRecordKindV1::TerminalReceipt,
        receipt.operation_identity_digest,
        receipt.receipt_digest,
        &envelope,
    ));
    drop(store);

    let mut reopened = must(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    let mut authority = authority(&request);
    let mut executor = executor(PlannerEffectDispositionV1::Succeeded);
    let error = must_err(execute_planner_request_v1(
        &request,
        1_200,
        &mut authority,
        &mut executor,
        &mut reopened,
    ));
    assert!(matches!(
        error,
        PlannerExecutionError::Store(message)
            if message.contains("without a durable dispatch claim")
    ));
    assert_eq!(authority.authorizations, 0);
    assert_eq!(authority.revalidations, 0);
    assert_eq!(executor.executions, 0);
    assert_eq!(executor.reconciliations, 0);
}

#[test]
fn reopened_terminal_must_match_the_original_claim_grant() {
    let directory = must(tempdir());
    let request = request();
    let operation_identity_digest = super::super::super::codec::operation_identity_digest(&request);
    let request_digest = super::super::super::codec::request_digest(&request);

    let mut store = must(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    must(store.claim_dispatch(
        operation_identity_digest,
        request_digest,
        digest("claim-grant"),
        request.final_payload_digest,
        1_000,
    ));

    let conflicting_grant = PlannerExecutionGrantV1 {
        grant_digest: digest("different-grant"),
        final_payload_digest: request.final_payload_digest,
        revocation_frontier_digest: request.revocation_frontier_digest,
        expires_at_micros: request.expires_at_micros,
    };
    let receipt = must(super::super::terminal_receipt(
        &request,
        &conflicting_grant,
        PlannerEffectObservationV1 {
            disposition: PlannerEffectDispositionV1::Succeeded,
            outcome_digest: digest("conflicting-outcome"),
            observed_at_micros: 1_100,
        },
    ));
    let envelope = super::super::encode_terminal_receipt(&receipt);
    must(store.append_execution_record(
        PlannerStoreRecordKindV1::TerminalReceipt,
        receipt.operation_identity_digest,
        receipt.receipt_digest,
        &envelope,
    ));
    drop(store);

    let mut reopened = must(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    let mut authority = authority(&request);
    let mut executor = executor(PlannerEffectDispositionV1::Succeeded);
    let error = must_err(execute_planner_request_v1(
        &request,
        1_200,
        &mut authority,
        &mut executor,
        &mut reopened,
    ));
    assert!(matches!(
        error,
        PlannerExecutionError::Store(message)
            if message.contains("does not match durable dispatch claim")
    ));
    assert_eq!(authority.authorizations, 0);
    assert_eq!(authority.revalidations, 0);
    assert_eq!(executor.executions, 0);
    assert_eq!(executor.reconciliations, 0);
}
