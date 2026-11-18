use pretty_assertions::assert_eq;
use std::io;

use super::INVALID_REQUEST_ERROR_CODE;
use super::READ_EXCEEDED;
use super::map_authorized_read_remote_error;
use super::map_classified_authorized_read_remote_error;
use crate::ExecServerError;
use crate::authorized_read_error::AuthorizedReadRpcError;
use crate::rpc::AUTHORIZED_READ_BOUND_EXCEEDED_ERROR_CODE;

#[test]
fn typed_oversize_error_retains_its_kind_and_fixed_message() {
    for message in [
        "authorized file read exceeds bound",
        "/private/secret server detail",
    ] {
        let error = map_authorized_read_remote_error(ExecServerError::Server {
            code: AUTHORIZED_READ_BOUND_EXCEEDED_ERROR_CODE,
            message: message.to_string(),
        });
        assert_eq!(error.kind(), io::ErrorKind::InvalidData);
        assert_eq!(error.to_string(), "authorized file read exceeds bound");
    }
}

#[test]
fn exact_legacy_oversize_error_preserves_kind_without_server_details() {
    let error = map_authorized_read_remote_error(ExecServerError::Server {
        code: -32603,
        message: "authorized file read exceeds bound".to_string(),
    });
    assert_eq!(error.kind(), io::ErrorKind::InvalidData);
    assert_eq!(error.to_string(), READ_EXCEEDED);
}

#[test]
fn legacy_oversize_lookalikes_remain_redacted_failures() {
    for (code, message) in [
        (
            -32603,
            "authorized file read exceeds bound: /private/secret",
        ),
        (-1, "authorized file read exceeds bound"),
        (-32603, "/private/secret internal failure"),
    ] {
        let error = map_authorized_read_remote_error(ExecServerError::Server {
            code,
            message: message.to_string(),
        });
        assert_eq!(error.kind(), io::ErrorKind::Other);
        assert_eq!(error.to_string(), "remote authorized file read failed");
    }
}

#[test]
fn authorized_read_denials_keep_the_existing_redacted_message() {
    for code in [INVALID_REQUEST_ERROR_CODE, -32602] {
        let error = map_authorized_read_remote_error(ExecServerError::Server {
            code,
            message: "/private/secret permission detail".to_string(),
        });
        assert_eq!(error.kind(), io::ErrorKind::InvalidInput);
        assert_eq!(
            error.to_string(),
            "remote authorized file read is not permitted"
        );
    }
}

#[test]
fn typed_authorized_read_errors_preserve_fixed_kind_and_message() {
    use crate::authorized_read_error::AuthorizedReadFailure;

    for (failure, expected_kind, expected_message) in [
        (
            AuthorizedReadFailure::PermissionDenied,
            io::ErrorKind::PermissionDenied,
            "Permission denied",
        ),
        (
            AuthorizedReadFailure::BoundExceeded,
            io::ErrorKind::InvalidData,
            "authorized file read exceeds bound",
        ),
    ] {
        let error = map_classified_authorized_read_remote_error(AuthorizedReadRpcError {
            failure: Some(failure),
            error: ExecServerError::Server {
                code: failure.rpc_error().code,
                message: "secret peer detail".to_string(),
            },
        });
        assert_eq!(error.kind(), expected_kind);
        assert_eq!(error.to_string(), expected_message);
    }
}

#[test]
fn old_peer_or_unknown_metadata_uses_existing_redacted_error_fallback() {
    for (code, expected_kind, expected_message) in [
        (
            -32600,
            io::ErrorKind::InvalidInput,
            "remote authorized file read is not permitted",
        ),
        (
            -32602,
            io::ErrorKind::InvalidInput,
            "remote authorized file read is not permitted",
        ),
        (
            -32603,
            io::ErrorKind::Other,
            "remote authorized file read failed",
        ),
        (
            -32601,
            io::ErrorKind::Unsupported,
            "remote exec-server does not support stable-handle authorized reads",
        ),
        (
            -32004,
            io::ErrorKind::NotFound,
            "remote authorized file is unavailable",
        ),
        (
            -32099,
            io::ErrorKind::Other,
            "remote authorized file read failed",
        ),
    ] {
        let error = map_classified_authorized_read_remote_error(
            AuthorizedReadRpcError::unclassified(ExecServerError::Server {
                code,
                message: "secret peer detail".to_string(),
            }),
        );
        assert_eq!(error.kind(), expected_kind);
        assert_eq!(error.to_string(), expected_message);
    }
}
