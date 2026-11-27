use super::map_authorized_read_remote_error;
use crate::ExecServerError;
use pretty_assertions::assert_eq;
use std::io;

#[test]
fn authorized_read_preserves_only_exact_path_free_server_errors() {
    let cases = [
        (
            -32600,
            "Permission denied",
            io::ErrorKind::PermissionDenied,
            "Permission denied",
        ),
        (
            -32603,
            "authorized file read exceeds bound",
            io::ErrorKind::InvalidData,
            "authorized file read exceeds bound",
        ),
        (
            -32602,
            "Permission denied",
            io::ErrorKind::InvalidInput,
            "remote authorized file read was rejected",
        ),
        (
            -32603,
            "Permission denied",
            io::ErrorKind::Other,
            "remote authorized file read failed",
        ),
        (
            -32600,
            "authorized file read exceeds bound",
            io::ErrorKind::InvalidInput,
            "remote authorized file read was rejected",
        ),
        (
            -32600,
            "Permission denied: SECRET-path",
            io::ErrorKind::InvalidInput,
            "remote authorized file read was rejected",
        ),
        (
            -32603,
            "authorized file read exceeds bound: SECRET-path",
            io::ErrorKind::Other,
            "remote authorized file read failed",
        ),
    ];
    for (code, message, expected_kind, expected_message) in cases {
        let error = map_authorized_read_remote_error(ExecServerError::Server {
            code,
            message: message.to_string(),
        });
        assert_eq!(
            (error.kind(), error.to_string()),
            (expected_kind, expected_message.to_string()),
            "unexpected mapping for code={code}, message={message}"
        );
    }
}
