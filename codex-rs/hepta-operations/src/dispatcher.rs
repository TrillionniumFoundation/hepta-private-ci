use std::time::Duration;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::DispatchClaim;
use crate::DispatchEffect;
use crate::DurableOperationError;
use crate::DurableOperationStore;
use crate::MAX_DURABLE_CLAIM_BATCH;
use crate::OperationIntentV1;

/// Bounded source-side dispatcher. Grant resolution and the actual effect
/// adapter remain host-owned dependencies; this type owns only polling,
/// fencing, durable state transitions and retry/indeterminate classification.
pub struct DurableDispatcher<'a> {
    store: &'a DurableOperationStore,
    destination: StableId,
    worker_id: StableId,
    owner_generation: Generation,
    lease: Duration,
    batch_limit: u32,
}

impl<'a> DurableDispatcher<'a> {
    pub fn new(
        store: &'a DurableOperationStore,
        destination: StableId,
        worker_id: StableId,
        owner_generation: Generation,
        lease: Duration,
        batch_limit: u32,
    ) -> Result<Self, DurableOperationError> {
        if batch_limit == 0 || batch_limit > MAX_DURABLE_CLAIM_BATCH {
            return Err(DurableOperationError::Invalid("dispatcher batch limit"));
        }
        Ok(Self {
            store,
            destination,
            worker_id,
            owner_generation,
            lease,
            batch_limit,
        })
    }

    pub fn destination(&self) -> &StableId {
        &self.destination
    }

    pub fn worker_id(&self) -> &StableId {
        &self.worker_id
    }

    pub async fn claim_batch(&self) -> Result<Vec<DispatchClaim>, DurableOperationError> {
        let mut claims = Vec::with_capacity(self.batch_limit as usize);
        for _ in 0..self.batch_limit {
            let claim = self
                .store
                .claim_next(
                    &self.destination,
                    &self.worker_id,
                    self.owner_generation,
                    self.lease,
                )
                .await?;
            let Some(claim) = claim else {
                break;
            };
            claims.push(claim);
        }
        Ok(claims)
    }

    /// Process one already-fenced claim. The signed grant must be resolved for
    /// this exact claim by the host immediately before this call.
    pub async fn dispatch_claim<T>(
        &self,
        authority: &FinalUseAuthority,
        signed_grant: &SignedFinalUseGrant,
        claim: DispatchClaim,
        effect: impl FnOnce(&OperationIntentV1) -> DispatchEffect<T>,
    ) -> Result<T, DurableOperationError> {
        if claim.intent.destination != self.destination
            || claim.worker_id != self.worker_id
            || claim.owner_generation != self.owner_generation
        {
            return Err(DurableOperationError::StaleLease);
        }
        let authorized = self
            .store
            .authorize_dispatch(authority, signed_grant, &claim)
            .await?;
        self.store.execute_authorized(authorized, effect).await
    }
}
