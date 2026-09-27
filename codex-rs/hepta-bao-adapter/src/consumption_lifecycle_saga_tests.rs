use super::*;
use std::os::unix::fs::PermissionsExt;

fn registry_path() -> (tempfile::TempDir, std::path::PathBuf) {
    let directory = tempfile::tempdir().expect("temporary directory");
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private directory");
    let path = directory.path().join("consumption-owner.json");
    (directory, path)
}

fn operation() -> BaoConsumptionOperationV1 {
    BaoConsumptionOperationV1 {
        operation_id: "operation:consumption-saga".into(),
        semantic_sha256: [1; 32],
        effect_sha256: [2; 32],
        request_sha256: [3; 32],
        consumer_id: "model-provider".into(),
        consumer_configuration_sha256: [4; 32],
        amount: 1,
        reservation_id: None,
        state: BaoConsumptionStateV1::Claimed,
        receipt: None,
        terminal_kind: None,
        terminal_code: None,
        terminal_evidence_sha256: None,
        terminal_observed_cost: None,
    }
}

fn receipt() -> BaoSecretReceipt {
    BaoSecretReceipt {
        request_sha256: [3; 32],
        response_sha256: [5; 32],
        secret_sha256: [6; 32],
        version: 7,
        secret_bytes: 8,
    }
}

fn reopen(path: &std::path::Path) -> DurableLeaseRegistryV1 {
    DurableLeaseRegistryV1::open(path).expect("reopen durable owner")
}

#[test]
fn claimed_reserved_and_dispatch_fenced_are_distinct_durable_states() {
    let (_directory, path) = registry_path();
    let mut owner = reopen(&path);
    owner.claim_consumption(operation()).expect("durable claim");
    drop(owner);

    let mut owner = reopen(&path);
    assert_eq!(
        owner
            .consumption_result("operation:consumption-saga")
            .expect("claimed row")
            .state,
        BaoConsumptionStateV1::Claimed
    );
    owner
        .mark_consumption_reserved(
            "operation:consumption-saga",
            "reservation:consumption-saga".into(),
        )
        .expect("bind reservation");
    drop(owner);

    let mut owner = reopen(&path);
    assert_eq!(
        owner
            .consumption_result("operation:consumption-saga")
            .expect("reserved row")
            .state,
        BaoConsumptionStateV1::Reserved
    );
    owner
        .mark_consumption_dispatch_fenced(
            "operation:consumption-saga",
            "reservation:consumption-saga",
        )
        .expect("commit dispatch fence");
    drop(owner);

    let owner = reopen(&path);
    assert_eq!(
        owner
            .consumption_result("operation:consumption-saga")
            .expect("dispatch-fenced row")
            .state,
        BaoConsumptionStateV1::DispatchFenced
    );
}

#[test]
fn every_success_boundary_reopens_without_redispatch() {
    let (_directory, path) = registry_path();
    let mut owner = reopen(&path);
    owner.claim_consumption(operation()).unwrap();
    owner
        .mark_consumption_reserved(
            "operation:consumption-saga",
            "reservation:consumption-saga".into(),
        )
        .unwrap();
    owner
        .mark_consumption_dispatch_fenced(
            "operation:consumption-saga",
            "reservation:consumption-saga",
        )
        .unwrap();
    owner
        .enter_consumption("operation:consumption-saga", receipt())
        .unwrap();
    drop(owner);

    let mut owner = reopen(&path);
    assert_eq!(
        owner
            .consumption_result("operation:consumption-saga")
            .unwrap()
            .state,
        BaoConsumptionStateV1::DeliveryPrepared
    );
    owner
        .observe_consumption("operation:consumption-saga", true)
        .unwrap();
    drop(owner);

    let mut owner = reopen(&path);
    assert_eq!(
        owner
            .consumption_result("operation:consumption-saga")
            .unwrap()
            .state,
        BaoConsumptionStateV1::ConsumerSucceeded
    );
    let stored = owner
        .settle_consumption("operation:consumption-saga")
        .unwrap();
    assert_eq!(stored, receipt());
    drop(owner);

    let mut owner = reopen(&path);
    assert_eq!(
        owner
            .settle_consumption("operation:consumption-saga")
            .unwrap(),
        receipt()
    );
    assert_eq!(
        owner
            .consumption_result("operation:consumption-saga")
            .unwrap()
            .state,
        BaoConsumptionStateV1::Succeeded
    );
}

