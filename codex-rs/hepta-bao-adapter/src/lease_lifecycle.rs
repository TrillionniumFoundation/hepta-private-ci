//! Durable OpenBao dynamic-secret lease lifecycle.
//!
//! Raw dynamic secret values are delivered only to a synchronous trusted callback.
//! The local journal persists provider lease identity and lifecycle metadata, never
//! secret values. Every provider operation is operation-idempotent locally and
//! ambiguity is made explicit instead of retried blindly.

use std::collections::BTreeMap;
use std::fmt;
use std::fs::File;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use codex_http_client::RequestBuilder;
use http::StatusCode;
use http::header::HeaderValue;
use serde::Deserialize;
use serde::Serialize;
use zeroize::Zeroizing;

use crate::BaoClient;

const MAX_RESPONSE_BYTES: usize = 1024 * 1024;
const MAX_REQUIRED_FIELDS: usize = 32;
const MAX_PROVIDER_LEASE_ID_BYTES: usize = 4096;
const MAX_RENEW_INCREMENT_SECONDS: u64 = 365 * 24 * 60 * 60;
const MAX_LEASE_DURATION_SECONDS: u64 = 365 * 24 * 60 * 60;
const MAX_REGISTRY_LEASES: usize = 65_536;
const MAX_REGISTRY_OPERATIONS: usize = 262_144;
const MAX_JOURNAL_BYTES: u64 = 256 * 1024 * 1024;
const MAX_JOURNAL_EVENT_BYTES: usize = 64 * 1024;

/// One provider-native dynamic-secret request. The provider response must carry
/// a real non-empty OpenBao lease_id and a positive lease_duration.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoDynamicLeaseRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub namespace: String,
    pub mount: String,
    pub path: String,
    pub operation_id: String,
    pub required_fields: Vec<String>,
}

/// A single logical renew operation. Reusing operation_id with the same
/// request is idempotent; reusing it with different semantics is rejected.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoRenewLeaseRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub namespace: String,
    pub lease_handle_sha256: [u8; 32],
    pub operation_id: String,
    pub increment_seconds: u64,
}

/// A single logical synchronous revoke operation.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoRevokeLeaseRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub namespace: String,
    pub lease_handle_sha256: [u8; 32],
    pub operation_id: String,
}

/// A provider lookup used to reconcile a known provider lease identity.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoReconcileLeaseRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub namespace: String,
    pub lease_handle_sha256: [u8; 32],
    pub operation_id: String,
}

/// Sensitive provider lease identity supplied only by a trusted recovery path.
/// Debug never reveals the value.
#[derive(Clone)]
pub struct BaoProviderLeaseId(Zeroizing<String>);

impl BaoProviderLeaseId {
    pub fn new(value: String) -> Result<Self, BaoLeaseError> {
        let value = Zeroizing::new(value);
        if !provider_lease_id(&value) {
            return Err(BaoLeaseError::InvalidRequest);
        }
        Ok(Self(value))
    }

    fn as_str(&self) -> &str {
        self.0.as_str()
    }
}

impl fmt::Debug for BaoProviderLeaseId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("BaoProviderLeaseId([REDACTED])")
    }
}

/// Stock OpenBao has no generic issuance idempotency key. If an issuance
/// response is lost before its lease_id is known, recovery therefore requires
/// trusted out-of-band evidence: either no lease was created, or a specific
/// observed lease identity must be adopted for later lookup/revocation.
#[derive(Clone, Debug)]
pub enum BaoUnknownIssueResolution {
    ConfirmedAbsent,
    ObservedLease(BaoProviderLeaseId),
}

#[derive(Clone, Debug)]
pub struct BaoUnknownIssueResolutionRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub namespace: String,
    pub lease_handle_sha256: [u8; 32],
    pub operation_id: String,
    pub evidence_sha256: [u8; 32],
    pub resolution: BaoUnknownIssueResolution,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SecretLeaseState {
    IssuePrepared,
    Issuing,
    IssuedPendingDelivery,
    Active,
    RenewPrepared,
    Renewing,
    RevokePrepared,
    RevokePending,
    ReconciliationRequired,
    Revoked,
    Expired,
    Failed,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ReconciliationReason {
    IssueOutcomeUnknown,
    RenewOutcomeUnknown,
    RevokeOutcomeUnknown,
    SecretDeliveryLost,
    DeliveryAuthorizationLost,
    ConsumerOutcomeUnknown,
    RevokeStillActive,
    OrphanedActiveLease,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LeaseDelivery {
    Delivered,
    AlreadyIssuedNoRedelivery,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct SecretLeaseMetadata {
    pub lease_handle_sha256: [u8; 32],
    pub state: SecretLeaseState,
    pub reconciliation_reason: Option<ReconciliationReason>,
    pub renewable: bool,
    pub issued_at_ms: Option<u64>,
    pub expires_at_ms: Option<u64>,
    pub generation: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct BaoLeaseReceipt {
    pub request_sha256: [u8; 32],
    pub lease: SecretLeaseMetadata,
    pub delivery: LeaseDelivery,
    pub secret_fields: usize,
    pub secret_bytes: usize,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct BaoLeaseMutationReceipt {
    pub request_sha256: [u8; 32],
    pub lease: SecretLeaseMetadata,
    pub idempotent_replay: bool,
}

/// Borrowed secret view valid only for the trusted synchronous callback.
pub struct BaoDynamicSecret<'a> {
    required_fields: &'a [String],
    data: &'a BTreeMap<String, SecretValue>,
}

impl fmt::Debug for BaoDynamicSecret<'_> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("BaoDynamicSecret([REDACTED])")
    }
}

impl<'a> BaoDynamicSecret<'a> {
    pub fn get(&self, field: &str) -> Option<&'a [u8]> {
        if self
            .required_fields
            .binary_search_by(|candidate| candidate.as_str().cmp(field))
            .is_err()
        {
            return None;
        }
        match self.data.get(field) {
            Some(SecretValue::String(value)) => Some(value.as_bytes()),
            _ => None,
        }
    }
}

#[derive(Clone)]
pub struct SecretLeaseRegistry(Arc<RegistryInner>);

impl fmt::Debug for SecretLeaseRegistry {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("SecretLeaseRegistry([PRIVATE DURABLE STATE])")
    }
}

impl SecretLeaseRegistry {
    pub fn open_state_dir(directory: &Path) -> Result<Self, LeaseRegistryError> {
        let (store, mut state) = JournalStore::open(directory)?;
        normalize_recovery(&mut state);
        Ok(Self(Arc::new(RegistryInner {
            state: Mutex::new(state),
            store,
        })))
    }

    pub fn lookup(
        &self,
        lease_handle_sha256: [u8; 32],
    ) -> Result<Option<SecretLeaseMetadata>, LeaseRegistryError> {
        let state = self
            .0
            .state
            .lock()
            .map_err(|_| LeaseRegistryError::Unavailable)?;
        ensure_registry_live(&state)?;
        Ok(state
            .leases
            .get(&lease_handle_sha256)
            .map(StoredLease::metadata))
    }

    pub fn lookup_by_operation_id(
        &self,
        operation_id: &str,
    ) -> Result<Option<SecretLeaseMetadata>, LeaseRegistryError> {
        let state = self
            .0
            .state
            .lock()
            .map_err(|_| LeaseRegistryError::Unavailable)?;
        ensure_registry_live(&state)?;
        Ok(state.operations.get(operation_id).and_then(|operation| {
            state
                .leases
                .get(&operation.lease_handle_sha256)
                .map(StoredLease::metadata)
        }))
    }

    fn prepare_issue(
        &self,
        request: &BaoDynamicLeaseRequest,
        request_sha256: [u8; 32],
        required_fields: Vec<String>,
    ) -> Result<PrepareIssue, LeaseRegistryError> {
        let mut state = self
            .0
            .state
            .lock()
            .map_err(|_| LeaseRegistryError::Unavailable)?;
        ensure_registry_live(&state)?;
        if let Some(replay) = replay_operation(
            &state,
            &request.operation_id,
            request_sha256,
            LeaseOperationKind::Issue,
        )? {
            return Ok(match replay {
                OperationReplay::Resume => PrepareIssue::Resume(
                    lease_for_operation(&state, &request.operation_id)?.clone(),
                ),
                OperationReplay::Completed => PrepareIssue::Completed(
                    lease_for_operation(&state, &request.operation_id)?.clone(),
                ),
                OperationReplay::NeedsReconciliation(reason) => {
                    PrepareIssue::NeedsReconciliation(reason)
                }
                OperationReplay::Failed(failure) => PrepareIssue::Failed(failure),
            });
        }
        if state.leases.len() >= MAX_REGISTRY_LEASES
            || state.operations.len() >= MAX_REGISTRY_OPERATIONS
        {
            return Err(LeaseRegistryError::CapacityExceeded);
        }
        let handle = lease_handle(request_sha256, &request.operation_id);
        if state.leases.contains_key(&handle) {
            return Err(LeaseRegistryError::InvalidState);
        }
        let lease = StoredLease {
            lease_handle_sha256: handle,
            issue_operation_id: request.operation_id.clone(),
            issue_request_sha256: request_sha256,
            subject_id: request.subject_id.clone(),
            consumer_id: request.consumer_id.clone(),
            namespace: request.namespace.clone(),
            mount: request.mount.clone(),
            path: request.path.clone(),
            required_fields,
            provider_lease_id: None,
            state: SecretLeaseState::IssuePrepared,
            reconciliation_reason: None,
            renewable: false,
            issued_at_ms: None,
            expires_at_ms: None,
            generation: 0,
            pending_operation_id: Some(request.operation_id.clone()),
            pending_operation_sha256: Some(request_sha256),
            pending_operation_kind: Some(LeaseOperationKind::Issue),
            pending_increment_seconds: None,
            pending_previous_state: None,
            pending_previous_reconciliation_reason: None,
            secret_fields: 0,
            secret_bytes: 0,
        };
        append_event(
            &self.0.store,
            &mut state,
            &request.operation_id,
            request_sha256,
            LeaseOperationKind::Issue,
            OperationPhase::Prepared,
            None,
            lease.clone(),
        )?;
        Ok(PrepareIssue::New(lease))
    }

