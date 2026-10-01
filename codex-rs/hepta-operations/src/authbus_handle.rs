//! Sealed `kernel.operations` identity for AuthBus product effects.
//!
//! A product caller cannot mint this handle from request metadata. It is issued
//! only after the durable operation owner has claimed the exact prepared row
//! under a current generation and writer fence. Crossing the AuthBus handoff
//! consumes the operation owner's final-use grant and durably records
//! `Indeterminate` before asynchronous provider work can start. Recovery and
//! terminal convergence therefore reuse the same operation identity.

use std::fmt;
use std::time::Duration;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::DispatchClaim;
use crate::DispatchEffect;
use crate::DurableOperationError;
use crate::DurableOperationRecord;
use crate::DurableOperationState;
use crate::DurableOperationStore;
use crate::ReconciliationReceiptV1;

const AUTHBUS_HANDOFF_DIGEST_DOMAIN: &[u8] =
    b"hepta.kernel.operations.authbus-handoff-entered.v1\0";

/// Linear exact claim over one durable operation.
pub struct AuthBusOperationHandle {
    claim: DispatchClaim,
    semantic_digest: Digest32,
}

impl fmt::Debug for AuthBusOperationHandle {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("AuthBusOperationHandle")
            .field("scope_id", &self.claim.intent.scope_id)
            .field("operation_id", &self.claim.intent.operation_id)
            .field("destination", &self.claim.intent.destination)
            .field("owner_generation", &self.claim.owner_generation)
            .field("writer_fence", &self.claim.fence)
            .finish_non_exhaustive()
    }
}

impl AuthBusOperationHandle {
    #[must_use]
    pub fn scope_id(&self) -> &StableId {
        &self.claim.intent.scope_id
    }

    #[must_use]
    pub fn operation_id(&self) -> &StableId {
        &self.claim.intent.operation_id
    }

    #[must_use]
    pub fn destination(&self) -> &StableId {
        &self.claim.intent.destination
    }

    #[must_use]
    pub fn payload_digest(&self) -> Digest32 {
        self.claim.intent.payload_digest
    }

    #[must_use]
    pub fn semantic_digest(&self) -> Digest32 {
        self.semantic_digest
    }

    #[must_use]
    pub fn owner_generation(&self) -> Generation {
        self.claim.owner_generation
    }

    #[must_use]
    pub fn writer_fence(&self) -> u64 {
        self.claim.fence
    }
}

/// Durable proof that the exact operation entered an asynchronous AuthBus path.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EnteredAuthBusOperationHandle {
    scope_id: StableId,
    operation_id: StableId,
    destination: StableId,
    payload_digest: Digest32,
    semantic_digest: Digest32,
    owner_generation: Generation,
    revision: u64,
    writer_fence: u64,
}

impl EnteredAuthBusOperationHandle {
    #[must_use]
    pub fn scope_id(&self) -> &StableId {
        &self.scope_id
    }

    #[must_use]
    pub fn operation_id(&self) -> &StableId {
        &self.operation_id
    }

    #[must_use]
    pub fn destination(&self) -> &StableId {
        &self.destination
    }

    #[must_use]
    pub fn payload_digest(&self) -> Digest32 {
        self.payload_digest
    }

    #[must_use]
    pub fn semantic_digest(&self) -> Digest32 {
        self.semantic_digest
    }

    #[must_use]
    pub fn owner_generation(&self) -> Generation {
        self.owner_generation
    }

    #[must_use]
    pub fn revision(&self) -> u64 {
        self.revision
    }

    #[must_use]
    pub fn writer_fence(&self) -> u64 {
        self.writer_fence
    }
}

impl DurableOperationStore {
    /// Claim the exact operation selected by the durable owner.
    pub async fn claim_authbus_operation(
        &self,
        scope_id: &StableId,
        operation_id: &StableId,
        expected_destination: &StableId,
        expected_payload_digest: Digest32,
        worker_id: &StableId,
        owner_generation: Generation,
        lease: Duration,
    ) -> Result<Option<AuthBusOperationHandle>, DurableOperationError> {
        if expected_payload_digest.is_zero() {
            return Err(DurableOperationError::Invalid(
                "AuthBus operation payload digest",
            ));
        }
        let current = self
            .operation(scope_id, operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(operation_id.clone()))?;
        if current.intent.destination != *expected_destination
            || current.intent.payload_digest != expected_payload_digest
        {
            return Err(DurableOperationError::Conflict(operation_id.clone()));
        }
        let Some(claim) = self
            .claim_operation(
                scope_id,
                operation_id,
                worker_id,
                owner_generation,
                lease,
            )
            .await?
        else {
            return Ok(None);
        };
        if claim.intent.destination != *expected_destination
            || claim.intent.payload_digest != expected_payload_digest
        {
            return Err(DurableOperationError::Corrupt(
                "claimed AuthBus operation binding changed".to_owned(),
            ));
        }
        let semantic_digest = claim.intent.semantic_digest();
        Ok(Some(AuthBusOperationHandle {
            claim,
            semantic_digest,
        }))
    }

