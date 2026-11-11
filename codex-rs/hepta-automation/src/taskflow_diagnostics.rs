//! Bounded storage-failure metadata for the durable TaskFlow ledger.
//!
//! Preserve the public error and never emit SQL, error messages, paths, owner
//! identifiers, or payloads. Stages and variant labels are fixed in source.

use std::io::Write;

use super::TaskFlowError;

pub(crate) fn storage_unavailable(stage: &'static str, error: sqlx::Error) -> TaskFlowError {
    let variant = match &error {
        sqlx::Error::Configuration(_) => "Configuration",
        sqlx::Error::InvalidArgument(_) => "InvalidArgument",
        sqlx::Error::Database(_) => "Database",
        sqlx::Error::Io(_) => "Io",
        sqlx::Error::Tls(_) => "Tls",
        sqlx::Error::Protocol(_) => "Protocol",
        sqlx::Error::RowNotFound => "RowNotFound",
        sqlx::Error::TypeNotFound { .. } => "TypeNotFound",
        sqlx::Error::ColumnIndexOutOfBounds { .. } => "ColumnIndexOutOfBounds",
        sqlx::Error::ColumnNotFound(_) => "ColumnNotFound",
        sqlx::Error::ColumnDecode { .. } => "ColumnDecode",
        sqlx::Error::Encode(_) => "Encode",
        sqlx::Error::Decode(_) => "Decode",
        sqlx::Error::AnyDriverError(_) => "AnyDriverError",
        sqlx::Error::PoolTimedOut => "PoolTimedOut",
        sqlx::Error::PoolClosed => "PoolClosed",
        sqlx::Error::WorkerCrashed => "WorkerCrashed",
        sqlx::Error::Migrate(_) => "Migrate",
        sqlx::Error::InvalidSavePointStatement => "InvalidSavePointStatement",
        sqlx::Error::BeginFailed => "BeginFailed",
        sqlx::Error::ConfigFile(_) => "ConfigFile",
        // SQLx exposes a non-exhaustive error enum.
        _ => "Other",
    };
    let sqlite_extended_code = error
        .as_database_error()
        .and_then(|error| error.code())
        .and_then(|code| code.parse::<i32>().ok());
    // Write directly to inherited stderr so the process test log captures this
    // without a tracing subscriber. Logging failure must preserve Unavailable.
    let _ = writeln!(
        std::io::stderr().lock(),
        "hepta_taskflow_storage_unavailable stage={stage} sqlx_variant={variant} sqlite_extended_code={sqlite_extended_code:?}"
    );
    TaskFlowError::Unavailable
}
