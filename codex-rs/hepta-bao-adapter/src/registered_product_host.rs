//! Public registered host: live execution and recovery share one owner fence.
//!
//! Keep raw transport integration separate from the registered product ingress.
//! The inner saga is crate-private so callers cannot bypass execution/recovery
//! exclusion by constructing a second host around the same durable registry.

use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_authbus::AuthBusAuthorityHost;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::FinalUseApprovalVerifier;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use codex_hepta_contracts::FinalUseRevocationReceipt;
use codex_hepta_contracts::SignedFinalUseApproval;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;

use crate::BaoApprovedReadV1;
use crate::BaoAuthBusEvidenceProvider;
use crate::BaoClient;
use crate::BaoFinalUseHostError;
use crate::BaoProductHostError;
use crate::BaoReadRequest;
use crate::BaoSecretReceipt;
use crate::DurableLeaseRegistryV1;
use crate::LeaseRegistryErrorV1;
use crate::RegisteredBaoConsumer;
use crate::recovery_exclusion::BaoExecutionGuard;

pub struct BaoFinalUseHost {
    inner: crate::final_use_host::BaoFinalUseHost,
}

impl fmt::Debug for BaoFinalUseHost {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BaoFinalUseHost")
            .field("inner", &self.inner)
            .finish()
    }
}

impl BaoFinalUseHost {
    pub fn new(
        authority: FinalUseAuthority,
        approval_verifier: FinalUseApprovalVerifier,
        revocation_verifier: FinalUseRevocationFeedVerifier,
        clock: Arc<dyn AuthorityClock>,
        consumers: impl IntoIterator<Item = RegisteredBaoConsumer>,
    ) -> Result<Self, BaoFinalUseHostError> {
        Ok(Self {
            inner: crate::final_use_host::BaoFinalUseHost::new(
                authority,
                approval_verifier,
                revocation_verifier,
                clock,
                consumers,
            )?,
        })
    }

    pub fn consumer_count(&self) -> usize {
        self.inner.consumer_count()
    }

    pub fn apply_revocation_update(
        &self,
        update: &SignedFinalUseRevocationUpdate,
    ) -> Result<FinalUseRevocationReceipt, BaoFinalUseHostError> {
        self.inner.apply_revocation_update(update)
    }

    /// Legacy registered read without a durable consumption operation.
    /// Quota-controlled product callers must use the operation-aware entrypoint.
    pub async fn consume_kv_v2(
        &self,
        client: &BaoClient,
        grant: &SignedFinalUseGrant,
        approval: &SignedFinalUseApproval,
        request: &BaoReadRequest,
    ) -> Result<BaoSecretReceipt, BaoFinalUseHostError> {
        self.inner
            .consume_kv_v2(client, grant, approval, request)
            .await
    }

    /// Hold the owner fence across every await, callback and terminal commit.
    /// A second live request or a reconciler returns WriterBusy, without
    /// observing absence, cancelling quota, or entering the consumer.
    pub async fn consume_kv_v2_with_authbus<E: BaoAuthBusEvidenceProvider>(
        &self,
        client: &BaoClient,
        authbus: &AuthBusAuthorityHost,
        registry: &Mutex<DurableLeaseRegistryV1>,
        read: BaoApprovedReadV1<'_>,
        evidence: &mut E,
    ) -> Result<BaoSecretReceipt, BaoProductHostError> {
        let _execution =
            BaoExecutionGuard::try_enter(registry).map_err(BaoProductHostError::Store)?;
        validate_owner(registry, read.admission.operation_id.as_str())?;
        self.inner
            .consume_kv_v2_with_authbus(client, authbus, registry, read, evidence)
            .await
    }

    /// Recovery cannot overlap a live request sharing this metadata owner.
    /// The AuthBus lookup additionally obtains a transactional snapshot so a
    /// cancelled, already-enqueued SQLite commit cannot be mistaken for absence.
    pub async fn reconcile_consumption<E: BaoAuthBusEvidenceProvider>(
        &self,
        authbus: &AuthBusAuthorityHost,
        registry: &Mutex<DurableLeaseRegistryV1>,
        operation_id: &str,
        evidence: &mut E,
    ) -> Result<BaoSecretReceipt, BaoProductHostError> {
        let _execution =
            BaoExecutionGuard::try_enter(registry).map_err(BaoProductHostError::Store)?;
        validate_owner(registry, operation_id)?;
        self.inner
            .reconcile_consumption(authbus, registry, operation_id, evidence)
            .await
    }
}

fn validate_owner(
    registry: &Mutex<DurableLeaseRegistryV1>,
    operation_id: &str,
) -> Result<(), BaoProductHostError> {
    let owner = registry
        .lock()
        .map_err(|_| BaoProductHostError::Store(LeaseRegistryErrorV1::Fenced))?;
    match owner.consumption_result(operation_id) {
        Ok(_) | Err(LeaseRegistryErrorV1::OperationNotFound) => Ok(()),
        Err(error) => Err(BaoProductHostError::Store(error)),
    }
}
