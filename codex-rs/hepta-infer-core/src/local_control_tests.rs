use super::*;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

struct Journal(PathBuf);

impl Journal {
    fn new() -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let time = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        Self(std::env::temp_dir().join(format!(
            "hepta-local-{time}-{}.journal",
            NEXT.fetch_add(1, Ordering::SeqCst)
        )))
    }
    fn open(&self) -> DurableInferenceControl {
        DurableInferenceControl::open(&self.0, 32).unwrap()
    }
}

impl Drop for Journal {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

fn request(id: &str) -> LocalRequest {
    LocalRequest {
        operation_id: id.into(),
        kind: LocalOperationKind::Load,
        worker_id: "worker".into(),
        worker_generation: 1,
        device_lease_id: "device".into(),
        model_digest: "1".repeat(64),
        model_tuple_digest: "2".repeat(64),
        request_digest: "3".repeat(64),
        payload_digest: "4".repeat(64),
        runtime_digest: "5".repeat(64),
        model_operation_id: None,
        reservation_bytes: 60,
        maximum_tokens: 32,
        deadline_unix_ms: 1000,
        policy: LocalResourcePolicy {
            maximum_memory_bytes: 100,
            maximum_models: 2,
            maximum_active_requests: 2,
        },
    }
}

fn dispatch(handle: Option<&str>) -> LocalDispatch {
    LocalDispatch {
        grant_id: "grant".into(),
        authority_witness_digest: "6".repeat(64),
        nonce_digest: "7".repeat(64),
        physical_handle_id: handle.map(str::to_string),
    }
}

fn observation() -> LocalObservation {
    LocalObservation {
        status: LocalTerminalStatus::Succeeded,
        physical_handle_id: Some("handle".into()),
        output: None,
        consumed_tokens: None,
        observed_memory_bytes: 60,
        correlation_digest: "8".repeat(64),
    }
}

fn loaded(control: &mut DurableInferenceControl) {
    control.reserve_local(request("load"), 100).unwrap();
    control.prepare_local("load", dispatch(None)).unwrap();
    control.observe_local("load", observation()).unwrap();
}

fn run(id: &str) -> LocalRequest {
    LocalRequest {
        operation_id: id.into(),
        kind: LocalOperationKind::Run,
        model_operation_id: Some("load".into()),
        reservation_bytes: 30,
        ..request(id)
    }
}

#[test]
fn every_local_boundary_reopens_without_reissuing_a_permit() {
    let file = Journal::new();
    let mut control = file.open();
    control.reserve_local(request("load"), 100).unwrap();
    let reserved = control.local_record("load").unwrap().clone();
    drop(control);
    let mut control = file.open();
    assert_eq!(control.local_record("load"), Some(&reserved));
    let permit = control.prepare_local("load", dispatch(None)).unwrap();
    assert_eq!(permit.operation_id(), "load");
    let dispatching = control.local_record("load").unwrap().clone();
    drop(permit);
    drop(control);
    let mut control = file.open();
    assert_eq!(control.local_record("load"), Some(&dispatching));
    assert!(control.prepare_local("load", dispatch(None)).is_err());
    control.mark_local_indeterminate("load", 200).unwrap();
    let unknown = control.local_record("load").unwrap().clone();
    drop(control);
    let mut control = file.open();
    assert_eq!(
        control.reserve_local(request("load"), 9000).unwrap(),
        unknown
    );
    assert_eq!(control.local_reserved_bytes("device").unwrap(), 60);
    control.observe_local("load", observation()).unwrap();
    let resident = control.local_record("load").unwrap().clone();
    drop(control);
    let mut control = file.open();
    assert_eq!(
        control.reserve_local(request("load"), 9000).unwrap(),
        resident
    );
    assert_eq!(control.local_reserved_bytes("device").unwrap(), 60);
    control.begin_local_unload("load").unwrap();
    drop(control);
    let mut control = file.open();
    assert_eq!(
        control.local_record("load").unwrap().state,
        LocalState::Unloading
    );
    assert_eq!(control.local_reserved_bytes("device").unwrap(), 60);
    control
        .observe_local_unloaded("load", "9".repeat(64))
        .unwrap();
    let released = control.local_record("load").unwrap().clone();
    drop(control);
    let mut control = file.open();
    assert_eq!(
        control.reserve_local(request("load"), 9000).unwrap(),
        released
    );
    assert_eq!(control.local_reserved_bytes("device").unwrap(), 0);
}

#[test]
fn aggregate_memory_and_policy_survive_generation_and_restart() {
    let file = Journal::new();
    let mut control = file.open();
    loaded(&mut control);
    drop(control);
    let mut control = file.open();
    let mut other = request("other");
    other.worker_generation = 2;
    assert_eq!(
        control.reserve_local(other.clone(), 100),
        Err(Error::CapacityExceeded)
    );
    other.policy.maximum_memory_bytes = 200;
    assert_eq!(control.reserve_local(other, 100), Err(Error::Conflict));
    assert_eq!(control.local_reserved_bytes("device").unwrap(), 60);
}

#[test]
fn unknown_run_holds_capacity_and_blocks_unload_until_terminal() {
    let file = Journal::new();
    let mut control = file.open();
    loaded(&mut control);
    control.reserve_local(run("run"), 101).unwrap();
    assert!(
        control
            .prepare_local("run", dispatch(Some("wrong")))
            .is_err()
    );
    control
        .prepare_local("run", dispatch(Some("handle")))
        .unwrap();
    control.cancel_local("run", 150).unwrap();
    assert_eq!(
        control.begin_local_unload("load"),
        Err(Error::InvalidTransition)
    );
    assert_eq!(
        control.reserve_local(run("second"), 150),
        Err(Error::CapacityExceeded)
    );
    let unknown = control.local_record("run").unwrap().clone();
    drop(control);
    let mut control = file.open();
    assert_eq!(control.local_record("run"), Some(&unknown));
    let terminal = LocalObservation {
        output: Some("result".into()),
        observed_memory_bytes: 30,
        ..observation()
    };
    control.observe_local("run", terminal.clone()).unwrap();
    let before = std::fs::read(&file.0).unwrap();
    control.observe_local("run", terminal).unwrap();
    assert_eq!(std::fs::read(&file.0).unwrap(), before);
    assert_eq!(control.local_reserved_bytes("device").unwrap(), 60);
    control.begin_local_unload("load").unwrap();
}

#[test]
fn failed_load_with_live_handle_is_not_a_resource_refund() {
    let file = Journal::new();
    let mut control = file.open();
    control.reserve_local(request("load"), 100).unwrap();
    control.prepare_local("load", dispatch(None)).unwrap();
    control
        .observe_local(
            "load",
            LocalObservation {
                status: LocalTerminalStatus::Failed,
                ..observation()
            },
        )
        .unwrap();
    assert_eq!(
        control.local_record("load").unwrap().state,
        LocalState::Unloading
    );
    assert_eq!(control.local_reserved_bytes("device").unwrap(), 60);
    drop(control);
    let mut control = file.open();
    assert_eq!(control.local_reserved_bytes("device").unwrap(), 60);
    control
        .observe_local_unloaded("load", "9".repeat(64))
        .unwrap();
    assert_eq!(control.local_reserved_bytes("device").unwrap(), 0);
}

#[test]
fn live_abort_refunds_but_recovered_dispatch_cannot_mint_an_abort() {
    let file = Journal::new();
    let mut control = file.open();
    control.reserve_local(request("load"), 100).unwrap();
    let permit = control.prepare_local("load", dispatch(None)).unwrap();
    control.abort_local_before_effect(permit).unwrap();
    assert_eq!(control.local_reserved_bytes("device").unwrap(), 0);
    drop(control);
    let mut control = file.open();
    assert_eq!(
        control.local_record("load").unwrap().state,
        LocalState::Cancelled
    );
    assert!(control.prepare_local("load", dispatch(None)).is_err());
}

#[test]
fn identity_drift_is_rejected_without_journal_mutation() {
    let file = Journal::new();
    let mut control = file.open();
    control.reserve_local(request("load"), 100).unwrap();
    let original = std::fs::read(&file.0).unwrap();
    for index in 0..5 {
        let mut changed = request("load");
        match index {
            0 => changed.deadline_unix_ms += 1,
            1 => changed.payload_digest = "a".repeat(64),
            2 => changed.model_tuple_digest = "b".repeat(64),
            3 => changed.reservation_bytes += 1,
            _ => changed.policy.maximum_active_requests += 1,
        }
        assert_eq!(control.reserve_local(changed, 100), Err(Error::Conflict));
    }
    assert_eq!(std::fs::read(&file.0).unwrap(), original);
}

#[test]
fn fencing_survives_reopen_and_does_not_prevent_cleanup() {
    let file = Journal::new();
    let mut control = file.open();
    loaded(&mut control);
    control.fence_local_generation("device", 1).unwrap();
    drop(control);
    let mut control = file.open();
    assert!(control.local_generation_fenced("device", 1));
    assert_eq!(control.reserve_local(run("run"), 100), Err(Error::Conflict));
    control.begin_local_unload("load").unwrap();
    control
        .observe_local_unloaded("load", "9".repeat(64))
        .unwrap();
    assert_eq!(control.local_reserved_bytes("device").unwrap(), 0);
    assert!(control.local_generation_fenced("device", 1));
}

#[test]
fn unknown_and_zero_usage_remain_distinct_across_replay() {
    let file = Journal::new();
    let mut control = file.open();
    loaded(&mut control);
    for (id, usage) in [("unknown", None), ("zero", Some(0))] {
        control.reserve_local(run(id), 100).unwrap();
        control.prepare_local(id, dispatch(Some("handle"))).unwrap();
        control
            .observe_local(
                id,
                LocalObservation {
                    output: Some(String::new()),
                    consumed_tokens: usage,
                    observed_memory_bytes: 30,
                    ..observation()
                },
            )
            .unwrap();
    }
    drop(control);
    let control = file.open();
    assert_eq!(
        control
            .local_record("unknown")
            .unwrap()
            .observation
            .as_ref()
            .unwrap()
            .consumed_tokens,
        None
    );
    assert_eq!(
        control
            .local_record("zero")
            .unwrap()
            .observation
            .as_ref()
            .unwrap()
            .consumed_tokens,
        Some(0)
    );
}

#[test]
fn exclusive_owner_and_cross_profile_identities_cannot_be_bypassed() {
    let file = Journal::new();
    let mut control = file.open();
    assert!(matches!(
        DurableInferenceControl::open(&file.0, 32),
        Err(Error::WriterUnavailable)
    ));
    control.reserve_local(request("load"), 100).unwrap();
    let hosted = crate::durable_control::native::NativeRequest {
        request_id: "load".into(),
        principal_id: "owner".into(),
        worker_generation: 1,
        model: "model".into(),
        payload_digest: "a".repeat(64),
    };
    assert_eq!(control.reserve_native(hosted, 1), Err(Error::Conflict));
}

#[test]
fn expired_new_admission_and_partial_journal_fail_closed() {
    use std::io::Write;
    let file = Journal::new();
    let mut control = file.open();
    assert_eq!(
        control.reserve_local(request("load"), 1000),
        Err(Error::InvalidTime)
    );
    control.reserve_local(request("load"), 100).unwrap();
    drop(control);
    std::fs::OpenOptions::new()
        .append(true)
        .open(&file.0)
        .unwrap()
        .write_all(b"local-v1|{\"Prepare\":")
        .unwrap();
    assert!(matches!(
        DurableInferenceControl::open(&file.0, 32),
        Err(Error::CorruptJournal("incomplete line"))
    ));
}
