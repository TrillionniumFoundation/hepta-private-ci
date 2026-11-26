use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_paths::HeptaAgentLayout;
use sqlx::Row;
use tokio::sync::Mutex as AsyncMutex;

use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::cognitive_federation::open_read_only_pool;
use crate::cognitive_model::COGNITIVE_SCHEMA_VERSION;
use crate::cognitive_path::canonical_path_without_redirection;
use crate::cognitive_store::resolve_active_database_path;
use crate::cognitive_store::unavailable;
use crate::cognitive_store::verify_store;

const MAX_RESIDENT_PEERS: usize = 128;
const MAX_INTEGRITY_AGE: Duration = Duration::from_secs(300);

#[derive(Clone, Eq, PartialEq)]
struct DatabaseIdentity {
    path: PathBuf,
    device: u64,
    inode: u64,
}

impl DatabaseIdentity {
    fn observe(layout: &HeptaAgentLayout) -> Result<Self, CognitiveStoreError> {
        let root = canonical_path_without_redirection(layout.cognitive_root())
            .map_err(unavailable)?
            .ok_or_else(|| unavailable("federation root was redirected"))?;
        let path = resolve_active_database_path(&root)?;
        let path = canonical_path_without_redirection(&path)
            .map_err(unavailable)?
            .ok_or_else(|| unavailable("federation database was redirected"))?;
        let metadata = std::fs::metadata(&path).map_err(unavailable)?;
        if !metadata.is_file() {
            return Err(unavailable("federation database is not a regular file"));
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            if metadata.nlink() != 1 {
                return Err(unavailable("federation database has multiple hard links"));
            }
            Ok(Self {
                path,
                device: metadata.dev(),
                inode: metadata.ino(),
            })
        }
        #[cfg(not(unix))]
        {
            // Reusing a connection without a stable file identity is unsafe.
            // Other hosts must supply an equivalent identity before enabling
            // this Linux/Unix product adapter.
            Err(unavailable(
                "stable federation file identity is unavailable on this host",
            ))
        }
    }
}

pub(crate) struct FederationPeer {
    pub(crate) owner: Arc<CognitiveStore>,
    layout: HeptaAgentLayout,
    identity: DatabaseIdentity,
    schema_cookie: i64,
    valid: AtomicBool,
    verified_at: Mutex<Instant>,
}

impl FederationPeer {
    pub(crate) async fn validate(&self) -> Result<(), CognitiveStoreError> {
        let result = self.validate_current().await;
        if result.is_err() {
            // Existing attachment handles must fail as well as new discovery.
            self.valid.store(false, Ordering::Release);
        }
        result
    }

    async fn validate_current(&self) -> Result<(), CognitiveStoreError> {
        if !self.valid.load(Ordering::Acquire)
            || self.verified_at.lock().map_err(unavailable)?.elapsed() >= MAX_INTEGRITY_AGE
        {
            return Err(unavailable(
                "federation integrity admission expired or was rejected",
            ));
        }
        if DatabaseIdentity::observe(&self.layout)? != self.identity {
            return Err(unavailable("federation active database identity changed"));
        }
        let schema_cookie: i64 = sqlx::query_scalar("PRAGMA schema_version")
            .fetch_one(&self.owner.pool)
            .await
            .map_err(unavailable)?;
        let meta = sqlx::query(
            "SELECT schema_version, owner_agent_id FROM cognitive_meta WHERE singleton = 1",
        )
        .fetch_one(&self.owner.pool)
        .await
        .map_err(unavailable)?;
        let schema_version: i64 = meta.try_get("schema_version").map_err(unavailable)?;
        let owner: String = meta.try_get("owner_agent_id").map_err(unavailable)?;
        if schema_cookie != self.schema_cookie
            || schema_version != i64::from(COGNITIVE_SCHEMA_VERSION)
        {
            return Err(CognitiveStoreError::Corrupt(
                "federation schema identity changed".to_string(),
            ));
        }
        if owner != self.layout.agent_id().as_str() {
            return Err(CognitiveStoreError::AccessDenied(
                "federation owner identity changed".to_string(),
            ));
        }
        if DatabaseIdentity::observe(&self.layout)? != self.identity {
            return Err(unavailable(
                "federation database identity changed during validation",
            ));
        }
        Ok(())
    }

