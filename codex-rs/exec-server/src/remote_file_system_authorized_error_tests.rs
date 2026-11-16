use pretty_assertions::assert_eq;
use std::io;

use super::INVALID_REQUEST_ERROR_CODE;
use super::READ_EXCEEDED;
use super::map_authorized_read_remote_error;
use crate::ExecServerError;
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
