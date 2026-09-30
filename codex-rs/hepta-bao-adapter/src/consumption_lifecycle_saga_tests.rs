use super::*;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;

struct UncertainParentSync;

impl LeaseRegistryPersistenceV1 for UncertainParentSync {
    fn write_and_sync_temp(&self, path: &Path, bytes: &[u8]) -> std::io::Result<()> {
        FsLeaseRegistryPersistenceV1.write_and_sync_temp(path, bytes)
    }

    fn rename(&self, from: &Path, to: &Path) -> std::io::Result<()> {
        FsLeaseRegistryPersistenceV1.rename(from, to)
    }

    fn sync_parent(&self, _parent: &Path) -> std::io::Result<()> {
        Err(std::io::Error::other("injected parent sync uncertainty"))
    }
}

type ConsumptionTransition = fn(&mut DurableLeaseRegistryV1) -> Result<(), LeaseRegistryErrorV1>;

#[test]
fn indeterminate_consumption_commits_cannot_be_confirmed_by_idempotent_retry() {
    const OPERATION_ID: &str = "operation:consumption-saga";
    const RESERVATION_ID: &str = "reservation:consumption-saga";
    let success_steps: [ConsumptionTransition; 5] = [
        |owner| owner.mark_consumption_reserved(OPERATION_ID, RESERVATION_ID.into()),
        |owner| owner.mark_consumption_dispatch_fenced(OPERATION_ID, RESERVATION_ID),
        |owner| owner.enter_consumption(OPERATION_ID, receipt()),
        |owner| owner.observe_consumption(OPERATION_ID, /*succeeded*/ true),
        |owner| owner.settle_consumption(OPERATION_ID).map(|_| ()),
    ];
    let branch_steps: [(usize, ConsumptionTransition); 4] = [
        (2, |owner| {
            owner.mark_consumption_indeterminate(OPERATION_ID)
        }),
        (2, |owner| {
            owner.record_provider_failure(
                OPERATION_ID,
                "provider_denied",
                [9; 32],
                /*observed_cost*/ 1,
            )
        }),
        (3, |owner| {
            owner.observe_consumption_not_applied(OPERATION_ID, [10; 32])
        }),
        (1, |owner| {
            owner
                .record_consumption_abort(
                    OPERATION_ID,
                    /*before_dispatch*/ true,
                    "reservation_cancelled",
                    [11; 32],
                )
                .map(|_| ())
        }),
    ];
    for (setup_count, transition) in success_steps.into_iter().enumerate().chain(branch_steps) {
        let (_directory, path) = registry_path().unwrap();
        let mut owner = reopen(&path).unwrap();
        owner.claim_consumption(operation()).unwrap();
        for setup in &success_steps[..setup_count] {
            setup(&mut owner).unwrap();
        }
        owner.persistence = Arc::new(UncertainParentSync);
        assert_eq!(
            transition(&mut owner),
            Err(LeaseRegistryErrorV1::CommitIndeterminate)
        );
        assert_eq!(transition(&mut owner), Err(LeaseRegistryErrorV1::Fenced));
        drop(owner);
        let mut owner = reopen(&path).unwrap();
        transition(&mut owner).unwrap();
    }
}

#[test]
fn indeterminate_failure_settlement_requires_owner_reopen() {
    const OPERATION_ID: &str = "operation:consumption-saga";
    let (_directory, path) = registry_path().unwrap();
    let mut owner = reopen(&path).unwrap();
    owner.claim_consumption(operation()).unwrap();
    owner
        .mark_consumption_reserved(OPERATION_ID, "reservation:consumption-saga".into())
        .unwrap();
    owner
        .mark_consumption_dispatch_fenced(OPERATION_ID, "reservation:consumption-saga")
        .unwrap();
    owner
        .record_provider_failure(
            OPERATION_ID,
            "provider_denied",
            [9; 32],
            /*observed_cost*/ 1,
        )
        .unwrap();
    owner.persistence = Arc::new(UncertainParentSync);
    assert_eq!(
        owner.settle_consumption_failure(OPERATION_ID),
        Err(LeaseRegistryErrorV1::CommitIndeterminate)
    );
    assert_eq!(
        owner.settle_consumption_failure(OPERATION_ID),
        Err(LeaseRegistryErrorV1::Fenced)
    );
    drop(owner);
    assert_eq!(
        reopen(&path)
            .unwrap()
            .settle_consumption_failure(OPERATION_ID)
            .unwrap()
            .state,
        BaoConsumptionStateV1::Failed
    );
}