#[test]
fn deterministic_provider_failure_is_immutable_and_terminal() {
    let (_directory, path) = registry_path();
    let mut owner = reopen(&path);
    owner.claim_consumption(operation()).unwrap();
    owner
        .mark_consumption_reserved(
            "operation:consumption-saga",
            "reservation:consumption-saga".into(),
        )
        .unwrap();
    owner
        .mark_consumption_dispatch_fenced(
            "operation:consumption-saga",
            "reservation:consumption-saga",
        )
        .unwrap();
    owner
        .record_provider_failure(
            "operation:consumption-saga",
            "provider_denied",
            [9; 32],
            1,
        )
        .unwrap();
    let revision = owner.state.revision;
    owner
        .record_provider_failure(
            "operation:consumption-saga",
            "provider_denied",
            [9; 32],
            1,
        )
        .unwrap();
    assert_eq!(owner.state.revision, revision);
    assert_eq!(
        owner.record_provider_failure(
            "operation:consumption-saga",
            "not_found",
            [10; 32],
            1,
        ),
        Err(LeaseRegistryErrorV1::InvalidTransition)
    );
    owner
        .settle_consumption_failure("operation:consumption-saga")
        .unwrap();
    drop(owner);

    let mut owner = reopen(&path);
    let row = owner
        .settle_consumption_failure("operation:consumption-saga")
        .unwrap();
    assert_eq!(row.state, BaoConsumptionStateV1::Failed);
    assert_eq!(row.terminal_code.as_deref(), Some("provider_denied"));
    assert_eq!(row.terminal_evidence_sha256, Some([9; 32]));
}

#[test]
fn proved_not_applied_settles_as_terminal_negative_without_reentry() {
    let (_directory, path) = registry_path();
    let mut owner = reopen(&path);
    owner.claim_consumption(operation()).unwrap();
    owner
        .mark_consumption_reserved(
            "operation:consumption-saga",
            "reservation:consumption-saga".into(),
        )
        .unwrap();
    owner
        .mark_consumption_dispatch_fenced(
            "operation:consumption-saga",
            "reservation:consumption-saga",
        )
        .unwrap();
    owner
        .enter_consumption("operation:consumption-saga", receipt())
        .unwrap();
    owner
        .mark_consumption_indeterminate("operation:consumption-saga")
        .unwrap();
    owner
        .observe_consumption_not_applied("operation:consumption-saga", [11; 32])
        .unwrap();
    drop(owner);

    let mut owner = reopen(&path);
    let row = owner
        .settle_consumption_failure("operation:consumption-saga")
        .unwrap();
    assert_eq!(row.state, BaoConsumptionStateV1::Failed);
    assert_eq!(row.terminal_kind.as_deref(), Some("consumer_not_applied"));
    assert_eq!(row.terminal_observed_cost, Some(0));
}

#[test]
fn exact_transition_retries_are_noops_and_semantic_drift_conflicts() {
    let (_directory, path) = registry_path();
    let mut owner = reopen(&path);
    owner.claim_consumption(operation()).unwrap();
    let revision = owner.state.revision;
    assert!(owner.claim_consumption(operation()).unwrap().is_some());
    assert_eq!(owner.state.revision, revision);

    let mut changed = operation();
    changed.effect_sha256 = [12; 32];
    assert_eq!(
        owner.claim_consumption(changed),
        Err(LeaseRegistryErrorV1::OperationConflict)
    );
    owner
        .mark_consumption_reserved(
            "operation:consumption-saga",
            "reservation:consumption-saga".into(),
        )
        .unwrap();
    let revision = owner.state.revision;
    owner
        .mark_consumption_reserved(
            "operation:consumption-saga",
            "reservation:consumption-saga".into(),
        )
        .unwrap();
    assert_eq!(owner.state.revision, revision);
    assert_eq!(
        owner.mark_consumption_reserved(
            "operation:consumption-saga",
            "reservation:other".into(),
        ),
        Err(LeaseRegistryErrorV1::OperationConflict)
    );
}