    /// Consume the operation-owner grant and persist uncertainty before the
    /// asynchronous product effect can begin.
    pub async fn enter_authbus_operation(
        &self,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        handle: AuthBusOperationHandle,
    ) -> Result<EnteredAuthBusOperationHandle, DurableOperationError> {
        let current = self
            .operation(handle.scope_id(), handle.operation_id())
            .await?
            .ok_or_else(|| DurableOperationError::Missing(handle.operation_id().clone()))?;
        validate_claim_record(&current, &handle)?;
        let scope_id = handle.scope_id().clone();
        let operation_id = handle.operation_id().clone();
        let expected_destination = handle.destination().clone();
        let expected_payload = handle.payload_digest();
        let expected_semantic = handle.semantic_digest();
        let expected_generation = handle.owner_generation();
        let expected_fence = handle.writer_fence();
        let authorized = self
            .authorize_dispatch(authority, grant, &handle.claim)
            .await?;
        self.execute_authorized(authorized, |_| DispatchEffect::Indeterminate {
            value: (),
            reason_digest: Digest32::of_bytes(AUTHBUS_HANDOFF_DIGEST_DOMAIN),
        })
        .await?;
        let current = self
            .operation(&scope_id, &operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(operation_id.clone()))?;
        if current.semantic_digest != expected_semantic
            || current.intent.destination != expected_destination
            || current.intent.payload_digest != expected_payload
            || current.intent.owner_generation != expected_generation
            || current.writer_fence != expected_fence
        {
            return Err(DurableOperationError::Conflict(operation_id));
        }
        if current.state != DurableOperationState::Indeterminate {
            return Err(DurableOperationError::InvalidTransition {
                from: current.state,
                to: "authbus_entered",
            });
        }
        Ok(entered_from_record(current))
    }

    /// Validate generation, revision, fence and exact request binding again
    /// immediately before product I/O.
    pub async fn validate_entered_authbus_operation(
        &self,
        handle: &EnteredAuthBusOperationHandle,
    ) -> Result<DurableOperationRecord, DurableOperationError> {
        let current = self
            .operation(handle.scope_id(), handle.operation_id())
            .await?
            .ok_or_else(|| DurableOperationError::Missing(handle.operation_id().clone()))?;
        if current.semantic_digest != handle.semantic_digest
            || current.intent.destination != handle.destination
            || current.intent.payload_digest != handle.payload_digest
        {
            return Err(DurableOperationError::Conflict(handle.operation_id().clone()));
        }
        if current.intent.owner_generation != handle.owner_generation {
            return Err(DurableOperationError::StaleGeneration);
        }
        if current.revision != handle.revision || current.writer_fence != handle.writer_fence {
            return Err(DurableOperationError::StaleLease);
        }
        if current.state != DurableOperationState::Indeterminate {
            return Err(DurableOperationError::InvalidTransition {
                from: current.state,
                to: "authbus_effect",
            });
        }
        Ok(current)
    }

    /// Recover the same identity after process loss or owner-generation change.
    pub async fn recover_entered_authbus_operation(
        &self,
        scope_id: &StableId,
        operation_id: &StableId,
        owner_generation: Generation,
    ) -> Result<EnteredAuthBusOperationHandle, DurableOperationError> {
        let current = self
            .operation(scope_id, operation_id)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(operation_id.clone()))?;
        let current = if matches!(
            current.state,
            DurableOperationState::Dispatching | DurableOperationState::Dispatched
        ) || current.intent.owner_generation != owner_generation
        {
            self.adopt_unsettled_generation(scope_id, operation_id, owner_generation)
                .await?
        } else {
            current
        };
        if current.state != DurableOperationState::Indeterminate {
            return Err(DurableOperationError::InvalidTransition {
                from: current.state,
                to: "authbus_recovery",
            });
        }
        Ok(entered_from_record(current))
    }

    /// Settle only from independently supplied destination evidence.
    pub async fn reconcile_entered_authbus_operation(
        &self,
        handle: &EnteredAuthBusOperationHandle,
        receipt: &ReconciliationReceiptV1,
    ) -> Result<DurableOperationRecord, DurableOperationError> {
        self.validate_entered_authbus_operation(handle).await?;
        self.observe_terminal(handle.scope_id(), handle.operation_id(), receipt)
            .await
    }
}

fn validate_claim_record(
    current: &DurableOperationRecord,
    handle: &AuthBusOperationHandle,
) -> Result<(), DurableOperationError> {
    if current.semantic_digest != handle.semantic_digest
        || current.intent != handle.claim.intent
        || current.intent.destination != *handle.destination()
        || current.intent.payload_digest != handle.payload_digest()
    {
        return Err(DurableOperationError::Conflict(handle.operation_id().clone()));
    }
    if current.intent.owner_generation != handle.owner_generation() {
        return Err(DurableOperationError::StaleGeneration);
    }
    if current.writer_fence != handle.writer_fence() {
        return Err(DurableOperationError::StaleLease);
    }
    if current.state != DurableOperationState::Prepared {
        return Err(DurableOperationError::InvalidTransition {
            from: current.state,
            to: "authbus_authorized",
        });
    }
    Ok(())
}

fn entered_from_record(current: DurableOperationRecord) -> EnteredAuthBusOperationHandle {
    EnteredAuthBusOperationHandle {
        scope_id: current.intent.scope_id,
        operation_id: current.intent.operation_id,
        destination: current.intent.destination,
        payload_digest: current.intent.payload_digest,
        semantic_digest: current.semantic_digest,
        owner_generation: current.intent.owner_generation,
        revision: current.revision,
        writer_fence: current.writer_fence,
    }
}