    async fn close(&self) {
        self.valid.store(false, Ordering::Release);
        self.owner.pool.close().await;
    }
}

#[derive(Default)]
struct PeerSlot {
    identity: Option<DatabaseIdentity>,
    peer: Option<Arc<FederationPeer>>,
    rejected: bool,
    retired: bool,
}

/// Bounded connection residency only. Capabilities, source validity and
/// retrieval results are never cached; their owner tables remain authoritative.
#[derive(Default)]
pub(crate) struct FederationPeerPools {
    slots: Mutex<BTreeMap<AgentId, Arc<AsyncMutex<PeerSlot>>>>,
    maintenance_cursor: AtomicUsize,
}

impl FederationPeerPools {
    fn slot(&self, owner: &AgentId) -> Result<Arc<AsyncMutex<PeerSlot>>, CognitiveStoreError> {
        let mut slots = self.slots.lock().map_err(unavailable)?;
        if let Some(slot) = slots.get(owner) {
            return Ok(Arc::clone(slot));
        }
        if slots.len() >= MAX_RESIDENT_PEERS {
            return Err(unavailable(
                "federation connection residency is at capacity",
            ));
        }
        let slot = Arc::new(AsyncMutex::new(PeerSlot::default()));
        slots.insert(owner.clone(), Arc::clone(&slot));
        Ok(slot)
    }

    pub(crate) async fn get(
        &self,
        layout: &HeptaAgentLayout,
    ) -> Result<Arc<FederationPeer>, CognitiveStoreError> {
        let slot = self.slot(layout.agent_id())?;
        let mut slot = slot.lock().await;
        if slot.retired {
            return Err(unavailable("federation enrollment was retired"));
        }
        let identity = match DatabaseIdentity::observe(layout) {
            Ok(identity) => identity,
            Err(error) => {
                Self::reject(&mut slot).await;
                return Err(error);
            }
        };
        if slot.identity.as_ref() == Some(&identity) {
            if !slot.rejected
                && let Some(peer) = &slot.peer
            {
                match peer.validate().await {
                    Ok(()) => return Ok(Arc::clone(peer)),
                    Err(error) => {
                        Self::reject(&mut slot).await;
                        return Err(error);
                    }
                }
            }
            return Err(unavailable(
                "federation peer requires integrity maintenance",
            ));
        }
        Self::reject(&mut slot).await;
        slot.identity = Some(identity.clone());
        let peer = Self::open(layout, identity).await?;
        slot.peer = Some(Arc::clone(&peer));
        slot.rejected = false;
        Ok(peer)
    }

    async fn open(
        layout: &HeptaAgentLayout,
        identity: DatabaseIdentity,
    ) -> Result<Arc<FederationPeer>, CognitiveStoreError> {
        let pool = open_read_only_pool(&identity.path).await?;
        let verification = verify_store(&pool, layout.agent_id()).await;
        if let Err(error) = verification {
            pool.close().await;
            return Err(error);
        }
        let schema_cookie = sqlx::query_scalar("PRAGMA schema_version")
            .fetch_one(&pool)
            .await
            .map_err(unavailable)?;
        let peer = Arc::new(FederationPeer {
            owner: Arc::new(CognitiveStore::from_read_only_pool(
                pool,
                layout.agent_id().clone(),
                identity.path.clone(),
            )),
            layout: layout.clone(),
            identity,
            schema_cookie,
            valid: AtomicBool::new(true),
            verified_at: Mutex::new(Instant::now()),
        });
        peer.validate().await?;
        Ok(peer)
    }

