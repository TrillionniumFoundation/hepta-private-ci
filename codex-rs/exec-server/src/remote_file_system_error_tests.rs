use std::io;

use codex_exec_server_protocol::JSONRPCErrorError;
use pretty_assertions::assert_eq;

use super::map_authorized_read_remote_error;
use super::map_remote_error;
use crate::ExecServerError;
use crate::file_system_error::map_fs_error;

#[test]
fn filesystem_error_round_trip_uses_type_and_code_not_message() {
    let message = "Unsupported sandbox: failed to write file";
    let cases = [
        (
            io::ErrorKind::Unsupported,
            -32005,
            io::ErrorKind::Unsupported,
        ),
        (io::ErrorKind::Other, -32603, io::ErrorKind::Other),
        (io::ErrorKind::NotFound, -32004, io::ErrorKind::NotFound),
        (
            io::ErrorKind::InvalidInput,
            -32600,
            io::ErrorKind::InvalidInput,
        ),
        (
            io::ErrorKind::PermissionDenied,
            -32600,
            io::ErrorKind::InvalidInput,
        ),
    ];
    for (kind, expected_code, expected_kind) in cases {
        let wire = serde_json::to_vec(&map_fs_error(io::Error::new(kind, message)))
            .expect("encode filesystem error");
        let response: JSONRPCErrorError =
            serde_json::from_slice(&wire).expect("decode filesystem error");
        assert_eq!(response.code, expected_code);
        let mapped = map_remote_error(ExecServerError::Server {
            code: response.code,
            message: response.message,
        });
        assert_eq!(
            (mapped.kind(), mapped.to_string()),
            (expected_kind, message.to_string()),
        );
    }
}

#[test]
fn authorized_read_unsupported_code_preserves_redaction() {
    let cases = [
        (
            -32005,
            io::ErrorKind::Unsupported,
            "remote authorized file read is unsupported",
        ),
        (
            -32603,
            io::ErrorKind::Other,
            "remote authorized file read failed",
        ),
    ];
    for (code, expected_kind, expected_message) in cases {
        let mapped = map_authorized_read_remote_error(ExecServerError::Server {
            code,
            message: "Unsupported sandbox at SECRET-path".to_string(),
        });
        assert_eq!(
            (mapped.kind(), mapped.to_string()),
            (expected_kind, expected_message.to_string()),
        );
    }
}
