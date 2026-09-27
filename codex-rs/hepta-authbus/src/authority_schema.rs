//! Compare live authority schema with the compiled migrations before recovery.
//!
//! Migration checksums attest the migration ledger, not the current tables or
//! triggers. The transient reference contains no authority data and never acts
//! as a second owner; it supplies SQLite's canonical schema representation.

use sqlx::SqlitePool;
use sqlx::migrate::Migrator;
use sqlx::sqlite::SqlitePoolOptions;

use crate::AuthBusAuthorityError;
use crate::authority_store::storage;

pub(crate) async fn verify_schema(
    pool: &SqlitePool,
    migrator: &Migrator,
) -> Result<(), AuthBusAuthorityError> {
    let reference = SqlitePoolOptions::new()
        .max_connections(1)
        .connect("sqlite::memory:")
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
        let quick_check: String = sqlx::query_scalar("PRAGMA quick_check")
            .fetch_one(pool)
            .await
            .map_err(storage)?;
        if quick_check != "ok" {
            return Err(AuthBusAuthorityError::CorruptState(
                "post-migration SQLite quick_check failed",
            ));
        }
        let foreign_key_violations: i64 =
            sqlx::query_scalar("SELECT COUNT(*) FROM pragma_foreign_key_check")
                .fetch_one(pool)
                .await
                .map_err(storage)?;
        if foreign_key_violations != 0 {
            return Err(AuthBusAuthorityError::CorruptState(
                "post-migration SQLite foreign_key_check failed",
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
