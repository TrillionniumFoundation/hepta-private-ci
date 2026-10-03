//! Existing durable owner rows implementation.

use super::*;

pub(super) fn fixed_u64_allow_zero(value: &[u8]) -> Result<u64, SqliteBaoOwnerErrorV1> {
    let bytes: [u8; 8] = value
        .try_into()
        .map_err(|_| SqliteBaoOwnerErrorV1::CorruptState("invalid fixed-width u64"))?;
    Ok(u64::from_be_bytes(bytes))
}

pub(super) fn u64_bytes(value: u64) -> [u8; 8] {
    value.to_be_bytes()
}

pub(super) fn storage(error: impl ToString) -> SqliteBaoOwnerErrorV1 {
    SqliteBaoOwnerErrorV1::Storage(error.to_string())
}

pub(super) fn map_write_error(error: sqlx::Error) -> SqliteBaoOwnerErrorV1 {
    if error
        .as_database_error()
        .is_some_and(sqlx::error::DatabaseError::is_unique_violation)
    {
        SqliteBaoOwnerErrorV1::OperationConflict
    } else {
        storage(error)
    }
}
