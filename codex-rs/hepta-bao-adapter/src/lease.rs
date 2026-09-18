//! Durable dynamic-secret lease coordinator for HeptaBao.
//!
//! The coordinator binds one caller operation id to one exact provider payload,
//! persists intent before dispatch, never blind-retries an uncertain provider
//! effect, and reconciles only through a provider-owned status lookup.
//!
//! Secret bytes are never stored in the lease journal or returned by receipts.
//! A successfully issued secret is delivered once through a synchronous trusted
//! consumer after the lease metadata is durable and final-use authority is
//! revalidated.

use std::fmt;
use std::path::Path;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::ProviderEffectAck;
use codex_hepta_contracts::ProviderEffectAckSource;
use codex_hepta_contracts::ProviderEffectAckStatus;
use codex_hepta_contracts::ProviderEffectAppendDisposition;
use codex_hepta_contracts::ProviderEffectBindingError;
use codex_hepta_contracts::ProviderEffectFuture;
use codex_hepta_contracts::ProviderEffectIdempotencyCapability;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectJournal;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::ProviderEffectLookup;
use codex_hepta_contracts::ProviderEffectState;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::VerifiedUseToken;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use zeroize::Zeroizing;

use crate::HEPTABAO_DESTINATION_ID;

pub const BAO_LEASE_SCHEMA_VERSION: u32 = 1;
pub const MAX_BAO_LEASE_TTL_SECONDS: u64 = 366 * 24 * 60 * 60;
pub const MAX_BAO_PROVIDER_PAYLOAD_BYTES: usize = 1024 * 1024;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BaoLeaseOperationKind {
    Issue,
    Renew,
    Revoke,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BaoSecretLeaseState {
    Active,
    Revoked,
    Expired,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoLeaseIssueRequest {
    pub operation_id: String,
    pub subject_id: String,
    pub consumer_id: String,
    pub namespace: String,
    pub role: String,
    pub scope_sha256: [u8; 32],
    pub ttl_seconds: u64,
    pub renewable: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoLeaseRenewRequest {
    pub operation_id: String,
    pub subject_id: String,
    pub namespace: String,
    pub lease_id: String,
    pub scope_sha256: [u8; 32],
    pub ttl_seconds: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoLeaseRevokeRequest {
    pub operation_id: String,
    pub subject_id: String,
    pub namespace: String,
    pub lease_id: String,
    pub scope_sha256: [u8; 32],
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoLeaseReconcileRequest {
    pub operation_id: String,
    pub subject_id: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum BaoLeaseRequest {
    Issue(BaoLeaseIssueRequest),
    Renew(BaoLeaseRenewRequest),
    Revoke(BaoLeaseRevokeRequest),
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoLeaseOperation {
    pub schema_version: u32,
    pub kind: BaoLeaseOperationKind,
    pub operation_id: String,
    pub subject_id: String,
    pub consumer_id: String,
    pub namespace: String,
    pub target_id: String,
    pub scope_sha256: [u8; 32],
    pub requested_ttl_seconds: Option<u64>,
    pub renewable: Option<bool>,
    pub provider_payload_sha256: Sha256Digest,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoLeaseProviderObservation {
    pub lease_id: String,
    pub state: BaoSecretLeaseState,
    pub issued_at_unix_ms: u64,
    pub expires_at_unix_ms: u64,
    pub renewable: bool,
    pub generation: u64,
    pub secret_sha256: [u8; 32],
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoSecretLeaseMetadata {
    pub lease_id: String,
    pub issued_by_operation_id: String,
    pub subject_id: String,
    pub consumer_id: String,
    pub namespace: String,
    pub scope_sha256: [u8; 32],
    pub state: BaoSecretLeaseState,
    pub issued_at_unix_ms: u64,
    pub expires_at_unix_ms: u64,
    pub renewable: bool,
    pub generation: u64,
    pub secret_sha256: [u8; 32],
}

pub struct BaoIssuedSecret(Zeroizing<Vec<u8>>);

impl BaoIssuedSecret {
    pub fn new(bytes: Vec<u8>) -> Result<Self, BaoLeaseError> {
        if bytes.is_empty() || bytes.len() > MAX_BAO_PROVIDER_PAYLOAD_BYTES {
            return Err(BaoLeaseError::InvalidProviderObservation);
        }
        Ok(Self(Zeroizing::new(bytes)))
    }

    fn expose(&self) -> &[u8] {
        self.0.as_slice()
    }
}

impl fmt::Debug for BaoIssuedSecret {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("BaoIssuedSecret([REDACTED])")
    }
}

#[derive(Debug)]
pub enum BaoLeaseProviderDispatch {
    Ack {
        ack: ProviderEffectAck,
        lease: Option<BaoLeaseProviderObservation>,
        secret: Option<BaoIssuedSecret>,
    },
    Rejected {
        reason_code: String,
    },
    NotDispatched {
        reason_code: String,
    },
    Unknown,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BaoLeaseProviderLookup {
    pub effect: ProviderEffectLookup,
    pub lease: Option<BaoLeaseProviderObservation>,
}

pub trait BaoLeaseProvider: Send + Sync {
    fn provider_scope(&self) -> &str;

    fn capability(&self) -> ProviderEffectIdempotencyCapability {
        ProviderEffectIdempotencyCapability::Unsupported
    }

    fn dispatch<'a>(
        &'a self,
        intent: &'a ProviderEffectIntent,
        operation: &'a BaoLeaseOperation,
        provider_payload: &'a [u8],
    ) -> ProviderEffectFuture<'a, BaoLeaseProviderDispatch>;

    fn lookup<'a>(
        &'a self,
        intent: &'a ProviderEffectIntent,
    ) -> ProviderEffectFuture<'a, BaoLeaseProviderLookup>;
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct BaoLeaseOperationReceipt {
    pub operation_id: String,
    pub provider_effect_key: String,
    pub state: ProviderEffectState,
    pub lease: Option<BaoSecretLeaseMetadata>,
    pub physical_dispatch_attempted: bool,
    pub secret_delivered: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum BaoLeaseError {
    InvalidConfiguration,
    InvalidRequest,
    UnsupportedProviderCapability,
    Authority(FinalUseError),
    Effect(ProviderEffectBindingError),
    OperationConflict,
    OperationNotFound,
    LeaseNotFound,
    LeaseNotActive,
    LeaseNotRenewable,
    BindingMismatch,
    StateLocked,
    UnsafeStateDirectory,
    StateUnavailable,
    StateCorrupt,
    StateCapacityExceeded,
    InvalidProviderObservation,
    MissingProviderObservation,
    UnexpectedSecret,
    SecretDigestMismatch,
    ConsumerIndeterminate,
}

impl fmt::Display for BaoLeaseError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for BaoLeaseError {}

impl From<FinalUseError> for BaoLeaseError {
    fn from(value: FinalUseError) -> Self {
        Self::Authority(value)
    }
}

impl From<ProviderEffectBindingError> for BaoLeaseError {
    fn from(value: ProviderEffectBindingError) -> Self {
        Self::Effect(value)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
struct StoredOperation {
    operation: BaoLeaseOperation,
    intent: ProviderEffectIntent,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "record", rename_all = "snake_case")]
enum LeaseJournalRecord {
    Initialize {
        provider_scope: String,
    },
    Intent {
        operation: BaoLeaseOperation,
        intent: ProviderEffectIntent,
    },
    Uncertainty {
        key: ProviderEffectKey,
        reason_code: String,
    },
    Ack {
        operation_id: String,
        ack: ProviderEffectAck,
        source: ProviderEffectAckSource,
        lease: Option<BaoSecretLeaseMetadata>,
    },
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
struct StoreState {
    provider_scope: Option<String>,
    effect: ProviderEffectJournal,
    operations: std::collections::BTreeMap<String, StoredOperation>,
    leases: std::collections::BTreeMap<String, BaoSecretLeaseMetadata>,
}

#[path = "lease_store.rs"]
mod store;

pub struct BaoLeaseCoordinator<P: BaoLeaseProvider> {
    provider: P,
    store: store::LeaseStore,
}

impl<P: BaoLeaseProvider> fmt::Debug for BaoLeaseCoordinator<P> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BaoLeaseCoordinator")
            .field("provider", &"[HEPTABAO LEASE PROVIDER]")
            .field("store", &self.store)
            .finish()
    }
}

impl<P: BaoLeaseProvider> BaoLeaseCoordinator<P> {
    pub fn open(provider: P, state_dir: &Path) -> Result<Self, BaoLeaseError> {
        validate_provider_scope(provider.provider_scope())?;
        let store = store::LeaseStore::open(state_dir, provider.provider_scope())?;
        Ok(Self { provider, store })
    }

    pub fn binding(
        &self,
        request: &BaoLeaseRequest,
        provider_payload: &[u8],
    ) -> Result<FinalUseBinding, BaoLeaseError> {
        let operation = match request {
            BaoLeaseRequest::Issue(request) => normalize_issue(request, provider_payload)?,
            BaoLeaseRequest::Renew(request) => {
                let lease = self
                    .store
                    .state()
                    .leases
                    .get(&request.lease_id)
                    .ok_or(BaoLeaseError::LeaseNotFound)?;
                normalize_renew(request, lease, provider_payload)?
            }
            BaoLeaseRequest::Revoke(request) => {
                let lease = self
                    .store
                    .state()
                    .leases
                    .get(&request.lease_id)
                    .ok_or(BaoLeaseError::LeaseNotFound)?;
                normalize_revoke(request, lease, provider_payload)?
            }
        };
        operation_binding(self.provider.provider_scope(), &operation)
    }

    pub fn reconcile_binding(
        &self,
        request: &BaoLeaseReconcileRequest,
    ) -> Result<FinalUseBinding, BaoLeaseError> {
        validate_operation_id(&request.operation_id)?;
        validate_component(&request.subject_id)?;
        let stored = self
            .store
            .state()
            .operations
            .get(&request.operation_id)
            .ok_or(BaoLeaseError::OperationNotFound)?;
        if stored.operation.subject_id != request.subject_id {
            return Err(BaoLeaseError::BindingMismatch);
        }
        reconcile_binding(self.provider.provider_scope(), stored)
    }

    pub async fn request_secret_lease(
        &mut self,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoLeaseIssueRequest,
        provider_payload: &[u8],
        consumer: impl FnOnce(&[u8]) -> Result<(), ()>,
    ) -> Result<BaoLeaseOperationReceipt, BaoLeaseError> {
        let operation = normalize_issue(request, provider_payload)?;
        let binding = operation_binding(self.provider.provider_scope(), &operation)?;
        let execution = self
            .execute_mutation(authority, grant, binding.clone(), operation, provider_payload)
            .await?;
        let mut receipt = execution.receipt;
        if let Some(secret) = execution.secret {
            authority
                .with_verified_use(execution.verified, &binding, || consumer(secret.expose()))?
                .map_err(|()| BaoLeaseError::ConsumerIndeterminate)?;
            receipt.secret_delivered = true;
        }
        Ok(receipt)
    }

    pub async fn renew(
        &mut self,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoLeaseRenewRequest,
        provider_payload: &[u8],
    ) -> Result<BaoLeaseOperationReceipt, BaoLeaseError> {
        let lease = self
            .store
            .state()
            .leases
            .get(&request.lease_id)
            .cloned()
            .ok_or(BaoLeaseError::LeaseNotFound)?;
        if lease.state != BaoSecretLeaseState::Active {
            return Err(BaoLeaseError::LeaseNotActive);
        }
        if !lease.renewable {
            return Err(BaoLeaseError::LeaseNotRenewable);
        }
        let operation = normalize_renew(request, &lease, provider_payload)?;
        let binding = operation_binding(self.provider.provider_scope(), &operation)?;
        let execution = self
            .execute_mutation(authority, grant, binding, operation, provider_payload)
            .await?;
        if execution.secret.is_some() {
            return Err(BaoLeaseError::UnexpectedSecret);
        }
        Ok(execution.receipt)
    }

    pub async fn revoke(
        &mut self,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoLeaseRevokeRequest,
        provider_payload: &[u8],
    ) -> Result<BaoLeaseOperationReceipt, BaoLeaseError> {
        let lease = self
            .store
            .state()
            .leases
            .get(&request.lease_id)
            .cloned()
            .ok_or(BaoLeaseError::LeaseNotFound)?;
        if lease.state == BaoSecretLeaseState::Revoked {
            return Err(BaoLeaseError::LeaseNotActive);
        }
        let operation = normalize_revoke(request, &lease, provider_payload)?;
        let binding = operation_binding(self.provider.provider_scope(), &operation)?;
        let execution = self
            .execute_mutation(authority, grant, binding, operation, provider_payload)
            .await?;
        if execution.secret.is_some() {
            return Err(BaoLeaseError::UnexpectedSecret);
        }
        Ok(execution.receipt)
    }

    pub async fn reconcile(
        &mut self,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoLeaseReconcileRequest,
    ) -> Result<BaoLeaseOperationReceipt, BaoLeaseError> {
        validate_operation_id(&request.operation_id)?;
        validate_component(&request.subject_id)?;
        if self.provider.capability()
            != ProviderEffectIdempotencyCapability::KeyAndStatusLookup
        {
            return Err(BaoLeaseError::UnsupportedProviderCapability);
        }
        let stored = self
            .store
            .state()
            .operations
            .get(&request.operation_id)
            .cloned()
            .ok_or(BaoLeaseError::OperationNotFound)?;
        if stored.operation.subject_id != request.subject_id {
            return Err(BaoLeaseError::BindingMismatch);
        }
        let binding = reconcile_binding(self.provider.provider_scope(), &stored)?;
        let _verified = authority.claim(grant, &binding)?;
        let current = self
            .store
            .state()
            .effect
            .state(&stored.intent.key)
            .unwrap_or(ProviderEffectState::Indeterminate);
        if current.is_terminal() {
            return Ok(self.receipt_for(&stored, current, false, false));
        }

        let lookup = self.provider.lookup(&stored.intent).await;
        let (effect, lease) = (lookup.effect, lookup.lease);
        match effect {
            ProviderEffectLookup::Ack(ack) => {
                if let Err(error) = ack.validate_for(&stored.intent) {
                    self.mark_indeterminate(&stored.intent.key, "provider_lookup_ack_invalid")?;
                    return Err(error.into());
                }
                let metadata =
                    self.metadata_for_ack(&stored, &ack, lease, ProviderEffectAckSource::StatusLookup)?;
                self.store.append(LeaseJournalRecord::Ack {
                    operation_id: stored.operation.operation_id.clone(),
                    ack,
                    source: ProviderEffectAckSource::StatusLookup,
                    lease: metadata,
                })?;
            }
            ProviderEffectLookup::NotFound => {
                if lease.is_some() {
                    return Err(BaoLeaseError::InvalidProviderObservation);
                }
                self.mark_indeterminate(&stored.intent.key, "provider_status_not_found")?;
            }
            ProviderEffectLookup::Conflict { .. } => {
                if lease.is_some() {
                    return Err(BaoLeaseError::InvalidProviderObservation);
                }
                self.mark_indeterminate(&stored.intent.key, "provider_payload_conflict")?;
            }
            ProviderEffectLookup::Unknown => {
                if lease.is_some() {
                    return Err(BaoLeaseError::InvalidProviderObservation);
                }
                self.mark_indeterminate(&stored.intent.key, "provider_lookup_unknown")?;
            }
        }
        let state = self
            .store
            .state()
            .effect
            .state(&stored.intent.key)
            .unwrap_or(ProviderEffectState::Indeterminate);
        Ok(self.receipt_for(&stored, state, false, false))
    }

    pub fn lease_metadata(
        &self,
        lease_id: &str,
        now_unix_ms: u64,
    ) -> Result<Option<BaoSecretLeaseMetadata>, BaoLeaseError> {
        validate_target(lease_id)?;
        let Some(mut lease) = self.store.state().leases.get(lease_id).cloned() else {
            return Ok(None);
        };
        if lease.state == BaoSecretLeaseState::Active && now_unix_ms >= lease.expires_at_unix_ms {
            lease.state = BaoSecretLeaseState::Expired;
        }
        Ok(Some(lease))
    }

    fn receipt_for(
        &self,
        stored: &StoredOperation,
        state: ProviderEffectState,
        physical_dispatch_attempted: bool,
        secret_delivered: bool,
    ) -> BaoLeaseOperationReceipt {
        let lease = lease_for_operation(self.store.state(), stored);
        BaoLeaseOperationReceipt {
            operation_id: stored.operation.operation_id.clone(),
            provider_effect_key: stored.intent.key.as_str().to_string(),
            state,
            lease,
            physical_dispatch_attempted,
            secret_delivered,
        }
    }

    async fn execute_mutation(
        &mut self,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        binding: FinalUseBinding,
        operation: BaoLeaseOperation,
        provider_payload: &[u8],
    ) -> Result<MutationExecution, BaoLeaseError> {
        if self.provider.capability()
            != ProviderEffectIdempotencyCapability::KeyAndStatusLookup
        {
            return Err(BaoLeaseError::UnsupportedProviderCapability);
        }
        let intent = intent_for(self.provider.provider_scope(), &operation)?;
        let stored = StoredOperation {
            operation: operation.clone(),
            intent: intent.clone(),
        };
        if let Some(existing) = self.store.state().operations.get(&operation.operation_id) {
            if existing != &stored {
                return Err(BaoLeaseError::OperationConflict);
            }
        }

        let verified = authority.claim(grant, &binding)?;
        let disposition = self.store.ensure_intent(stored.clone())?;
        let current = self
            .store
            .state()
            .effect
            .state(&intent.key)
            .unwrap_or(ProviderEffectState::Indeterminate);
        if disposition == ProviderEffectAppendDisposition::AlreadyPresent {
            if current == ProviderEffectState::Pending {
                self.mark_indeterminate(&intent.key, "provider_imported_pending")?;
            }
            let state = self
                .store
                .state()
                .effect
                .state(&intent.key)
                .unwrap_or(ProviderEffectState::Indeterminate);
            return Ok(MutationExecution {
                receipt: self.receipt_for(&stored, state, false, false),
                secret: None,
                verified,
            });
        }

        let dispatch = self
            .provider
            .dispatch(&intent, &operation, provider_payload)
            .await;
        match dispatch {
            BaoLeaseProviderDispatch::Ack { ack, lease, secret } => {
                if let Err(error) = ack.validate_for(&intent) {
                    self.mark_indeterminate(&intent.key, "provider_dispatch_ack_invalid")?;
                    return Err(error.into());
                }
                let metadata = match self.metadata_for_ack(
                    &stored,
                    &ack,
                    lease,
                    ProviderEffectAckSource::DispatchResponse,
                ) {
                    Ok(metadata) => metadata,
                    Err(error) => {
                        self.mark_indeterminate(&intent.key, "provider_dispatch_observation_invalid")?;
                        return Err(error);
                    }
                };
                let secret = match self.validate_dispatch_secret(
                    &stored,
                    &ack,
                    metadata.as_ref(),
                    secret,
                ) {
                    Ok(secret) => secret,
                    Err(error) => {
                        self.mark_indeterminate(
                            &intent.key,
                            "provider_dispatch_secret_invalid",
                        )?;
                        return Err(error);
                    }
                };
                self.store.append(LeaseJournalRecord::Ack {
                    operation_id: operation.operation_id.clone(),
                    ack,
                    source: ProviderEffectAckSource::DispatchResponse,
                    lease: metadata,
                })?;
                let state = self
                    .store
                    .state()
                    .effect
                    .state(&intent.key)
                    .unwrap_or(ProviderEffectState::Indeterminate);
                Ok(MutationExecution {
                    receipt: self.receipt_for(&stored, state, true, false),
                    secret,
                    verified,
                })
            }
            BaoLeaseProviderDispatch::Rejected { reason_code } => {
                self.mark_indeterminate(
                    &intent.key,
                    validated_reason_code(&reason_code, "provider_dispatch_rejected"),
                )?;
                Ok(MutationExecution {
                    receipt: self.receipt_for(
                        &stored,
                        ProviderEffectState::Indeterminate,
                        true,
                        false,
                    ),
                    secret: None,
                    verified,
                })
            }
            BaoLeaseProviderDispatch::NotDispatched { reason_code } => {
                self.mark_indeterminate(
                    &intent.key,
                    validated_reason_code(&reason_code, "provider_not_dispatched"),
                )?;
                Ok(MutationExecution {
                    receipt: self.receipt_for(
                        &stored,
                        ProviderEffectState::Indeterminate,
                        false,
                        false,
                    ),
                    secret: None,
                    verified,
                })
            }
            BaoLeaseProviderDispatch::Unknown => {
                self.mark_indeterminate(&intent.key, "provider_dispatch_unknown")?;
                Ok(MutationExecution {
                    receipt: self.receipt_for(
                        &stored,
                        ProviderEffectState::Indeterminate,
                        true,
                        false,
                    ),
                    secret: None,
                    verified,
                })
            }
        }
    }

    fn metadata_for_ack(
        &self,
        stored: &StoredOperation,
        ack: &ProviderEffectAck,
        observation: Option<BaoLeaseProviderObservation>,
        source: ProviderEffectAckSource,
    ) -> Result<Option<BaoSecretLeaseMetadata>, BaoLeaseError> {
        match ack.status {
            ProviderEffectAckStatus::Accepted | ProviderEffectAckStatus::Rejected => {
                if observation.is_some() {
                    return Err(BaoLeaseError::InvalidProviderObservation);
                }
                Ok(None)
            }
            ProviderEffectAckStatus::Completed => {
                let observation = observation.ok_or(BaoLeaseError::MissingProviderObservation)?;
                metadata_from_observation(self.store.state(), stored, observation, source).map(Some)
            }
        }
    }

    fn validate_dispatch_secret(
        &self,
        stored: &StoredOperation,
        ack: &ProviderEffectAck,
        metadata: Option<&BaoSecretLeaseMetadata>,
        secret: Option<BaoIssuedSecret>,
    ) -> Result<Option<BaoIssuedSecret>, BaoLeaseError> {
        match (stored.operation.kind, ack.status) {
            (BaoLeaseOperationKind::Issue, ProviderEffectAckStatus::Completed) => {
                let metadata = metadata.ok_or(BaoLeaseError::MissingProviderObservation)?;
                let secret = secret.ok_or(BaoLeaseError::MissingProviderObservation)?;
                if Digest32::of_bytes(secret.expose()).into_array() != metadata.secret_sha256 {
                    return Err(BaoLeaseError::SecretDigestMismatch);
                }
                Ok(Some(secret))
            }
            (_, _) if secret.is_some() => Err(BaoLeaseError::UnexpectedSecret),
            _ => Ok(None),
        }
    }

    fn mark_indeterminate(
        &mut self,
        key: &ProviderEffectKey,
        reason_code: &str,
    ) -> Result<(), BaoLeaseError> {
        if self.store.state().effect.state(key) == Some(ProviderEffectState::Indeterminate) {
            return Ok(());
        }
        self.store.append(LeaseJournalRecord::Uncertainty {
            key: key.clone(),
            reason_code: reason_code.to_string(),
        })
    }
}

struct MutationExecution {
    receipt: BaoLeaseOperationReceipt,
    secret: Option<BaoIssuedSecret>,
    verified: VerifiedUseToken,
}

fn normalize_issue(
    request: &BaoLeaseIssueRequest,
    provider_payload: &[u8],
) -> Result<BaoLeaseOperation, BaoLeaseError> {
    validate_operation_id(&request.operation_id)?;
    validate_component(&request.subject_id)?;
    validate_component(&request.consumer_id)?;
    validate_namespace(&request.namespace)?;
    validate_target(&request.role)?;
    validate_scope(request.scope_sha256)?;
    validate_ttl(request.ttl_seconds)?;
    validate_provider_payload(provider_payload)?;
    Ok(BaoLeaseOperation {
        schema_version: BAO_LEASE_SCHEMA_VERSION,
        kind: BaoLeaseOperationKind::Issue,
        operation_id: request.operation_id.clone(),
        subject_id: request.subject_id.clone(),
        consumer_id: request.consumer_id.clone(),
        namespace: request.namespace.clone(),
        target_id: request.role.clone(),
        scope_sha256: request.scope_sha256,
        requested_ttl_seconds: Some(request.ttl_seconds),
        renewable: Some(request.renewable),
        provider_payload_sha256: Sha256Digest::for_bytes(provider_payload),
    })
}

fn normalize_renew(
    request: &BaoLeaseRenewRequest,
    lease: &BaoSecretLeaseMetadata,
    provider_payload: &[u8],
) -> Result<BaoLeaseOperation, BaoLeaseError> {
    validate_operation_id(&request.operation_id)?;
    validate_component(&request.subject_id)?;
    validate_namespace(&request.namespace)?;
    validate_target(&request.lease_id)?;
    validate_scope(request.scope_sha256)?;
    validate_ttl(request.ttl_seconds)?;
    validate_provider_payload(provider_payload)?;
    validate_lease_binding(
        lease,
        &request.subject_id,
        &request.namespace,
        &request.scope_sha256,
    )?;
    Ok(BaoLeaseOperation {
        schema_version: BAO_LEASE_SCHEMA_VERSION,
        kind: BaoLeaseOperationKind::Renew,
        operation_id: request.operation_id.clone(),
        subject_id: request.subject_id.clone(),
        consumer_id: lease.consumer_id.clone(),
        namespace: request.namespace.clone(),
        target_id: request.lease_id.clone(),
        scope_sha256: request.scope_sha256,
        requested_ttl_seconds: Some(request.ttl_seconds),
        renewable: Some(lease.renewable),
        provider_payload_sha256: Sha256Digest::for_bytes(provider_payload),
    })
}

fn normalize_revoke(
    request: &BaoLeaseRevokeRequest,
    lease: &BaoSecretLeaseMetadata,
    provider_payload: &[u8],
) -> Result<BaoLeaseOperation, BaoLeaseError> {
    validate_operation_id(&request.operation_id)?;
    validate_component(&request.subject_id)?;
    validate_namespace(&request.namespace)?;
    validate_target(&request.lease_id)?;
    validate_scope(request.scope_sha256)?;
    validate_provider_payload(provider_payload)?;
    validate_lease_binding(
        lease,
        &request.subject_id,
        &request.namespace,
        &request.scope_sha256,
    )?;
    Ok(BaoLeaseOperation {
        schema_version: BAO_LEASE_SCHEMA_VERSION,
        kind: BaoLeaseOperationKind::Revoke,
        operation_id: request.operation_id.clone(),
        subject_id: request.subject_id.clone(),
        consumer_id: lease.consumer_id.clone(),
        namespace: request.namespace.clone(),
        target_id: request.lease_id.clone(),
        scope_sha256: request.scope_sha256,
        requested_ttl_seconds: None,
        renewable: Some(lease.renewable),
        provider_payload_sha256: Sha256Digest::for_bytes(provider_payload),
    })
}

fn validate_operation(
    operation: &BaoLeaseOperation,
    provider_scope: &str,
) -> Result<(), BaoLeaseError> {
    if operation.schema_version != BAO_LEASE_SCHEMA_VERSION {
        return Err(BaoLeaseError::InvalidRequest);
    }
    validate_provider_scope(provider_scope)?;
    validate_operation_id(&operation.operation_id)?;
    validate_component(&operation.subject_id)?;
    validate_component(&operation.consumer_id)?;
    validate_namespace(&operation.namespace)?;
    validate_target(&operation.target_id)?;
    validate_scope(operation.scope_sha256)?;
    Sha256Digest::parse(operation.provider_payload_sha256.as_str().to_string())
        .map_err(|_| BaoLeaseError::InvalidRequest)?;
    match operation.kind {
        BaoLeaseOperationKind::Issue | BaoLeaseOperationKind::Renew => {
            validate_ttl(
                operation
                    .requested_ttl_seconds
                    .ok_or(BaoLeaseError::InvalidRequest)?,
            )?;
            if operation.renewable.is_none() {
                return Err(BaoLeaseError::InvalidRequest);
            }
        }
        BaoLeaseOperationKind::Revoke => {
            if operation.requested_ttl_seconds.is_some() || operation.renewable.is_none() {
                return Err(BaoLeaseError::InvalidRequest);
            }
        }
    }
    Ok(())
}

fn intent_for(
    provider_scope: &str,
    operation: &BaoLeaseOperation,
) -> Result<ProviderEffectIntent, BaoLeaseError> {
    validate_operation(operation, provider_scope)?;
    let key_material = bound_bytes(
        b"hepta.bao.lease.effect-key.v1",
        &[provider_scope.as_bytes(), operation.operation_id.as_bytes()],
    );
    let key = ProviderEffectKey::parse(format!(
        "provider-effect:v1:{}",
        Digest32::of_bytes(&key_material)
    ))?;
    let operation_bytes =
        serde_json::to_vec(operation).map_err(|_| BaoLeaseError::InvalidRequest)?;
    let payload_material =
        bound_bytes(b"hepta.bao.lease.effect-payload.v1", &[operation_bytes.as_slice()]);
    Ok(ProviderEffectIntent::new(
        key,
        Sha256Digest::for_bytes(&payload_material),
    ))
}

fn operation_binding(
    provider_scope: &str,
    operation: &BaoLeaseOperation,
) -> Result<FinalUseBinding, BaoLeaseError> {
    let intent = intent_for(provider_scope, operation)?;
    let operation_bytes =
        serde_json::to_vec(operation).map_err(|_| BaoLeaseError::InvalidRequest)?;
    let request_material = bound_bytes(
        b"hepta.bao.lease.request.v1",
        &[provider_scope.as_bytes(), operation_bytes.as_slice()],
    );
    let payload_material = bound_bytes(
        b"hepta.bao.lease.provider-payload.v1",
        &[
            intent.payload_sha256.as_str().as_bytes(),
            operation.provider_payload_sha256.as_str().as_bytes(),
        ],
    );
    Ok(FinalUseBinding {
        subject_id: operation.subject_id.clone(),
        destination_id: HEPTABAO_DESTINATION_ID.to_string(),
        request_sha256: Digest32::of_bytes(&request_material).into_array(),
        scope_sha256: operation.scope_sha256,
        payload_sha256: Digest32::of_bytes(&payload_material).into_array(),
    })
}

fn reconcile_binding(
    provider_scope: &str,
    stored: &StoredOperation,
) -> Result<FinalUseBinding, BaoLeaseError> {
    validate_operation(&stored.operation, provider_scope)?;
    stored.intent.validate()?;
    let request_material = bound_bytes(
        b"hepta.bao.lease.reconcile-request.v1",
        &[
            provider_scope.as_bytes(),
            stored.operation.operation_id.as_bytes(),
            stored.intent.key.as_str().as_bytes(),
        ],
    );
    let payload_material = bound_bytes(
        b"hepta.bao.lease.reconcile-payload.v1",
        &[
            stored.intent.key.as_str().as_bytes(),
            stored.intent.payload_sha256.as_str().as_bytes(),
        ],
    );
    Ok(FinalUseBinding {
        subject_id: stored.operation.subject_id.clone(),
        destination_id: HEPTABAO_DESTINATION_ID.to_string(),
        request_sha256: Digest32::of_bytes(&request_material).into_array(),
        scope_sha256: stored.operation.scope_sha256,
        payload_sha256: Digest32::of_bytes(&payload_material).into_array(),
    })
}

fn metadata_from_observation(
    state: &StoreState,
    stored: &StoredOperation,
    observation: BaoLeaseProviderObservation,
    source: ProviderEffectAckSource,
) -> Result<BaoSecretLeaseMetadata, BaoLeaseError> {
    validate_target(&observation.lease_id)?;
    if observation.generation == 0
        || observation.issued_at_unix_ms >= observation.expires_at_unix_ms
        || observation.secret_sha256 == [0; 32]
    {
        return Err(BaoLeaseError::InvalidProviderObservation);
    }
    match stored.operation.kind {
        BaoLeaseOperationKind::Issue => {
            if source == ProviderEffectAckSource::DispatchResponse
                && observation.state != BaoSecretLeaseState::Active
            {
                return Err(BaoLeaseError::InvalidProviderObservation);
            }
            if !matches!(
                observation.state,
                BaoSecretLeaseState::Active | BaoSecretLeaseState::Expired
            ) {
                return Err(BaoLeaseError::InvalidProviderObservation);
            }
            if observation.renewable != stored.operation.renewable.unwrap_or(false) {
                return Err(BaoLeaseError::InvalidProviderObservation);
            }
            let requested = stored
                .operation
                .requested_ttl_seconds
                .ok_or(BaoLeaseError::InvalidProviderObservation)?;
            let observed_ttl_ms = observation
                .expires_at_unix_ms
                .checked_sub(observation.issued_at_unix_ms)
                .ok_or(BaoLeaseError::InvalidProviderObservation)?;
            if observed_ttl_ms > requested.saturating_mul(1000) {
                return Err(BaoLeaseError::InvalidProviderObservation);
            }
            if state.leases.contains_key(&observation.lease_id) {
                return Err(BaoLeaseError::InvalidProviderObservation);
            }
            Ok(BaoSecretLeaseMetadata {
                lease_id: observation.lease_id,
                issued_by_operation_id: stored.operation.operation_id.clone(),
                subject_id: stored.operation.subject_id.clone(),
                consumer_id: stored.operation.consumer_id.clone(),
                namespace: stored.operation.namespace.clone(),
                scope_sha256: stored.operation.scope_sha256,
                state: observation.state,
                issued_at_unix_ms: observation.issued_at_unix_ms,
                expires_at_unix_ms: observation.expires_at_unix_ms,
                renewable: observation.renewable,
                generation: observation.generation,
                secret_sha256: observation.secret_sha256,
            })
        }
        BaoLeaseOperationKind::Renew => {
            let previous = state
                .leases
                .get(&stored.operation.target_id)
                .ok_or(BaoLeaseError::LeaseNotFound)?;
            if previous.state != BaoSecretLeaseState::Active
                || !previous.renewable
                || observation.lease_id != previous.lease_id
                || observation.state != BaoSecretLeaseState::Active
                || observation.generation <= previous.generation
                || observation.expires_at_unix_ms <= previous.expires_at_unix_ms
                || observation.issued_at_unix_ms != previous.issued_at_unix_ms
                || observation.renewable != previous.renewable
                || observation.secret_sha256 != previous.secret_sha256
            {
                return Err(BaoLeaseError::InvalidProviderObservation);
            }
            let mut next = previous.clone();
            next.expires_at_unix_ms = observation.expires_at_unix_ms;
            next.generation = observation.generation;
            Ok(next)
        }
        BaoLeaseOperationKind::Revoke => {
            let previous = state
                .leases
                .get(&stored.operation.target_id)
                .ok_or(BaoLeaseError::LeaseNotFound)?;
            if previous.state == BaoSecretLeaseState::Revoked
                || observation.lease_id != previous.lease_id
                || observation.state != BaoSecretLeaseState::Revoked
                || observation.generation <= previous.generation
                || observation.issued_at_unix_ms != previous.issued_at_unix_ms
                || observation.expires_at_unix_ms != previous.expires_at_unix_ms
                || observation.renewable != previous.renewable
                || observation.secret_sha256 != previous.secret_sha256
            {
                return Err(BaoLeaseError::InvalidProviderObservation);
            }
            let mut next = previous.clone();
            next.state = BaoSecretLeaseState::Revoked;
            next.generation = observation.generation;
            Ok(next)
        }
    }
}

fn apply_record(state: &mut StoreState, record: &LeaseJournalRecord) -> Result<(), BaoLeaseError> {
    match record {
        LeaseJournalRecord::Initialize { provider_scope } => {
            validate_provider_scope(provider_scope)?;
            if state.provider_scope.is_some()
                || !state.operations.is_empty()
                || !state.leases.is_empty()
            {
                return Err(BaoLeaseError::StateCorrupt);
            }
            state.provider_scope = Some(provider_scope.clone());
            Ok(())
        }
        LeaseJournalRecord::Intent { operation, intent } => {
            let provider_scope = state
                .provider_scope
                .as_deref()
                .ok_or(BaoLeaseError::StateCorrupt)?;
            validate_operation(operation, provider_scope)?;
            let expected = intent_for(provider_scope, operation)?;
            if &expected != intent || state.operations.contains_key(&operation.operation_id) {
                return Err(BaoLeaseError::OperationConflict);
            }
            state.effect.record_intent(intent.clone())?;
            state.operations.insert(
                operation.operation_id.clone(),
                StoredOperation {
                    operation: operation.clone(),
                    intent: intent.clone(),
                },
            );
            Ok(())
        }
        LeaseJournalRecord::Uncertainty { key, reason_code } => {
            state.effect.mark_indeterminate(key, reason_code.clone())?;
            Ok(())
        }
        LeaseJournalRecord::Ack {
            operation_id,
            ack,
            source,
            lease,
        } => {
            let stored = state
                .operations
                .get(operation_id)
                .cloned()
                .ok_or(BaoLeaseError::OperationNotFound)?;
            if ack.key != stored.intent.key {
                return Err(BaoLeaseError::Effect(ProviderEffectBindingError::KeyMismatch));
            }
            ack.validate_for(&stored.intent)?;
            match ack.status {
                ProviderEffectAckStatus::Accepted | ProviderEffectAckStatus::Rejected => {
                    if lease.is_some() {
                        return Err(BaoLeaseError::StateCorrupt);
                    }
                }
                ProviderEffectAckStatus::Completed => {
                    let metadata = lease.as_ref().ok_or(BaoLeaseError::StateCorrupt)?;
                    validate_metadata_transition(state, &stored, metadata)?;
                }
            }
            state
                .effect
                .record_ack_from_source(ack.clone(), *source)?;
            if let Some(metadata) = lease {
                state
                    .leases
                    .insert(metadata.lease_id.clone(), metadata.clone());
            }
            Ok(())
        }
    }
}

fn validate_metadata_transition(
    state: &StoreState,
    stored: &StoredOperation,
    metadata: &BaoSecretLeaseMetadata,
) -> Result<(), BaoLeaseError> {
    validate_target(&metadata.lease_id)?;
    validate_operation_id(&metadata.issued_by_operation_id)?;
    validate_component(&metadata.subject_id)?;
    validate_component(&metadata.consumer_id)?;
    validate_namespace(&metadata.namespace)?;
    validate_scope(metadata.scope_sha256)?;
    if metadata.generation == 0
        || metadata.issued_at_unix_ms >= metadata.expires_at_unix_ms
        || metadata.secret_sha256 == [0; 32]
        || metadata.subject_id != stored.operation.subject_id
        || metadata.consumer_id != stored.operation.consumer_id
        || metadata.namespace != stored.operation.namespace
        || metadata.scope_sha256 != stored.operation.scope_sha256
    {
        return Err(BaoLeaseError::StateCorrupt);
    }
    match stored.operation.kind {
        BaoLeaseOperationKind::Issue => {
            if metadata.issued_by_operation_id != stored.operation.operation_id
                || state.leases.contains_key(&metadata.lease_id)
            {
                return Err(BaoLeaseError::StateCorrupt);
            }
        }
        BaoLeaseOperationKind::Renew => {
            let previous = state
                .leases
                .get(&stored.operation.target_id)
                .ok_or(BaoLeaseError::StateCorrupt)?;
            if metadata.lease_id != previous.lease_id
                || metadata.issued_by_operation_id != previous.issued_by_operation_id
                || metadata.state != BaoSecretLeaseState::Active
                || metadata.generation <= previous.generation
                || metadata.expires_at_unix_ms <= previous.expires_at_unix_ms
                || metadata.issued_at_unix_ms != previous.issued_at_unix_ms
                || metadata.renewable != previous.renewable
                || metadata.secret_sha256 != previous.secret_sha256
            {
                return Err(BaoLeaseError::StateCorrupt);
            }
        }
        BaoLeaseOperationKind::Revoke => {
            let previous = state
                .leases
                .get(&stored.operation.target_id)
                .ok_or(BaoLeaseError::StateCorrupt)?;
            if metadata.lease_id != previous.lease_id
                || metadata.issued_by_operation_id != previous.issued_by_operation_id
                || metadata.state != BaoSecretLeaseState::Revoked
                || metadata.generation <= previous.generation
                || metadata.issued_at_unix_ms != previous.issued_at_unix_ms
                || metadata.expires_at_unix_ms != previous.expires_at_unix_ms
                || metadata.renewable != previous.renewable
                || metadata.secret_sha256 != previous.secret_sha256
            {
                return Err(BaoLeaseError::StateCorrupt);
            }
        }
    }
    Ok(())
}

fn lease_for_operation(state: &StoreState, stored: &StoredOperation) -> Option<BaoSecretLeaseMetadata> {
    match stored.operation.kind {
        BaoLeaseOperationKind::Issue => state
            .leases
            .values()
            .find(|lease| lease.issued_by_operation_id == stored.operation.operation_id)
            .cloned(),
        BaoLeaseOperationKind::Renew | BaoLeaseOperationKind::Revoke => {
            state.leases.get(&stored.operation.target_id).cloned()
        }
    }
}

fn validate_lease_binding(
    lease: &BaoSecretLeaseMetadata,
    subject_id: &str,
    namespace: &str,
    scope_sha256: &[u8; 32],
) -> Result<(), BaoLeaseError> {
    if lease.subject_id != subject_id
        || lease.namespace != namespace
        || &lease.scope_sha256 != scope_sha256
    {
        return Err(BaoLeaseError::BindingMismatch);
    }
    Ok(())
}

fn validate_provider_scope(value: &str) -> Result<(), BaoLeaseError> {
    if value.is_empty()
        || value.len() > 256
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:/".contains(&byte))
    {
        return Err(BaoLeaseError::InvalidConfiguration);
    }
    Ok(())
}

fn validate_component(value: &str) -> Result<(), BaoLeaseError> {
    if value.is_empty()
        || value.len() > 128
        || value == "."
        || value == ".."
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:".contains(&byte))
    {
        return Err(BaoLeaseError::InvalidRequest);
    }
    Ok(())
}

fn validate_operation_id(value: &str) -> Result<(), BaoLeaseError> {
    validate_component(value)
}

fn validate_namespace(value: &str) -> Result<(), BaoLeaseError> {
    if value.is_empty() {
        return Ok(());
    }
    if value.len() > 1024 || !value.split('/').all(|segment| validate_component(segment).is_ok()) {
        return Err(BaoLeaseError::InvalidRequest);
    }
    Ok(())
}

fn validate_target(value: &str) -> Result<(), BaoLeaseError> {
    if value.is_empty()
        || value.len() > 1024
        || !value.split('/').all(|segment| validate_component(segment).is_ok())
    {
        return Err(BaoLeaseError::InvalidRequest);
    }
    Ok(())
}

fn validate_scope(value: [u8; 32]) -> Result<(), BaoLeaseError> {
    if value == [0; 32] {
        return Err(BaoLeaseError::InvalidRequest);
    }
    Ok(())
}

fn validate_ttl(value: u64) -> Result<(), BaoLeaseError> {
    if value == 0 || value > MAX_BAO_LEASE_TTL_SECONDS {
        return Err(BaoLeaseError::InvalidRequest);
    }
    Ok(())
}

fn validate_provider_payload(value: &[u8]) -> Result<(), BaoLeaseError> {
    if value.len() > MAX_BAO_PROVIDER_PAYLOAD_BYTES {
        return Err(BaoLeaseError::InvalidRequest);
    }
    Ok(())
}

fn validated_reason_code<'a>(value: &'a str, fallback: &'static str) -> &'a str {
    if !value.is_empty()
        && value.len() <= 128
        && value.bytes().all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || matches!(byte, b'_' | b'-' | b'.')
        })
    {
        value
    } else {
        fallback
    }
}

fn bound_bytes(domain: &[u8], parts: &[&[u8]]) -> Vec<u8> {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(domain);
    bytes.push(0);
    for part in parts {
        bytes.extend_from_slice(&u64::try_from(part.len()).unwrap_or(u64::MAX).to_be_bytes());
        bytes.extend_from_slice(part);
    }
    bytes
}

#[cfg(all(test, unix))]
#[path = "lease_tests.rs"]
mod tests;