    fn prepare_existing_operation(
        &self,
        lease_handle_sha256: [u8; 32],
        operation_id: &str,
        request_sha256: [u8; 32],
        kind: LeaseOperationKind,
        increment_seconds: Option<u64>,
    ) -> Result<PrepareExisting, LeaseRegistryError> {
        let mut state = self
            .0
            .state
            .lock()
            .map_err(|_| LeaseRegistryError::Unavailable)?;
        ensure_registry_live(&state)?;
        if let Some(replay) = replay_operation(&state, operation_id, request_sha256, kind)? {
            return Ok(match replay {
                OperationReplay::Resume => PrepareExisting::Resume(
                    lease_for_operation(&state, operation_id)?.clone(),
                ),
                OperationReplay::Completed => PrepareExisting::Completed(
                    lease_for_operation(&state, operation_id)?.clone(),
                ),
                OperationReplay::NeedsReconciliation(reason) => {
                    PrepareExisting::NeedsReconciliation(reason)
                }
                OperationReplay::Failed(failure) => PrepareExisting::Failed(failure),
            });
        }
        if state.operations.len() >= MAX_REGISTRY_OPERATIONS {
            return Err(LeaseRegistryError::CapacityExceeded);
        }
        let current = state
            .leases
            .get(&lease_handle_sha256)
            .cloned()
            .ok_or(LeaseRegistryError::LeaseNotFound)?;
        validate_operation_subject(&current)?;
        match kind {
            LeaseOperationKind::Renew => {
                if current.state != SecretLeaseState::Active {
                    return Err(LeaseRegistryError::InvalidTransition);
                }
                if !current.renewable {
                    return Err(LeaseRegistryError::LeaseNotRenewable);
                }
            }
            LeaseOperationKind::Revoke => {
                if matches!(
                    current.state,
                    SecretLeaseState::Revoked | SecretLeaseState::Expired | SecretLeaseState::Failed
                ) {
                    return Err(LeaseRegistryError::LeaseTerminal);
                }
                if current.provider_lease_id.is_none() {
                    return Err(LeaseRegistryError::MissingProviderLease);
                }
            }
            LeaseOperationKind::Reconcile => {
                if !matches!(
                    current.state,
                    SecretLeaseState::ReconciliationRequired
                        | SecretLeaseState::Issuing
                        | SecretLeaseState::IssuedPendingDelivery
                        | SecretLeaseState::Renewing
                        | SecretLeaseState::RevokePending
                ) {
                    return Err(LeaseRegistryError::InvalidTransition);
                }
                if current.provider_lease_id.is_none() {
                    return Err(LeaseRegistryError::MissingProviderLease);
                }
            }
            LeaseOperationKind::ResolveUnknownIssue | LeaseOperationKind::Issue => {
                return Err(LeaseRegistryError::InvalidTransition);
            }
        }
        let mut next = current.clone();
        next.pending_previous_state = Some(current.state);
        next.pending_previous_reconciliation_reason = current.reconciliation_reason;
        next.pending_operation_id = Some(operation_id.to_owned());
        next.pending_operation_sha256 = Some(request_sha256);
        next.pending_operation_kind = Some(kind);
        next.pending_increment_seconds = increment_seconds;
        next.reconciliation_reason = current.reconciliation_reason;
        next.state = match kind {
            LeaseOperationKind::Renew => SecretLeaseState::RenewPrepared,
            LeaseOperationKind::Revoke => SecretLeaseState::RevokePrepared,
            LeaseOperationKind::Reconcile => SecretLeaseState::ReconciliationRequired,
            LeaseOperationKind::ResolveUnknownIssue | LeaseOperationKind::Issue => {
                return Err(LeaseRegistryError::InvalidTransition);
            }
        };
        append_event(
            &self.0.store,
            &mut state,
            operation_id,
            request_sha256,
            kind,
            OperationPhase::Prepared,
            None,
            next.clone(),
        )?;
        Ok(PrepareExisting::New(next))
    }

    fn prepare_unknown_issue_resolution(
        &self,
        request: &BaoUnknownIssueResolutionRequest,
        request_sha256: [u8; 32],
    ) -> Result<PrepareExisting, LeaseRegistryError> {
        let mut state = self
            .0
            .state
            .lock()
            .map_err(|_| LeaseRegistryError::Unavailable)?;
        ensure_registry_live(&state)?;
        if let Some(replay) = replay_operation(
            &state,
            &request.operation_id,
            request_sha256,
            LeaseOperationKind::ResolveUnknownIssue,
        )? {
            return Ok(match replay {
                OperationReplay::Resume => PrepareExisting::Resume(
                    lease_for_operation(&state, &request.operation_id)?.clone(),
                ),
                OperationReplay::Completed => PrepareExisting::Completed(
                    lease_for_operation(&state, &request.operation_id)?.clone(),
                ),
                OperationReplay::NeedsReconciliation(reason) => {
                    PrepareExisting::NeedsReconciliation(reason)
                }
                OperationReplay::Failed(failure) => PrepareExisting::Failed(failure),
            });
        }
        if state.operations.len() >= MAX_REGISTRY_OPERATIONS {
            return Err(LeaseRegistryError::CapacityExceeded);
        }
        let current = state
            .leases
            .get(&request.lease_handle_sha256)
            .cloned()
            .ok_or(LeaseRegistryError::LeaseNotFound)?;
        if current.state != SecretLeaseState::ReconciliationRequired
            || current.reconciliation_reason != Some(ReconciliationReason::IssueOutcomeUnknown)
            || current.provider_lease_id.is_some()
        {
            return Err(LeaseRegistryError::InvalidTransition);
        }
        let mut next = current.clone();
        next.pending_previous_state = Some(current.state);
        next.pending_previous_reconciliation_reason = current.reconciliation_reason;
        next.pending_operation_id = Some(request.operation_id.clone());
        next.pending_operation_sha256 = Some(request_sha256);
        next.pending_operation_kind = Some(LeaseOperationKind::ResolveUnknownIssue);
        append_event(
            &self.0.store,
            &mut state,
            &request.operation_id,
            request_sha256,
            LeaseOperationKind::ResolveUnknownIssue,
            OperationPhase::Prepared,
            None,
            next.clone(),
        )?;
        Ok(PrepareExisting::New(next))
    }

    fn mark_dispatching(
        &self,
        operation_id: &str,
        request_sha256: [u8; 32],
        kind: LeaseOperationKind,
    ) -> Result<StoredLease, LeaseRegistryError> {
        let mut state = self
            .0
            .state
            .lock()
            .map_err(|_| LeaseRegistryError::Unavailable)?;
        ensure_registry_live(&state)?;
        let mut lease = lease_for_operation(&state, operation_id)?.clone();
        require_pending(&lease, operation_id, request_sha256, kind)?;
        lease.state = match kind {
            LeaseOperationKind::Issue => SecretLeaseState::Issuing,
            LeaseOperationKind::Renew => SecretLeaseState::Renewing,
            LeaseOperationKind::Revoke => SecretLeaseState::RevokePending,
            LeaseOperationKind::Reconcile | LeaseOperationKind::ResolveUnknownIssue => lease.state,
        };
        append_event(
            &self.0.store,
            &mut state,
            operation_id,
            request_sha256,
            kind,
            OperationPhase::Dispatching,
            None,
            lease.clone(),
        )?;
        Ok(lease)
    }

    fn observe_issue(
        &self,
        operation_id: &str,
        request_sha256: [u8; 32],
        provider_lease_id: Zeroizing<String>,
        renewable: bool,
        issued_at_ms: u64,
        expires_at_ms: u64,
        secret_fields: usize,
        secret_bytes: usize,
    ) -> Result<StoredLease, LeaseRegistryError> {
        let mut state = self
            .0
            .state
            .lock()
            .map_err(|_| LeaseRegistryError::Unavailable)?;
        ensure_registry_live(&state)?;
        let mut lease = lease_for_operation(&state, operation_id)?.clone();
        require_pending(
            &lease,
            operation_id,
            request_sha256,
            LeaseOperationKind::Issue,
        )?;
        if lease.state != SecretLeaseState::Issuing || !provider_lease_id(&provider_lease_id) {
            return Err(LeaseRegistryError::InvalidTransition);
        }
        lease.provider_lease_id = Some(provider_lease_id);
        lease.renewable = renewable;
        lease.issued_at_ms = Some(issued_at_ms);
        lease.expires_at_ms = Some(expires_at_ms);
        lease.generation = 1;
        lease.secret_fields = secret_fields;
        lease.secret_bytes = secret_bytes;
        lease.state = SecretLeaseState::IssuedPendingDelivery;
        lease.reconciliation_reason = None;
        append_event(
            &self.0.store,
            &mut state,
            operation_id,
            request_sha256,
            LeaseOperationKind::Issue,
            OperationPhase::ProviderObserved,
            None,
            lease.clone(),
        )?;
        Ok(lease)
    }

    fn complete_issue(
        &self,
        operation_id: &str,
        request_sha256: [u8; 32],
    ) -> Result<StoredLease, LeaseRegistryError> {
        self.complete_transition(
            operation_id,
            request_sha256,
            LeaseOperationKind::Issue,
            |lease| {
                if lease.state != SecretLeaseState::IssuedPendingDelivery {
                    return Err(LeaseRegistryError::InvalidTransition);
                }
                lease.state = SecretLeaseState::Active;
                lease.reconciliation_reason = None;
                clear_pending(lease);
                Ok(())
            },
        )
    }

    fn complete_renew(
        &self,
        operation_id: &str,
        request_sha256: [u8; 32],
        renewable: bool,
        expires_at_ms: u64,
    ) -> Result<StoredLease, LeaseRegistryError> {
        self.complete_transition(
            operation_id,
            request_sha256,
            LeaseOperationKind::Renew,
            |lease| {
                if lease.state != SecretLeaseState::Renewing {
                    return Err(LeaseRegistryError::InvalidTransition);
                }
                lease.renewable = renewable;
                lease.expires_at_ms = Some(expires_at_ms);
                lease.generation = lease
                    .generation
                    .checked_add(1)
                    .ok_or(LeaseRegistryError::InvalidState)?;
                lease.state = SecretLeaseState::Active;
                lease.reconciliation_reason = None;
                clear_pending(lease);
                Ok(())
            },
        )
    }

    fn complete_revoke(
        &self,
        operation_id: &str,
        request_sha256: [u8; 32],
    ) -> Result<StoredLease, LeaseRegistryError> {
        self.complete_transition(
            operation_id,
            request_sha256,
            LeaseOperationKind::Revoke,
            |lease| {
                if lease.state != SecretLeaseState::RevokePending {
                    return Err(LeaseRegistryError::InvalidTransition);
                }
                lease.state = SecretLeaseState::Revoked;
                lease.renewable = false;
                lease.expires_at_ms = Some(now_ms_registry()?);
                lease.reconciliation_reason = None;
                clear_pending(lease);
                Ok(())
            },
        )
    }

