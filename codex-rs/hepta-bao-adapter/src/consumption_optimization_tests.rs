use super::*;
use std::os::unix::fs::PermissionsExt;
use std::sync::atomic::{AtomicUsize, Ordering};

fn fixture() -> (tempfile::TempDir, std::path::PathBuf) {
    let dir = tempfile::tempdir().unwrap();
    std::fs::set_permissions(dir.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let path = dir.path().join("owner.json");
    (dir, path)
}
fn operation(id: &str) -> BaoConsumptionOperationV1 {
    BaoConsumptionOperationV1 { operation_id: id.into(), semantic_sha256: [1; 32], effect_sha256: [2; 32],
        request_sha256: [3; 32], consumer_id: "consumer:fixture".into(), consumer_configuration_sha256: [4; 32],
        amount: 1, created_at_unix_ms: Some(100), reservation_id: None, state: BaoConsumptionStateV1::Claimed,
        receipt: None, terminal_kind: None, terminal_code: None, terminal_evidence_sha256: None, terminal_observed_cost: None }
}
fn receipt() -> BaoSecretReceipt {
    BaoSecretReceipt { request_sha256: [3; 32], response_sha256: [5; 32], secret_sha256: [6; 32], version: 1, secret_bytes: 8 }
}
fn legacy_file(path: &std::path::Path, state: &str, schema: u32) {
    let mut row = serde_json::to_value(operation("op:legacy")).unwrap();
    let map = row.as_object_mut().unwrap();
    for key in ["created_at_unix_ms", "terminal_kind", "terminal_code", "terminal_evidence_sha256", "terminal_observed_cost"] { map.remove(key); }
    map.insert("state".into(), serde_json::json!(state));
    map.insert("reservation_id".into(), serde_json::json!("reservation:legacy"));
    map.insert("receipt".into(), serde_json::to_value(receipt()).unwrap());
    let doc = serde_json::json!({"schema_version":schema,"revision":8,"time_frontier_unix_ms":0,
        "operations":{},"leases":{},"consumptions":{"op:legacy":row}});
    std::fs::write(path, serde_json::to_vec(&doc).unwrap()).unwrap();
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600)).unwrap();
}

#[test]
fn legacy_success_records_reopen_without_inventing_current_terminal_evidence() {
    for (old, expected) in [("consumer_succeeded", BaoConsumptionStateV1::LegacyConsumerSucceeded), ("succeeded", BaoConsumptionStateV1::LegacySucceeded)] {
        let (_dir, path) = fixture();
        legacy_file(&path, old, 3);
        let original = std::fs::read(&path).unwrap();
        let mut owner = DurableLeaseRegistryV1::open(&path).unwrap();
        let row = owner.consumption_result("op:legacy").unwrap();
        assert_eq!(row.state, expected); assert_eq!(row.receipt, Some(receipt()));
        assert_eq!(row.terminal_evidence_sha256, None);
        assert_eq!(std::fs::read(&path).unwrap(), original);
        assert_eq!(owner.settle_consumption("op:legacy"), Err(LeaseRegistryErrorV1::InvalidTransition));
        owner.claim_consumption(operation("op:new")).unwrap();
        drop(owner);
        let owner = DurableLeaseRegistryV1::open(&path).unwrap();
        assert_eq!(owner.consumption_result("op:legacy").unwrap(), row);
        assert_eq!(owner.state.schema_version, 4);
    }
}

#[test]
fn current_schema_missing_terminal_tuple_is_corruption_not_a_migration() {
    let (_dir, path) = fixture(); legacy_file(&path, "succeeded", 4);
    assert_eq!(DurableLeaseRegistryV1::open(&path).unwrap_err(), LeaseRegistryErrorV1::CorruptState);
}

#[test]
fn partial_legacy_terminal_tuple_is_never_filled_in() {
    let (_dir, path) = fixture(); legacy_file(&path, "succeeded", 3);
    let mut doc: serde_json::Value = serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    doc["consumptions"]["op:legacy"]["terminal_kind"] = serde_json::json!("success");
    std::fs::write(&path, serde_json::to_vec(&doc).unwrap()).unwrap();
    assert_eq!(DurableLeaseRegistryV1::open(&path).unwrap_err(), LeaseRegistryErrorV1::CorruptState);
}

#[test]
fn failed_history_releases_only_future_reserve_not_deduplication_identity() {
    let (_dir, path) = fixture(); let mut owner = DurableLeaseRegistryV1::open(&path).unwrap();
    owner.claim_consumption(operation("op:failed")).unwrap();
    owner.record_consumption_abort("op:failed", crate::lease_lifecycle::BaoAbortStage::BeforeReservation, "no_reservation", [7; 32]).unwrap();
    let terminal = owner.consumption_result("op:failed").unwrap();
    let mut next = owner.state.clone();
    for i in 0..3000 {
        let mut row = terminal.clone(); row.operation_id = format!("op:failed:{i}");
        next.consumptions.insert(row.operation_id.clone(), row);
    }
    owner.commit(next, 0).unwrap();
    let summary = owner.diagnostics(1000).unwrap();
    assert_eq!(summary.consumption_result_reserve_bytes, 0);
    assert_eq!(summary.terminal_count, 3001);
    assert!(summary.encoded_store_bytes < MAX_STORE_BYTES);
    assert_eq!(owner.claim_consumption(operation("op:failed")).unwrap(), Some(terminal));
}

