use serde::Serialize;
use serde::de::DeserializeOwned;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Row;
use sqlx::sqlite::SqliteRow;

use crate::AllocationGrant;
use crate::DurableFleetError;
use crate::ResourceVectorV1;

pub(crate) fn validate_identity(value: &str, field: &str) -> Result<(), DurableFleetError> {
    if value.is_empty()
        || value.len() > 256
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-/".contains(&byte))
    {
        return Err(DurableFleetError::Invalid(format!(
            "invalid {field} identity"
        )));
    }
    Ok(())
}

pub(crate) fn validate_digest(value: &str) -> Result<(), DurableFleetError> {
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(DurableFleetError::Invalid(
            "digest must be non-zero lowercase SHA-256 hex".to_string(),
        ));
    }
    Ok(())
}

pub(crate) fn validate_grant(grant: &AllocationGrant) -> Result<(), DurableFleetError> {
    for (value, field) in [
        (&grant.allocation_id, "allocation"),
        (&grant.request_id, "request"),
        (&grant.principal_id, "principal"),
        (&grant.host_id, "host"),
        (&grant.failure_domain_id, "failure domain"),
    ] {
        validate_identity(value, field)?;
    }
    validate_digest(&grant.semantic_digest)?;
    grant
        .resources
        .validate_nonzero()
        .map_err(|error| DurableFleetError::Invalid(error.to_string()))?;
    if grant.host_generation == 0
        || grant.authority_epoch == 0
        || grant.lease_generation == 0
        || grant.revoked
    {
        return Err(DurableFleetError::Invalid(
            "invalid allocation generation or state".to_string(),
        ));
    }
    Ok(())
}

pub(crate) fn decode_grant(row: &SqliteRow) -> Result<AllocationGrant, DurableFleetError> {
    Ok(AllocationGrant {
        allocation_id: row.try_get("allocation_id").map_err(sqlx_decode_error)?,
        request_id: row.try_get("request_id").map_err(sqlx_decode_error)?,
        principal_id: row.try_get("principal_id").map_err(sqlx_decode_error)?,
        host_id: row.try_get("host_id").map_err(sqlx_decode_error)?,
        failure_domain_id: row
            .try_get("failure_domain_id")
            .map_err(sqlx_decode_error)?,
        host_generation: to_u64(row.try_get("host_generation").map_err(sqlx_decode_error)?)?,
        authority_epoch: to_u64(row.try_get("authority_epoch").map_err(sqlx_decode_error)?)?,
        lease_generation: to_u64(row.try_get("lease_generation").map_err(sqlx_decode_error)?)?,
        expires_at_ms: to_u64(row.try_get("expires_at_ms").map_err(sqlx_decode_error)?)?,
        resources: decode_vector(row, "")?,
        semantic_digest: row.try_get("semantic_digest").map_err(sqlx_decode_error)?,
        revoked: false,
    })
}

pub(crate) fn decode_vector(
    row: &SqliteRow,
    prefix: &str,
) -> Result<ResourceVectorV1, DurableFleetError> {
    let get = |name: &str| -> Result<u64, DurableFleetError> {
        let column = format!("{prefix}{name}");
        to_u64(
            row.try_get::<i64, _>(column.as_str())
                .map_err(sqlx_decode_error)?,
        )
    };
    ResourceVectorV1 {
        cpu_millis: get("cpu_millis")?,
        memory_bytes: get("memory_bytes")?,
        accelerator_millis: get("accelerator_millis")?,
        concurrent_turns: get("concurrent_turns")?,
        tool_processes: get("tool_processes")?,
        turn_queue_slots: get("turn_queue_slots")?,
    }
    .validate()
    .map_err(|error| DurableFleetError::Corrupt(error.to_string()))
}

pub(crate) fn to_i64(value: u64) -> Result<i64, DurableFleetError> {
    i64::try_from(value).map_err(|_| DurableFleetError::Invalid("u64 exceeds SQLite range".into()))
}

pub(crate) fn to_u64(value: i64) -> Result<u64, DurableFleetError> {
    u64::try_from(value).map_err(|_| DurableFleetError::Corrupt("negative durable integer".into()))
}

pub(crate) fn resource_digest(vector: ResourceVectorV1) -> String {
    hex_lower(&vector.semantic_digest())
}

pub(crate) fn content_digest<T: Serialize>(value: &T) -> Result<String, DurableFleetError> {
    let bytes =
        serde_json::to_vec(value).map_err(|error| DurableFleetError::Invalid(error.to_string()))?;
    Ok(hex_lower(&Sha256::digest(bytes)))
}

pub(crate) fn encode_json<T: Serialize>(value: &T) -> Result<String, DurableFleetError> {
    serde_json::to_string(value).map_err(|error| DurableFleetError::Invalid(error.to_string()))
}

pub(crate) fn decode_json<T: DeserializeOwned>(value: &str) -> Result<T, DurableFleetError> {
    serde_json::from_str(value).map_err(|error| DurableFleetError::Corrupt(error.to_string()))
}

pub(crate) fn operation_id(kind: &str, subject_id: &str, revision: u64) -> String {
    format!("fleet:{kind}:{subject_id}:{revision}")
}

fn sqlx_decode_error(error: sqlx::Error) -> DurableFleetError {
    DurableFleetError::Corrupt(error.to_string())
}

fn hex_lower(bytes: &[u8]) -> String {
    use std::fmt::Write as _;

    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        let _ = write!(&mut output, "{byte:02x}");
    }
    output
}
