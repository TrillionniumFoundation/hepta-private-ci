//! One bounded cleanup pool per exact-generation native worker. Requests use
//! lightweight identity/schema probes; startup and maintenance check all data.

use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use tokio::sync::Mutex;

use crate::native_app_server::Result;
use crate::native_cleanup_store::NativeCleanupBacklogMetrics;
use crate::native_cleanup_store::NativeCleanupStore;

const MAX_INTEGRITY_AGE: Duration = Duration::from_secs(300);

#[derive(Clone, Debug, Eq, PartialEq)]
struct FileIdentity {
    canonical: PathBuf,
    device: u64,
    inode: u64,
}

impl FileIdentity {
    fn capture(path: &Path) -> Result<Self> {
        let metadata = std::fs::symlink_metadata(path)?;
        if !metadata.is_file() || metadata.file_type().is_symlink() {
            return Err("native cleanup path is not a regular file".into());
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            if metadata.nlink() != 1 {
                return Err("native cleanup file has multiple links".into());
            }
            Ok(Self {
                canonical: std::fs::canonicalize(path)?,
                device: metadata.dev(),
                inode: metadata.ino(),
            })
        }
        #[cfg(not(unix))]
        {
            Err("native cleanup pooling requires stable filesystem identity on this host".into())
        }
    }
}

struct CachedStore {
    store: NativeCleanupStore,
    identity: FileIdentity,
    schema_cookie: i64,
    integrity_at: Instant,
}

#[derive(Clone, Copy)]
enum Access {
    Serve,
    Maintain,
}

pub(crate) struct NativeCleanupOwner {
    path: PathBuf,
    owner_id: String,
    generation: u64,
    cached: Mutex<Option<CachedStore>>,
    quarantined: AtomicBool,
}

impl NativeCleanupOwner {
    pub(crate) fn new(path: PathBuf, owner_id: String, generation: u64) -> Self {
        Self {
            path,
            owner_id,
            generation,
            cached: Mutex::new(None),
            quarantined: AtomicBool::new(false),
        }
    }

    pub(crate) async fn get(&self) -> Result<NativeCleanupStore> {
        self.access(Access::Serve).await
    }

    async fn access(&self, access: Access) -> Result<NativeCleanupStore> {
        if matches!(access, Access::Serve) && self.quarantined.load(Ordering::Acquire) {
            return Err("native cleanup owner is quarantined pending integrity maintenance".into());
        }
        let mut cached = self.cached.lock().await;
        if matches!(access, Access::Serve) && self.quarantined.load(Ordering::Acquire) {
            return Err("native cleanup owner is quarantined pending integrity maintenance".into());
        }
        if cached.is_none() {
            let store =
                NativeCleanupStore::open(&self.path, self.owner_id.clone(), self.generation)
                    .await?;
            let identity = FileIdentity::capture(&self.path)?;
            let schema_cookie = store.probe_schema().await?;
            if identity != FileIdentity::capture(&self.path)? {
                store.close().await;
                return Err("native cleanup identity changed during admission".into());
            }
            *cached = Some(CachedStore {
                store,
                identity,
                schema_cookie,
                integrity_at: Instant::now(),
            });
        }
        let entry = cached
            .as_mut()
            .ok_or("native cleanup owner admission omitted its pool")?;
        self.require_identity(entry).await?;
        let cookie = match entry.store.probe_schema().await {
            Ok(cookie) => cookie,
            Err(error) => {
                self.quarantined.store(true, Ordering::Release);
                return Err(error.into());
            }
        };
        match access {
            Access::Serve => {
                if cookie != entry.schema_cookie
                    || entry.integrity_at.elapsed() >= MAX_INTEGRITY_AGE
                {
                    self.quarantined.store(true, Ordering::Release);
                    return Err("native cleanup schema/integrity cut requires maintenance".into());
                }
            }
            Access::Maintain => {
                if let Err(error) = entry.store.verify_integrity().await {
                    self.quarantined.store(true, Ordering::Release);
                    return Err(error.into());
                }
                entry.schema_cookie = entry.store.probe_schema().await?;
                entry.integrity_at = Instant::now();
                self.quarantined.store(false, Ordering::Release);
            }
        }
        self.require_identity(entry).await?;
        Ok(entry.store.clone())
    }

    async fn require_identity(&self, entry: &CachedStore) -> Result<()> {
        match FileIdentity::capture(&self.path) {
            Ok(identity) if identity == entry.identity => Ok(()),
            result => {
                self.quarantined.store(true, Ordering::Release);
                entry.store.close().await;
                match result {
                    Err(error) => Err(error),
                    Ok(_) => Err(
                        "native cleanup file identity changed; recreate the generation owner"
                            .into(),
                    ),
                }
            }
        }
    }

    pub(crate) async fn maintain(&self, budget: Duration) -> Result<NativeCleanupBacklogMetrics> {
        if budget.is_zero() {
            return Err("native cleanup maintenance budget is zero".into());
        }
        let maintenance = async {
            let store = self.access(Access::Maintain).await?;
            store.recover_expired(now_ms()?).await?;
            Ok::<_, Box<dyn std::error::Error + Send + Sync>>(store.metrics().await?)
        };
        match tokio::time::timeout(budget, maintenance).await {
            Ok(result) => result,
            Err(_) => {
                self.quarantined.store(true, Ordering::Release);
                Err("native cleanup integrity maintenance budget elapsed".into())
            }
        }
    }
}

fn now_ms() -> Result<u64> {
    Ok(u64::try_from(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_millis(),
    )?)
}

#[cfg(test)]
#[path = "native_cleanup_owner_tests.rs"]
mod tests;