fn registry_path() -> std::io::Result<(tempfile::TempDir, std::path::PathBuf)> {
    let directory = tempfile::tempdir()?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let path = directory.path().join("consumption-owner.json");
    Ok((directory, path))
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
        created_revision: 0,
        updated_revision: 0,
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

fn reopen(path: &std::path::Path) -> Result<DurableLeaseRegistryV1, LeaseRegistryErrorV1> {
    DurableLeaseRegistryV1::open(path)
}

#[test]
fn claimed_reserved_and_dispatch_fenced_are_distinct_durable_states() {
    let (_directory, path) = registry_path().expect("create private registry fixture");
    let mut owner = reopen(&path).expect("reopen durable owner");
    owner.claim_consumption(operation()).expect("durable claim");
    drop(owner);

    let mut owner = reopen(&path).expect("reopen durable owner");
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

    let mut owner = reopen(&path).expect("reopen durable owner");
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

    let owner = reopen(&path).expect("reopen durable owner");
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
    let (_directory, path) = registry_path().expect("create private registry fixture");
    let mut owner = reopen(&path).expect("reopen durable owner");
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

    let mut owner = reopen(&path).expect("reopen durable owner");
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

    let mut owner = reopen(&path).expect("reopen durable owner");
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

    let mut owner = reopen(&path).expect("reopen durable owner");
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
    let (_directory, path) = registry_path().expect("create private registry fixture");
    let mut owner = reopen(&path).expect("reopen durable owner");
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
        .record_provider_failure("operation:consumption-saga", "provider_denied", [9; 32], 1)
        .unwrap();
    let revision = owner.state.revision;
    owner
        .record_provider_failure("operation:consumption-saga", "provider_denied", [9; 32], 1)
        .unwrap();
    assert_eq!(owner.state.revision, revision);
    assert_eq!(
        owner.record_provider_failure("operation:consumption-saga", "not_found", [10; 32], 1,),
        Err(LeaseRegistryErrorV1::InvalidTransition)
    );
    owner
        .settle_consumption_failure("operation:consumption-saga")
        .unwrap();
    drop(owner);

    let mut owner = reopen(&path).expect("reopen durable owner");
    let row = owner
        .settle_consumption_failure("operation:consumption-saga")
        .unwrap();
    assert_eq!(row.state, BaoConsumptionStateV1::Failed);
    assert_eq!(row.terminal_code.as_deref(), Some("provider_denied"));
    assert_eq!(row.terminal_evidence_sha256, Some([9; 32]));
}

#[test]
fn proved_not_applied_settles_as_terminal_negative_without_reentry() {
    let (_directory, path) = registry_path().expect("create private registry fixture");
    let mut owner = reopen(&path).expect("reopen durable owner");
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

    let mut owner = reopen(&path).expect("reopen durable owner");
    let row = owner
        .settle_consumption_failure("operation:consumption-saga")
        .unwrap();
    assert_eq!(row.state, BaoConsumptionStateV1::Failed);
    assert_eq!(row.terminal_kind.as_deref(), Some("consumer_not_applied"));
    assert_eq!(row.terminal_observed_cost, Some(0));
}

#[test]
fn exact_transition_retries_are_noops_and_semantic_drift_conflicts() {
    let (_directory, path) = registry_path().expect("create private registry fixture");
    let mut owner = reopen(&path).expect("reopen durable owner");
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
        owner.mark_consumption_reserved("operation:consumption-saga", "reservation:other".into(),),
        Err(LeaseRegistryErrorV1::OperationConflict)
    );
}

#[test]
fn predispatch_crash_recovery_can_close_claimed_or_reserved_rows() {
    let (_directory, path) = registry_path().expect("create private registry fixture");
    let mut owner = reopen(&path).expect("reopen durable owner");
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
fn durable_phase_recovery_and_capacity_rules_are_single_sourced() {
    assert_eq!(
        BaoConsumptionStateV1::Claimed.phase(),
        BaoConsumptionPhaseV1::Unreserved
    );
    assert_eq!(
        BaoConsumptionStateV1::Reserved.recovery_action(),
        BaoConsumptionRecoveryActionV1::CancelOrExpireReservation
    );
    assert!(BaoConsumptionStateV1::DispatchFenced.has_dispatch_fence());
    assert_eq!(
        BaoConsumptionStateV1::ProviderFailed.phase(),
        BaoConsumptionPhaseV1::TerminalEvidence
    );
    assert!(BaoConsumptionStateV1::ProviderFailed.requires_future_capacity());
    assert!(BaoConsumptionStateV1::Failed.is_terminal());
    assert!(!BaoConsumptionStateV1::Failed.requires_future_capacity());
    assert_eq!(
        BaoConsumptionStateV1::Succeeded.recovery_action(),
        BaoConsumptionRecoveryActionV1::ReturnHistoricalSuccess
    );
}

#[test]
fn terminal_failure_releases_future_capacity_but_preserves_history() {
    let (_directory, path) = registry_path().expect("create private registry fixture");
    let mut owner = reopen(&path).expect("reopen durable owner");
    owner.claim_consumption(operation()).unwrap();
    let before = owner.diagnostics().unwrap();
    assert_eq!(before.consumption_future_reserve_bytes, 4096);

    owner
        .record_consumption_abort(
            "operation:consumption-saga",
            false,
            "no_reservation",
            [15; 32],
        )
        .unwrap();
    let after = owner.diagnostics().unwrap();
    assert_eq!(after.consumption_count, 1);
    assert_eq!(after.consumption_future_reserve_bytes, 0);
    assert_eq!(
        after
            .consumption_by_state
            .get(&BaoConsumptionStateV1::Failed),
        Some(&1)
    );
    assert!(after.commit_metrics.confirmed_commits >= 2);
    assert!(after.commit_metrics.confirmed_bytes > 0);
}

#[test]
fn receipt_debug_and_telemetry_do_not_expose_sensitive_digests() {
    let receipt = receipt();
    let debug = format!("{receipt:?}");
    assert!(debug.contains("[SENSITIVE DIGEST]"));
    assert!(!debug.contains("6, 6, 6"));
    assert_eq!(
        receipt.telemetry(),
        BaoSecretTelemetryV1 {
            version: 7,
            secret_bytes: 8,
        }
    );
}
