use std::io;

use codex_exec_server_protocol::JSONRPCErrorError;

use crate::ExecServerError;
use crate::protocol::FS_READ_FILE_AUTHORIZED_METHOD;

/// Optional metadata on the existing JSON-RPC error envelope, scoped to the
/// authorized-read method. Legacy error codes and the public client API remain
/// unchanged; old or unrecognized metadata must use the legacy redacted path.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum AuthorizedReadFailure {
    PermissionDenied,
    BoundExceeded,
}

#[derive(Debug)]
pub(crate) struct AuthorizedReadRpcError {
    pub(crate) failure: Option<AuthorizedReadFailure>,
    pub(crate) error: ExecServerError,
}

impl AuthorizedReadRpcError {
    pub(crate) fn unclassified(error: ExecServerError) -> Self {
        Self {
            failure: None,
            error,
        }
    }
}

impl AuthorizedReadFailure {
    pub(crate) fn from_io_kind(kind: io::ErrorKind) -> Option<Self> {
        match kind {
            io::ErrorKind::PermissionDenied => Some(Self::PermissionDenied),
            io::ErrorKind::InvalidData => Some(Self::BoundExceeded),
            _ => None,
        }
    }

    pub(crate) fn rpc_error(self) -> JSONRPCErrorError {
        JSONRPCErrorError {
            code: self.rpc_code(),
            message: self.message().to_string(),
            data: Some(serde_json::json!({
                "method": FS_READ_FILE_AUTHORIZED_METHOD,
                "version": 1,
                "kind": self.wire_kind(),
            })),
        }
    }

    pub(crate) fn from_rpc_error(error: &JSONRPCErrorError) -> Option<Self> {
        let data = error.data.as_ref()?.as_object()?;
        if data.len() != 3
            || data.get("method")?.as_str()? != FS_READ_FILE_AUTHORIZED_METHOD
            || data.get("version")?.as_u64()? != 1
        {
            return None;
        }
        let failure = match data.get("kind")?.as_str()? {
            "permissionDenied" => Self::PermissionDenied,
            "boundExceeded" => Self::BoundExceeded,
            _ => return None,
        };
        (error.code == failure.rpc_code()).then_some(failure)
    }

    pub(crate) fn into_io_error(self) -> io::Error {
        let kind = match self {
            Self::PermissionDenied => io::ErrorKind::PermissionDenied,
            Self::BoundExceeded => io::ErrorKind::InvalidData,
        };
        io::Error::new(kind, self.message())
    }

    fn rpc_code(self) -> i64 {
        match self {
            Self::PermissionDenied => -32600,
            Self::BoundExceeded => -32603,
        }
    }

    fn wire_kind(self) -> &'static str {
        match self {
            Self::PermissionDenied => "permissionDenied",
            Self::BoundExceeded => "boundExceeded",
        }
    }

    fn message(self) -> &'static str {
        match self {
            Self::PermissionDenied => "Permission denied",
            Self::BoundExceeded => "authorized file read exceeds bound",
        }
    }
}

#[cfg(test)]
#[path = "authorized_read_error_tests.rs"]
mod tests;
