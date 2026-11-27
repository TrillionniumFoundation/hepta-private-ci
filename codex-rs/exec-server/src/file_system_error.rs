use std::io;

use codex_exec_server_protocol::JSONRPCErrorError;

use crate::rpc::internal_error;
use crate::rpc::invalid_request;
use crate::rpc::not_found;

/// Filesystem execution is unsupported, rather than denied by a working sandbox.
pub(crate) const UNSUPPORTED_FILE_SYSTEM_ERROR_CODE: i64 = -32005;

pub(crate) fn map_fs_error(error: io::Error) -> JSONRPCErrorError {
    match error.kind() {
        io::ErrorKind::NotFound => not_found(error.to_string()),
        io::ErrorKind::InvalidInput | io::ErrorKind::PermissionDenied => {
            invalid_request(error.to_string())
        }
        io::ErrorKind::Unsupported => JSONRPCErrorError {
            code: UNSUPPORTED_FILE_SYSTEM_ERROR_CODE,
            message: error.to_string(),
            data: None,
        },
        _ => internal_error(error.to_string()),
    }
}

pub(crate) fn file_system_error_kind(code: i64) -> io::ErrorKind {
    match code {
        -32004 => io::ErrorKind::NotFound,
        -32600 => io::ErrorKind::InvalidInput,
        UNSUPPORTED_FILE_SYSTEM_ERROR_CODE => io::ErrorKind::Unsupported,
        _ => io::ErrorKind::Other,
    }
}
