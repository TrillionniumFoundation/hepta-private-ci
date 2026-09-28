//! Bounded off-executor ingress for the existing host, not a second supervisor.
//! A started job retains its permit and owner even if its awaiting caller is
//! cancelled. Cancellation is not evidence that the effect did not happen.
use std::sync::{Arc, Mutex};
use codex_hepta_authbus::AuthBusAuthorityHost;
use codex_hepta_contracts::{SignedFinalUseApproval, SignedFinalUseGrant};
use tokio::sync::{Notify, Semaphore};
use crate::{BaoApprovedReadV1, BaoAuthBusAdmission, BaoAuthBusEvidenceProvider, BaoClient, BaoFinalUseHost,
    BaoProductHostError, BaoReadRequest, BaoSecretReceipt, DurableLeaseRegistryV1};

pub struct BaoOwnedRead {
    pub admission: BaoAuthBusAdmission,
    pub grant: SignedFinalUseGrant,
    pub approval: SignedFinalUseApproval,
    pub request: BaoReadRequest,
}

#[derive(Debug, thiserror::Error)]
pub enum BaoWorkerError {
    #[error("bounded Bao worker capacity exhausted or admission stopped; no job entered")]
    NotAdmitted,
    #[error("Bao worker requires an active Tokio runtime; no job entered")]
    RuntimeUnavailable,
    #[error("Bao worker exited without a result; reconcile the original operation")]
    OutcomeIndeterminate,
    #[error(transparent)]
    Product(#[from] BaoProductHostError),
}

struct BlockingBudget {
    slots: Arc<Semaphore>,
    completed: Arc<Notify>,
    capacity: usize,
}
impl BlockingBudget {
    fn new(capacity: usize) -> Result<Self, BaoWorkerError> {
        if !(1..=64).contains(&capacity) { return Err(BaoWorkerError::NotAdmitted); }
        Ok(Self { slots: Arc::new(Semaphore::new(capacity)), completed: Arc::new(Notify::new()), capacity })
    }
    async fn run<T: Send + 'static>(&self, task: impl FnOnce() -> T + Send + 'static) -> Result<T, BaoWorkerError> {
        let permit = self.slots.clone().try_acquire_owned().map_err(|_| BaoWorkerError::NotAdmitted)?;
        let runtime = tokio::runtime::Handle::try_current().map_err(|_| BaoWorkerError::RuntimeUnavailable)?;
        let completed = self.completed.clone();
        runtime.spawn_blocking(move || {
            // Order matters: release capacity before waking drain waiters, also on unwind.
            struct Completion { permit: Option<tokio::sync::OwnedSemaphorePermit>, completed: Arc<Notify> }
            impl Drop for Completion {
                fn drop(&mut self) { self.permit.take(); self.completed.notify_waiters(); }
            }
            let _completion = Completion { permit: Some(permit), completed };
            task()
        }).await.map_err(|_| BaoWorkerError::OutcomeIndeterminate)
    }
    async fn drain(&self) {
        self.slots.close();
        loop {
            let changed = self.completed.notified();
            tokio::pin!(changed);
            changed.as_mut().enable();
            if self.slots.available_permits() == self.capacity { return; }
            changed.await;
        }
    }
}

/// Dependencies are enrolled once by the product host. No secret bytes enter
/// the queue; the read carries only the independently approved metadata binding.
pub struct BaoBlockingIngress {
    host: Arc<BaoFinalUseHost>,
    client: Arc<BaoClient>,
    authbus: Arc<AuthBusAuthorityHost>,
    registry: Arc<Mutex<DurableLeaseRegistryV1>>,
    budget: BlockingBudget,
}
impl BaoBlockingIngress {
    pub fn new(host: Arc<BaoFinalUseHost>, client: Arc<BaoClient>, authbus: Arc<AuthBusAuthorityHost>,
        registry: Arc<Mutex<DurableLeaseRegistryV1>>, max_in_flight: usize) -> Result<Self, BaoWorkerError>
    {
        Ok(Self { host, client, authbus, registry, budget: BlockingBudget::new(max_in_flight)? })
    }
    pub async fn consume<E: BaoAuthBusEvidenceProvider + Send + 'static>(
        &self, read: BaoOwnedRead, mut evidence: E,
    ) -> Result<BaoSecretReceipt, BaoWorkerError> {
        let runtime = tokio::runtime::Handle::try_current().map_err(|_| BaoWorkerError::RuntimeUnavailable)?;
        let host = self.host.clone(); let client = self.client.clone();
        let authbus = self.authbus.clone(); let registry = self.registry.clone();
        self.budget.run(move || runtime.block_on(host.consume_kv_v2_with_authbus(
            &client, &authbus, &registry,
            BaoApprovedReadV1 { admission: &read.admission, grant: &read.grant, approval: &read.approval, request: &read.request },
            &mut evidence,
        ))).await?.map_err(BaoWorkerError::Product)
    }
    /// Observer-only recovery. A failed or cancelled call never requeues a read.
    pub async fn reconcile<E: BaoAuthBusEvidenceProvider + Send + 'static>(
        &self, operation_id: String, mut evidence: E,
    ) -> Result<BaoSecretReceipt, BaoWorkerError> {
        let runtime = tokio::runtime::Handle::try_current().map_err(|_| BaoWorkerError::RuntimeUnavailable)?;
        let host = self.host.clone(); let authbus = self.authbus.clone(); let registry = self.registry.clone();
        self.budget.run(move || runtime.block_on(host.reconcile_consumption(
            &authbus, &registry, &operation_id, &mut evidence,
        ))).await?.map_err(BaoWorkerError::Product)
    }
    pub fn stop_admission(&self) { self.budget.slots.close(); }
    /// Waits for started work; cancelling this wait does not cancel that work.
    /// The owning runtime must remain alive until drain completes.
    pub async fn drain(&self) { self.budget.drain().await; }
    pub fn active_jobs(&self) -> usize { self.budget.capacity - self.budget.slots.available_permits() }
}

#[cfg(test)]
#[path = "blocking_ingress_tests.rs"]
mod tests;
