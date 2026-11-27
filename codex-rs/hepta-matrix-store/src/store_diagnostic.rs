use std::io::Write;

use sqlx::error::DatabaseError;
use sqlx::sqlite::SqliteError;

use super::MatrixDurableError;

// These identify code sites, including helpers shared by other store operations.
// They do not identify an event, turn, caller, or time of failure.
pub(super) enum SqlxSite {
    AdmissionBegin,
    LoadDispatch,
    DecodeDispatch,
    AdmissionIdempotentCommit,
    LoadBinding,
    DecodeBinding,
    RoomTombstone,
    LoadRoomThread,
    DecodeRoomThread,
    CountOtherThread,
    BindRoomThread,
    AdmissionUpdate,
    AppendChange,
    TrimChange,
    AdmissionCommit,
}

impl SqlxSite {
    pub(super) fn unavailable(self) -> impl FnOnce(sqlx::Error) -> MatrixDurableError {
        move |error| {
            let site = match self {
                Self::AdmissionBegin => "ADMISSION_BEGIN",
                Self::LoadDispatch => "LOAD_DISPATCH",
                Self::DecodeDispatch => "DECODE_DISPATCH",
                Self::AdmissionIdempotentCommit => "ADMISSION_IDEMPOTENT_COMMIT",
                Self::LoadBinding => "LOAD_BINDING",
                Self::DecodeBinding => "DECODE_BINDING",
                Self::RoomTombstone => "ROOM_TOMBSTONE",
                Self::LoadRoomThread => "LOAD_ROOM_THREAD",
                Self::DecodeRoomThread => "DECODE_ROOM_THREAD",
                Self::CountOtherThread => "COUNT_OTHER_THREAD",
                Self::BindRoomThread => "BIND_ROOM_THREAD",
                Self::AdmissionUpdate => "ADMISSION_UPDATE",
                Self::AppendChange => "APPEND_CHANGE",
                Self::TrimChange => "TRIM_CHANGE",
                Self::AdmissionCommit => "ADMISSION_COMMIT",
            };
            // Never format the error or inspect its message or nested sources.
            let class = match &error {
                sqlx::Error::Configuration(_) => "CONFIGURATION",
                sqlx::Error::InvalidArgument(_) => "INVALID_ARGUMENT",
                sqlx::Error::Database(_) => "DATABASE",
                sqlx::Error::Io(_) => "IO",
                sqlx::Error::Tls(_) => "TLS",
                sqlx::Error::Protocol(_) => "PROTOCOL",
                sqlx::Error::RowNotFound => "ROW_NOT_FOUND",
                sqlx::Error::TypeNotFound { .. } => "TYPE_NOT_FOUND",
                sqlx::Error::ColumnIndexOutOfBounds { .. } => "COLUMN_INDEX_OUT_OF_BOUNDS",
                sqlx::Error::ColumnNotFound(_) => "COLUMN_NOT_FOUND",
                sqlx::Error::ColumnDecode { .. } => "COLUMN_DECODE",
                sqlx::Error::Encode(_) => "ENCODE",
                sqlx::Error::Decode(_) => "DECODE",
                sqlx::Error::AnyDriverError(_) => "ANY_DRIVER_ERROR",
                sqlx::Error::PoolTimedOut => "POOL_TIMED_OUT",
                sqlx::Error::PoolClosed => "POOL_CLOSED",
                sqlx::Error::WorkerCrashed => "WORKER_CRASHED",
                sqlx::Error::Migrate(_) => "MIGRATE",
                sqlx::Error::InvalidSavePointStatement => "INVALID_SAVE_POINT_STATEMENT",
                sqlx::Error::BeginFailed => "BEGIN_FAILED",
                sqlx::Error::ConfigFile(_) => "CONFIG_FILE",
                _ => "OTHER",
            };
            let sqlite_code = match &error {
                sqlx::Error::Database(database) => database
                    .try_downcast_ref::<SqliteError>()
                    .and_then(DatabaseError::code)
                    .and_then(|code| {
                        if code.is_empty()
                            || code.len() > 10
                            || !code.bytes().all(|byte| byte.is_ascii_digit())
                            || (code.len() > 1 && code.starts_with('0'))
                        {
                            return None;
                        }
                        code.parse::<i32>().ok()
                    }),
                _ => None,
            };
            // One bounded record on the existing error path. A failed diagnostic
            // write must not replace the original durable-store error.
            let stderr = std::io::stderr();
            let mut stderr = stderr.lock();
            match sqlite_code {
                Some(code) => {
                    let _ = writeln!(
                        stderr,
                        "MATRIX_STORE_SQLX site={site} class={class} sqlite_code={code}"
                    );
                }
                None => {
                    let _ = writeln!(
                        stderr,
                        "MATRIX_STORE_SQLX site={site} class={class} sqlite_code=UNKNOWN"
                    );
                }
            }
            MatrixDurableError::Unavailable
        }
    }
}
