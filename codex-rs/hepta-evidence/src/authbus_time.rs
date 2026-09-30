use serde::Serialize;
use sqlx::Sqlite;
use sqlx::Transaction;
#[cfg(test)]
use sqlx::sqlite::SqlitePool;

use crate::EvidenceError;
use crate::HeptaEvidenceStore;
use crate::schema_validation::classify_sqlx_error;
use crate::store::now_millis;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct AuthBusTimeFloor {
    pub wall_time_ms: u64,
    pub revision: u64,
}

impl HeptaEvidenceStore {
    /// Advance the Evidence-owned time floor from the host observation and
    /// return the monotonic value. Clock rollback is clamped, never accepted as
    /// a younger message/lease/retention instant.
    pub async fn authbus_time_floor(&self) -> Result<AuthBusTimeFloor, EvidenceError> {
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(classify_sqlx_error)?;
        let floor = advance_authbus_time_floor(&mut tx, now_millis()?).await?;
        tx.commit().await.map_err(classify_sqlx_error)?;
        Ok(floor)
    }

    pub async fn authbus_monotonic_now_ms(&self) -> Result<u64, EvidenceError> {
        Ok(self.authbus_time_floor().await?.wall_time_ms)
    }
}

pub(crate) async fn authbus_now(
    tx: &mut Transaction<'_, Sqlite>,
) -> Result<i64, EvidenceError> {
    let floor = advance_authbus_time_floor(tx, now_millis()?).await?;
    i64::try_from(floor.wall_time_ms)
        .map_err(|_| EvidenceError::Corrupt("AuthBus time floor exceeds i64".into()))
}

async fn advance_authbus_time_floor(
    tx: &mut Transaction<'_, Sqlite>,
    observed_at_ms: i64,
) -> Result<AuthBusTimeFloor, EvidenceError> {
    if observed_at_ms < 0 {
        return Err(EvidenceError::Unavailable(
            "host clock predates Unix epoch".into(),
        ));
    }
    let (current_ms, current_revision): (i64, i64) = sqlx::query_as(
        "SELECT observed_at_ms, revision
         FROM authbus_time_floor WHERE singleton = 1",
    )
    .fetch_one(&mut **tx)
    .await
    .map_err(classify_sqlx_error)?;
    if current_ms < 0 || current_revision < 1 {
        return Err(EvidenceError::Corrupt(
            "invalid AuthBus time-floor singleton".into(),
        ));
    }
    let (wall_time_ms, revision) = if observed_at_ms > current_ms {
        let next_revision = current_revision
            .checked_add(1)
            .ok_or_else(|| EvidenceError::Corrupt("AuthBus time-floor revision overflow".into()))?;
        let affected = sqlx::query(
            "UPDATE authbus_time_floor
             SET observed_at_ms = ?, revision = ?
             WHERE singleton = 1 AND observed_at_ms = ? AND revision = ?",
        )
        .bind(observed_at_ms)
        .bind(next_revision)
        .bind(current_ms)
        .bind(current_revision)
        .execute(&mut **tx)
        .await
        .map_err(classify_sqlx_error)?
        .rows_affected();
        if affected != 1 {
            return Err(EvidenceError::Corrupt(
                "AuthBus time-floor compare-and-set failed".into(),
            ));
        }
        (observed_at_ms, next_revision)
    } else {
        (current_ms, current_revision)
    };
    Ok(AuthBusTimeFloor {
        wall_time_ms: u64::try_from(wall_time_ms)
            .map_err(|_| EvidenceError::Corrupt("negative AuthBus time floor".into()))?,
        revision: u64::try_from(revision)
            .map_err(|_| EvidenceError::Corrupt("invalid AuthBus time-floor revision".into()))?,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    async fn pool() -> SqlitePool {
        let pool = SqlitePool::connect("sqlite::memory:")
            .await
            .expect("in-memory SQLite");
        sqlx::query(
            "CREATE TABLE authbus_time_floor (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                observed_at_ms INTEGER NOT NULL CHECK (observed_at_ms >= 0),
                revision INTEGER NOT NULL CHECK (revision >= 1)
             ) WITHOUT ROWID",
        )
        .execute(&pool)
        .await
        .expect("time-floor table");
        sqlx::query(
            "CREATE TRIGGER authbus_time_floor_monotonic
             BEFORE UPDATE OF observed_at_ms, revision ON authbus_time_floor
             WHEN NEW.observed_at_ms <= OLD.observed_at_ms
               OR NEW.revision != OLD.revision + 1
             BEGIN SELECT RAISE(ABORT, 'monotonic'); END",
        )
        .execute(&pool)
        .await
        .expect("time-floor trigger");
        sqlx::query(
            "INSERT INTO authbus_time_floor(singleton, observed_at_ms, revision)
             VALUES (1, 0, 1)",
        )
        .execute(&pool)
        .await
        .expect("time-floor singleton");
        pool
    }

    #[tokio::test]
    async fn clamps_rollback_and_advances_only_forward() {
        let pool = pool().await;
        let mut tx = pool.begin_with("BEGIN IMMEDIATE").await.expect("tx");
        let first = advance_authbus_time_floor(&mut tx, 100)
            .await
            .expect("advance");
        tx.commit().await.expect("commit");
        assert_eq!(first.wall_time_ms, 100);

        let mut tx = pool.begin_with("BEGIN IMMEDIATE").await.expect("tx");
        let rollback = advance_authbus_time_floor(&mut tx, 50)
            .await
            .expect("clamp rollback");
        tx.commit().await.expect("commit");
        assert_eq!(rollback, first);

        let mut tx = pool.begin_with("BEGIN IMMEDIATE").await.expect("tx");
        let later = advance_authbus_time_floor(&mut tx, 150)
            .await
            .expect("advance later");
        tx.commit().await.expect("commit");
        assert_eq!(later.wall_time_ms, 150);
        assert_eq!(later.revision, first.revision + 1);
    }
}