#[test]
fn predispatch_crash_recovery_can_close_claimed_or_reserved_rows() {
    let (_directory, path) = registry_path();
    let mut owner = reopen(&path);
    owner.claim_consumption(operation()).unwrap();
    owner
        .record_consumption_abort(
            "operation:consumption-saga",
            false,
            "no_reservation",
            [13; 32],
        )
        .unwrap();
    assert_eq!(
        owner
            .consumption_result("operation:consumption-saga")
            .unwrap()
            .state,
        BaoConsumptionStateV1::Failed
    );

    let mut second = operation();
    second.operation_id = "operation:reserved-crash".into();
    owner.claim_consumption(second).unwrap();
    owner
        .mark_consumption_reserved(
            "operation:reserved-crash",
            "reservation:reserved-crash".into(),
        )
        .unwrap();
    owner
        .record_consumption_abort(
            "operation:reserved-crash",
            true,
            "reservation_cancelled",
            [14; 32],
        )
        .unwrap();
    assert_eq!(
        owner
            .consumption_result("operation:reserved-crash")
            .unwrap()
            .state,
        BaoConsumptionStateV1::Failed
    );
}

#[test]
fn schema_three_success_reopens_without_inventing_or_discarding_history() {
    for state in [BaoConsumptionStateV1::ConsumerSucceeded, BaoConsumptionStateV1::Succeeded] {
        let (_directory, path) = registry_path();
        let mut owner = reopen(&path);
        let mut row = operation();
        row.state = state;
        row.reservation_id = Some("reservation:legacy".into());
        row.receipt = Some(receipt());
        // Construct a genuine schema-3 document: terminal fields did not exist.
        owner.state.schema_version = 3;
        owner.state.consumptions.insert(row.operation_id.clone(), row.clone());
        std::fs::write(&path, serde_json::to_vec(&owner.state).unwrap()).unwrap();
        drop(owner);
        let owner = reopen(&path);
        let recovered = owner.consumption_result(&row.operation_id).unwrap();
        assert_eq!(recovered.state, state);
        assert_eq!(recovered.receipt, row.receipt);
        assert_eq!(recovered.terminal_evidence_sha256, Some(receipt_digest(&receipt()).unwrap()));
        assert_eq!(recovered.terminal_observed_cost, Some(row.amount));
    }
}

#[test]
fn schema_three_missing_success_receipt_is_not_fabricated() {
    let (_directory, path) = registry_path();
    let mut owner = reopen(&path);
    let mut row = operation();
    row.state = BaoConsumptionStateV1::Succeeded;
    row.reservation_id = Some("reservation:legacy".into());
    owner.state.schema_version = 3;
    owner.state.consumptions.insert(row.operation_id.clone(), row);
    std::fs::write(&path, serde_json::to_vec(&owner.state).unwrap()).unwrap();
    drop(owner);
    assert!(matches!(DurableLeaseRegistryV1::open(&path), Err(LeaseRegistryErrorV1::CorruptState)));
}

