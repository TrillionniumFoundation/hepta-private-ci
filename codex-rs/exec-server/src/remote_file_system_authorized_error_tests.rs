use super::ExecServerError;
use super::map_authorized_read_remote_error;
use pretty_assertions::assert_eq;
use std::io::ErrorKind;

#[test]
fn known_authorized_read_failures_preserve_local_error_contract() {
    let cases = [
        (-32600, "Permission denied", ErrorKind::PermissionDenied),
        (
            -32603,
            "authorized file read exceeds bound",
            ErrorKind::InvalidData,
        ),
        (-32004, "No such file or directory", ErrorKind::NotFound),
    ];
    for (code, message, expected_kind) in cases {
        let error = map_authorized_read_remote_error(ExecServerError::Server {
            code,
            message: message.to_string(),
        });
        assert_eq!((error.kind(), error.to_string()), (expected_kind, message.to_string()));
    }
}

#[test]
fn remote_diagnostics_with_private_details_remain_redacted() {
    let cases = [
        (-32600, "Permission denied: /private/secret", ErrorKind::InvalidInput),
        (-32603, "authorized file read exceeds bound: /private/secret", ErrorKind::Other),
        (-32004, "No such file or directory: /private/secret", ErrorKind::NotFound),
        (-32603, "Permission denied", ErrorKind::Other),
        (-32600, "authorized file read exceeds bound", ErrorKind::InvalidInput),
    ];
    for (code, message, expected_kind) in cases {
        let error = map_authorized_read_remote_error(ExecServerError::Server {
            code,
            message: message.to_string(),
        });
        assert_eq!(error.kind(), expected_kind);
        assert!(!error.to_string().contains("/private/secret"));
        assert_ne!(error.to_string(), message);
    }
}