    fn complete_reconcile_present(
        &self,
        operation_id: &str,
        request_sha256: [u8; 32],
        renewable: bool,
        expires_at_ms: u64,
    ) -> Result<StoredLease, LeaseRegistryError> {
        self.complete_transition(
            operation_id,
            request_sha256,
            LeaseOperationKind::Reconcile,
            |lease| {
                let previous_state = lease
                    .pending_previous_state
                    .ok_or(LeaseRegistryError::InvalidTransition)?;
                let previous_reason = lease.pending_previous_reconciliation_reason;
                lease.renewable = renewable;
                lease.expires_at_ms = Some(expires_at_ms);
                match previous_reason {
                    Some(ReconciliationReason::RenewOutcomeUnknown) => {
                        lease.state = SecretLeaseState::Active;
                        lease.reconciliation_reason = None;
                        lease.generation = lease
                            .generation
                            .checked_add(1)
                            .ok_or(LeaseRegistryError::InvalidState)?;
                    }
                    Some(ReconciliationReason::RevokeOutcomeUnknown) => {
                        lease.state = SecretLeaseState::ReconciliationRequired;
                        lease.reconciliation_reason =
                            Some(ReconciliationReason::RevokeStillActive);
                    }
                    Some(
                        ReconciliationReason::IssueOutcomeUnknown
                        | ReconciliationReason::SecretDeliveryLost
                        | ReconciliationReason::DeliveryAuthorizationLost
                        | ReconciliationReason::OrphanedActiveLease,
                    ) => {
                        lease.state = SecretLeaseState::ReconciliationRequired;
                        lease.reconciliation_reason =
                            Some(ReconciliationReason::OrphanedActiveLease);
                    }
                    Some(ReconciliationReason::ConsumerOutcomeUnknown) => {
                        lease.state = SecretLeaseState::ReconciliationRequired;
                        lease.reconciliation_reason =
                            Some(ReconciliationReason::ConsumerOutcomeUnknown);
                    }
                    Some(ReconciliationReason::RevokeStillActive) => {
                        lease.state = SecretLeaseState::ReconciliationRequired;
                        lease.reconciliation_reason =
                            Some(ReconciliationReason::RevokeStillActive);
                    }
                    None => {
                        lease.state = match previous_state {
                            SecretLeaseState::Renewing => SecretLeaseState::Active,
                            SecretLeaseState::RevokePending => {
                                SecretLeaseState::ReconciliationRequired
                            }
                            SecretLeaseState::Issuing | SecretLeaseState::IssuedPendingDelivery => {
                                SecretLeaseState::ReconciliationRequired
                            }
                            state => state,
                        };
                        if lease.state == SecretLeaseState::ReconciliationRequired {
                            lease.reconciliation_reason =
                                Some(ReconciliationReason::OrphanedActiveLease);
                        }
                    }
                }
                clear_pending(lease);
                Ok(())
            },
        )
    }

    fn complete_reconcile_absent(
        &self,
        operation_id: &str,
        request_sha256: [u8; 32],
    ) -> Result<StoredLease, LeaseRegistryError> {
        self.complete_transition(
            operation_id,
            request_sha256,
            LeaseOperationKind::Reconcile,
            |lease| {
                let previous_reason = lease.pending_previous_reconciliation_reason;
                lease.state = match previous_reason {
                    Some(ReconciliationReason::RevokeOutcomeUnknown)
                    | Some(ReconciliationReason::RevokeStillActive) => SecretLeaseState::Revoked,
                    _ => SecretLeaseState::Expired,
                };
                lease.renewable = false;
                lease.expires_at_ms = Some(now_ms_registry()?);
                lease.reconciliation_reason = None;
                clear_pending(lease);
                Ok(())
            },
        )
    }

    fn complete_unknown_issue_resolution(
        &self,
        operation_id: &str,
        request_sha256: [u8; 32],
        resolution: &BaoUnknownIssueResolution,
    ) -> Result<StoredLease, LeaseRegistryError> {
        let mut state = self
            .0
            .state
            .lock()
            .map_err(|_| LeaseRegistryError::Unavailable)?;
        ensure_registry_live(&state)?;
        let current = lease_for_operation(&state, operation_id)?.clone();
        require_pending(
            &current,
            operation_id,
            request_sha256,
            LeaseOperationKind::ResolveUnknownIssue,
        )?;
        let mut next = current.clone();
        match resolution {
            BaoUnknownIssueResolution::ConfirmedAbsent => {
                next.state = SecretLeaseState::Failed;
                next.reconciliation_reason = None;
                clear_pending(&mut next);
                let original = state
                    .operations
                    .get(&next.issue_operation_id)
                    .cloned()
                    .ok_or(LeaseRegistryError::InvalidState)?;
                append_event(
                    &self.0.store,
                    &mut state,
                    &next.issue_operation_id,
                    original.request_sha256,
                    LeaseOperationKind::Issue,
                    OperationPhase::Failed,
                    Some(LeaseFailureKind::ConfirmedAbsent),
                    next.clone(),
                )?;
                append_event(
                    &self.0.store,
                    &mut state,
                    operation_id,
                    request_sha256,
                    LeaseOperationKind::ResolveUnknownIssue,
                    OperationPhase::Completed,
                    None,
                    next.clone(),
                )?;
            }
            BaoUnknownIssueResolution::ObservedLease(provider_id) => {
                next.provider_lease_id = Some(Zeroizing::new(provider_id.as_str().to_owned()));
                next.state = SecretLeaseState::ReconciliationRequired;
                next.reconciliation_reason = Some(ReconciliationReason::OrphanedActiveLease);
                clear_pending(&mut next);
                append_event(
                    &self.0.store,
                    &mut state,
                    operation_id,
                    request_sha256,
                    LeaseOperationKind::ResolveUnknownIssue,
                    OperationPhase::Completed,
                    None,
                    next.clone(),
                )?;
            }
        }
        Ok(next)
    }

    fn mark_reconciliation(
        &self,
        operation_id: &str,
        request_sha256: [u8; 32],
        kind: LeaseOperationKind,
        reason: ReconciliationReason,
    ) -> Result<StoredLease, LeaseRegistryError> {
        let mut state = self
            .0
            .state
            .lock()
            .map_err(|_| LeaseRegistryError::Unavailable)?;
        ensure_registry_live(&state)?;
        let mut lease = lease_for_operation(&state, operation_id)?.clone();
        require_pending(&lease, operation_id, request_sha256, kind)?;
        lease.state = SecretLeaseState::ReconciliationRequired;
        lease.reconciliation_reason = Some(reason);
        append_event(
            &self.0.store,
            &mut state,
            operation_id,
            request_sha256,
            kind,
            OperationPhase::ReconciliationRequired,
            None,
            lease.clone(),
        )?;
        Ok(lease)
    }

    fn mark_explicit_failure(
        &self,
        operation_id: &str,
        request_sha256: [u8; 32],
        kind: LeaseOperationKind,
        failure: LeaseFailureKind,
    ) -> Result<StoredLease, LeaseRegistryError> {
        let mut state = self
            .0
            .state
            .lock()
            .map_err(|_| LeaseRegistryError::Unavailable)?;
        ensure_registry_live(&state)?;
        let mut lease = lease_for_operation(&state, operation_id)?.clone();
        require_pending(&lease, operation_id, request_sha256, kind)?;
        match kind {
            LeaseOperationKind::Issue => {
                lease.state = SecretLeaseState::Failed;
                lease.reconciliation_reason = None;
            }
            _ => restore_previous_state(&mut lease)?,
        }
        clear_pending(&mut lease);
        append_event(
            &self.0.store,
            &mut state,
            operation_id,
            request_sha256,
            kind,
            OperationPhase::Failed,
            Some(failure),
            lease.clone(),
        )?;
        Ok(lease)
    }

    fn complete_transition(
        &self,
        operation_id: &str,
        request_sha256: [u8; 32],
        kind: LeaseOperationKind,
        update: impl FnOnce(&mut StoredLease) -> Result<(), LeaseRegistryError>,
    ) -> Result<StoredLease, LeaseRegistryError> {
        let mut state = self
            .0
            .state
            .lock()
            .map_err(|_| LeaseRegistryError::Unavailable)?;
        ensure_registry_live(&state)?;
        let mut lease = lease_for_operation(&state, operation_id)?.clone();
        require_pending(&lease, operation_id, request_sha256, kind)?;
        update(&mut lease)?;
        append_event(
            &self.0.store,
            &mut state,
            operation_id,
            request_sha256,
            kind,
            OperationPhase::Completed,
            None,
            lease.clone(),
        )?;
        Ok(lease)
    }

    fn provider_identity(
        &self,
        lease_handle_sha256: [u8; 32],
    ) -> Result<Zeroizing<String>, LeaseRegistryError> {
        let state = self
            .0
            .state
            .lock()
            .map_err(|_| LeaseRegistryError::Unavailable)?;
        ensure_registry_live(&state)?;
        state
            .leases
            .get(&lease_handle_sha256)
            .and_then(|lease| lease.provider_lease_id.clone())
            .ok_or(LeaseRegistryError::MissingProviderLease)
    }

    fn assert_request_owner(
        &self,
        lease_handle_sha256: [u8; 32],
        subject_id: &str,
        consumer_id: &str,
        namespace: &str,
    ) -> Result<(), LeaseRegistryError> {
        let state = self
            .0
            .state
            .lock()
            .map_err(|_| LeaseRegistryError::Unavailable)?;
        ensure_registry_live(&state)?;
        let lease = state
            .leases
            .get(&lease_handle_sha256)
            .ok_or(LeaseRegistryError::LeaseNotFound)?;
        if lease.subject_id != subject_id
            || lease.consumer_id != consumer_id
            || lease.namespace != namespace
        {
            return Err(LeaseRegistryError::BindingMismatch);
        }
        Ok(())
    }
}

struct RegistryInner {
    state: Mutex<RegistryState>,
    store: JournalStore,
}

