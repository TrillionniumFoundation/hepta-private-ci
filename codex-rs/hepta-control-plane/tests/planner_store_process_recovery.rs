use std::io::BufRead;
use std::io::BufReader;
use std::path::Path;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;

use codex_hepta_control_plane::PlannerStoreConfigV1;
use codex_hepta_control_plane::PlannerStoreError;
use codex_hepta_control_plane::PlannerStoreRecordKindV1;
use codex_hepta_control_plane::PlannerStoreV1;
use codex_hepta_types::Digest32;
use tempfile::tempdir;

const CRASH_ENVELOPE: &[u8] = b"planner-store-process-synced-record-v1";

struct ChildGuard(Child);

impl ChildGuard {
    fn kill_and_wait(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

impl Drop for ChildGuard {
    fn drop(&mut self) {
        self.kill_and_wait();
    }
}

fn fixture() -> &'static str {
    env!("CARGO_BIN_EXE_planner_store_process_fixture")
}

fn spawn_lock_holder(root: &Path) -> std::io::Result<ChildGuard> {
    let child = Command::new(fixture())
        .arg("hold")
        .arg(root)
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()?;
    // Own cleanup before any fallible readiness operation.
    let mut holder = ChildGuard(child);
    let stdout = holder
        .0
        .stdout
        .take()
        .ok_or_else(|| std::io::Error::other("planner store holder stdout is unavailable"))?;
    let mut line = String::new();
    BufReader::new(stdout).read_line(&mut line)?;
    if line.trim() != "READY" {
        return Err(std::io::Error::other(
            "planner store holder did not become ready",
        ));
    }
    Ok(holder)
}

#[test]
fn operating_system_lock_is_reclaimed_after_abnormal_owner_exit() {
    let directory = tempdir().expect("temporary store");
    let mut holder = spawn_lock_holder(directory.path()).expect("ready store holder");
    assert!(matches!(
        PlannerStoreV1::open(directory.path(), PlannerStoreConfigV1::default()),
        Err(PlannerStoreError::Locked)
    ));

    holder.kill_and_wait();
    let reopened = PlannerStoreV1::open(directory.path(), PlannerStoreConfigV1::default())
        .expect("reopen after killed owner");
    assert!(reopened.records().is_empty());
}

#[test]
fn synced_frame_survives_abort_without_drop_or_in_memory_publish() {
    let directory = tempdir().expect("temporary store");
    let status = Command::new(fixture())
        .arg("crash-after-sync")
        .arg(directory.path())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .expect("run crash fixture");
    assert!(!status.success());

    let reopened = PlannerStoreV1::open(directory.path(), PlannerStoreConfigV1::default())
        .expect("reopen synced frame");
    assert_eq!(reopened.records().len(), 1);
    let record = &reopened.records()[0];
    assert_eq!(record.kind, PlannerStoreRecordKindV1::Decision);
    assert_eq!(
        record.operation_identity_digest,
        Digest32::of_bytes(b"planner-store-process-operation-v1")
    );
    assert_eq!(
        record.payload_digest,
        Digest32::of_bytes(b"planner-store-process-payload-v1")
    );
    assert_eq!(record.envelope, CRASH_ENVELOPE);
}

#[test]
fn restore_holds_the_destination_owner_boundary_for_the_whole_replacement() {
    let source = tempdir().expect("source store");
    let backup = tempdir().expect("backup store");
    let destination = tempdir().expect("destination store");
    let anchor = Digest32::of_bytes(b"planner-store-process-anchor-v1");

    let mut source_store = PlannerStoreV1::open(source.path(), PlannerStoreConfigV1::default())
        .expect("open source store");
    source_store
        .append(
            PlannerStoreRecordKindV1::Decision,
            Digest32::of_bytes(b"restore-operation-v1"),
            Digest32::of_bytes(b"restore-payload-v1"),
            b"restore-envelope-v1",
        )
        .expect("append source record");
    source_store.checkpoint(anchor).expect("checkpoint source");
    source_store
        .backup_to(backup.path())
        .expect("backup source");
    drop(source_store);

    let mut holder = spawn_lock_holder(destination.path()).expect("ready destination holder");
    assert!(matches!(
        PlannerStoreV1::restore_from_backup(
            backup.path(),
            destination.path(),
            PlannerStoreConfigV1::default(),
        ),
        Err(PlannerStoreError::Locked)
    ));
    holder.kill_and_wait();

    let restored = PlannerStoreV1::restore_from_backup(
        backup.path(),
        destination.path(),
        PlannerStoreConfigV1::default(),
    )
    .expect("restore after destination owner exits");
    assert_eq!(restored.records().len(), 1);
    restored
        .verify_checkpoint(anchor)
        .expect("verify restored checkpoint");
}
