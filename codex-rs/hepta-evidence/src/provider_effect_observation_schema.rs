//! Migration 0016 replaces content-unique projections with observation logs.
//! Reintroducing a unique content index would silently discard later status
//! observations or quarantine events, even when all current rows are valid.

use sqlx::Row;
use sqlx::SqlitePool;

use crate::EvidenceError;
use crate::schema_validation::classify_sqlx_error;

pub(crate) async fn verify_schema(pool: &SqlitePool) -> Result<(), EvidenceError> {
    for query in [
        "PRAGMA index_list(provider_effect_acknowledgements)",
        "PRAGMA index_list(provider_effect_uncertainties)",
    ] {
        let indexes = sqlx::query(query)
            .fetch_all(pool)
            .await
            .map_err(classify_sqlx_error)?;
        for index in indexes {
            if index
                .try_get::<i64, _>("unique")
                .map_err(classify_sqlx_error)?
                != 0
            {
                return Err(EvidenceError::Corrupt(
                    "provider effect observation history has a content-unique index".into(),
                ));
            }
        }
    }
    Ok(())
}
