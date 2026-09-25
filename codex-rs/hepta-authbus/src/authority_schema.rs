//! Compare live authority schema with the compiled migrations before recovery.
//!
//! Migration checksums attest the migration ledger, not the current tables or
//! triggers. The transient reference contains no authority data and never acts
//! as a second owner; it supplies SQLite's canonical schema representation.

use sqlx::SqlitePool;
use sqlx::migrate::Migrator;

use crate::AuthBusAuthorityError;
use crate::authority_store::storage;

pub(crate) async fn verify_schema(
    pool: &SqlitePool,
    migrator: &Migrator,
) -> Result<(), AuthBusAuthorityError> {
    let reference = codex_state_sqlite::open_schema_reference_pool()
        .await
        .map_err(storage)?;
    let result = async {
        migrator.run(&reference).await.map_err(storage)?;
        let query = "SELECT type, name, tbl_name, sql FROM sqlite_schema
                     WHERE name NOT GLOB 'sqlite_*' AND sql IS NOT NULL
                     ORDER BY type, name";
        let expected = sqlx::query_as::<_, (String, String, String, String)>(query)
            .fetch_all(&reference)
            .await
            .map_err(storage)?;
        let actual = sqlx::query_as::<_, (String, String, String, String)>(query)
            .fetch_all(pool)
            .await
            .map_err(storage)?;
        if actual != expected {
            return Err(AuthBusAuthorityError::CorruptState(
                "live authority schema differs from compiled migrations",
            ));
        }
        Ok(())
    }
    .await;
    reference.close().await;
    result
}

#[cfg(test)]
#[path = "authority_schema_tests.rs"]
mod tests;