#[test]
fn terminal_idempotent_paths_reject_a_fenced_owner() {
    let (_dir, path) = fixture(); let mut owner = DurableLeaseRegistryV1::open(&path).unwrap();
    owner.claim_consumption(operation("op:failed")).unwrap();
    owner.record_consumption_abort("op:failed", crate::lease_lifecycle::BaoAbortStage::BeforeReservation, "no_reservation", [7; 32]).unwrap();
    owner.fenced = true;
    assert_eq!(owner.settle_consumption_failure("op:failed"), Err(LeaseRegistryErrorV1::Fenced));
    assert_eq!(owner.record_consumption_abort("op:failed", crate::lease_lifecycle::BaoAbortStage::BeforeReservation, "no_reservation", [7; 32]), Err(LeaseRegistryErrorV1::Fenced));
}

#[test]
fn recovery_cursor_advances_past_pending_and_terminal_rows_with_bounded_scan() {
    let (_dir, path) = fixture(); let mut owner = DurableLeaseRegistryV1::open(&path).unwrap();
    for id in ["op:a", "op:b", "op:c"] { owner.claim_consumption(operation(id)).unwrap(); }
    owner.record_consumption_abort("op:b", crate::lease_lifecycle::BaoAbortStage::BeforeReservation, "no_reservation", [7; 32]).unwrap();
    let first = owner.pending_consumptions(None, 2).unwrap();
    assert_eq!(first.operation_ids, vec!["op:a".to_owned()]);
    assert_eq!(first.scanned, 2);
    let second = owner.pending_consumptions(first.next_after.as_deref(), 2).unwrap();
    assert_eq!(second.operation_ids, vec!["op:c".to_owned()]); assert!(second.next_after.is_none());
    assert!(owner.pending_consumptions(None, 257).is_err());
}

#[test]
fn diagnostics_separate_unknown_age_future_age_and_sensitive_debug() {
    let (_dir, path) = fixture(); let mut owner = DurableLeaseRegistryV1::open(&path).unwrap();
    let mut unknown = operation("op:unknown"); unknown.created_at_unix_ms = None;
    let mut future = operation("op:future"); future.created_at_unix_ms = Some(2000);
    for row in [operation("op:known"), unknown, future] { owner.claim_consumption(row).unwrap(); }
    let summary = owner.diagnostics(1000).unwrap();
    assert_eq!(summary.oldest_pending_age_ms, Some(900)); assert_eq!(summary.pending_age_unknown, 1);
    assert_eq!(summary.future_dated_pending, 1); assert_eq!(summary.consumption_result_reserve_bytes, 3 * 4096);
    let row = owner.consumption_result("op:known").unwrap();
    for text in [format!("{row:?}"), format!("{:?}", receipt()), serde_json::to_string(&summary).unwrap()] {
        assert!(!text.contains("op:known")); assert!(!text.contains("consumer:fixture"));
        assert!(!text.contains("[6, 6, 6")); assert!(!text.contains("secret_sha256"));
    }
}

struct CrashPersistence { cut: usize, count: AtomicUsize }
impl CrashPersistence { fn boundary(&self) { if self.count.fetch_add(1, Ordering::SeqCst) + 1 == self.cut { std::process::exit(86); } } }
impl LeaseRegistryPersistenceV1 for CrashPersistence {
    fn write_and_sync_temp(&self, path: &std::path::Path, bytes: &[u8]) -> std::io::Result<()> {
        self.boundary(); FsLeaseRegistryPersistenceV1.write_and_sync_temp(path, bytes)?; self.boundary(); Ok(())
    }
    fn rename(&self, from: &std::path::Path, to: &std::path::Path) -> std::io::Result<()> {
        self.boundary(); FsLeaseRegistryPersistenceV1.rename(from, to)?; self.boundary(); Ok(())
    }
    fn sync_parent(&self, path: &std::path::Path) -> std::io::Result<()> {
        self.boundary(); FsLeaseRegistryPersistenceV1.sync_parent(path)?; self.boundary(); Ok(())
    }
}

#[test]
fn crash_child() {
    let Ok(path) = std::env::var("HEPTA_BAO_OWNER_CRASH_PATH") else { return; };
    let cut = std::env::var("HEPTA_BAO_OWNER_CRASH_CUT").unwrap().parse().unwrap();
    let mut owner = DurableLeaseRegistryV1::open_with_persistence(path, Arc::new(CrashPersistence { cut, count: AtomicUsize::new(0) })).unwrap();
    owner.claim_consumption(operation("op:crash")).unwrap();
    owner.mark_consumption_reserved("op:crash", "reservation:crash".into()).unwrap();
    owner.mark_consumption_dispatch_fenced("op:crash", "reservation:crash").unwrap();
    owner.enter_consumption("op:crash", receipt()).unwrap();
    owner.observe_consumption("op:crash", true).unwrap();
    owner.settle_consumption("op:crash").unwrap();
}

#[test]
fn thirty_six_process_exit_boundaries_preserve_reopen_and_deduplication() {
    for cut in 1..=36 {
        let (_dir, path) = fixture(); drop(DurableLeaseRegistryV1::open(&path).unwrap());
        let output = std::process::Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "lease_lifecycle::consumption::optimization_tests::crash_child", "--nocapture"])
            .env("HEPTA_BAO_OWNER_CRASH_PATH", &path).env("HEPTA_BAO_OWNER_CRASH_CUT", cut.to_string()).output().unwrap();
        assert_eq!(output.status.code(), Some(86), "cut={cut}; {}", String::from_utf8_lossy(&output.stdout));
        let mut owner = DurableLeaseRegistryV1::open(&path).unwrap();
        match owner.consumption_result("op:crash") {
            Ok(before) => assert_eq!(owner.claim_consumption(operation("op:crash")).unwrap(), Some(before)),
            Err(LeaseRegistryErrorV1::OperationNotFound) => { assert!(owner.claim_consumption(operation("op:crash")).unwrap().is_none()); }
            other => panic!("unexpected recovery {other:?}"),
        }
        assert_eq!(owner.state.consumptions.len(), 1);
    }
}
