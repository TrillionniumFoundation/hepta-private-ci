use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::DispatchLease;
use crate::DurableOperationError;
use crate::DurableOperationState;
use crate::DurableOperationStatus;
use crate::DurableOperationStore;
use crate::OperationIdentity;
use crate::ReconciliationOutcome;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DispatchEnvelope {
    pub lease: DispatchLease,
    pub request_digest: Digest32,
}

impl DispatchEnvelope {
    pub fn from_lease(lease: DispatchLease) -> Self {
        let request_digest = request_digest(&lease);
        Self {
            lease,
            request_digest,
        }
    }

    pub fn final_use_binding(&self) -> FinalUseBinding {
        FinalUseBinding {
            subject_id: self.lease.identity.operation_id.as_str().to_owned(),
            destination_id: self.lease.destination_id.as_str().to_owned(),
            request_sha256: self.request_digest.into_array(),
            scope_sha256: Digest32::of_bytes(self.lease.identity.scope_id.as_str().as_bytes())
                .into_array(),
            payload_sha256: self.lease.payload_digest.into_array(),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DispatchResult {
    /// The adapter guarantees the external effect boundary was not entered.
    NotAttempted {
        reason_digest: Digest32,
        retry_after_ms: i64,
    },
    /// Queue/network acceptance is ordinary evidence only, never terminal success.
    TransportAccepted {
        acknowledgement_digest: Digest32,
        acknowledgement_watermark: u64,
    },
    /// A trusted destination observer produced a terminal result.
    Terminal {
        observer_id: StableId,
        observer_generation: Generation,
        outcome: ReconciliationOutcome,
        evidence_digest: Digest32,
    },
    /// The adapter cannot determine whether the effect crossed the boundary.
    UnknownEffect { reason_digest: Digest32 },
}

pub trait DestinationEffectAdapter {
    /// This method is intentionally synchronous because the current
    /// `kernel.authority` final-use API holds its revocation fence only while
    /// this call executes. Async adapters must expose a synchronous final-use
    /// entry wrapper or extend the authority boundary before production use.
    fn dispatch(&self, envelope: &DispatchEnvelope) -> DispatchResult;
}

#[derive(Debug)]
pub enum DurableDispatchError {
    Store(DurableOperationError),
    Authority(FinalUseError),
}

impl std::fmt::Display for DurableDispatchError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Store(error) => write!(formatter, "{error}"),
            Self::Authority(error) => write!(formatter, "final-use authority rejected dispatch: {error}"),
        }
    }
}

impl std::error::Error for DurableDispatchError {}

impl From<DurableOperationError> for DurableDispatchError {
    fn from(value: DurableOperationError) -> Self {
        Self::Store(value)
    }
}

impl From<FinalUseError> for DurableDispatchError {
    fn from(value: FinalUseError) -> Self {
        Self::Authority(value)
    }
}

pub struct DurableDispatcher<'a> {
    store: &'a DurableOperationStore,
    authority: &'a FinalUseAuthority,
}

impl<'a> DurableDispatcher<'a> {
    pub const fn new(store: &'a DurableOperationStore, authority: &'a FinalUseAuthority) -> Self {
        Self { store, authority }
    }

