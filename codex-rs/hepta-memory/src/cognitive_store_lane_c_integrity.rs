//! Reopen admission for the rebuildable Lane C witness.
//!
//! Trigger definitions are authenticated by the owner's canonical schema
//! oracle before this independent content audit runs. The full audit belongs
//! to startup/recovery; request-hot exact-ID reads retain their indexed bound.

use sqlx::Executor;
use sqlx::Sqlite;

use super::CognitiveStoreError;
use super::unavailable;

pub(super) async fn verify<'e>(
    executor: impl Executor<'e, Database = Sqlite>,
) -> Result<(), CognitiveStoreError> {
    let drift: bool = sqlx::query_scalar(
        "SELECT EXISTS (
             SELECT 1 FROM lane_c_scope_witness_audit
             UNION ALL
             SELECT 1 FROM lane_c_head_validity_audit
         )",
    )
    .fetch_one(executor)
    .await
    .map_err(unavailable)?;
    if drift {
        return Err(CognitiveStoreError::Corrupt(
            "Lane C witness does not match its canonical source rows".to_string(),
        ));
    }
    Ok(())
}
