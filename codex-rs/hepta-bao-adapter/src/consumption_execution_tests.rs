use super::*;
use std::os::unix::fs::PermissionsExt;

#[test]
fn concurrent_recovery_is_excluded_and_drop_releases_identity() {
    let root = tempfile::tempdir().unwrap();
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700)).unwrap();
    let owner = DurableLeaseRegistryV1::open(root.path().join("owner.json")).unwrap();
    let guard = owner.consumption_execution("operation:one").unwrap();
    assert!(matches!(owner.consumption_execution("operation:one"), Err(LeaseRegistryErrorV1::WriterBusy)));
    let other = owner.consumption_execution("operation:two").unwrap();
    drop(guard);
    let recovered = owner.consumption_execution("operation:one").unwrap();
    drop((other, recovered));
    assert!(owner.executions.0.lock().unwrap().is_empty());
}
#[test]
fn in_flight_guard_retains_os_writer_exclusion_after_registry_drop() {
    let root = tempfile::tempdir().unwrap();
    fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700)).unwrap();
    let path = root.path().join("owner.json");
    let owner = DurableLeaseRegistryV1::open(&path).unwrap();
    let guard = owner.consumption_execution("operation:retained").unwrap();
    drop(owner);
    assert!(matches!(DurableLeaseRegistryV1::open(&path), Err(LeaseRegistryErrorV1::WriterBusy)));
    drop(guard);
    DurableLeaseRegistryV1::open(&path).unwrap();
}
