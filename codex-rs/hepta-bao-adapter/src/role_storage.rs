//! Role-local SQL owners share the established private FULL connection policy.

use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use sqlx::SqlitePool;

use crate::ConsumerPortError;

pub(crate) struct RoleCommitFence {
    fenced: Arc<AtomicBool>,
    armed: bool,
}

impl RoleCommitFence {
    pub fn arm(fenced: &Arc<AtomicBool>) -> Result<Self, ConsumerPortError> {
        if fenced.load(Ordering::Acquire) {
            return Err(ConsumerPortError::Unavailable);
        }
        Ok(Self {
            fenced: Arc::clone(fenced),
            armed: true,
        })
    }
    pub fn committed(&mut self) {
        self.armed = false;
    }
}
impl Drop for RoleCommitFence {
    fn drop(&mut self) {
        if self.armed {
            self.fenced.store(true, Ordering::Release);
        }
    }
}

pub(crate) async fn open_role_pool(
    path: &Path,
    migrator: &'static sqlx::migrate::Migrator,
) -> Result<SqlitePool, ConsumerPortError> {
    crate::sqlite_owner::prepare_private_storage(path).map_err(unavailable)?;
    let home =
        AbsolutePathBuf::try_from(path.parent().ok_or(ConsumerPortError::Invalid)?.to_owned())
            .map_err(unavailable)?;
    let pool = SqliteConfig::from_sqlite_home(home)
        .open_durable_evidence_pool(path)
        .await
        .map_err(unavailable)?;
    let result = async {
        let check: String = sqlx::query_scalar("PRAGMA quick_check")
            .fetch_one(&pool)
            .await
            .map_err(unavailable)?;
        if check != "ok" {
            return Err(ConsumerPortError::Unavailable);
        }
        migrator.run(&pool).await.map_err(unavailable)?;
        crate::sqlite_owner::secure_database_file(path).map_err(unavailable)?;
        verify_schema(&pool, migrator).await
    }
    .await;
    if let Err(error) = result {
        pool.close().await;
        return Err(error);
    }
    Ok(pool)
}

pub(crate) async fn verify_schema(
    pool: &SqlitePool,
    migrator: &'static sqlx::migrate::Migrator,
) -> Result<(), ConsumerPortError> {
    let reference = SqliteConfig::from_sqlite_home(
        AbsolutePathBuf::try_from(std::env::temp_dir()).map_err(unavailable)?,
    )
    .open_durable_evidence_pool(Path::new(":memory:"))
    .await
    .map_err(unavailable)?;
    let result = async {
        let mut connection = reference.acquire().await.map_err(unavailable)?;
        migrator.run(&mut *connection).await.map_err(unavailable)?;
        let query = "SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*' AND sql IS NOT NULL ORDER BY type,name";
        let expected = sqlx::query_as::<_, (String,String,String,String)>(query)
            .fetch_all(&mut *connection).await.map_err(unavailable)?;
        let actual = sqlx::query_as::<_, (String,String,String,String)>(query)
            .fetch_all(pool).await.map_err(unavailable)?;
        if actual != expected { return Err(ConsumerPortError::Unavailable); }
        Ok(())
    }.await;
    reference.close().await;
    result
}

pub(crate) fn unavailable<T>(_error: T) -> ConsumerPortError {
    ConsumerPortError::Unavailable
}
