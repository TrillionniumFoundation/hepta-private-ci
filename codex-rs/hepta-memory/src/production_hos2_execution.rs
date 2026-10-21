//! Serialize native dispatch and observation within the retained source owner.
//!
//! This gate belongs to the existing cross-process writer lock. It supplies no
//! authority, durable state, retry proof or native terminal evidence. In-process
//! cancellation cannot release an unresolved use into an observer that would
//! mistake an older D result for the current request.

use super::ProductionWriterError;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use tokio::sync::Semaphore;
use tokio::sync::SemaphorePermit;
use tokio::sync::TryAcquireError;

pub(super) struct Hos2OwnerGate {
    use_permit: Semaphore,
    interrupted: AtomicBool,
}

impl Default for Hos2OwnerGate {
    fn default() -> Self {
        Self {
            use_permit: Semaphore::new(/*permits*/ 1),
            interrupted: AtomicBool::new(/*v*/ false),
        }
    }
}

pub(super) struct Hos2OwnerUse<'a> {
    _permit: SemaphorePermit<'a>,
    interrupted: &'a AtomicBool,
    completed: bool,
    unrecorded_contradiction: bool,
}

impl Hos2OwnerGate {
    pub(super) async fn dispatch(&self) -> Result<Hos2OwnerUse<'_>, ProductionWriterError> {
        let permit = self.use_permit.acquire().await
            .map_err(|error| ProductionWriterError::Durability(format!("original HOS2 use gate is closed: {error}")))?;
        Hos2OwnerUse::new(permit, &self.interrupted)
    }

    pub(super) fn observe(&self) -> Result<Option<Hos2OwnerUse<'_>>, ProductionWriterError> {
        let permit = match self.use_permit.try_acquire() {
            Ok(permit) => permit,
            Err(TryAcquireError::NoPermits) => return Ok(None),
            Err(TryAcquireError::Closed) => return Err(ProductionWriterError::Durability(
                "original HOS2 use gate is closed".to_string(),
            )),
        };
        Hos2OwnerUse::new(permit, &self.interrupted).map(Some)
    }
}

impl<'a> Hos2OwnerUse<'a> {
    fn new(permit: SemaphorePermit<'a>, interrupted: &'a AtomicBool) -> Result<Self, ProductionWriterError> {
        if interrupted.load(Ordering::Acquire) {
            return Err(ProductionWriterError::Durability(
                "HOS2 original owner has an interrupted use; independently authenticated recovery is required".to_string(),
            ));
        }
        Ok(Self { _permit: permit, interrupted, completed: false, unrecorded_contradiction: false })
    }

    pub(super) fn contradiction_observed(&mut self) {
        self.unrecorded_contradiction = true;
    }

    pub(super) fn contradiction_recorded(&mut self) {
        self.unrecorded_contradiction = false;
    }

    /// A normally returned unknown observation may use the original recovery
    /// path. A known contradiction must first reach the original SQLite event.
    /// Dropping the future, unwinding, or failing that append leaves this live
    /// owner stopped; claim expiry alone cannot make observation safe.
    pub(super) fn complete(mut self) {
        self.completed = !self.unrecorded_contradiction;
    }
}

impl Drop for Hos2OwnerUse<'_> {
    fn drop(&mut self) {
        if !self.completed {
            // Publish the stop before returning the sole use permit. The
            // next dispatcher/observer checks it only after acquiring that
            // permit, so no clone can race through an interrupted owner.
            self.interrupted.store(/*val*/ true, Ordering::Release);
        }
    }
}