    async fn reject(slot: &mut PeerSlot) {
        slot.rejected = true;
        if let Some(peer) = slot.peer.take() {
            peer.close().await;
        }
    }

    /// Visits owners fairly within one wall-clock budget. A timed-out or
    /// corrupt source is quarantined, including its already-issued readers.
    /// An explicit maintenance visit can readmit a repaired physical generation.
    pub(crate) async fn maintain(
        &self,
        layouts: &[HeptaAgentLayout],
        budget: Duration,
    ) -> Result<usize, CognitiveStoreError> {
        if budget.is_zero() || layouts.len() > MAX_RESIDENT_PEERS {
            return Err(CognitiveStoreError::Invalid(
                "invalid federation maintenance budget or owner count".to_string(),
            ));
        }
        let deadline = tokio::time::Instant::now() + budget;
        let enrolled = layouts
            .iter()
            .map(|layout| layout.agent_id().clone())
            .collect::<BTreeSet<_>>();
        // Releasing removed enrollment is explicit and closes old handles.
        let obsolete = {
            let slots = self.slots.lock().map_err(unavailable)?;
            slots
                .iter()
                .filter(|(owner, _)| !enrolled.contains(*owner))
                .map(|(owner, slot)| (owner.clone(), Arc::clone(slot)))
                .collect::<Vec<_>>()
        };
        for (owner, slot) in obsolete {
            let mut guard = tokio::time::timeout_at(deadline, slot.lock())
                .await
                .map_err(|_| unavailable("federation enrollment retirement timed out"))?;
            guard.retired = true;
            Self::reject(&mut guard).await;
            let mut slots = self.slots.lock().map_err(unavailable)?;
            if slots
                .get(&owner)
                .is_some_and(|current| Arc::ptr_eq(current, &slot))
            {
                slots.remove(&owner);
            }
        }
        let start = self.maintenance_cursor.load(Ordering::Relaxed);
        let mut verified = 0;
        let mut first_error = None;
        for offset in 0..layouts.len() {
            if tokio::time::Instant::now() >= deadline {
                break;
            }
            let index = start.wrapping_add(offset) % layouts.len();
            self.maintenance_cursor
                .store(index.wrapping_add(1), Ordering::Relaxed);
            let layout = &layouts[index];
            let slot = self.slot(layout.agent_id())?;
            let mut slot = tokio::time::timeout_at(deadline, slot.lock())
                .await
                .map_err(|_| unavailable("federation maintenance admission timed out"))?;
            let check = async {
                let identity = DatabaseIdentity::observe(layout)?;
                if slot.identity.as_ref() != Some(&identity) || slot.rejected || slot.peer.is_none()
                {
                    Self::reject(&mut slot).await;
                    slot.identity = Some(identity.clone());
                    let peer = Self::open(layout, identity).await?;
                    slot.peer = Some(peer);
                } else if let Some(peer) = &slot.peer {
                    verify_store(&peer.owner.pool, layout.agent_id()).await?;
                    *peer.verified_at.lock().map_err(unavailable)? = Instant::now();
                    // Admission can expire while maintenance was queued. Only
                    // a completed full check is allowed to restore it.
                    peer.valid.store(true, Ordering::Release);
                    peer.validate().await?;
                }
                slot.rejected = false;
                Ok::<_, CognitiveStoreError>(())
            };
            match tokio::time::timeout_at(deadline, check).await {
                Ok(Ok(())) => verified += 1,
                result => {
                    Self::reject(&mut slot).await;
                    let error = match result {
                        Ok(Err(error)) => error,
                        Err(_) => unavailable("federation integrity maintenance timed out"),
                        Ok(Ok(())) => unreachable!(),
                    };
                    if first_error.is_none() {
                        first_error = Some(error);
                    }
                }
            }
        }
        if let Some(error) = first_error {
            Err(error)
        } else {
            Ok(verified)
        }
    }
}

#[cfg(test)]
#[path = "cognitive_federation_pool_tests.rs"]
mod tests;
