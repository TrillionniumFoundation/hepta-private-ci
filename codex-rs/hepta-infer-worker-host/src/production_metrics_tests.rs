use super::*;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use std::fs::OpenOptions;
use std::io::Write;

fn native_request(id: &str) -> NativeRequest {
    NativeRequest {
        request_id: id.to_string(),
        principal_id: "principal.1".to_string(),
        worker_generation: 2,
        model: "model".to_string(),
        payload_digest: "a".repeat(64),
    }
}

#[test]
fn live_native_wal_emits_durable_metrics_and_both_journals_reopen() {
    let dir = tempfile::tempdir().expect("dir");
    let journal = dir.path().join("native-control.wal");
    let metrics = production_metrics_journal_path_v1(&journal).expect("metrics path");
    assert_ne!(journal, metrics);
    {
        let mut control = open_metrics_bound_native_control_v1(&journal, 32).expect("bootstrap");
        assert!(control.production_metrics_ready());
        control
            .reserve_native(native_request("request.1"), 1)
            .expect("real WAL commit");
        assert!(control.flush_production_metrics());
        assert!(std::fs::metadata(&metrics).expect("metrics file").len() > 0);
    }
    {
        let reopened = open_metrics_bound_native_control_v1(&journal, 32).expect("replay");
        assert!(reopened.native_record("request.1").is_some());
        assert!(reopened.production_metrics_ready());
        assert!(reopened.flush_production_metrics());
    }
}

#[test]
fn damaged_evidence_journal_denies_serving_without_mutating_control_wal() {
    let dir = tempfile::tempdir().expect("dir");
    let journal = dir.path().join("native-control.wal");
    let metrics = production_metrics_journal_path_v1(&journal).expect("metrics path");
    {
        let mut control = open_metrics_bound_native_control_v1(&journal, 32).expect("bootstrap");
        control
            .reserve_native(native_request("request.1"), 1)
            .expect("real WAL commit");
        assert!(control.flush_production_metrics());
    }
    let control_bytes = std::fs::read(&journal).expect("control bytes");
    OpenOptions::new()
        .append(true)
        .open(&metrics)
        .expect("metrics file")
        .write_all(b"torn-group-without-newline")
        .expect("damage metrics");
    assert!(open_metrics_bound_native_control_v1(&journal, 32).is_err());
    assert_eq!(std::fs::read(&journal).expect("control after denial"), control_bytes);
    let read_only_control = DurableInferenceControl::open(&journal, 32).expect("WAL integrity");
    assert!(read_only_control.native_record("request.1").is_some());
}

#[test]
fn relative_native_journals_cannot_satisfy_production_readiness() {
    assert!(production_metrics_journal_path_v1(Path::new("control.wal")).is_err());
}

#[cfg(unix)]
#[test]
fn native_production_wal_refuses_unsafe_files_directories_and_aliases() {
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::fs::symlink;

    let dir = tempfile::tempdir().expect("private root");
    let journal = dir.path().join("control.wal");
    {
        let control =
            open_metrics_bound_native_control_v1(&journal, 32).expect("private bootstrap");
        assert!(control.production_metrics_ready());
    }
    let before = std::fs::read(&journal).expect("WAL bytes");

    std::fs::set_permissions(&journal, std::fs::Permissions::from_mode(0o644))
        .expect("relax WAL mode");
    assert!(open_metrics_bound_native_control_v1(&journal, 32).is_err());
    std::fs::set_permissions(&journal, std::fs::Permissions::from_mode(0o600))
        .expect("restore WAL mode");

    let alias = dir.path().join("alias.wal");
    symlink(&journal, &alias).expect("alias WAL");
    assert!(open_metrics_bound_native_control_v1(&alias, 32).is_err());

    let exposed = dir.path().join("writable-by-others");
    std::fs::create_dir(&exposed).expect("make exposed directory");
    std::fs::set_permissions(&exposed, std::fs::Permissions::from_mode(0o777))
        .expect("expose directory");
    assert!(open_metrics_bound_native_control_v1(&exposed.join("control.wal"), 32).is_err());
    assert_eq!(std::fs::read(&journal).expect("unmodified WAL"), before);
}