    /// Claim one outbox row, consume a real single-use authority token and
    /// dispatch exactly once for this lease. Any acknowledgement-only or
    /// uncertain result is persisted as indeterminate and is never blindly
    /// retried by this method.
    pub async fn dispatch_once(
        &self,
        identity: &OperationIdentity,
        worker_id: &StableId,
        owner_generation: Generation,
        lease_ms: i64,
        signed_grant: &SignedFinalUseGrant,
        adapter: &impl DestinationEffectAdapter,
    ) -> Result<DurableOperationStatus, DurableDispatchError> {
        let lease = self
            .store
            .claim_outbox(identity, worker_id, owner_generation, lease_ms)
            .await?;
        let envelope = DispatchEnvelope::from_lease(lease.clone());
        let binding = envelope.final_use_binding();

        // Claim the nonce as close as possible to the effect boundary. A store
        // failure after this point consumes the grant but does not permit an
        // unrecorded retry with the same authority.
        let token = self.authority.claim(signed_grant, &binding)?;
        let authority_epoch = Generation::new(signed_grant.grant.authority_epoch)
            .map_err(|_| DurableOperationError::InvalidRequest("invalid final-use authority epoch"))?;
        self.store
            .bind_authority_epoch(identity, authority_epoch)
            .await?;
        self.store.mark_dispatch_started(&lease).await?;

        let result = match self
            .authority
            .with_verified_use(token, &binding, || adapter.dispatch(&envelope))
        {
            Ok(result) => result,
            Err(error) => {
                let reason = Digest32::of_bytes(
                    format!("hepta.kernel.operations.final-use-failed.v1\0{error}").as_bytes(),
                );
                self.store.mark_indeterminate(&lease, reason).await?;
                return Err(error.into());
            }
        };

        match result {
            DispatchResult::NotAttempted {
                reason_digest,
                retry_after_ms,
            } => {
                self.store
                    .requeue_not_attempted(&lease, reason_digest, retry_after_ms)
                    .await?;
            }
            DispatchResult::TransportAccepted {
                acknowledgement_digest,
                acknowledgement_watermark,
            } => {
                self.store
                    .record_transport_ack(
                        &lease,
                        acknowledgement_digest,
                        acknowledgement_watermark,
                    )
                    .await?;
            }
            DispatchResult::Terminal {
                observer_id,
                observer_generation,
                outcome,
                evidence_digest,
            } => {
                return Ok(self
                    .store
                    .observe_terminal(
                        identity,
                        observer_generation,
                        &observer_id,
                        outcome,
                        evidence_digest,
                    )
                    .await?);
            }
            DispatchResult::UnknownEffect { reason_digest } => {
                self.store.mark_indeterminate(&lease, reason_digest).await?;
            }
        }

        self.store
            .operation_status(identity)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(identity.operation_id.clone()).into())
    }

    /// Reconcile an already-dispatched/indeterminate operation without
    /// consuming another dispatch grant. The observer generation fences stale
    /// reconcilers and can take ownership only monotonically.
    pub async fn reconcile(
        &self,
        identity: &OperationIdentity,
        observer_id: &StableId,
        observer_generation: Generation,
        outcome: ReconciliationOutcome,
        evidence_digest: Digest32,
    ) -> Result<DurableOperationStatus, DurableDispatchError> {
        let status = self
            .store
            .operation_status(identity)
            .await?
            .ok_or_else(|| DurableOperationError::Missing(identity.operation_id.clone()))?;
        if !matches!(
            status.state,
            DurableOperationState::Dispatched | DurableOperationState::Indeterminate
        ) {
            return Err(DurableOperationError::InvalidTransition {
                from: match status.state {
                    DurableOperationState::Prepared => "prepared",
                    DurableOperationState::Applied => "applied",
                    DurableOperationState::NotApplied => "not_applied",
                    DurableOperationState::Quarantined => "quarantined",
                    DurableOperationState::Dispatched => "dispatched",
                    DurableOperationState::Indeterminate => "indeterminate",
                },
                to: "terminal_reconciliation",
            }
            .into());
        }
        Ok(self
            .store
            .observe_terminal(
                identity,
                observer_generation,
                observer_id,
                outcome,
                evidence_digest,
            )
            .await?)
    }
}

fn request_digest(lease: &DispatchLease) -> Digest32 {
    let mut bytes = b"hepta.kernel.operations.final-use-request.v1\0".to_vec();
    push_id(&mut bytes, &lease.identity.scope_id);
    push_id(&mut bytes, &lease.identity.operation_id);
    push_id(&mut bytes, &lease.destination_id);
    bytes.extend_from_slice(lease.payload_digest.as_array());
    bytes.extend_from_slice(lease.semantic_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    let len = u32::try_from(raw.len()).unwrap_or(u32::MAX);
    bytes.extend_from_slice(&len.to_be_bytes());
    bytes.extend_from_slice(raw);
}
