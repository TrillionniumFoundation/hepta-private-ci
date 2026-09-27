use hepta_native::model::{OperationKey, PlatformPayload};
use hepta_native::platform::{PlatformAdapter, PlatformPolicy, SystemPlatformAdapter};

#[test]
fn path_effects_remain_unavailable_before_and_after_resource_replacement() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("document.txt");
    std::fs::write(&path, b"same bytes").unwrap();
    let mut platform = SystemPlatformAdapter::new(
        PlatformPolicy::new(vec![temp.path().to_path_buf()], false, false).unwrap(),
    );
    let key = OperationKey {
        session_id: "session.1".to_owned(),
        session_generation: 1,
        operation_id: "operation.1".to_owned(),
    };
    for replaced in [false, true] {
        if replaced {
            std::fs::rename(&path, temp.path().join("original.txt")).unwrap();
            std::fs::write(&path, b"same bytes").unwrap();
        }
        for payload in [
            PlatformPayload::OpenPath { path: path.clone() },
            PlatformPayload::RevealPath { path: path.clone() },
        ] {
            assert!(!platform.permission(&payload).unwrap().allowed);
            assert!(platform.confirmation_resource(&payload).is_err());
            assert!(platform.invoke_confirmed(&key, &payload, &None).is_err());
            assert!(platform.invoke(&key, &payload).is_err());
        }
    }
}
