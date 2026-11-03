//! Shared lifetime fence for the original durable writer generation.
//!
//! The lock is local synchronization, never an authority issuer. An owned read
//! permit spans each mutation/physical entry; release and rollback take its
//! write side. A canceled caller cannot drop a commit's permit prematurely.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::MutexGuard;

use tokio::sync::OwnedRwLockReadGuard;
use tokio::sync::OwnedRwLockWriteGuard;
use tokio::sync::RwLock;

use super::DurableWriterLock;
use super::ProductionDurableWriter;
use super::ProductionLeaseReceipt;
use super::ProductionWriterError;

pub(super) struct WriterLifecycle {
    closed: Mutex<bool>,
    permits: Arc<RwLock<()>>,
}

impl Default for WriterLifecycle {
    fn default() -> Self {
        Self {
            closed: Mutex::new(false),
            permits: Arc::new(RwLock::new(())),
        }
    }
}

impl WriterLifecycle {
    pub(super) fn lock_open(&self) -> Result<MutexGuard<'_, bool>, ProductionWriterError> {
        let state = self.closed.lock().map_err(|_| {
            ProductionWriterError::Durability("writer lifetime fence is poisoned".to_string())
        })?;
        if *state {
            return Err(ProductionWriterError::StaleReceipt);
        }
        Ok(state)
    }
}

/// Keeps the existing writer generation open through an owned asynchronous
/// operation. It is not cloneable, serializable, or an authorization grant.
#[must_use = "retain the lease guard through the owned commit or concrete entry"]
pub struct ProductionCurrentLeaseGuard {
    _writer_lock: Arc<DurableWriterLock>,
    _permit: OwnedRwLockReadGuard<()>,
}

/// Exclusive side of the same writer lifetime fence. Retained preparation
/// uses it only while inspecting the original operation ledger and restoring
/// original in-memory owner state; it must end before ordinary admission.
pub(super) struct ProductionPreparationFence {
    _writer_lock: Arc<DurableWriterLock>,
    _permit: OwnedRwLockWriteGuard<()>,
}

impl ProductionDurableWriter {
    pub(super) async fn acquire_preparation_fence(&self) -> Result<ProductionPreparationFence, ProductionWriterError> {
        if self.live_verifier.is_none() { return Err(ProductionWriterError::LiveVerifierRequired); }
        drop(self.lifecycle.lock_open()?);
        let permit = Arc::clone(&self.lifecycle.permits).write_owned().await;
        drop(self.lifecycle.lock_open()?);
        self.verify_authority().await?;
        drop(self.lifecycle.lock_open()?);
        Ok(ProductionPreparationFence { _writer_lock: Arc::clone(&self._writer_lock), _permit: permit })
    }

    /// Obtain an owned permit on this exact live-verified writer generation.
    ///
    /// The host must move this value into the task that owns the commit, rather
    /// than hold it only in a cancelable task waiting for that commit.
    pub async fn acquire_current_lease(
        &self,
    ) -> Result<ProductionCurrentLeaseGuard, ProductionWriterError> {
        if self.live_verifier.is_none() {
            return Err(ProductionWriterError::LiveVerifierRequired);
        }
        self.acquire_owner_lease().await
    }

    // The original dispatcher also has a qualification-only constructor
    // without a retained verifier. It still needs this same lifetime fence;
    // public native/semantic entry requires acquire_current_lease instead.
    pub(super) async fn acquire_owner_lease(
        &self,
    ) -> Result<ProductionCurrentLeaseGuard, ProductionWriterError> {
        drop(self.lifecycle.lock_open()?);
        let permit = Arc::clone(&self.lifecycle.permits).read_owned().await;
        drop(self.lifecycle.lock_open()?);
        self.verify_authority().await?;
        drop(self.lifecycle.lock_open()?);
        Ok(ProductionCurrentLeaseGuard {
            _writer_lock: Arc::clone(&self._writer_lock),
            _permit: permit,
        })
    }

    pub(super) async fn close_owned_lease(
        &self,
        rollback: bool,
    ) -> Result<ProductionLeaseReceipt, ProductionWriterError> {
        // This synchronous linearization also prevents a prepared handoff
        // from entering while a release is waiting on an earlier permit.
        *self.lifecycle.lock_open()? = true;
        let writer = self.clone();
        tokio::spawn(async move {
            let _permit = Arc::clone(&writer.lifecycle.permits).write_owned().await;
            let result: Result<ProductionLeaseReceipt, ProductionWriterError> = async {
                writer.verify_authority().await?;
                let (head, disposition) = if rollback {
                    (writer.lease.rollback_lease().await?, "rolled_back")
                } else {
                    (writer.lease.release().await?, "released")
                };
                Ok(ProductionLeaseReceipt::new(&writer.authority, head, disposition))
            }.await;
            if result.is_err() {
                // A rejected close (for example unresolved outcomes) must
                // leave observation/reconciliation available. No prepared
                // entry survives this exclusive permit, and a new permit
                // revalidates the durable lease before any operation.
                *writer.lifecycle.closed.lock().map_err(|_| {
                    ProductionWriterError::Durability("writer lifetime fence is poisoned".to_string())
                })? = false;
            }
            result
        })
        .await
        .map_err(|error| ProductionWriterError::Durability(format!("writer close task: {error}")))?
    }

    pub(super) async fn recover_owned_lease(
        &self,
        occurrence_key: String,
    ) -> Result<super::ProductionRecoveryReceipt, ProductionWriterError> {
        let writer = self.clone();
        tokio::spawn(async move {
            let _permit = Arc::clone(&writer.lifecycle.permits).write_owned().await;
            drop(writer.lifecycle.lock_open()?);
            writer.verify_authority().await?;
            let result = writer
                .lease
                .finalize_replayed_occurrence(&occurrence_key)
                .await?;
            if matches!(result, super::LocalReplayFinalization::Released { .. }) {
                *writer.lifecycle.lock_open()? = true;
            }
            Ok(super::ProductionRecoveryReceipt::from_local(
                &writer.authority,
                writer.lease_id(),
                &occurrence_key,
                result,
            ))
        })
        .await
        .map_err(|error| ProductionWriterError::Durability(format!("writer recovery task: {error}")))?
    }
}

