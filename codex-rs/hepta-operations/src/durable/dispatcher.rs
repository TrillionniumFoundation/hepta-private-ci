use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::DispatchLease;
use super::DurableOperationError;
use super::DurableOperationStore;
use super::MAX_OPERATION_CLAIM_BATCH;
use super::MAX_OPERATION_LEASE_MS;

/// Result returned synchronously by an effect adapter while a final-use token
/// is being consumed. Neither variant is terminal operation success.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DispatchBoundaryResult<T> {
    /// The transport/queue acknowledged the dispatch. Terminal effect state
    /// still requires independent reconciliation.
    Acknowledged {
        value: T,
        acknowledgement_digest: Digest32,
    },
    /// The call may have crossed the effect boundary but no trustworthy
    /// acknowledgement was obtained. Blind retry is prohibited.
    Indeterminate { reason_digest: Digest32 },
}

/// Bounded claim/dispatch coordinator for one owner generation.
///
/// The dispatcher never manufactures authority. `dispatch_authorized` consumes
/// a real `kernel.authority` final-use token immediately around the synchronous
/// adapter boundary, records `Dispatched` durably before entry, and keeps queue
/// acknowledgement separate from terminal effect observation.
#[derive(Clone)]
pub struct DurableDispatcher {
    store: DurableOperationStore,
    worker_id: StableId,
    owner_generation: Generation,
    lease_ms: i64,
}

impl DurableDispatcher {
    pub fn new(
        store: DurableOperationStore,
        worker_id: StableId,
        owner_generation: Generation,
        lease_ms: i64,
    ) -> Result<Self, DurableOperationError> {
        if !(1..=MAX_OPERATION_LEASE_MS).contains(&lease_ms) {
            return Err(DurableOperationError::Invalid(
                "dispatcher lease must be 1..=60000 milliseconds",
            ));
        }
        Ok(Self {
            store,
            worker_id,
            owner_generation,
            lease_ms,
        })
    }

    pub fn store(&self) -> &DurableOperationStore {
        &self.store
    }

    pub async fn claim_ready(
        &self,
        limit: u32,
    ) -> Result<Vec<DispatchLease>, DurableOperationError> {
        if limit == 0 || limit > MAX_OPERATION_CLAIM_BATCH {
            return Err(DurableOperationError::Invalid(
                "dispatcher batch must be 1..=256",
            ));
        }
        let pending = self.store.pending_outbox(limit).await?;
        let mut leases = Vec::with_capacity(pending.len());
        for status in pending {
            match self
                .store
                .claim_outbox(
                    &status.scope,
                    &status.operation_id,
                    &self.worker_id,
                    self.owner_generation,
                    self.lease_ms,
                )
                .await
            {
                Ok(lease) => leases.push(lease),
                Err(
                    DurableOperationError::StaleLease
                    | DurableOperationError::UnavailableState
                    | DurableOperationError::ReconciliationRequired,
                ) => {}
                Err(error) => return Err(error),
            }
        }
        Ok(leases)
    }

    pub async fn dispatch_authorized<T, F>(
        &self,
        authority: &FinalUseAuthority,
        signed: &SignedFinalUseGrant,
        lease: &DispatchLease,
        dispatch_digest: Digest32,
        adapter: F,
    ) -> Result<DispatchBoundaryResult<T>, DurableOperationError>
    where
        F: FnOnce(&DispatchLease) -> DispatchBoundaryResult<T>,
    {
        if dispatch_digest.is_zero() {
            return Err(DurableOperationError::Invalid("dispatch digest is zero"));
        }
        if lease.owner_generation != self.owner_generation || lease.worker_id != self.worker_id {
            return Err(DurableOperationError::StaleLease);
        }

        let (token, binding) = self.store.claim_final_use(authority, signed, lease).await?;
        // Persist the conservative may-have-crossed state before adapter entry.
        // If the process dies immediately afterwards, recovery reconciles instead
        // of replaying an effect whose external status is unknown.
        self.store.mark_dispatched(lease, dispatch_digest).await?;

        let result = authority.with_verified_use(token, &binding, || adapter(lease))?;
        match &result {
            DispatchBoundaryResult::Acknowledged {
                acknowledgement_digest,
                ..
            } => {
                if acknowledgement_digest.is_zero() {
                    let reason = Digest32::of_bytes(
                        b"hepta.kernel.operations.invalid-acknowledgement.v1",
                    );
                    self.store.mark_indeterminate(lease, reason).await?;
                    return Err(DurableOperationError::Invalid(
                        "adapter acknowledgement digest is zero",
                    ));
                }
                self.store
                    .acknowledge_outbox(lease, *acknowledgement_digest)
                    .await?;
            }
            DispatchBoundaryResult::Indeterminate { reason_digest } => {
                let reason = if reason_digest.is_zero() {
                    Digest32::of_bytes(b"hepta.kernel.operations.invalid-indeterminate.v1")
                } else {
                    *reason_digest
                };
                self.store.mark_indeterminate(lease, reason).await?;
                if reason_digest.is_zero() {
                    return Err(DurableOperationError::Invalid(
                        "adapter indeterminate reason digest is zero",
                    ));
                }
            }
        }
        Ok(result)
    }
}

#[cfg(test)]
#[path = "dispatcher_tests.rs"]
mod tests;