#[derive(Default)]
struct RegistryState {
    next_sequence: u64,
    leases: BTreeMap<[u8; 32], StoredLease>,
    operations: BTreeMap<String, StoredOperation>,
    failed: bool,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredLease {
    lease_handle_sha256: [u8; 32],
    issue_operation_id: String,
    issue_request_sha256: [u8; 32],
    subject_id: String,
    consumer_id: String,
    namespace: String,
    mount: String,
    path: String,
    required_fields: Vec<String>,
    provider_lease_id: Option<Zeroizing<String>>,
    state: SecretLeaseState,
    reconciliation_reason: Option<ReconciliationReason>,
    renewable: bool,
    issued_at_ms: Option<u64>,
    expires_at_ms: Option<u64>,
    generation: u64,
    pending_operation_id: Option<String>,
    pending_operation_sha256: Option<[u8; 32]>,
    pending_operation_kind: Option<LeaseOperationKind>,
    pending_increment_seconds: Option<u64>,
    pending_previous_state: Option<SecretLeaseState>,
    pending_previous_reconciliation_reason: Option<ReconciliationReason>,
    secret_fields: usize,
    secret_bytes: usize,
}

impl StoredLease {
    fn metadata(&self) -> SecretLeaseMetadata {
        SecretLeaseMetadata {
            lease_handle_sha256: self.lease_handle_sha256,
            state: self.state,
            reconciliation_reason: self.reconciliation_reason,
            renewable: self.renewable,
            issued_at_ms: self.issued_at_ms,
            expires_at_ms: self.expires_at_ms,
            generation: self.generation,
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
enum LeaseOperationKind {
    Issue,
    Renew,
    Revoke,
    Reconcile,
    ResolveUnknownIssue,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
enum OperationPhase {
    Prepared,
    Dispatching,
    ProviderObserved,
    Completed,
    ReconciliationRequired,
    Failed,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LeaseFailureKind {
    ProviderDenied,
    NotFound,
    ConfirmedAbsent,
}

#[derive(Clone)]
struct StoredOperation {
    request_sha256: [u8; 32],
    kind: LeaseOperationKind,
    phase: OperationPhase,
    lease_handle_sha256: [u8; 32],
    failure: Option<LeaseFailureKind>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct JournalEvent {
    schema: u32,
    sequence: u64,
    operation_id: String,
    request_sha256: [u8; 32],
    kind: LeaseOperationKind,
    phase: OperationPhase,
    failure: Option<LeaseFailureKind>,
    lease: StoredLease,
}

struct JournalStore {
    root: File,
    journal: File,
    _lock: File,
}

impl JournalStore {
    fn open(root: &Path) -> Result<(Self, RegistryState), LeaseRegistryError> {
        let root = prepare_directory(root)?;
        let initialized = entry_exists(&root, "lease.lock")?;
        let lock = open_private(&root, "lease.lock", Access::Create)?;
        lock.try_lock()
            .map_err(|_| LeaseRegistryError::StateLocked)?;
        let has_journal = entry_exists(&root, "leases.journal")?;
        if initialized && !has_journal {
            return Err(LeaseRegistryError::InvalidState);
        }
        let mut journal = open_private(&root, "leases.journal", Access::Append)?;
        root.sync_all()
            .map_err(|_| LeaseRegistryError::Unavailable)?;
        let length = journal
            .metadata()
            .map_err(|_| LeaseRegistryError::Unavailable)?
            .len();
        if length > MAX_JOURNAL_BYTES {
            return Err(LeaseRegistryError::CapacityExceeded);
        }
        journal
            .seek(SeekFrom::Start(0))
            .map_err(|_| LeaseRegistryError::Unavailable)?;
        let mut bytes = Zeroizing::new(Vec::new());
        journal
            .take(MAX_JOURNAL_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| LeaseRegistryError::Unavailable)?;
        if bytes.len() as u64 > MAX_JOURNAL_BYTES {
            return Err(LeaseRegistryError::CapacityExceeded);
        }
        let mut state = RegistryState {
            next_sequence: 1,
            ..RegistryState::default()
        };
        parse_journal(&bytes, &mut state)?;
        journal
            .seek(SeekFrom::End(0))
            .map_err(|_| LeaseRegistryError::Unavailable)?;
        Ok((
            Self {
                root,
                journal,
                _lock: lock,
            },
            state,
        ))
    }

    fn append(&self, event: &JournalEvent) -> Result<(), LeaseRegistryError> {
        let mut bytes =
            Zeroizing::new(serde_json::to_vec(event).map_err(|_| LeaseRegistryError::InvalidState)?);
        if bytes.len() >= MAX_JOURNAL_EVENT_BYTES {
            return Err(LeaseRegistryError::CapacityExceeded);
        }
        bytes.push(b'\n');
        let current = self
            .journal
            .metadata()
            .map_err(|_| LeaseRegistryError::Unavailable)?
            .len();
        if current.saturating_add(bytes.len() as u64) > MAX_JOURNAL_BYTES {
            return Err(LeaseRegistryError::CapacityExceeded);
        }
        let mut journal = &self.journal;
        journal
            .write_all(&bytes)
            .and_then(|()| journal.sync_all())
            .map_err(|_| LeaseRegistryError::Unavailable)?;
        self.root
            .sync_all()
            .map_err(|_| LeaseRegistryError::Unavailable)
    }
}

fn parse_journal(bytes: &[u8], state: &mut RegistryState) -> Result<(), LeaseRegistryError> {
    for chunk in bytes.split_inclusive(|byte| *byte == b'\n') {
        if !chunk.ends_with(b"\n") {
            break;
        }
        if chunk.len() <= 1 || chunk.len() > MAX_JOURNAL_EVENT_BYTES {
            return Err(LeaseRegistryError::InvalidState);
        }
        let event: JournalEvent = serde_json::from_slice(&chunk[..chunk.len() - 1])
            .map_err(|_| LeaseRegistryError::InvalidState)?;
        apply_event(state, event)?;
    }
    Ok(())
}

fn apply_event(state: &mut RegistryState, event: JournalEvent) -> Result<(), LeaseRegistryError> {
    if event.schema != 1
        || event.sequence != state.next_sequence
        || !component(&event.operation_id)
        || event.request_sha256 == [0; 32]
        || event.lease.lease_handle_sha256 == [0; 32]
        || event.lease.issue_request_sha256 == [0; 32]
        || !component(&event.lease.issue_operation_id)
        || !component(&event.lease.subject_id)
        || !component(&event.lease.consumer_id)
        || (!event.lease.namespace.is_empty() && !segmented(&event.lease.namespace))
        || !segmented(&event.lease.mount)
        || !segmented(&event.lease.path)
        || event.lease.required_fields.is_empty()
        || event.lease.required_fields.len() > MAX_REQUIRED_FIELDS
        || event
            .lease
            .provider_lease_id
            .as_ref()
            .is_some_and(|value| !provider_lease_id(value))
    {
        return Err(LeaseRegistryError::InvalidState);
    }
    if let Some(existing) = state.operations.get(&event.operation_id)
        && (existing.request_sha256 != event.request_sha256
            || existing.kind != event.kind
            || existing.lease_handle_sha256 != event.lease.lease_handle_sha256)
    {
        return Err(LeaseRegistryError::InvalidState);
    }
    if let Some(existing) = state.leases.get(&event.lease.lease_handle_sha256)
        && (existing.issue_operation_id != event.lease.issue_operation_id
            || existing.issue_request_sha256 != event.lease.issue_request_sha256
            || existing.subject_id != event.lease.subject_id
            || existing.consumer_id != event.lease.consumer_id
            || existing.namespace != event.lease.namespace
            || existing.mount != event.lease.mount
            || existing.path != event.lease.path
            || existing.required_fields != event.lease.required_fields)
    {
        return Err(LeaseRegistryError::InvalidState);
    }
    state.operations.insert(
        event.operation_id,
        StoredOperation {
            request_sha256: event.request_sha256,
            kind: event.kind,
            phase: event.phase,
            lease_handle_sha256: event.lease.lease_handle_sha256,
            failure: event.failure,
        },
    );
    state
        .leases
        .insert(event.lease.lease_handle_sha256, event.lease);
    if state.leases.len() > MAX_REGISTRY_LEASES || state.operations.len() > MAX_REGISTRY_OPERATIONS {
        return Err(LeaseRegistryError::CapacityExceeded);
    }
    state.next_sequence = state
        .next_sequence
        .checked_add(1)
        .ok_or(LeaseRegistryError::InvalidState)?;
    Ok(())
}

fn append_event(
    store: &JournalStore,
    state: &mut RegistryState,
    operation_id: &str,
    request_sha256: [u8; 32],
    kind: LeaseOperationKind,
    phase: OperationPhase,
    failure: Option<LeaseFailureKind>,
    lease: StoredLease,
) -> Result<(), LeaseRegistryError> {
    if state.failed {
        return Err(LeaseRegistryError::Unavailable);
    }
    let event = JournalEvent {
        schema: 1,
        sequence: state.next_sequence,
        operation_id: operation_id.to_owned(),
        request_sha256,
        kind,
        phase,
        failure,
        lease,
    };
    if store.append(&event).is_err() {
        state.failed = true;
        return Err(LeaseRegistryError::Unavailable);
    }
    if apply_event(state, event).is_err() {
        state.failed = true;
        return Err(LeaseRegistryError::InvalidState);
    }
    Ok(())
}

fn normalize_recovery(state: &mut RegistryState) {
    let handles: Vec<[u8; 32]> = state.leases.keys().copied().collect();
    for handle in handles {
        let Some(lease) = state.leases.get_mut(&handle) else {
            continue;
        };
        let reason = match lease.state {
            SecretLeaseState::Issuing => Some(ReconciliationReason::IssueOutcomeUnknown),
            SecretLeaseState::IssuedPendingDelivery => Some(ReconciliationReason::SecretDeliveryLost),
            SecretLeaseState::Renewing => Some(ReconciliationReason::RenewOutcomeUnknown),
            SecretLeaseState::RevokePending => Some(ReconciliationReason::RevokeOutcomeUnknown),
            _ => None,
        };
        let Some(reason) = reason else {
            continue;
        };
        lease.state = SecretLeaseState::ReconciliationRequired;
        lease.reconciliation_reason = Some(reason);
        if let Some(operation_id) = lease.pending_operation_id.as_ref()
            && let Some(operation) = state.operations.get_mut(operation_id)
        {
            operation.phase = OperationPhase::ReconciliationRequired;
        }
    }
}

fn ensure_registry_live(state: &RegistryState) -> Result<(), LeaseRegistryError> {
    if state.failed {
        Err(LeaseRegistryError::Unavailable)
    } else {
        Ok(())
    }
}

fn replay_operation(
    state: &RegistryState,
    operation_id: &str,
    request_sha256: [u8; 32],
    kind: LeaseOperationKind,
) -> Result<Option<OperationReplay>, LeaseRegistryError> {
    let Some(operation) = state.operations.get(operation_id) else {
        return Ok(None);
    };
    if operation.request_sha256 != request_sha256 || operation.kind != kind {
        return Err(LeaseRegistryError::OperationConflict);
    }
    Ok(Some(match operation.phase {
        OperationPhase::Prepared => OperationReplay::Resume,
        OperationPhase::Completed => OperationReplay::Completed,
        OperationPhase::Dispatching
        | OperationPhase::ProviderObserved
        | OperationPhase::ReconciliationRequired => {
            let lease = state
                .leases
                .get(&operation.lease_handle_sha256)
                .ok_or(LeaseRegistryError::InvalidState)?;
            OperationReplay::NeedsReconciliation(
                lease
                    .reconciliation_reason
                    .unwrap_or(ReconciliationReason::IssueOutcomeUnknown),
            )
        }
        OperationPhase::Failed => OperationReplay::Failed(
            operation
                .failure
                .ok_or(LeaseRegistryError::InvalidState)?,
        ),
    }))
}

fn lease_for_operation<'a>(
    state: &'a RegistryState,
    operation_id: &str,
) -> Result<&'a StoredLease, LeaseRegistryError> {
    let operation = state
        .operations
        .get(operation_id)
        .ok_or(LeaseRegistryError::InvalidState)?;
    state
        .leases
        .get(&operation.lease_handle_sha256)
        .ok_or(LeaseRegistryError::InvalidState)
}

fn require_pending(
    lease: &StoredLease,
    operation_id: &str,
    request_sha256: [u8; 32],
    kind: LeaseOperationKind,
) -> Result<(), LeaseRegistryError> {
    if lease.pending_operation_id.as_deref() != Some(operation_id)
        || lease.pending_operation_sha256 != Some(request_sha256)
        || lease.pending_operation_kind != Some(kind)
    {
        return Err(LeaseRegistryError::InvalidTransition);
    }
    Ok(())
}

fn clear_pending(lease: &mut StoredLease) {
    lease.pending_operation_id = None;
    lease.pending_operation_sha256 = None;
    lease.pending_operation_kind = None;
    lease.pending_increment_seconds = None;
    lease.pending_previous_state = None;
    lease.pending_previous_reconciliation_reason = None;
}

fn restore_previous_state(lease: &mut StoredLease) -> Result<(), LeaseRegistryError> {
    lease.state = lease
        .pending_previous_state
        .ok_or(LeaseRegistryError::InvalidTransition)?;
    lease.reconciliation_reason = lease.pending_previous_reconciliation_reason;
    Ok(())
}

fn validate_operation_subject(lease: &StoredLease) -> Result<(), LeaseRegistryError> {
    if lease.subject_id.is_empty() || lease.consumer_id.is_empty() {
        return Err(LeaseRegistryError::InvalidState);
    }
    Ok(())
}

enum PrepareIssue {
    New(StoredLease),
    Resume(StoredLease),
    Completed(StoredLease),
    NeedsReconciliation(ReconciliationReason),
    Failed(LeaseFailureKind),
}

enum PrepareExisting {
    New(StoredLease),
    Resume(StoredLease),
    Completed(StoredLease),
    NeedsReconciliation(ReconciliationReason),
    Failed(LeaseFailureKind),
}

enum OperationReplay {
    Resume,
    Completed,
    NeedsReconciliation(ReconciliationReason),
    Failed(LeaseFailureKind),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LeaseRegistryError {
    Unavailable,
    UnsafeStateDirectory,
    StateLocked,
    InvalidState,
    CapacityExceeded,
    OperationConflict,
    LeaseNotFound,
    LeaseNotRenewable,
    LeaseTerminal,
    MissingProviderLease,
    InvalidTransition,
    BindingMismatch,
}

impl fmt::Display for LeaseRegistryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for LeaseRegistryError {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BaoLeaseError {
    InvalidRequest,
    Authority(FinalUseError),
    Registry(LeaseRegistryError),
    ProviderDenied,
    ProviderUnavailable,
    NotFound,
    TransportUnavailable,
    TimedOut,
    ResponseTooLarge,
    InvalidResponse,
    ProviderLeaseMismatch,
    ReconciliationRequired(ReconciliationReason),
    PriorOperationFailed(LeaseFailureKind),
    ConsumerIndeterminate,
}

impl fmt::Display for BaoLeaseError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for BaoLeaseError {}

impl From<LeaseRegistryError> for BaoLeaseError {
    fn from(error: LeaseRegistryError) -> Self {
        Self::Registry(error)
    }
}

impl BaoClient {
    /// Binding proposal for provider-native dynamic lease issuance.
    pub fn dynamic_lease_binding(
        &self,
        request: &BaoDynamicLeaseRequest,
    ) -> Result<FinalUseBinding, BaoLeaseError> {
        let fields = validate_issue_request(request)?;
        let request_sha256 = issue_request_digest(self, request, &fields)?;
        Ok(operation_binding(
            self,
            &request.subject_id,
            &request.consumer_id,
            &request.namespace,
            "issue",
            request_sha256,
            Some((&request.mount, &request.path)),
            None,
        )?)
    }

    pub fn renew_lease_binding(
        &self,
        request: &BaoRenewLeaseRequest,
    ) -> Result<FinalUseBinding, BaoLeaseError> {
        validate_existing_request(
            &request.subject_id,
            &request.consumer_id,
            &request.namespace,
            &request.operation_id,
            request.lease_handle_sha256,
        )?;
        if request.increment_seconds > MAX_RENEW_INCREMENT_SECONDS {
            return Err(BaoLeaseError::InvalidRequest);
        }
        let digest = renew_request_digest(self, request)?;
        operation_binding(
            self,
            &request.subject_id,
            &request.consumer_id,
            &request.namespace,
            "renew",
            digest,
            None,
            Some(request.lease_handle_sha256),
        )
    }

    pub fn revoke_lease_binding(
        &self,
        request: &BaoRevokeLeaseRequest,
    ) -> Result<FinalUseBinding, BaoLeaseError> {
        validate_existing_request(
            &request.subject_id,
            &request.consumer_id,
            &request.namespace,
            &request.operation_id,
            request.lease_handle_sha256,
        )?;
        let digest = revoke_request_digest(self, request)?;
        operation_binding(
            self,
            &request.subject_id,
            &request.consumer_id,
            &request.namespace,
            "revoke",
            digest,
            None,
            Some(request.lease_handle_sha256),
        )
    }

    pub fn reconcile_lease_binding(
        &self,
        request: &BaoReconcileLeaseRequest,
    ) -> Result<FinalUseBinding, BaoLeaseError> {
        validate_existing_request(
            &request.subject_id,
            &request.consumer_id,
            &request.namespace,
            &request.operation_id,
            request.lease_handle_sha256,
        )?;
        let digest = reconcile_request_digest(self, request)?;
        operation_binding(
            self,
            &request.subject_id,
            &request.consumer_id,
            &request.namespace,
            "reconcile",
            digest,
            None,
            Some(request.lease_handle_sha256),
        )
    }

    pub fn unknown_issue_resolution_binding(
        &self,
        request: &BaoUnknownIssueResolutionRequest,
    ) -> Result<FinalUseBinding, BaoLeaseError> {
        validate_existing_request(
            &request.subject_id,
            &request.consumer_id,
            &request.namespace,
            &request.operation_id,
            request.lease_handle_sha256,
        )?;
        if request.evidence_sha256 == [0; 32] {
            return Err(BaoLeaseError::InvalidRequest);
        }
        let digest = unknown_issue_resolution_digest(self, request)?;
        operation_binding(
            self,
            &request.subject_id,
            &request.consumer_id,
            &request.namespace,
            "resolve-unknown-issue",
            digest,
            None,
            Some(request.lease_handle_sha256),
        )
    }

    /// Issues a provider-native dynamic secret and delivers only the requested
    /// string fields to the trusted callback. No secret bytes are persisted or
    /// returned. The local operation_id prevents blind duplicate issuance.
    pub async fn request_secret_lease(
        &self,
        registry: &SecretLeaseRegistry,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoDynamicLeaseRequest,
        consumer: impl FnOnce(&BaoDynamicSecret<'_>) -> Result<(), ()>,
    ) -> Result<BaoLeaseReceipt, BaoLeaseError> {
        let fields = validate_issue_request(request)?;
        let binding = self.dynamic_lease_binding(request)?;
        let request_sha256 = binding.request_sha256;
        match registry.prepare_issue(request, request_sha256, fields.clone())? {
            PrepareIssue::Completed(lease) => {
                return Ok(BaoLeaseReceipt {
                    request_sha256,
                    lease: lease.metadata(),
                    delivery: LeaseDelivery::AlreadyIssuedNoRedelivery,
                    secret_fields: lease.secret_fields,
                    secret_bytes: lease.secret_bytes,
                });
            }
            PrepareIssue::NeedsReconciliation(reason) => {
                return Err(BaoLeaseError::ReconciliationRequired(reason));
            }
            PrepareIssue::Failed(failure) => {
                return Err(BaoLeaseError::PriorOperationFailed(failure));
            }
            PrepareIssue::New(_) | PrepareIssue::Resume(_) => {}
        }

        let verified = authority
            .claim(grant, &binding)
            .map_err(BaoLeaseError::Authority)?;
        registry.mark_dispatching(
            &request.operation_id,
            request_sha256,
            LeaseOperationKind::Issue,
        )?;

        let url = dynamic_url(self, &request.mount, &request.path)?;
        let network_request = authorized_request(self, self.client.get(url), &request.namespace)?;
        let response = match network_request.send().await {
            Ok(response) => response,
            Err(error) => {
                registry.mark_reconciliation(
                    &request.operation_id,
                    request_sha256,
                    LeaseOperationKind::Issue,
                    ReconciliationReason::IssueOutcomeUnknown,
                )?;
                return Err(transport_error(error));
            }
        };
        match response.status() {
            StatusCode::OK => {}
            StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN => {
                registry.mark_explicit_failure(
                    &request.operation_id,
                    request_sha256,
                    LeaseOperationKind::Issue,
                    LeaseFailureKind::ProviderDenied,
                )?;
                return Err(BaoLeaseError::ProviderDenied);
            }
            StatusCode::NOT_FOUND => {
                registry.mark_explicit_failure(
                    &request.operation_id,
                    request_sha256,
                    LeaseOperationKind::Issue,
                    LeaseFailureKind::NotFound,
                )?;
                return Err(BaoLeaseError::NotFound);
            }
            _ => {
                registry.mark_reconciliation(
                    &request.operation_id,
                    request_sha256,
                    LeaseOperationKind::Issue,
                    ReconciliationReason::IssueOutcomeUnknown,
                )?;
                return Err(BaoLeaseError::ProviderUnavailable);
            }
        }

        let body = match read_bounded_body(response).await {
            Ok(body) => body,
            Err(error) => {
                registry.mark_reconciliation(
                    &request.operation_id,
                    request_sha256,
                    LeaseOperationKind::Issue,
                    ReconciliationReason::IssueOutcomeUnknown,
                )?;
                return Err(error);
            }
        };
        let decoded: DynamicLeaseResponse = match serde_json::from_slice(&body) {
            Ok(decoded) => decoded,
            Err(_) => {
                registry.mark_reconciliation(
                    &request.operation_id,
                    request_sha256,
                    LeaseOperationKind::Issue,
                    ReconciliationReason::IssueOutcomeUnknown,
                )?;
                return Err(BaoLeaseError::InvalidResponse);
            }
        };
        if !provider_lease_id(&decoded.lease_id)
            || decoded.lease_duration == 0
            || decoded.lease_duration > MAX_LEASE_DURATION_SECONDS
        {
            registry.mark_reconciliation(
                &request.operation_id,
                request_sha256,
                LeaseOperationKind::Issue,
                ReconciliationReason::IssueOutcomeUnknown,
            )?;
            return Err(BaoLeaseError::InvalidResponse);
        }
        let mut secret_bytes = 0usize;
        for field in &fields {
            let Some(SecretValue::String(value)) = decoded.data.get(field) else {
                registry.mark_reconciliation(
                    &request.operation_id,
                    request_sha256,
                    LeaseOperationKind::Issue,
                    ReconciliationReason::IssueOutcomeUnknown,
                )?;
                return Err(BaoLeaseError::InvalidResponse);
            };
            secret_bytes = secret_bytes
                .checked_add(value.len())
                .ok_or(BaoLeaseError::InvalidResponse)?;
            if secret_bytes > MAX_RESPONSE_BYTES {
                return Err(BaoLeaseError::ResponseTooLarge);
            }
        }
        let issued_at_ms = now_ms()?;
        let expires_at_ms = expiry_from_ttl(issued_at_ms, decoded.lease_duration)?;
        registry.observe_issue(
            &request.operation_id,
            request_sha256,
            decoded.lease_id.clone(),
            decoded.renewable,
            issued_at_ms,
            expires_at_ms,
            fields.len(),
            secret_bytes,
        )?;

        let view = BaoDynamicSecret {
            required_fields: &fields,
            data: &decoded.data,
        };
        let delivery = match authority.with_verified_use(verified, &binding, || consumer(&view)) {
            Ok(Ok(())) => LeaseDelivery::Delivered,
            Ok(Err(())) => {
                registry.mark_reconciliation(
                    &request.operation_id,
                    request_sha256,
                    LeaseOperationKind::Issue,
                    ReconciliationReason::ConsumerOutcomeUnknown,
                )?;
                return Err(BaoLeaseError::ConsumerIndeterminate);
            }
            Err(error) => {
                registry.mark_reconciliation(
                    &request.operation_id,
                    request_sha256,
                    LeaseOperationKind::Issue,
                    ReconciliationReason::DeliveryAuthorizationLost,
                )?;
                return Err(BaoLeaseError::Authority(error));
            }
        };
        let lease = registry.complete_issue(&request.operation_id, request_sha256)?;
        Ok(BaoLeaseReceipt {
            request_sha256,
            lease: lease.metadata(),
            delivery,
            secret_fields: fields.len(),
            secret_bytes,
        })
    }

    pub async fn renew_secret_lease(
        &self,
        registry: &SecretLeaseRegistry,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoRenewLeaseRequest,
    ) -> Result<BaoLeaseMutationReceipt, BaoLeaseError> {
        let binding = self.renew_lease_binding(request)?;
        registry.assert_request_owner(
            request.lease_handle_sha256,
            &request.subject_id,
            &request.consumer_id,
            &request.namespace,
        )?;
        match registry.prepare_existing_operation(
            request.lease_handle_sha256,
            &request.operation_id,
            binding.request_sha256,
            LeaseOperationKind::Renew,
            Some(request.increment_seconds),
        )? {
            PrepareExisting::Completed(lease) => {
                return Ok(BaoLeaseMutationReceipt {
                    request_sha256: binding.request_sha256,
                    lease: lease.metadata(),
                    idempotent_replay: true,
                });
            }
            PrepareExisting::NeedsReconciliation(reason) => {
                return Err(BaoLeaseError::ReconciliationRequired(reason));
            }
            PrepareExisting::Failed(failure) => {
                return Err(BaoLeaseError::PriorOperationFailed(failure));
            }
            PrepareExisting::New(_) | PrepareExisting::Resume(_) => {}
        }
        authority
            .claim(grant, &binding)
            .map_err(BaoLeaseError::Authority)?;
        registry.mark_dispatching(
            &request.operation_id,
            binding.request_sha256,
            LeaseOperationKind::Renew,
        )?;
        let provider_id = registry.provider_identity(request.lease_handle_sha256)?;
        let url = system_url(self, &["leases", "renew"])?;
        let payload = RenewPayload {
            lease_id: provider_id.as_str(),
            increment: request.increment_seconds,
        };
        let network_request = authorized_request(
            self,
            self.client.post(url).json(&payload),
            &request.namespace,
        )?;
        let response = match network_request.send().await {
            Ok(response) => response,
            Err(error) => {
                registry.mark_reconciliation(
                    &request.operation_id,
                    binding.request_sha256,
                    LeaseOperationKind::Renew,
                    ReconciliationReason::RenewOutcomeUnknown,
                )?;
                return Err(transport_error(error));
            }
        };
        match response.status() {
            StatusCode::OK => {}
            StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN => {
                registry.mark_explicit_failure(
                    &request.operation_id,
                    binding.request_sha256,
                    LeaseOperationKind::Renew,
                    LeaseFailureKind::ProviderDenied,
                )?;
                return Err(BaoLeaseError::ProviderDenied);
            }
            StatusCode::NOT_FOUND => {
                registry.mark_explicit_failure(
                    &request.operation_id,
                    binding.request_sha256,
                    LeaseOperationKind::Renew,
                    LeaseFailureKind::NotFound,
                )?;
                return Err(BaoLeaseError::NotFound);
            }
            _ => {
                registry.mark_reconciliation(
                    &request.operation_id,
                    binding.request_sha256,
                    LeaseOperationKind::Renew,
                    ReconciliationReason::RenewOutcomeUnknown,
                )?;
                return Err(BaoLeaseError::ProviderUnavailable);
            }
        }
        let body = read_bounded_body(response).await?;
        let decoded: LeaseMutationResponse =
            serde_json::from_slice(&body).map_err(|_| BaoLeaseError::InvalidResponse)?;
        if decoded.lease_id.as_str() != provider_id.as_str()
            || decoded.lease_duration == 0
            || decoded.lease_duration > MAX_LEASE_DURATION_SECONDS
        {
            registry.mark_reconciliation(
                &request.operation_id,
                binding.request_sha256,
                LeaseOperationKind::Renew,
                ReconciliationReason::RenewOutcomeUnknown,
            )?;
            return Err(BaoLeaseError::ProviderLeaseMismatch);
        }
        let expires_at_ms = expiry_from_ttl(now_ms()?, decoded.lease_duration)?;
        let lease = registry.complete_renew(
            &request.operation_id,
            binding.request_sha256,
            decoded.renewable,
            expires_at_ms,
        )?;
        Ok(BaoLeaseMutationReceipt {
            request_sha256: binding.request_sha256,
            lease: lease.metadata(),
            idempotent_replay: false,
        })
    }

    pub async fn revoke_secret_lease(
        &self,
        registry: &SecretLeaseRegistry,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoRevokeLeaseRequest,
    ) -> Result<BaoLeaseMutationReceipt, BaoLeaseError> {
        let binding = self.revoke_lease_binding(request)?;
        registry.assert_request_owner(
            request.lease_handle_sha256,
            &request.subject_id,
            &request.consumer_id,
            &request.namespace,
        )?;
        match registry.prepare_existing_operation(
            request.lease_handle_sha256,
            &request.operation_id,
            binding.request_sha256,
            LeaseOperationKind::Revoke,
            None,
        )? {
            PrepareExisting::Completed(lease) => {
                return Ok(BaoLeaseMutationReceipt {
                    request_sha256: binding.request_sha256,
                    lease: lease.metadata(),
                    idempotent_replay: true,
                });
            }
            PrepareExisting::NeedsReconciliation(reason) => {
                return Err(BaoLeaseError::ReconciliationRequired(reason));
            }
            PrepareExisting::Failed(failure) => {
                return Err(BaoLeaseError::PriorOperationFailed(failure));
            }
            PrepareExisting::New(_) | PrepareExisting::Resume(_) => {}
        }
        authority
            .claim(grant, &binding)
            .map_err(BaoLeaseError::Authority)?;
        registry.mark_dispatching(
            &request.operation_id,
            binding.request_sha256,
            LeaseOperationKind::Revoke,
        )?;
        let provider_id = registry.provider_identity(request.lease_handle_sha256)?;
        let url = system_url(self, &["leases", "revoke"])?;
        let payload = RevokePayload {
            lease_id: provider_id.as_str(),
            sync: true,
        };
        let network_request = authorized_request(
            self,
            self.client.post(url).json(&payload),
            &request.namespace,
        )?;
        let response = match network_request.send().await {
            Ok(response) => response,
            Err(error) => {
                registry.mark_reconciliation(
                    &request.operation_id,
                    binding.request_sha256,
                    LeaseOperationKind::Revoke,
                    ReconciliationReason::RevokeOutcomeUnknown,
                )?;
                return Err(transport_error(error));
            }
        };
        match response.status() {
            StatusCode::OK | StatusCode::NO_CONTENT => {
                let lease =
                    registry.complete_revoke(&request.operation_id, binding.request_sha256)?;
                Ok(BaoLeaseMutationReceipt {
                    request_sha256: binding.request_sha256,
                    lease: lease.metadata(),
                    idempotent_replay: false,
                })
            }
            StatusCode::NOT_FOUND => {
                let lease =
                    registry.complete_revoke(&request.operation_id, binding.request_sha256)?;
                Ok(BaoLeaseMutationReceipt {
                    request_sha256: binding.request_sha256,
                    lease: lease.metadata(),
                    idempotent_replay: false,
                })
            }
            StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN => {
                registry.mark_explicit_failure(
                    &request.operation_id,
                    binding.request_sha256,
                    LeaseOperationKind::Revoke,
                    LeaseFailureKind::ProviderDenied,
                )?;
                Err(BaoLeaseError::ProviderDenied)
            }
            _ => {
                registry.mark_reconciliation(
                    &request.operation_id,
                    binding.request_sha256,
                    LeaseOperationKind::Revoke,
                    ReconciliationReason::RevokeOutcomeUnknown,
                )?;
                Err(BaoLeaseError::ProviderUnavailable)
            }
        }
    }

    /// Reconciles operations whose provider lease identity is known. Lookup is
    /// read-only. A missing lease closes revoke ambiguity as revoked and other
    /// ambiguity as expired. A still-present lease after an unknown revoke
    /// remains reconciliation-required and may be revoked with a new grant.
    pub async fn reconcile_secret_lease(
        &self,
        registry: &SecretLeaseRegistry,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoReconcileLeaseRequest,
    ) -> Result<BaoLeaseMutationReceipt, BaoLeaseError> {
        let binding = self.reconcile_lease_binding(request)?;
        registry.assert_request_owner(
            request.lease_handle_sha256,
            &request.subject_id,
            &request.consumer_id,
            &request.namespace,
        )?;
        match registry.prepare_existing_operation(
            request.lease_handle_sha256,
            &request.operation_id,
            binding.request_sha256,
            LeaseOperationKind::Reconcile,
            None,
        )? {
            PrepareExisting::Completed(lease) => {
                return Ok(BaoLeaseMutationReceipt {
                    request_sha256: binding.request_sha256,
                    lease: lease.metadata(),
                    idempotent_replay: true,
                });
            }
            PrepareExisting::NeedsReconciliation(reason) => {
                return Err(BaoLeaseError::ReconciliationRequired(reason));
            }
            PrepareExisting::Failed(failure) => {
                return Err(BaoLeaseError::PriorOperationFailed(failure));
            }
            PrepareExisting::New(_) | PrepareExisting::Resume(_) => {}
        }
        let verified = authority
            .claim(grant, &binding)
            .map_err(BaoLeaseError::Authority)?;
        registry.mark_dispatching(
            &request.operation_id,
            binding.request_sha256,
            LeaseOperationKind::Reconcile,
        )?;
        let provider_id = registry.provider_identity(request.lease_handle_sha256)?;
        let url = system_url(self, &["leases", "lookup"])?;
        let payload = LeaseLookupPayload {
            lease_id: provider_id.as_str(),
        };
        let network_request = authorized_request(
            self,
            self.client.post(url).json(&payload),
            &request.namespace,
        )?;
        let response = match network_request.send().await {
            Ok(response) => response,
            Err(error) => {
                registry.mark_explicit_failure(
                    &request.operation_id,
                    binding.request_sha256,
                    LeaseOperationKind::Reconcile,
                    LeaseFailureKind::NotFound,
                )?;
                return Err(transport_error(error));
            }
        };
        match response.status() {
            StatusCode::OK => {
                let body = read_bounded_body(response).await?;
                let decoded: LeaseLookupResponse =
                    serde_json::from_slice(&body).map_err(|_| BaoLeaseError::InvalidResponse)?;
                if decoded.data.id.as_str() != provider_id.as_str()
                    || decoded.data.ttl > MAX_LEASE_DURATION_SECONDS
                {
                    registry.mark_explicit_failure(
                        &request.operation_id,
                        binding.request_sha256,
                        LeaseOperationKind::Reconcile,
                        LeaseFailureKind::NotFound,
                    )?;
                    return Err(BaoLeaseError::ProviderLeaseMismatch);
                }
                authority
                    .with_verified_use(verified, &binding, || ())
                    .map_err(BaoLeaseError::Authority)?;
                let expires_at_ms = expiry_from_ttl(now_ms()?, decoded.data.ttl)?;
                let lease = registry.complete_reconcile_present(
                    &request.operation_id,
                    binding.request_sha256,
                    decoded.data.renewable,
                    expires_at_ms,
                )?;
                Ok(BaoLeaseMutationReceipt {
                    request_sha256: binding.request_sha256,
                    lease: lease.metadata(),
                    idempotent_replay: false,
                })
            }
            StatusCode::NOT_FOUND => {
                authority
                    .with_verified_use(verified, &binding, || ())
                    .map_err(BaoLeaseError::Authority)?;
                let lease = registry.complete_reconcile_absent(
                    &request.operation_id,
                    binding.request_sha256,
                )?;
                Ok(BaoLeaseMutationReceipt {
                    request_sha256: binding.request_sha256,
                    lease: lease.metadata(),
                    idempotent_replay: false,
                })
            }
            StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN => {
                registry.mark_explicit_failure(
                    &request.operation_id,
                    binding.request_sha256,
                    LeaseOperationKind::Reconcile,
                    LeaseFailureKind::ProviderDenied,
                )?;
                Err(BaoLeaseError::ProviderDenied)
            }
            _ => {
                registry.mark_explicit_failure(
                    &request.operation_id,
                    binding.request_sha256,
                    LeaseOperationKind::Reconcile,
                    LeaseFailureKind::NotFound,
                )?;
                Err(BaoLeaseError::ProviderUnavailable)
            }
        }
    }

    /// Resolves the only generic stock-OpenBao case that cannot be queried:
    /// issuance dispatched, response lost, and lease_id never observed.
    /// The evidence digest is signed by the independent authority issuer.
    pub fn resolve_unknown_issue(
        &self,
        registry: &SecretLeaseRegistry,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        request: &BaoUnknownIssueResolutionRequest,
    ) -> Result<BaoLeaseMutationReceipt, BaoLeaseError> {
        let binding = self.unknown_issue_resolution_binding(request)?;
        registry.assert_request_owner(
            request.lease_handle_sha256,
            &request.subject_id,
            &request.consumer_id,
            &request.namespace,
        )?;
        match registry.prepare_unknown_issue_resolution(request, binding.request_sha256)? {
            PrepareExisting::Completed(lease) => {
                return Ok(BaoLeaseMutationReceipt {
                    request_sha256: binding.request_sha256,
                    lease: lease.metadata(),
                    idempotent_replay: true,
                });
            }
            PrepareExisting::NeedsReconciliation(reason) => {
                return Err(BaoLeaseError::ReconciliationRequired(reason));
            }
            PrepareExisting::Failed(failure) => {
                return Err(BaoLeaseError::PriorOperationFailed(failure));
            }
            PrepareExisting::New(_) | PrepareExisting::Resume(_) => {}
        }
        let verified = authority
            .claim(grant, &binding)
            .map_err(BaoLeaseError::Authority)?;
        let lease = authority
            .with_verified_use(verified, &binding, || {
                registry.complete_unknown_issue_resolution(
                    &request.operation_id,
                    binding.request_sha256,
                    &request.resolution,
                )
            })
            .map_err(BaoLeaseError::Authority)??;
        Ok(BaoLeaseMutationReceipt {
            request_sha256: binding.request_sha256,
            lease: lease.metadata(),
            idempotent_replay: false,
        })
    }
}

fn validate_issue_request(
    request: &BaoDynamicLeaseRequest,
) -> Result<Vec<String>, BaoLeaseError> {
    if !component(&request.subject_id)
        || !component(&request.consumer_id)
        || (!request.namespace.is_empty() && !segmented(&request.namespace))
        || !segmented(&request.mount)
        || !segmented(&request.path)
        || !component(&request.operation_id)
        || request.required_fields.is_empty()
        || request.required_fields.len() > MAX_REQUIRED_FIELDS
    {
        return Err(BaoLeaseError::InvalidRequest);
    }
    let mut fields = request.required_fields.clone();
    if fields.iter().any(|field| !component(field)) {
        return Err(BaoLeaseError::InvalidRequest);
    }
    fields.sort();
    if fields.windows(2).any(|window| window[0] == window[1]) {
        return Err(BaoLeaseError::InvalidRequest);
    }
    Ok(fields)
}

fn validate_existing_request(
    subject_id: &str,
    consumer_id: &str,
    namespace: &str,
    operation_id: &str,
    lease_handle_sha256: [u8; 32],
) -> Result<(), BaoLeaseError> {
    if !component(subject_id)
        || !component(consumer_id)
        || (!namespace.is_empty() && !segmented(namespace))
        || !component(operation_id)
        || lease_handle_sha256 == [0; 32]
    {
        return Err(BaoLeaseError::InvalidRequest);
    }
    Ok(())
}

fn issue_request_digest(
    client: &BaoClient,
    request: &BaoDynamicLeaseRequest,
    fields: &[String],
) -> Result<[u8; 32], BaoLeaseError> {
    digest_json(&(
        "hepta.bao.dynamic-lease.issue.v1",
        client.origin.as_str(),
        client.ca_sha256,
        &request.subject_id,
        &request.consumer_id,
        &request.namespace,
        &request.mount,
        &request.path,
        &request.operation_id,
        fields,
    ))
}

fn renew_request_digest(
    client: &BaoClient,
    request: &BaoRenewLeaseRequest,
) -> Result<[u8; 32], BaoLeaseError> {
    digest_json(&(
        "hepta.bao.dynamic-lease.renew.v1",
        client.origin.as_str(),
        client.ca_sha256,
        request,
    ))
}

fn revoke_request_digest(
    client: &BaoClient,
    request: &BaoRevokeLeaseRequest,
) -> Result<[u8; 32], BaoLeaseError> {
    digest_json(&(
        "hepta.bao.dynamic-lease.revoke.v1",
        client.origin.as_str(),
        client.ca_sha256,
        request,
    ))
}

fn reconcile_request_digest(
    client: &BaoClient,
    request: &BaoReconcileLeaseRequest,
) -> Result<[u8; 32], BaoLeaseError> {
    digest_json(&(
        "hepta.bao.dynamic-lease.reconcile.v1",
        client.origin.as_str(),
        client.ca_sha256,
        request,
    ))
}

fn unknown_issue_resolution_digest(
    client: &BaoClient,
    request: &BaoUnknownIssueResolutionRequest,
) -> Result<[u8; 32], BaoLeaseError> {
    let resolution_digest = match &request.resolution {
        BaoUnknownIssueResolution::ConfirmedAbsent => {
            Digest32::of_bytes(b"confirmed-absent").into_array()
        }
        BaoUnknownIssueResolution::ObservedLease(provider_id) => {
            Digest32::of_bytes(provider_id.as_str().as_bytes()).into_array()
        }
    };
    digest_json(&(
        "hepta.bao.dynamic-lease.resolve-unknown-issue.v1",
        client.origin.as_str(),
        client.ca_sha256,
        &request.subject_id,
        &request.consumer_id,
        &request.namespace,
        request.lease_handle_sha256,
        &request.operation_id,
        request.evidence_sha256,
        resolution_digest,
    ))
}

fn operation_binding(
    client: &BaoClient,
    subject_id: &str,
    consumer_id: &str,
    namespace: &str,
    operation: &str,
    request_sha256: [u8; 32],
    dynamic_path: Option<(&str, &str)>,
    lease_handle_sha256: Option<[u8; 32]>,
) -> Result<FinalUseBinding, BaoLeaseError> {
    let scope_sha256 = digest_json(&(
        "hepta.bao.dynamic-lease.scope.v1",
        client.origin.as_str(),
        client.ca_sha256,
        namespace,
        consumer_id,
        operation,
        dynamic_path,
        lease_handle_sha256,
    ))?;
    Ok(FinalUseBinding {
        subject_id: subject_id.to_owned(),
        destination_id: "provider:heptabao".to_owned(),
        request_sha256,
        scope_sha256,
        payload_sha256: request_sha256,
    })
}

fn digest_json<T: Serialize + ?Sized>(value: &T) -> Result<[u8; 32], BaoLeaseError> {
    let bytes = serde_json::to_vec(value).map_err(|_| BaoLeaseError::InvalidRequest)?;
    Ok(Digest32::of_bytes(&bytes).into_array())
}

fn lease_handle(request_sha256: [u8; 32], operation_id: &str) -> [u8; 32] {
    let mut bytes = b"hepta.bao.dynamic-lease.handle.v1\0".to_vec();
    bytes.extend_from_slice(&request_sha256);
    let operation = operation_id.as_bytes();
    bytes.extend_from_slice(&(operation.len() as u32).to_be_bytes());
    bytes.extend_from_slice(operation);
    Digest32::of_bytes(&bytes).into_array()
}

fn dynamic_url(
    client: &BaoClient,
    mount: &str,
    path: &str,
) -> Result<url::Url, BaoLeaseError> {
    let mut url = client.origin.clone();
    {
        let mut parts = url
            .path_segments_mut()
            .map_err(|_| BaoLeaseError::InvalidRequest)?;
        parts.clear().push("v1");
        for part in mount.split('/') {
            parts.push(part);
        }
        for part in path.split('/') {
            parts.push(part);
        }
    }
    Ok(url)
}

fn system_url(client: &BaoClient, path: &[&str]) -> Result<url::Url, BaoLeaseError> {
    let mut url = client.origin.clone();
    {
        let mut parts = url
            .path_segments_mut()
            .map_err(|_| BaoLeaseError::InvalidRequest)?;
        parts.clear().push("v1").push("sys");
        for part in path {
            parts.push(part);
        }
    }
    Ok(url)
}

fn authorized_request(
    client: &BaoClient,
    request: RequestBuilder,
    namespace: &str,
) -> Result<RequestBuilder, BaoLeaseError> {
    let mut token =
        HeaderValue::from_str(&client.token.0).map_err(|_| BaoLeaseError::InvalidRequest)?;
    token.set_sensitive(true);
    let mut request = request
        .header("X-Vault-Token", token)
        .header("Accept", "application/json");
    if !namespace.is_empty() {
        request = request.header("X-Vault-Namespace", namespace);
    }
    Ok(request)
}

async fn read_bounded_body(
    mut response: codex_http_client::HttpResponse,
) -> Result<Zeroizing<Vec<u8>>, BaoLeaseError> {
    if response
        .content_length()
        .is_some_and(|length| length > MAX_RESPONSE_BYTES as u64)
    {
        return Err(BaoLeaseError::ResponseTooLarge);
    }
    let mut body = Zeroizing::new(Vec::new());
    while let Some(chunk) = response.chunk().await.map_err(transport_error)? {
        if chunk.len() > MAX_RESPONSE_BYTES.saturating_sub(body.len()) {
            return Err(BaoLeaseError::ResponseTooLarge);
        }
        body.extend_from_slice(&chunk);
    }
    Ok(body)
}

fn transport_error(error: codex_http_client::HttpError) -> BaoLeaseError {
    if error.is_timeout() {
        BaoLeaseError::TimedOut
    } else {
        BaoLeaseError::TransportUnavailable
    }
}

fn now_ms() -> Result<u64, BaoLeaseError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| BaoLeaseError::ProviderUnavailable)?
        .as_millis();
    u64::try_from(millis).map_err(|_| BaoLeaseError::ProviderUnavailable)
}

fn now_ms_registry() -> Result<u64, LeaseRegistryError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| LeaseRegistryError::Unavailable)?
        .as_millis();
    u64::try_from(millis).map_err(|_| LeaseRegistryError::Unavailable)
}

fn expiry_from_ttl(now_ms: u64, ttl_seconds: u64) -> Result<u64, BaoLeaseError> {
    ttl_seconds
        .checked_mul(1000)
        .and_then(|ttl_ms| now_ms.checked_add(ttl_ms))
        .ok_or(BaoLeaseError::InvalidResponse)
}

fn component(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value != "."
        && value != ".."
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:".contains(&byte))
}

fn segmented(value: &str) -> bool {
    !value.is_empty() && value.len() <= 1024 && value.split('/').all(component)
}

fn provider_lease_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= MAX_PROVIDER_LEASE_ID_BYTES
        && value.bytes().all(|byte| byte.is_ascii_graphic())
}

#[derive(Deserialize)]
struct DynamicLeaseResponse {
    lease_id: Zeroizing<String>,
    lease_duration: u64,
    renewable: bool,
    data: BTreeMap<String, SecretValue>,
}

#[derive(Deserialize)]
#[serde(untagged)]
enum SecretValue {
    String(Zeroizing<String>),
    Bool(bool),
    Number(serde_json::Number),
    Array(Vec<SecretValue>),
    Object(BTreeMap<String, SecretValue>),
    Null(()),
}

#[derive(Deserialize)]
struct LeaseMutationResponse {
    lease_id: Zeroizing<String>,
    lease_duration: u64,
    renewable: bool,
}

#[derive(Deserialize)]
struct LeaseLookupResponse {
    data: LeaseLookupData,
}

#[derive(Deserialize)]
struct LeaseLookupData {
    id: Zeroizing<String>,
    ttl: u64,
    renewable: bool,
}

#[derive(Serialize)]
struct RenewPayload<'a> {
    lease_id: &'a str,
    increment: u64,
}

#[derive(Serialize)]
struct RevokePayload<'a> {
    lease_id: &'a str,
    sync: bool,
}

#[derive(Serialize)]
struct LeaseLookupPayload<'a> {
    lease_id: &'a str,
}