#[test]
fn fenced_owner_cannot_acknowledge_an_idempotent_transition() {
    let (_directory, path) = registry_path();
    let mut owner = reopen(&path);
    let op = "operation:consumption-saga";
    owner.claim_consumption(operation()).unwrap();
    owner.mark_consumption_reserved(op, "reservation:original".into()).unwrap();
    owner.mark_consumption_dispatch_fenced(op, "reservation:original").unwrap();
    owner.enter_consumption(op, receipt()).unwrap();
    owner.observe_consumption(op, true).unwrap();
    owner.settle_consumption(op).unwrap();
    owner.fenced = true;
    assert_eq!(owner.mark_consumption_reserved(op, "reservation:original".into()), Err(LeaseRegistryErrorV1::Fenced));
    assert_eq!(owner.mark_consumption_dispatch_fenced(op, "reservation:original"), Err(LeaseRegistryErrorV1::Fenced));
    assert_eq!(owner.enter_consumption(op, receipt()), Err(LeaseRegistryErrorV1::Fenced));
    assert_eq!(owner.observe_consumption(op, true), Err(LeaseRegistryErrorV1::Fenced));
    assert_eq!(owner.settle_consumption(op), Err(LeaseRegistryErrorV1::Fenced));
}

#[test]
fn schema_three_completed_lease_result_does_not_need_legacy_requalification() {
    let (_directory, path) = registry_path();
    let mut owner = reopen(&path);
    owner.prepare_issue("lease:issue".into(), [17; 32]).unwrap();
    owner.reconcile("lease:issue", ProviderLeaseObservationV1::IssueApplied {
        lease: SecretLeaseMetadataV1 {
            lease_id: "lease:original".into(),
            secret_reference_id: "secret:original".into(),
            consumer_id: "model-provider".into(),
            scope_sha256: [18; 32],
            provider_metadata_sha256: [19; 32],
            issued_at_unix_ms: 1_000,
            expires_at_unix_ms: 2_000,
            renewable: true,
            generation: 1,
            state: SecretLeaseStateV1::Active,
        }
    }).unwrap();
    let expected = owner.operation_result("lease:issue").unwrap();
    owner.state.schema_version = 3;
    std::fs::write(&path, serde_json::to_vec(&owner.state).unwrap()).unwrap();
    drop(owner);
    let owner = reopen(&path);
    assert_eq!(owner.operation_result("lease:issue").unwrap(), expected);
}

#[test]
fn postfence_without_delivery_can_close_but_cannot_refund() {
    for unknown in [false, true] {
        let (_directory, path) = registry_path();
        let mut owner = reopen(&path);
        let op = "operation:consumption-saga";
        owner.claim_consumption(operation()).unwrap();
        owner.mark_consumption_reserved(op, "reservation:original".into()).unwrap();
        owner.mark_consumption_dispatch_fenced(op, "reservation:original").unwrap();
        if unknown { owner.mark_consumption_indeterminate(op).unwrap(); }
        drop(owner);
        let mut owner = reopen(&path);
        let _exclusive_recovery = owner.consumption_execution(op).unwrap();
        owner.record_delivery_abort(op).unwrap();
        let before = owner.consumption_result(op).unwrap();
        owner.record_delivery_abort(op).unwrap();
        assert_eq!(owner.consumption_result(op).unwrap(), before);
        let terminal = owner.settle_consumption_failure(op).unwrap();
        assert_eq!(terminal.terminal_observed_cost, Some(terminal.amount));
        assert_eq!(terminal.terminal_code.as_deref(), Some("delivery_not_prepared"));
        assert!(terminal.receipt.is_none());
    }
}

#[test]
fn prepared_delivery_cannot_be_reclassified_as_never_prepared() {
    let (_directory, path) = registry_path();
    let mut owner = reopen(&path);
    let op = "operation:consumption-saga";
    owner.claim_consumption(operation()).unwrap();
    owner.mark_consumption_reserved(op, "reservation:original".into()).unwrap();
    owner.mark_consumption_dispatch_fenced(op, "reservation:original").unwrap();
    owner.enter_consumption(op, receipt()).unwrap();
    assert_eq!(owner.record_delivery_abort(op), Err(LeaseRegistryErrorV1::InvalidTransition));
    owner.mark_consumption_indeterminate(op).unwrap();
    assert_eq!(owner.record_delivery_abort(op), Err(LeaseRegistryErrorV1::InvalidTransition));
}
