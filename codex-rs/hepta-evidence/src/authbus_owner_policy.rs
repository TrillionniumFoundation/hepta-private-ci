//! One monotonic owner-policy commitment across issuer changes in a PQ domain.

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::AuthBusAdmissionError;
use crate::EvidenceError;
use crate::schema_validation::classify_sqlx_error;

pub(crate) async fn update_required(
    tx: &mut Transaction<'_, Sqlite>,
    revision: Generation,
    digest: Digest32,
) -> Result<bool, AuthBusAdmissionError> {
    let checkpointed: bool =
        sqlx::query_scalar("SELECT EXISTS(SELECT 1 FROM authbus_restore_checkpoint)")
            .fetch_one(&mut **tx)
            .await
            .map_err(classify_sqlx_error)?;
    if !checkpointed {
        return Err(codex_hepta_authbus::Error::ExternalCheckpointRequired.into());
    }
    let previous: Option<(Vec<u8>, Vec<u8>)> = sqlx::query_as(
        "SELECT policy_revision, policy_digest FROM authbus_owner_policy_floor WHERE singleton = 1",
    )
    .fetch_optional(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    let revision = revision.get().to_be_bytes();
    if let Some((prior_revision, prior_digest)) = previous {
        if revision.as_slice() < prior_revision.as_slice()
            || (revision.as_slice() == prior_revision.as_slice()
                && digest.as_array().as_slice() != prior_digest.as_slice())
        {
            return Err(AuthBusAdmissionError::OwnerPolicyMismatch);
        }
        return Ok(revision.as_slice() != prior_revision.as_slice());
    }
    // An added empty migration table cannot turn a previously used PQ store
    // into a fresh policy authority. No historical policy can be inferred from
    // a current owner file or reconstructed from a potentially old backup.
    let used: bool = sqlx::query_scalar(
        "SELECT EXISTS(SELECT 1 FROM authbus_issuer_floor) OR
         EXISTS(SELECT 1 FROM authbus_replay_sequences) OR
         EXISTS(SELECT 1 FROM authbus_outbox) OR
         EXISTS(SELECT 1 FROM authbus_retired_epochs)",
    )
    .fetch_one(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    if used {
        return Err(AuthBusAdmissionError::OwnerPolicyInitializationRequired);
    }
    Ok(true)
}

pub(crate) async fn store(
    tx: &mut Transaction<'_, Sqlite>,
    revision: Generation,
    digest: Digest32,
) -> Result<(), EvidenceError> {
    sqlx::query(
        "INSERT INTO authbus_owner_policy_floor VALUES (1, ?, ?)
         ON CONFLICT(singleton) DO UPDATE SET policy_revision = excluded.policy_revision,
         policy_digest = excluded.policy_digest",
    )
    .bind(revision.get().to_be_bytes().as_slice())
    .bind(digest.as_array().as_slice())
    .execute(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    Ok(())
}

pub(crate) async fn require_current(
    tx: &mut Transaction<'_, Sqlite>,
    expected: Option<(Generation, Digest32)>,
) -> Result<(), AuthBusAdmissionError> {
    let current: Option<(Vec<u8>, Vec<u8>)> = sqlx::query_as(
        "SELECT policy_revision, policy_digest FROM authbus_owner_policy_floor WHERE singleton = 1",
    )
    .fetch_optional(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    match (current, expected) {
        (None, None) => Ok(()),
        (Some((revision, digest)), Some((expected_revision, expected_digest)))
            if revision == expected_revision.get().to_be_bytes()
                && digest == expected_digest.as_array().as_slice() =>
        {
            Ok(())
        }
        _ => Err(AuthBusAdmissionError::OwnerPolicyMismatch),
    }
}

pub(crate) async fn append_frontier(
    tx: &mut Transaction<'_, Sqlite>,
    bytes: &mut Vec<u8>,
) -> Result<(), EvidenceError> {
    let policy: Option<(Vec<u8>, Vec<u8>)> = sqlx::query_as(
        "SELECT policy_revision, policy_digest FROM authbus_owner_policy_floor WHERE singleton = 1",
    )
    .fetch_optional(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    // Preserve the existing commitment while the new table is empty. A used
    // legacy domain still cannot initialize it through update_required.
    if let Some((revision, digest)) = policy {
        bytes.extend_from_slice(b"hepta.authbus.owner-policy.v1\0");
        bytes.extend_from_slice(&revision);
        bytes.extend_from_slice(&digest);
    }
    Ok(())
}

#[cfg(test)]
#[path = "authbus_owner_policy_tests.rs"]
mod tests;
