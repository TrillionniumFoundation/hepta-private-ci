use std::fmt::Debug;

use codex_hepta_control_plane::GrantRequestV1;
use codex_hepta_control_plane::PlannerAuthorizationDecisionV1;
use codex_hepta_control_plane::PlannerAuthorityConsumerV1;
use codex_hepta_control_plane::PlannerAuthorityRevalidationV1;
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

#[cfg(target_os = "linux")]
#[test]
fn exited_process_lock_is_reclaimed() {
    let directory = must(tempdir());
    must(std::fs::write(
        directory.path().join("planner-store.lock"),
        b"4294967295:0",
    ));
    let store = must(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    assert!(directory.path().join("planner-store.lock").exists());
    drop(store);
    assert!(!directory.path().join("planner-store.lock").exists());
}

#[test]
fn disk_full_does_not_publish_or_dirty_the_log() {
    let directory = must(tempdir());
    let mut store = must(PlannerStoreV1::open(
        directory.path(),
        PlannerStoreConfigV1::default(),
    ));
    store.set_failpoint(Some(
        PlannerStoreFailpointV1::DiskFullBeforeFrameWrite,
    ));
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
    assert_eq!(reconciled.disposition, PlannerEffectDispositionV1::Succeeded);
    assert_eq!(store.records().len(), 3);
    assert_eq!(
        store.records()[0].kind,
        PlannerStoreRecordKindV1::Selection
    );
    assert_eq!(
        store.records()[1].kind,
        PlannerStoreRecordKindV1::TerminalReceipt
    );
    assert_eq!(
        store.records()[2].kind,
        PlannerStoreRecordKindV1::Reconciliation
    );
}
