use pretty_assertions::assert_eq;

use super::*;

#[test]
fn authorized_read_failure_metadata_roundtrips_without_remote_messages() {
    for failure in [
        AuthorizedReadFailure::PermissionDenied,
        AuthorizedReadFailure::BoundExceeded,
    ] {
        let mut error = failure.rpc_error();
        error.message = "secret path or peer-controlled detail".to_string();
        assert_eq!(AuthorizedReadFailure::from_rpc_error(&error), Some(failure));
        assert_eq!(failure.into_io_error().to_string(), failure.message());
    }
}

#[test]
fn absent_malformed_unknown_and_wrong_method_metadata_is_not_classified() {
    let invalid_data = [
        None,
        Some(serde_json::Value::Null),
        Some(serde_json::json!("permissionDenied")),
        Some(serde_json::json!([])),
        Some(serde_json::json!({})),
        Some(
            serde_json::json!({"method": FS_READ_FILE_AUTHORIZED_METHOD, "kind": "permissionDenied"}),
        ),
        Some(
            serde_json::json!({"method": FS_READ_FILE_AUTHORIZED_METHOD, "version": "1", "kind": "permissionDenied"}),
        ),
        Some(
            serde_json::json!({"method": FS_READ_FILE_AUTHORIZED_METHOD, "version": 2, "kind": "permissionDenied"}),
        ),
        Some(
            serde_json::json!({"method": FS_READ_FILE_AUTHORIZED_METHOD, "version": 1, "kind": "unknown"}),
        ),
        Some(
            serde_json::json!({"method": FS_READ_FILE_AUTHORIZED_METHOD, "version": 1, "kind": 1}),
        ),
        Some(
            serde_json::json!({"method": "fs/readFile", "version": 1, "kind": "permissionDenied"}),
        ),
        Some(
            serde_json::json!({"method": FS_READ_FILE_AUTHORIZED_METHOD, "version": 1, "kind": "permissionDenied", "extra": true}),
        ),
    ];
    for data in invalid_data {
        let error = JSONRPCErrorError {
            code: -32600,
            message: "Permission denied".to_string(),
            data,
        };
        assert_eq!(AuthorizedReadFailure::from_rpc_error(&error), None);
    }
}

#[test]
fn recognized_metadata_requires_matching_legacy_error_code() {
    for failure in [
        AuthorizedReadFailure::PermissionDenied,
        AuthorizedReadFailure::BoundExceeded,
    ] {
        for code in [-32600, -32603, -32601, -32602, -32004, -32000, 0] {
            let mut error = failure.rpc_error();
            error.code = code;
            assert_eq!(
                AuthorizedReadFailure::from_rpc_error(&error),
                (code == failure.rpc_code()).then_some(failure)
            );
        }
    }
}

// Diagnostic-only: fail rather than count unsupported early returns as native coverage.
#[test]
fn diagnostic_macos_arm_stable_handle_capability_is_required() {
    assert!(cfg!(all(target_os = "macos", target_arch = "aarch64")));
    assert!(
        crate::local_environment_info()
            .capabilities
            .stable_handle_authorized_read
    );
}
