use std::fmt::Debug;

use codex_hepta_control_plane::GrantRequestV1;
use codex_hepta_control_plane::PlannerAuthorityConsumerV1;
use codex_hepta_control_plane::PlannerAuthorityRevalidationV1;
use codex_hepta_control_plane::PlannerAuthorizationDecisionV1;
use codex_hepta_control_plane::PlannerEffectDispositionV1;
use codex_hepta_control_plane::PlannerEffectExecutorV1;
use codex_hepta_control_plane::PlannerEffectObservationV1;
use codex_hepta_control_plane::PlannerExecutionError;
use codex_hepta_control_plane::PlannerExecutionGrantV1;
use codex_hepta_control_plane::PlannerStoreConfigV1;
use codex_hepta_control_plane::PlannerStoreError;
use codex_hepta_control_plane::PlannerStoreFailpointV1;
use codex_hepta_control_plane::PlannerStoreRecordKindV1;
use codex_hepta_control_plane::PlannerStoreV1;
use codex_hepta_control_plane::PlannerTerminalReceiptSinkV1;
use codex_hepta_control_plane::execute_planner_request_v1;
use codex_hepta_control_plane::reconcile_planner_request_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use tempfile::tempdir;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn must_err<T, E: Debug>(result: Result<T, E>) -> E {
    match result {
        Err(error) => error,
        Ok(_) => panic!("expected error"),
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn request() -> GrantRequestV1 {
    GrantRequestV1 {
        operation_id: id("durable-effect"),
        candidate_id: id("candidate-one"),
        plan_digest: digest("plan"),
        final_payload_digest: digest("payload"),
        objective_digest: digest("objective"),
        snapshot_digest: digest("snapshot"),
        revocation_frontier_digest: digest("revocations"),
        expires_at_micros: 2_000,
    }
}

struct Authority;

impl PlannerAuthorityConsumerV1 for Authority {
    fn authorize(
        &mut self,
        request: &GrantRequestV1,
        _now_micros: u64,
    ) -> Result<PlannerAuthorizationDecisionV1, PlannerExecutionError> {
        Ok(PlannerAuthorizationDecisionV1::Granted(
            PlannerExecutionGrantV1 {
                grant_digest: digest("grant"),
                final_payload_digest: request.final_payload_digest,
                revocation_frontier_digest: request.revocation_frontier_digest,
                expires_at_micros: request.expires_at_micros,
            },
        ))
    }

    fn revalidate(
        &mut self,
        _request: &GrantRequestV1,
        _grant: &PlannerExecutionGrantV1,
        _now_micros: u64,
    ) -> Result<PlannerAuthorityRevalidationV1, PlannerExecutionError> {
        Ok(PlannerAuthorityRevalidationV1::Current)
    }
}

struct Executor {
    next: PlannerEffectDispositionV1,
}

impl PlannerEffectExecutorV1 for Executor {
    fn execute(
        &mut self,
        _request: &GrantRequestV1,
        _grant: &PlannerExecutionGrantV1,
    ) -> Result<PlannerEffectObservationV1, PlannerExecutionError> {
        Ok(PlannerEffectObservationV1 {
            disposition: self.next,
            outcome_digest: digest("first-observation"),
            observed_at_micros: 1_100,
        })
    }

    fn reconcile(
        &mut self,
        _operation_identity_digest: Digest32,
    ) -> Result<PlannerEffectObservationV1, PlannerExecutionError> {
        Ok(PlannerEffectObservationV1 {
            disposition: self.next,
            outcome_digest: digest("reconciled-observation"),
            observed_at_micros: 1_500,
        })
    }
}

fn execute_once(
    store: &mut PlannerStoreV1,
    disposition: PlannerEffectDispositionV1,
) -> codex_hepta_control_plane::PlannerTerminalReceiptV1 {
    let mut authority = Authority;
    let mut executor = Executor { next: disposition };
    must(execute_planner_request_v1(
        &request(),
        1_000,
        &mut authority,
        &mut executor,
        store,
    ))
}

#[test]
fn failed_open_releases_the_writer_lock() {
    let directory = must(tempdir());
    must(std::fs::write(
        directory.path().join("planner-store.v1.log"),
        vec![0_u8; 119],
    ));
    let error = must_err(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    assert!(matches!(error, PlannerStoreError::CorruptHeader));
    assert!(!directory.path().join("planner-store.lock").exists());

    must(std::fs::write(
        directory.path().join("planner-store.v1.log"),
        b"",
    ));
    let store = must(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    assert!(store.records().is_empty());
}

#[test]
fn exited_process_lock_is_reclaimed() {
    let directory = must(tempdir());
    let lock_path = directory.path().join("planner-store.lock");
    // A legacy token or interrupted diagnostic write is not kernel ownership.
    must(std::fs::write(&lock_path, b"stale-owner-diagnostic"));
    let store = must(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    assert!(lock_path.exists());
    #[cfg(unix)]
    let original_inode = {
        use std::os::unix::fs::MetadataExt;
        must(std::fs::metadata(&lock_path)).ino()
    };
    assert!(matches!(
        PlannerStoreV1::open(directory.path(), PlannerStoreConfigV1::default()),
        Err(PlannerStoreError::Locked)
    ));
    drop(store);
    // Keep the lock inode stable so another opener cannot lock a replacement.
    assert!(lock_path.exists());
    let reopened = must(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    assert!(reopened.records().is_empty());
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        assert_eq!(must(std::fs::metadata(&lock_path)).ino(), original_inode);
    }
}

#[test]
fn disk_full_does_not_publish_or_dirty_the_log() {
    let directory = must(tempdir());
    let mut store = must(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    store.set_failpoint(Some(PlannerStoreFailpointV1::DiskFullBeforeFrameWrite));
    let error = must_err(store.append(
        PlannerStoreRecordKindV1::Decision,
        digest("operation"),
        digest("payload"),
        b"complete decision envelope",
    ));
    assert!(matches!(error, PlannerStoreError::Io(_)));
    assert!(store.records().is_empty());
    drop(store);

    let reopened = must(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    assert!(reopened.records().is_empty());
}

#[test]
fn indeterminate_dispatch_can_converge_to_a_durable_reconciliation() {
    let directory = must(tempdir());
    let mut store = must(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    let request = request();
    let mut authority = Authority;
    let mut executor = Executor {
        next: PlannerEffectDispositionV1::Indeterminate,
    };
    let first = must(execute_planner_request_v1(
        &request,
        1_000,
        &mut authority,
        &mut executor,
        &mut store,
    ));
    assert_eq!(first.disposition, PlannerEffectDispositionV1::Indeterminate);

    executor.next = PlannerEffectDispositionV1::Succeeded;
    let reconciled = must(reconcile_planner_request_v1(
        &request,
        digest("grant"),
        &mut executor,
        &mut store,
    ));
    assert_eq!(
        reconciled.disposition,
        PlannerEffectDispositionV1::Succeeded
    );
    assert_eq!(store.records().len(), 3);
    assert_eq!(store.records()[0].kind, PlannerStoreRecordKindV1::Selection);
    assert_eq!(
        store.records()[1].kind,
        PlannerStoreRecordKindV1::TerminalReceipt
    );
    assert_eq!(
        store.records()[2].kind,
        PlannerStoreRecordKindV1::Reconciliation
    );
}

#[test]
fn valid_terminal_receipt_without_a_durable_claim_is_rejected() {
    let source_directory = must(tempdir());
    let mut source = must(PlannerStoreV1::open(
        source_directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    let receipt = execute_once(&mut source, PlannerEffectDispositionV1::Succeeded);

    let destination_directory = must(tempdir());
    let mut destination = must(PlannerStoreV1::open(
        destination_directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    let error = must_err(destination.append_terminal_receipt(&receipt));
    assert!(matches!(
        error,
        PlannerExecutionError::Store(message)
            if message.contains("requires a durable dispatch claim")
    ));
    assert!(destination.records().is_empty());
}

#[test]
fn forged_terminal_receipt_digest_is_rejected_before_store_mutation() {
    let source_directory = must(tempdir());
    let mut source = must(PlannerStoreV1::open(
        source_directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    let mut receipt = execute_once(&mut source, PlannerEffectDispositionV1::Succeeded);
    receipt.receipt_digest = digest("forged-receipt");

    let destination_directory = must(tempdir());
    let mut destination = must(PlannerStoreV1::open(
        destination_directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    let error = must_err(destination.append_terminal_receipt(&receipt));
    assert_eq!(error, PlannerExecutionError::InvalidObservation);
    assert!(destination.records().is_empty());
}

#[test]
fn conclusive_terminal_receipt_cannot_be_replaced() {
    let first_directory = must(tempdir());
    let mut first_store = must(PlannerStoreV1::open(
        first_directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    let committed = execute_once(&mut first_store, PlannerEffectDispositionV1::Succeeded);

    let conflicting_directory = must(tempdir());
    let mut conflicting_store = must(PlannerStoreV1::open(
        conflicting_directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    let conflicting = execute_once(&mut conflicting_store, PlannerEffectDispositionV1::Failed);
    assert_ne!(committed.receipt_digest, conflicting.receipt_digest);

    let error = must_err(first_store.append_reconciliation_receipt(&conflicting));
    assert!(matches!(
        error,
        PlannerExecutionError::Store(message)
            if message.contains("conclusive terminal receipt is immutable")
    ));
    assert_eq!(first_store.records().len(), 2);
}

#[test]
fn poisoned_store_cannot_return_a_stale_conclusive_dispatch() {
    let directory = must(tempdir());
    let mut store = must(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    execute_once(&mut store, PlannerEffectDispositionV1::Succeeded);

    store.set_failpoint(Some(PlannerStoreFailpointV1::AfterLogSyncBeforePublish));
    let failure = store.append(
        PlannerStoreRecordKindV1::Decision,
        digest("later-operation"),
        digest("later-payload"),
        b"later decision",
    );
    assert!(matches!(failure, Err(PlannerStoreError::Failpoint(_))));
    assert!(store.recovery_required());

    let mut authority = Authority;
    let mut executor = Executor {
        next: PlannerEffectDispositionV1::Succeeded,
    };
    let error = must_err(execute_planner_request_v1(
        &request(),
        1_100,
        &mut authority,
        &mut executor,
        &mut store,
    ));
    assert!(matches!(
        error,
        PlannerExecutionError::Store(message) if message.contains("recovery required")
    ));
}