#[cfg(unix)]
#[test]
fn native_production_wal_rejects_hardlink_alias() {
    let dir = tempfile::tempdir().expect("private root");
    let journal = dir.path().join("control.wal");
    {
        let control = open_metrics_bound_native_control_v1(&journal, 32).expect("initial writer");
        assert!(control.production_metrics_ready());
    }
    std::fs::hard_link(&journal, dir.path().join("second-name.wal"))
        .expect("make hardlink");
    assert!(open_metrics_bound_native_control_v1(&journal, 32).is_err());
}

#[test]
fn native_production_bootstrap_requires_exclusive_wal_and_metrics_writers() {
    let dir = tempfile::tempdir().expect("private root");
    let journal = dir.path().join("control.wal");
    let metrics = production_metrics_journal_path_v1(&journal).expect("metrics path");
    {
        let first = open_metrics_bound_native_control_v1(&journal, 32).expect("first owner");
        assert!(open_metrics_bound_native_control_v1(&journal, 32).is_err());
        assert!(first.production_metrics_ready());
    }
    {
        let locked_metrics =
            codex_hepta_agentd::DurablePhaseMetricSinkV1::open(&metrics, 16, 8, 25)
                .expect("standalone Evidence writer");
        assert!(open_metrics_bound_native_control_v1(&journal, 32).is_err());
        assert!(locked_metrics.healthy());
    }
    let reopened = open_metrics_bound_native_control_v1(&journal, 32).expect("both locks released");
    assert!(reopened.production_metrics_ready());
}

#[cfg(unix)]
#[test]
fn native_production_bootstrap_denies_hardlinked_metrics_without_touching_wal() {
    let dir = tempfile::tempdir().expect("private root");
    let journal = dir.path().join("control.wal");
    let metrics = production_metrics_journal_path_v1(&journal).expect("metrics path");
    {
        let mut owner = open_metrics_bound_native_control_v1(&journal, 32)
            .expect("initial production owner");
        owner
            .reserve_native(native_request("request.1"), 1)
            .expect("durable native WAL");
        assert!(owner.flush_production_metrics());
    }
    let wal_before = std::fs::read(&journal).expect("WAL before");
    let metrics_before = std::fs::read(&metrics).expect("metrics before");
    let alias = dir.path().join("metrics-second-name");
    std::fs::hard_link(&metrics, &alias).expect("hardlink metrics inode");
    assert!(open_metrics_bound_native_control_v1(&journal, 32).is_err());
    assert_eq!(std::fs::read(&journal).expect("WAL unchanged"), wal_before);
    assert_eq!(std::fs::read(&metrics).expect("metrics unchanged"), metrics_before);
    std::fs::remove_file(&alias).expect("unlink alias");
    let reopened = open_metrics_bound_native_control_v1(&journal, 32)
        .expect("recovery once metrics alias removed");
    assert!(reopened.native_record("request.1").is_some());
    assert!(reopened.production_metrics_ready());
}

#[cfg(unix)]
#[test]
fn native_startup_denies_directory_sync_failure_before_admitting_effects() {
    let dir = tempfile::tempdir().expect("private journal directory");
    let journal = dir.path().join("native-control.wal");
    let metrics = production_metrics_journal_path_v1(&journal).expect("metrics path");
    let mut barrier_called = false;
    let error = open_native_control_with_directory_barrier_v1(&journal, 32, |path| {
        barrier_called = true;
        assert_eq!(path, journal.as_path());
        assert!(path.exists(), "control WAL must be created before directory fsync");
        assert!(
            metrics.exists(),
            "Evidence journal must be created before directory fsync"
        );
        Err(io::Error::other("injected parent fsync failure"))
    });
    assert!(error.is_err(), "startup must fail closed on sync failure");
    assert!(barrier_called);
    // A failed bootstrap releases both exclusive locks without forging a
    // successful journal record or discarding either journal.
    assert_eq!(std::fs::metadata(&journal).expect("control WAL").len(), 0);
    let reopened = open_metrics_bound_native_control_v1(&journal, 32)
        .expect("locks released after failed directory fsync");
    assert!(reopened.production_metrics_ready());
    assert_eq!(std::fs::metadata(&metrics).expect("metrics").len(), 0);
}