enum Access {
    Create,
    Append,
}

#[cfg(unix)]
fn prepare_directory(root: &Path) -> Result<File, LeaseRegistryError> {
    use std::os::unix::fs::DirBuilderExt;
    use std::os::unix::fs::MetadataExt;

    if let Err(error) = std::fs::DirBuilder::new().mode(0o700).create(root)
        && error.kind() != std::io::ErrorKind::AlreadyExists
    {
        return Err(LeaseRegistryError::Unavailable);
    }
    let directory: File = rustix::fs::open(
        root,
        rustix::fs::OFlags::RDONLY
            | rustix::fs::OFlags::DIRECTORY
            | rustix::fs::OFlags::NOFOLLOW
            | rustix::fs::OFlags::CLOEXEC,
        rustix::fs::Mode::empty(),
    )
    .map_err(|_| LeaseRegistryError::UnsafeStateDirectory)?
    .into();
    let metadata = directory
        .metadata()
        .map_err(|_| LeaseRegistryError::Unavailable)?;
    if !metadata.is_dir()
        || metadata.mode() & 0o077 != 0
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(LeaseRegistryError::UnsafeStateDirectory);
    }
    Ok(directory)
}

#[cfg(unix)]
fn open_private(
    directory: &File,
    name: &str,
    access: Access,
) -> Result<File, LeaseRegistryError> {
    use std::os::unix::fs::MetadataExt;
    use rustix::fs::Mode;
    use rustix::fs::OFlags;

    let flags = match access {
        Access::Create => OFlags::RDWR | OFlags::CREATE,
        Access::Append => OFlags::RDWR | OFlags::CREATE | OFlags::APPEND,
    } | OFlags::NOFOLLOW
        | OFlags::CLOEXEC;
    let file: File = rustix::fs::openat(directory, name, flags, Mode::RUSR | Mode::WUSR)
        .map_err(|_| LeaseRegistryError::Unavailable)?
        .into();
    let metadata = file
        .metadata()
        .map_err(|_| LeaseRegistryError::Unavailable)?;
    if !metadata.is_file()
        || metadata.mode() & 0o077 != 0
        || metadata.nlink() != 1
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(LeaseRegistryError::UnsafeStateDirectory);
    }
    Ok(file)
}

#[cfg(unix)]
fn entry_exists(directory: &File, name: &str) -> Result<bool, LeaseRegistryError> {
    match rustix::fs::statat(directory, name, rustix::fs::AtFlags::SYMLINK_NOFOLLOW) {
        Ok(_) => Ok(true),
        Err(rustix::io::Errno::NOENT) => Ok(false),
        Err(_) => Err(LeaseRegistryError::Unavailable),
    }
}

#[cfg(not(unix))]
fn prepare_directory(_root: &Path) -> Result<File, LeaseRegistryError> {
    Err(LeaseRegistryError::UnsafeStateDirectory)
}

#[cfg(not(unix))]
fn open_private(
    _directory: &File,
    _name: &str,
    _access: Access,
) -> Result<File, LeaseRegistryError> {
    Err(LeaseRegistryError::UnsafeStateDirectory)
}

#[cfg(not(unix))]
fn entry_exists(_directory: &File, _name: &str) -> Result<bool, LeaseRegistryError> {
    Err(LeaseRegistryError::UnsafeStateDirectory)
}

#[cfg(all(test, unix))]
#[path = "lease_lifecycle_tests.rs"]
mod tests;
