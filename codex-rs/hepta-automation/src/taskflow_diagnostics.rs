//! Bounded storage diagnostics without SQL, paths, owner IDs or database messages.

use std::io::Write;

use crate::TaskFlowError;

pub(crate) fn unavailable(
    error: &sqlx::Error,
    location: &'static std::panic::Location<'static>,
) -> TaskFlowError {
    let code = error
        .as_database_error()
        .and_then(sqlx::error::DatabaseError::code)
        .and_then(|code| code.parse::<u32>().ok());
    let category = match error {
        sqlx::Error::Database(_) => "database",
        sqlx::Error::PoolTimedOut => "pool_timeout",
        sqlx::Error::PoolClosed => "pool_closed",
        sqlx::Error::Io(_) => "io",
        _ => "other",
    };
    let _ = writeln!(
        std::io::stderr().lock(),
        "TaskFlow storage unavailable: category={category} sqlite_code={code:?} at {}:{}",
        location.file(),
        location.line(),
    );
    TaskFlowError::Unavailable
}

#[cfg(test)]
#[path = "taskflow_diagnostics_tests.rs"]
mod tests;
