use hepta_native::model::{OperationKey, PlatformPayload};
use hepta_native::platform::{PlatformAdapter, PlatformPolicy, SystemPlatformAdapter};

#[test]
fn replacing_a_confirmed_path_is_rejected_before_launch() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("document.txt");
    std::fs::write(&path, b"same bytes").unwrap();
    let payload = PlatformPayload::OpenPath { path: path.clone() };
    let mut platform = SystemPlatformAdapter::new(
        PlatformPolicy::new(vec![temp.path().to_path_buf()], false, false).unwrap(),
    );
    let old = platform.confirmation_resource(&payload).unwrap();
    assert!(old.is_some());
    assert!(platform.permission(&payload).unwrap().allowed);
    std::fs::rename(&path, temp.path().join("original.txt")).unwrap();
    std::fs::write(&path, b"same bytes").unwrap();
    assert_ne!(old, platform.confirmation_resource(&payload).unwrap());
    let key = OperationKey {
        session_id: "session.1".to_owned(),
        session_generation: 1,
        operation_id: "operation.1".to_owned(),
    };
    assert!(platform.invoke_confirmed(&key, &payload, &old).is_err());
}

#[test]
fn repeated_resource_snapshot_is_stable_for_unchanged_object() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("document.txt");
    std::fs::write(&path, b"stable").unwrap();
    let payload = PlatformPayload::RevealPath { path };
    let platform = SystemPlatformAdapter::new(
        PlatformPolicy::new(vec![temp.path().to_path_buf()], false, false).unwrap(),
    );
    assert_eq!(
        platform.confirmation_resource(&payload).unwrap(),
        platform.confirmation_resource(&payload).unwrap()
    );
}
