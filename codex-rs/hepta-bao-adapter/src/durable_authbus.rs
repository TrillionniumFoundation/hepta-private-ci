//! Bao composition that accepts only an entered durable operation handle.
//!
//! The operation identifier is never accepted as request metadata. The
//! `kernel.operations` owner has already claimed the exact row, consumed its
//! own final-use grant and persisted an `Indeterminate` handoff before this
//! module can start provider I/O. Consequently a crash, timeout or
//! `MutationOutcomeUnknown` cannot be retried under a fresh operation identity.
//! Terminal convergence remains the responsibility of an independent observer
//! through `DurableOperationStore::reconcile_entered_authbus_operation`.

use codex_hepta_authbus::AuthBusExecutionPort;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_operations::DurableOperationError;
use codex_hepta_operations::DurableOperationStore;
use codex_hepta_operations::EnteredAuthBusOperationHandle;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::BaoAuthBusAdmission;
use crate::BaoAuthBusError;
use crate::BaoAuthBusEvidenceProvider;
use crate::BaoClient;
use crate::BaoClientError;
use crate::BaoReadRequest;
use crate::BaoSecretReceipt;

pub const BAO_DURABLE_OPERATION_DESTINATION: &str = "provider:heptabao";

/// AuthBus policy/quota inputs for an operation whose identity is supplied by
/// the sealed durable handle rather than by this structure.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BaoDurableAuthBusAdmission {
    pub policy_revision: u64,
    pub quota_key: StableId,
    pub expected_quota_revision: u64,
    pub amount: u64,
    pub expires_at_ms: u64,
}

/// Caller-visible correlation across the durable operation ledger, AuthBus
/// reservation effect and provider receipt.
///
/// `reconciliation_required` is always true. Provider success here is not
/// allowed to forge the independent terminal receipt required by the operation
/// owner.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BaoDurableAuthBusReceipt {
    pub operation_scope_id: StableId,
    pub operation_id: StableId,
    pub owner_generation: Generation,
    pub operation_semantic_digest: Digest32,
    pub authbus_effect_digest: Digest32,
    pub provider_receipt: BaoSecretReceipt,
    pub reconciliation_required: bool,
}

#[derive(Debug, thiserror::Error)]
pub enum BaoDurableAuthBusError {
    #[error("Bao request does not match the entered durable operation")]
    InvalidOperationBinding,
    #[error(transparent)]
    Operation(#[from] DurableOperationError),
    #[error(transparent)]
    AuthBus(#[from] BaoAuthBusError),
}

impl BaoClient {
    /// Digest that a `DurableOperationIntentV1` must store as `payload_digest`
    /// for this exact Bao request.
    pub fn durable_operation_payload_digest(
        &self,
        request: &BaoReadRequest,
    ) -> Result<Digest32, BaoClientError> {
        Ok(Digest32::from_array(self.binding(request)?.request_sha256))
    }

    /// Execute the existing quota-controlled Bao path only after validating a
    /// non-forgeable operation-owner handle against current durable state.
    ///
    /// The operation must have destination `provider:heptabao` and payload
    /// digest `durable_operation_payload_digest(request)`. A stale revision,
    /// writer fence or owner generation is rejected before trusted-time,
    /// reservation or network activity.
    pub async fn consume_kv_v2_with_durable_authbus_operation<
        E: BaoAuthBusEvidenceProvider,
    >(
        &self,
        operations: &DurableOperationStore,
        operation: &EnteredAuthBusOperationHandle,
        authbus: AuthBusExecutionPort<'_>,
        admission: &BaoDurableAuthBusAdmission,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoReadRequest,
        evidence: &mut E,
        consumer: impl FnOnce(&[u8]) -> Result<(), ()>,
    ) -> Result<BaoDurableAuthBusReceipt, BaoDurableAuthBusError> {
        let current = operations
            .validate_entered_authbus_operation(operation)
            .await?;
        let destination = StableId::new(BAO_DURABLE_OPERATION_DESTINATION)
            .map_err(|_| BaoDurableAuthBusError::InvalidOperationBinding)?;
        let payload_digest = self
            .durable_operation_payload_digest(request)
            .map_err(BaoAuthBusError::from)?;
        if operation.destination() != &destination
            || operation.payload_digest() != payload_digest
            || current.intent.destination != destination
            || current.intent.payload_digest != payload_digest
            || current.semantic_digest != operation.semantic_digest()
        {
            return Err(BaoDurableAuthBusError::InvalidOperationBinding);
        }

        let effect_digest = self
            .authbus_effect_digest(request, operation.operation_id())
            .map_err(BaoAuthBusError::from)?;
        let provider_receipt = self
            .consume_kv_v2_with_authbus(
                authbus,
                &BaoAuthBusAdmission {
                    policy_revision: admission.policy_revision,
                    quota_key: admission.quota_key.clone(),
                    expected_quota_revision: admission.expected_quota_revision,
                    operation_id: operation.operation_id().clone(),
                    amount: admission.amount,
                    expires_at_ms: admission.expires_at_ms,
                },
                authority,
                grant,
                request,
                evidence,
                consumer,
            )
            .await?;

        Ok(BaoDurableAuthBusReceipt {
            operation_scope_id: operation.scope_id().clone(),
            operation_id: operation.operation_id().clone(),
            owner_generation: operation.owner_generation(),
            operation_semantic_digest: operation.semantic_digest(),
            authbus_effect_digest: effect_digest,
            provider_receipt,
            reconciliation_required: true,
        })
    }
}
