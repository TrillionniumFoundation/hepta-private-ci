//! Bounded federation I/O. Pool caching does not cache authorization decisions.
use std::collections::BTreeMap;
use std::collections::VecDeque;
use std::future::Future;
use std::sync::Mutex;
use std::time::Duration;

use sqlx::SqlitePool;
use tokio::task::JoinSet;
use tokio::time::Instant;

use super::COGNITIVE_DB_FILENAME;
use super::CognitiveStoreError;
use super::HeptaAgentLayout;
use super::MAX_FEDERATION_OWNER_LAYOUTS_PER_AGENT;
use super::canonical_path_without_redirection;
use super::open_read_only_pool;
use super::unavailable;
use super::verify_read_only_store;

const MAX_IN_FLIGHT: usize = 4;
const POOL_RECHECK_INTERVAL: Duration = Duration::from_secs(60);

pub(super) struct BoundedBatch<T> {
    pub values: Vec<T>,
    pub incomplete: bool,
}

/// Preserve completed values on a deadline; never silently replace them with empty.
pub(super) async fn bounded<T, R, F, Fut>(
    items: Vec<T>,
    deadline: Instant,
    mut run: F,
) -> BoundedBatch<R>
where
    T: Send + 'static,
    R: Send + 'static,
    F: FnMut(T) -> Fut,
    Fut: Future<Output = R> + Send + 'static,
{
    let total = items.len();
    let mut remaining: VecDeque<_> = items.into_iter().enumerate().collect();
    let mut tasks = JoinSet::new();
    let mut completed = BTreeMap::new();
    let mut incomplete = false;
    loop {
        if Instant::now() >= deadline {
            incomplete |= completed.len() != total;
            break;
        }
        while tasks.len() < MAX_IN_FLIGHT {
            let Some((index, item)) = remaining.pop_front() else {
                break;
            };
            let future = run(item);
            tasks.spawn(async move { (index, future.await) });
        }
        if tasks.is_empty() {
            break;
        }
        match tokio::time::timeout_at(deadline, tasks.join_next()).await {
            Ok(Some(Ok((index, value)))) => {
                completed.insert(index, value);
            }
            Ok(Some(Err(_))) => incomplete = true,
            Ok(None) => break,
            Err(_) => {
                incomplete = true;
                break;
            }
        }
    }
    // Dropping the JoinSet aborts unfinished read-only work. No detached tasks.
    drop(tasks);
    BoundedBatch {
        values: completed.into_values().collect(),
        incomplete,
    }
}

struct CachedPool {
    identity: (u64, u64),
    checked_at: Instant,
    pool: SqlitePool,
}

#[derive(Default)]
pub(super) struct PoolDirectory {
    pools: Mutex<BTreeMap<String, CachedPool>>,
}

impl PoolDirectory {
    pub(super) async fn pool(
        &self,
        layout: &HeptaAgentLayout,
    ) -> Result<SqlitePool, CognitiveStoreError> {
        let path = layout.cognitive_root().join(COGNITIVE_DB_FILENAME);
        if canonical_path_without_redirection(&path)
            .map_err(unavailable)?
            .is_none()
        {
            return Err(CognitiveStoreError::Unavailable(
                "federation source path changed".to_string(),
            ));
        }
        let before = identity(&std::fs::metadata(&path).map_err(unavailable)?);
        let key = layout.agent_id().as_str().to_owned();
        {
            let mut pools = self.pools.lock().map_err(unavailable)?;
            if let Some(cached) = pools.get(&key)
                && Some(cached.identity) == before
                && cached.checked_at.elapsed() < POOL_RECHECK_INTERVAL
            {
                return Ok(cached.pool.clone());
            }
            pools.remove(&key);
        }
        let pool = open_read_only_pool(&path).await?;
        verify_read_only_store(&pool, layout.agent_id()).await?;
        let after = identity(&std::fs::metadata(&path).map_err(unavailable)?);
        if before != after {
            return Err(CognitiveStoreError::Unavailable(
                "federation source replaced during open".to_string(),
            ));
        }
        if let Some(identity) = after {
            let mut pools = self.pools.lock().map_err(unavailable)?;
            if pools.len() < MAX_FEDERATION_OWNER_LAYOUTS_PER_AGENT || pools.contains_key(&key) {
                pools.insert(
                    key,
                    CachedPool {
                        identity,
                        checked_at: Instant::now(),
                        pool: pool.clone(),
                    },
                );
            }
        }
        Ok(pool)
    }
}

// Without a stable file identity, open and verify instead of reusing a stale pool.
fn identity(metadata: &std::fs::Metadata) -> Option<(u64, u64)> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        Some((metadata.dev(), metadata.ino()))
    }
    #[cfg(not(unix))]
    {
        let _ = metadata;
        None
    }
}

#[cfg(test)]
#[path = "cognitive_federation_runtime_tests.rs"]
mod tests;
