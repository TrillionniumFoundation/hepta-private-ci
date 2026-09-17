use std::collections::BTreeMap;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

use codex_hepta_contracts::FinalUseBinding;
use serde::Deserialize;
use serde::Serialize;

use crate::lease_types::DynamicSecretLeaseRequest;
use crate::lease_types::LeaseOperationKind;
use crate::lease_types::LeaseOperationObservation;
use crate::lease_types::LeaseOperationState;
use crate::lease_types::MAX_LEASE_OPERATIONS;
use crate::lease_types::MAX_LEASE_RECORDS;
use crate::lease_types::MAX_LEASE_REGISTRY_BYTES;
use crate::lease_types::SECRET_LEASE_SCHEMA_VERSION;
use crate::lease_types::SecretLeaseError;
use crate::lease_types::SecretLeaseMetadata;
use crate::lease_types::SecretLeaseState;
use crate::lease_types::UnknownIssueResolution;
use crate::lease_types::UnknownIssueResolutionRequest;
use crate::lease_types::valid_lease_id;
use crate::lease_types::valid_operation_id;

const STATE_FILE: &str = "lease-registry.json";
const NEXT_FILE: &str = "lease-registry.next";
const LOCK_FILE: &str = "lease-registry.lock";

#[derive(Clone)]
pub struct SecretLeaseRegistry {
    inner: Arc<RegistryInner>,
}

struct RegistryInner {
    root: PathBuf,
    _lock: File,
    state: Mutex<RegistryState>,
    unavailable: AtomicBool,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct RegistryState {
    schema_version: u32,
    leases: BTreeMap<String, SecretLeaseMetadata>,
    operations: BTreeMap<String, OperationRecord>,
}

impl Default for RegistryState {
    fn default() -> Self {
        Self {
            schema_version: SECRET_LEASE_SCHEMA_VERSION,
            leases: BTreeMap::new(),
            operations: BTreeMap::new(),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct OperationRecord {
    operation_id: String,
    kind: LeaseOperationKind,
    state: LeaseOperationState,
    lease_id: Option<String>,
    request_sha256: [u8; 32],
    updated_at_unix_ms: u64,
    prior_lease_state: Option<SecretLeaseState>,
    issue_context: Option<IssueContext>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct IssueContext {
    request: DynamicSecretLeaseRequest,
    scope_sha256: [u8; 32],
}

impl SecretLeaseRegistry {
    pub fn open_state_dir(path: impl AsRef<Path>) -> Result<Self, SecretLeaseError> {
        let root = path.as_ref().to_path_buf();
        prepare_directory(&root)?;

        let lock_path = root.join(LOCK_FILE);
        let lock_preexisted = lock_path.exists();
        if lock_preexisted
            && fs::symlink_metadata(&lock_path).is_ok_and(|metadata| metadata.file_type().is_symlink())
        {
            return Err(SecretLeaseError::StateDirectoryUnsafe);
        }
        let lock = open_private_file(&lock_path, true, false)?;
        match lock.try_lock() {
            Ok(()) => {}
            Err(TryLockError::WouldBlock) => return Err(SecretLeaseError::StateLocked),
            Err(TryLockError::Error(_)) => return Err(SecretLeaseError::Storage),
        }

        let state_path = root.join(STATE_FILE);
        let state = if state_path.exists() {
            load_state(&state_path)?
        } else if lock_preexisted {
            return Err(SecretLeaseError::StateCorrupt);
        } else {
            RegistryState::default()
        };
        validate_state(&state)?;

        let registry = Self {
            inner: Arc::new(RegistryInner {
                root,
                _lock: lock,
                state: Mutex::new(state),
                unavailable: AtomicBool::new(false),
            }),
        };
        if !state_path.exists() {
            let snapshot = registry.snapshot()?;
            registry.persist(&snapshot)?;
        }
        Ok(registry)
    }

    pub fn lease(&self, lease_id: &str) -> Result<Option<SecretLeaseMetadata>, SecretLeaseError> {
        self.ensure_available()?;
        let state = self
            .inner
            .state
            .lock()
            .map_err(|_| SecretLeaseError::StateUnavailable)?;
        Ok(state.leases.get(lease_id).cloned())
    }

    pub fn operation(
        &self,
        operation_id: &str,
    ) -> Result<Option<LeaseOperationObservation>, SecretLeaseError> {
        self.ensure_available()?;
        let state = self
            .inner
            .state
            .lock()
            .map_err(|_| SecretLeaseError::StateUnavailable)?;
        Ok(state.operations.get(operation_id).map(observation))
    }

    pub(crate) fn preflight_operation(
        &self,
        operation_id: &str,
        request_sha256: [u8; 32],
    ) -> Result<(), SecretLeaseError> {
        self.ensure_available()?;
        let state = self
            .inner
            .state
            .lock()
            .map_err(|_| SecretLeaseError::StateUnavailable)?;
        check_operation_slot(&state, operation_id, request_sha256)
    }

    pub(crate) fn reserve_issue(
        &self,
        request: DynamicSecretLeaseRequest,
        binding: &FinalUseBinding,
        now_ms: u64,
    ) -> Result<(), SecretLeaseError> {
        self.mutate(|state| {
            check_operation_slot(state, &request.operation_id, binding.request_sha256)?;
            ensure_operation_capacity(state)?;
            state.operations.insert(
                request.operation_id.clone(),
                OperationRecord {
                    operation_id: request.operation_id.clone(),
                    kind: LeaseOperationKind::Issue,
                    state: LeaseOperationState::OutcomeUnknown,
                    lease_id: None,
                    request_sha256: binding.request_sha256,
                    updated_at_unix_ms: now_ms,
                    prior_lease_state: None,
                    issue_context: Some(IssueContext {
                        request,
                        scope_sha256: binding.scope_sha256,
                    }),
                },
            );
            Ok(())
        })
    }

    pub(crate) fn touch_unknown(
        &self,
        operation_id: &str,
        now_ms: u64,
    ) -> Result<(), SecretLeaseError> {
        self.mutate(|state| {
            let operation = state
                .operations
                .get_mut(operation_id)
                .ok_or(SecretLeaseError::StateCorrupt)?;
            if operation.state != LeaseOperationState::OutcomeUnknown {
                return Err(SecretLeaseError::StateCorrupt);
            }
            operation.updated_at_unix_ms = now_ms;
            Ok(())
        })
    }

    pub(crate) fn reject_issue(
        &self,
        operation_id: &str,
        now_ms: u64,
    ) -> Result<(), SecretLeaseError> {
        self.mutate(|state| {
            let operation = state
                .operations
                .get_mut(operation_id)
                .ok_or(SecretLeaseError::StateCorrupt)?;
            if operation.kind != LeaseOperationKind::Issue
                || operation.state != LeaseOperationState::OutcomeUnknown
            {
                return Err(SecretLeaseError::StateCorrupt);
            }
            operation.state = LeaseOperationState::Rejected;
            operation.updated_at_unix_ms = now_ms;
            Ok(())
        })
    }

    pub(crate) fn complete_issue(
        &self,
        metadata: SecretLeaseMetadata,
        now_ms: u64,
    ) -> Result<(), SecretLeaseError> {
        self.mutate(|state| {
            if state.leases.len() >= MAX_LEASE_RECORDS && !state.leases.contains_key(&metadata.lease_id) {
                return Err(SecretLeaseError::CapacityExceeded);
            }
            let operation = state
                .operations
                .get(&metadata.issued_operation_id)
                .ok_or(SecretLeaseError::StateCorrupt)?;
            if operation.kind != LeaseOperationKind::Issue
                || operation.state != LeaseOperationState::OutcomeUnknown
                || operation.request_sha256 != metadata.request_sha256
            {
                return Err(SecretLeaseError::StateCorrupt);
            }
            if state
                .leases
                .get(&metadata.lease_id)
                .is_some_and(|existing| existing != &metadata)
            {
                return Err(SecretLeaseError::OperationConflict);
            }
            let operation = state
                .operations
                .get_mut(&metadata.issued_operation_id)
                .ok_or(SecretLeaseError::StateCorrupt)?;
            operation.state = LeaseOperationState::Completed;
            operation.lease_id = Some(metadata.lease_id.clone());
            operation.updated_at_unix_ms = now_ms;
            state.leases.insert(metadata.lease_id.clone(), metadata);
            Ok(())
        })
    }

    pub(crate) fn begin_renew(
        &self,
        operation_id: &str,
        request_sha256: [u8; 32],
        lease_id: &str,
        subject_id: &str,
        consumer_id: &str,
        now_ms: u64,
    ) -> Result<SecretLeaseMetadata, SecretLeaseError> {
        self.begin_lease_mutation(
            LeaseOperationKind::Renew,
            SecretLeaseState::RenewOutcomeUnknown,
            operation_id,
            request_sha256,
            lease_id,
            subject_id,
            consumer_id,
            now_ms,
            |state| state == SecretLeaseState::Active,
        )
    }

    pub(crate) fn begin_revoke(
        &self,
        operation_id: &str,
        request_sha256: [u8; 32],
        lease_id: &str,
        subject_id: &str,
        consumer_id: &str,
        now_ms: u64,
    ) -> Result<SecretLeaseMetadata, SecretLeaseError> {
        self.begin_lease_mutation(
            LeaseOperationKind::Revoke,
            SecretLeaseState::RevokeOutcomeUnknown,
            operation_id,
            request_sha256,
            lease_id,
            subject_id,
            consumer_id,
            now_ms,
            |state| {
                matches!(
                    state,
                    SecretLeaseState::Active
                        | SecretLeaseState::RenewOutcomeUnknown
                        | SecretLeaseState::RevokeRequired
                )
            },
        )
    }

    fn begin_lease_mutation(
        &self,
        kind: LeaseOperationKind,
        in_flight_state: SecretLeaseState,
        operation_id: &str,
        request_sha256: [u8; 32],
        lease_id: &str,
        subject_id: &str,
        consumer_id: &str,
        now_ms: u64,
        allowed: impl FnOnce(SecretLeaseState) -> bool,
    ) -> Result<SecretLeaseMetadata, SecretLeaseError> {
        self.mutate(|state| {
            check_operation_slot(state, operation_id, request_sha256)?;
            ensure_operation_capacity(state)?;
            let prior = {
                let lease = state
                    .leases
                    .get(lease_id)
                    .ok_or(SecretLeaseError::LeaseNotFound)?;
                if lease.subject_id != subject_id || lease.consumer_id != consumer_id {
                    return Err(SecretLeaseError::LeaseIdentityMismatch);
                }
                if !allowed(lease.state) {
                    return Err(SecretLeaseError::LeaseNotActive);
                }
                if kind == LeaseOperationKind::Renew && !lease.renewable {
                    return Err(SecretLeaseError::LeaseNotRenewable);
                }
                lease.state
            };
            let current = {
                let lease = state
                    .leases
                    .get_mut(lease_id)
                    .ok_or(SecretLeaseError::StateCorrupt)?;
                lease.state = in_flight_state;
                lease.last_operation_id = operation_id.to_owned();
                lease.observed_at_unix_ms = now_ms;
                lease.clone()
            };
            state.operations.insert(
                operation_id.to_owned(),
                OperationRecord {
                    operation_id: operation_id.to_owned(),
                    kind,
                    state: LeaseOperationState::OutcomeUnknown,
                    lease_id: Some(lease_id.to_owned()),
                    request_sha256,
                    updated_at_unix_ms: now_ms,
                    prior_lease_state: Some(prior),
                    issue_context: None,
                },
            );
            Ok(current)
        })
    }

    pub(crate) fn reject_lease_mutation(
        &self,
        operation_id: &str,
        now_ms: u64,
    ) -> Result<SecretLeaseMetadata, SecretLeaseError> {
        self.mutate(|state| {
            let (lease_id, prior) = mutation_context(state, operation_id)?;
            let current = {
                let lease = state
                    .leases
                    .get_mut(&lease_id)
                    .ok_or(SecretLeaseError::StateCorrupt)?;
                lease.state = prior;
                lease.observed_at_unix_ms = now_ms;
                lease.clone()
            };
            let operation = state
                .operations
                .get_mut(operation_id)
                .ok_or(SecretLeaseError::StateCorrupt)?;
            operation.state = LeaseOperationState::Rejected;
            operation.updated_at_unix_ms = now_ms;
            Ok(current)
        })
    }

    pub(crate) fn complete_renew(
        &self,
        operation_id: &str,
        lease_duration_seconds: u64,
        renewable: bool,
        now_ms: u64,
    ) -> Result<SecretLeaseMetadata, SecretLeaseError> {
        self.mutate(|state| {
            let lease_id = operation_lease_id(state, operation_id, LeaseOperationKind::Renew)?;
            let current = {
                let lease = state
                    .leases
                    .get_mut(&lease_id)
                    .ok_or(SecretLeaseError::StateCorrupt)?;
                lease.state = if lease_duration_seconds == 0
                    || lease_duration_seconds > lease.max_lease_duration_seconds
                {
                    SecretLeaseState::RevokeRequired
                } else {
                    SecretLeaseState::Active
                };
                lease.renewable = renewable;
                lease.lease_duration_seconds = lease_duration_seconds;
                lease.observed_at_unix_ms = now_ms;
                lease.expires_at_unix_ms = expiry(now_ms, lease_duration_seconds)?;
                lease.rotation_generation = lease
                    .rotation_generation
                    .checked_add(1)
                    .ok_or(SecretLeaseError::StateCorrupt)?;
                lease.last_operation_id = operation_id.to_owned();
                lease.clone()
            };
            complete_operation(state, operation_id, LeaseOperationState::Completed, now_ms)?;
            Ok(current)
        })
    }

    pub(crate) fn complete_provider_absent_mutation(
        &self,
        operation_id: &str,
        now_ms: u64,
    ) -> Result<SecretLeaseMetadata, SecretLeaseError> {
        self.mutate(|state| {
            let operation = state
                .operations
                .get(operation_id)
                .ok_or(SecretLeaseError::StateCorrupt)?;
            if operation.state != LeaseOperationState::OutcomeUnknown
                || !matches!(operation.kind, LeaseOperationKind::Renew | LeaseOperationKind::Revoke)
            {
                return Err(SecretLeaseError::StateCorrupt);
            }
            let lease_id = operation
                .lease_id
                .clone()
                .ok_or(SecretLeaseError::StateCorrupt)?;
            let current = terminalize_lease(
                state,
                &lease_id,
                operation_id,
                SecretLeaseState::ProviderAbsent,
                now_ms,
            )?;
            complete_operation(state, operation_id, LeaseOperationState::Completed, now_ms)?;
            Ok(current)
        })
    }

    pub(crate) fn complete_revoke(
        &self,
        operation_id: &str,
        now_ms: u64,
    ) -> Result<SecretLeaseMetadata, SecretLeaseError> {
        self.mutate(|state| {
            let lease_id = operation_lease_id(state, operation_id, LeaseOperationKind::Revoke)?;
            let current = terminalize_lease(
                state,
                &lease_id,
                operation_id,
                SecretLeaseState::Revoked,
                now_ms,
            )?;
            complete_operation(state, operation_id, LeaseOperationState::Completed, now_ms)?;
            Ok(current)
        })
    }

    pub(crate) fn reconcile_active(
        &self,
        operation_id: &str,
        target_operation_id: &str,
        request_sha256: [u8; 32],
        lease_id: &str,
        subject_id: &str,
        consumer_id: &str,
        lease_duration_seconds: u64,
        renewable: bool,
        now_ms: u64,
    ) -> Result<SecretLeaseMetadata, SecretLeaseError> {
        self.mutate(|state| {
            check_operation_slot(state, operation_id, request_sha256)?;
            ensure_operation_capacity(state)?;
            validate_reconciliation_target(state, target_operation_id, lease_id)?;
            validate_reconcilable_lease(state, target_operation_id, lease_id, subject_id, consumer_id)?;

            let current = {
                let lease = state
                    .leases
                    .get_mut(lease_id)
                    .ok_or(SecretLeaseError::LeaseNotFound)?;
                lease.state = if lease_duration_seconds == 0
                    || lease_duration_seconds > lease.max_lease_duration_seconds
                {
                    SecretLeaseState::RevokeRequired
                } else {
                    SecretLeaseState::Active
                };
                lease.renewable = renewable;
                lease.lease_duration_seconds = lease_duration_seconds;
                lease.observed_at_unix_ms = now_ms;
                lease.expires_at_unix_ms = expiry(now_ms, lease_duration_seconds)?;
                lease.rotation_generation = lease
                    .rotation_generation
                    .checked_add(1)
                    .ok_or(SecretLeaseError::StateCorrupt)?;
                lease.last_operation_id = operation_id.to_owned();
                lease.clone()
            };
            complete_operation(
                state,
                target_operation_id,
                LeaseOperationState::Reconciled,
                now_ms,
            )?;
            insert_reconcile_operation(
                state,
                operation_id,
                target_operation_id,
                lease_id,
                request_sha256,
                now_ms,
            );
            Ok(current)
        })
    }

    pub(crate) fn reconcile_absent(
        &self,
        operation_id: &str,
        target_operation_id: &str,
        request_sha256: [u8; 32],
        lease_id: &str,
        subject_id: &str,
        consumer_id: &str,
        now_ms: u64,
    ) -> Result<SecretLeaseMetadata, SecretLeaseError> {
        self.mutate(|state| {
            check_operation_slot(state, operation_id, request_sha256)?;
            ensure_operation_capacity(state)?;
            validate_reconciliation_target(state, target_operation_id, lease_id)?;
            validate_reconcilable_lease(state, target_operation_id, lease_id, subject_id, consumer_id)?;

            let current = terminalize_lease(
                state,
                lease_id,
                operation_id,
                SecretLeaseState::ProviderAbsent,
                now_ms,
            )?;
            complete_operation(
                state,
                target_operation_id,
                LeaseOperationState::Reconciled,
                now_ms,
            )?;
            insert_reconcile_operation(
                state,
                operation_id,
                target_operation_id,
                lease_id,
                request_sha256,
                now_ms,
            );
            Ok(current)
        })
    }

    pub(crate) fn validate_unknown_issue_resolution(
        &self,
        request: &UnknownIssueResolutionRequest,
        resolution_request_sha256: [u8; 32],
    ) -> Result<(), SecretLeaseError> {
        self.ensure_available()?;
        let state = self
            .inner
            .state
            .lock()
            .map_err(|_| SecretLeaseError::StateUnavailable)?;
        check_operation_slot(
            &state,
            &request.resolution_operation_id,
            resolution_request_sha256,
        )?;
        let issue = state
            .operations
            .get(&request.issue_operation_id)
            .ok_or(SecretLeaseError::ReconciliationRequired)?;
        if issue.kind != LeaseOperationKind::Issue
            || issue.state != LeaseOperationState::OutcomeUnknown
        {
            return Err(SecretLeaseError::OperationAlreadyTerminal);
        }
        let context = issue
            .issue_context
            .as_ref()
            .ok_or(SecretLeaseError::StateCorrupt)?;
        if context.request.subject_id != request.subject_id
            || context.request.consumer_id != request.consumer_id
        {
            return Err(SecretLeaseError::LeaseIdentityMismatch);
        }
        Ok(())
    }

    pub(crate) fn resolve_unknown_issue(
        &self,
        request: &UnknownIssueResolutionRequest,
        resolution_request_sha256: [u8; 32],
        now_ms: u64,
    ) -> Result<Option<SecretLeaseMetadata>, SecretLeaseError> {
        self.mutate(|state| {
            check_operation_slot(
                state,
                &request.resolution_operation_id,
                resolution_request_sha256,
            )?;
            ensure_operation_capacity(state)?;
            let context = {
                let issue = state
                    .operations
                    .get(&request.issue_operation_id)
                    .ok_or(SecretLeaseError::ReconciliationRequired)?;
                if issue.kind != LeaseOperationKind::Issue
                    || issue.state != LeaseOperationState::OutcomeUnknown
                {
                    return Err(SecretLeaseError::OperationAlreadyTerminal);
                }
                issue
                    .issue_context
                    .clone()
                    .ok_or(SecretLeaseError::StateCorrupt)?
            };
            if context.request.subject_id != request.subject_id
                || context.request.consumer_id != request.consumer_id
            {
                return Err(SecretLeaseError::LeaseIdentityMismatch);
            }

            let adopted = match &request.resolution {
                UnknownIssueResolution::NoLeaseObserved => {
                    complete_operation(
                        state,
                        &request.issue_operation_id,
                        LeaseOperationState::ResolvedNoLease,
                        now_ms,
                    )?;
                    None
                }
                UnknownIssueResolution::LeaseObserved {
                    lease_id,
                    lease_duration_seconds,
                    renewable,
                } => {
                    if !valid_lease_id(lease_id) || *lease_duration_seconds == 0 {
                        return Err(SecretLeaseError::InvalidRequest);
                    }
                    if state.leases.len() >= MAX_LEASE_RECORDS
                        && !state.leases.contains_key(lease_id)
                    {
                        return Err(SecretLeaseError::CapacityExceeded);
                    }
                    let issue_request_sha256 = state
                        .operations
                        .get(&request.issue_operation_id)
                        .ok_or(SecretLeaseError::StateCorrupt)?
                        .request_sha256;
                    let metadata = SecretLeaseMetadata {
                        schema_version: SECRET_LEASE_SCHEMA_VERSION,
                        lease_id: lease_id.clone(),
                        subject_id: context.request.subject_id.clone(),
                        consumer_id: context.request.consumer_id.clone(),
                        issued_operation_id: request.issue_operation_id.clone(),
                        last_operation_id: request.resolution_operation_id.clone(),
                        namespace: context.request.namespace.clone(),
                        mount: context.request.mount.clone(),
                        path: context.request.path.clone(),
                        secret_fields: context.request.secret_fields.clone(),
                        renewable: *renewable,
                        lease_duration_seconds: *lease_duration_seconds,
                        max_lease_duration_seconds: context.request.max_lease_duration_seconds,
                        observed_at_unix_ms: now_ms,
                        expires_at_unix_ms: expiry(now_ms, *lease_duration_seconds)?,
                        rotation_generation: 1,
                        state: SecretLeaseState::RevokeRequired,
                        request_sha256: issue_request_sha256,
                        scope_sha256: context.scope_sha256,
                    };
                    if state
                        .leases
                        .get(lease_id)
                        .is_some_and(|existing| existing != &metadata)
                    {
                        return Err(SecretLeaseError::OperationConflict);
                    }
                    state.leases.insert(lease_id.clone(), metadata.clone());
                    let issue = state
                        .operations
                        .get_mut(&request.issue_operation_id)
                        .ok_or(SecretLeaseError::StateCorrupt)?;
                    issue.state = LeaseOperationState::Completed;
                    issue.lease_id = Some(lease_id.clone());
                    issue.updated_at_unix_ms = now_ms;
                    Some(metadata)
                }
            };

            state.operations.insert(
                request.resolution_operation_id.clone(),
                OperationRecord {
                    operation_id: request.resolution_operation_id.clone(),
                    kind: LeaseOperationKind::ResolveUnknownIssue,
                    state: LeaseOperationState::Completed,
                    lease_id: adopted.as_ref().map(|lease| lease.lease_id.clone()),
                    request_sha256: resolution_request_sha256,
                    updated_at_unix_ms: now_ms,
                    prior_lease_state: None,
                    issue_context: None,
                },
            );
            Ok(adopted)
        })
    }

    fn snapshot(&self) -> Result<RegistryState, SecretLeaseError> {
        self.ensure_available()?;
        self.inner
            .state
            .lock()
            .map(|state| state.clone())
            .map_err(|_| SecretLeaseError::StateUnavailable)
    }

    fn mutate<T>(
        &self,
        mutate: impl FnOnce(&mut RegistryState) -> Result<T, SecretLeaseError>,
    ) -> Result<T, SecretLeaseError> {
        self.ensure_available()?;
        let mut guard = self.inner.state.lock().map_err(|_| {
            self.inner.unavailable.store(true, Ordering::Release);
            SecretLeaseError::StateUnavailable
        })?;
        let mut next = guard.clone();
        let result = mutate(&mut next)?;
        validate_state(&next)?;
        if let Err(error) = self.persist(&next) {
            self.inner.unavailable.store(true, Ordering::Release);
            return Err(error);
        }
        *guard = next;
        Ok(result)
    }

    fn persist(&self, state: &RegistryState) -> Result<(), SecretLeaseError> {
        persist_state(&self.inner.root, state)
    }

    fn ensure_available(&self) -> Result<(), SecretLeaseError> {
        if self.inner.unavailable.load(Ordering::Acquire) {
            Err(SecretLeaseError::StateUnavailable)
        } else {
            Ok(())
        }
    }
}

fn observation(record: &OperationRecord) -> LeaseOperationObservation {
    LeaseOperationObservation {
        operation_id: record.operation_id.clone(),
        kind: record.kind,
        state: record.state,
        lease_id: record.lease_id.clone(),
        request_sha256: record.request_sha256,
        updated_at_unix_ms: record.updated_at_unix_ms,
    }
}

fn ensure_operation_capacity(state: &RegistryState) -> Result<(), SecretLeaseError> {
    if state.operations.len() >= MAX_LEASE_OPERATIONS {
        Err(SecretLeaseError::CapacityExceeded)
    } else {
        Ok(())
    }
}

fn check_operation_slot(
    state: &RegistryState,
    operation_id: &str,
    request_sha256: [u8; 32],
) -> Result<(), SecretLeaseError> {
    if !valid_operation_id(operation_id) || request_sha256 == [0; 32] {
        return Err(SecretLeaseError::InvalidRequest);
    }
    let Some(existing) = state.operations.get(operation_id) else {
        return Ok(());
    };
    if existing.request_sha256 != request_sha256 {
        return Err(SecretLeaseError::OperationConflict);
    }
    match existing.state {
        LeaseOperationState::OutcomeUnknown => Err(SecretLeaseError::ReconciliationRequired),
        LeaseOperationState::Completed => Err(SecretLeaseError::OperationAlreadyCompleted),
        LeaseOperationState::Reconciled
        | LeaseOperationState::Rejected
        | LeaseOperationState::ResolvedNoLease => Err(SecretLeaseError::OperationAlreadyTerminal),
    }
}

fn mutation_context(
    state: &RegistryState,
    operation_id: &str,
) -> Result<(String, SecretLeaseState), SecretLeaseError> {
    let operation = state
        .operations
        .get(operation_id)
        .ok_or(SecretLeaseError::StateCorrupt)?;
    if operation.state != LeaseOperationState::OutcomeUnknown
        || !matches!(operation.kind, LeaseOperationKind::Renew | LeaseOperationKind::Revoke)
    {
        return Err(SecretLeaseError::StateCorrupt);
    }
    Ok((
        operation
            .lease_id
            .clone()
            .ok_or(SecretLeaseError::StateCorrupt)?,
        operation
            .prior_lease_state
            .ok_or(SecretLeaseError::StateCorrupt)?,
    ))
}

fn operation_lease_id(
    state: &RegistryState,
    operation_id: &str,
    kind: LeaseOperationKind,
) -> Result<String, SecretLeaseError> {
    let operation = state
        .operations
        .get(operation_id)
        .ok_or(SecretLeaseError::StateCorrupt)?;
    if operation.kind != kind || operation.state != LeaseOperationState::OutcomeUnknown {
        return Err(SecretLeaseError::StateCorrupt);
    }
    operation
        .lease_id
        .clone()
        .ok_or(SecretLeaseError::StateCorrupt)
}

fn complete_operation(
    state: &mut RegistryState,
    operation_id: &str,
    terminal_state: LeaseOperationState,
    now_ms: u64,
) -> Result<(), SecretLeaseError> {
    let operation = state
        .operations
        .get_mut(operation_id)
        .ok_or(SecretLeaseError::StateCorrupt)?;
    operation.state = terminal_state;
    operation.updated_at_unix_ms = now_ms;
    Ok(())
}

fn terminalize_lease(
    state: &mut RegistryState,
    lease_id: &str,
    operation_id: &str,
    terminal_state: SecretLeaseState,
    now_ms: u64,
) -> Result<SecretLeaseMetadata, SecretLeaseError> {
    let lease = state
        .leases
        .get_mut(lease_id)
        .ok_or(SecretLeaseError::StateCorrupt)?;
    lease.state = terminal_state;
    lease.renewable = false;
    lease.lease_duration_seconds = 0;
    lease.observed_at_unix_ms = now_ms;
    lease.expires_at_unix_ms = now_ms;
    lease.rotation_generation = lease
        .rotation_generation
        .checked_add(1)
        .ok_or(SecretLeaseError::StateCorrupt)?;
    lease.last_operation_id = operation_id.to_owned();
    Ok(lease.clone())
}

fn validate_reconciliation_target(
    state: &RegistryState,
    target_operation_id: &str,
    lease_id: &str,
) -> Result<LeaseOperationKind, SecretLeaseError> {
    let operation = state
        .operations
        .get(target_operation_id)
        .ok_or(SecretLeaseError::ReconciliationRequired)?;
    if operation.state != LeaseOperationState::OutcomeUnknown
        || !matches!(operation.kind, LeaseOperationKind::Renew | LeaseOperationKind::Revoke)
        || operation.lease_id.as_deref() != Some(lease_id)
    {
        return Err(SecretLeaseError::ReconciliationRequired);
    }
    Ok(operation.kind)
}

fn validate_reconcilable_lease(
    state: &RegistryState,
    target_operation_id: &str,
    lease_id: &str,
    subject_id: &str,
    consumer_id: &str,
) -> Result<(), SecretLeaseError> {
    let target_kind = validate_reconciliation_target(state, target_operation_id, lease_id)?;
    let lease = state
        .leases
        .get(lease_id)
        .ok_or(SecretLeaseError::LeaseNotFound)?;
    if lease.subject_id != subject_id || lease.consumer_id != consumer_id {
        return Err(SecretLeaseError::LeaseIdentityMismatch);
    }
    let expected = match target_kind {
        LeaseOperationKind::Renew => SecretLeaseState::RenewOutcomeUnknown,
        LeaseOperationKind::Revoke => SecretLeaseState::RevokeOutcomeUnknown,
        _ => return Err(SecretLeaseError::StateCorrupt),
    };
    if lease.state != expected {
        return Err(SecretLeaseError::ReconciliationRequired);
    }
    Ok(())
}

fn insert_reconcile_operation(
    state: &mut RegistryState,
    operation_id: &str,
    target_operation_id: &str,
    lease_id: &str,
    request_sha256: [u8; 32],
    now_ms: u64,
) {
    state.operations.insert(
        operation_id.to_owned(),
        OperationRecord {
            operation_id: operation_id.to_owned(),
            kind: LeaseOperationKind::Reconcile,
            state: LeaseOperationState::Completed,
            lease_id: Some(lease_id.to_owned()),
            request_sha256,
            updated_at_unix_ms: now_ms,
            prior_lease_state: None,
            // Reconcile operations are linked through the binding and the target
            // operation's transition to `Reconciled`; no secret/request body is stored.
            issue_context: None,
        },
    );
    debug_assert!(state.operations.contains_key(target_operation_id));
}

fn expiry(now_ms: u64, ttl_seconds: u64) -> Result<u64, SecretLeaseError> {
    ttl_seconds
        .checked_mul(1000)
        .and_then(|delta| now_ms.checked_add(delta))
        .ok_or(SecretLeaseError::InvalidResponse)
}

fn prepare_directory(root: &Path) -> Result<(), SecretLeaseError> {
    if root.exists() {
        let metadata = fs::symlink_metadata(root).map_err(|_| SecretLeaseError::Storage)?;
        if metadata.file_type().is_symlink() || !metadata.is_dir() {
            return Err(SecretLeaseError::StateDirectoryUnsafe);
        }
        #[cfg(unix)]
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err(SecretLeaseError::StateDirectoryUnsafe);
        }
    } else {
        fs::create_dir_all(root).map_err(|_| SecretLeaseError::Storage)?;
        #[cfg(unix)]
        fs::set_permissions(root, fs::Permissions::from_mode(0o700))
            .map_err(|_| SecretLeaseError::Storage)?;
    }
    Ok(())
}

fn open_private_file(
    path: &Path,
    create: bool,
    truncate: bool,
) -> Result<File, SecretLeaseError> {
    let mut options = OpenOptions::new();
    options.read(true).write(true).create(create).truncate(truncate);
    #[cfg(unix)]
    options.mode(0o600);
    let file = options.open(path).map_err(|_| SecretLeaseError::Storage)?;
    let metadata = file.metadata().map_err(|_| SecretLeaseError::Storage)?;
    if !metadata.is_file() {
        return Err(SecretLeaseError::StateDirectoryUnsafe);
    }
    #[cfg(unix)]
    if metadata.permissions().mode() & 0o077 != 0 {
        return Err(SecretLeaseError::StateDirectoryUnsafe);
    }
    Ok(file)
}

fn load_state(path: &Path) -> Result<RegistryState, SecretLeaseError> {
    if fs::symlink_metadata(path).is_ok_and(|metadata| metadata.file_type().is_symlink()) {
        return Err(SecretLeaseError::StateDirectoryUnsafe);
    }
    let mut file = open_private_file(path, false, false)?;
    let size = file
        .metadata()
        .map_err(|_| SecretLeaseError::Storage)?
        .len();
    if size == 0 || size > MAX_LEASE_REGISTRY_BYTES {
        return Err(SecretLeaseError::StateCorrupt);
    }
    let mut bytes = Vec::with_capacity(size as usize);
    file.read_to_end(&mut bytes)
        .map_err(|_| SecretLeaseError::Storage)?;
    serde_json::from_slice(&bytes).map_err(|_| SecretLeaseError::StateCorrupt)
}

fn persist_state(root: &Path, state: &RegistryState) -> Result<(), SecretLeaseError> {
    let bytes = serde_json::to_vec(state).map_err(|_| SecretLeaseError::StateCorrupt)?;
    if bytes.len() as u64 > MAX_LEASE_REGISTRY_BYTES {
        return Err(SecretLeaseError::CapacityExceeded);
    }
    let next = root.join(NEXT_FILE);
    if fs::symlink_metadata(&next).is_ok_and(|metadata| metadata.file_type().is_symlink()) {
        return Err(SecretLeaseError::StateDirectoryUnsafe);
    }
    let mut file = open_private_file(&next, true, true)?;
    file.write_all(&bytes)
        .map_err(|_| SecretLeaseError::Storage)?;
    file.sync_all().map_err(|_| SecretLeaseError::Storage)?;
    fs::rename(&next, root.join(STATE_FILE)).map_err(|_| SecretLeaseError::Storage)?;
    #[cfg(unix)]
    File::open(root)
        .and_then(|directory| directory.sync_all())
        .map_err(|_| SecretLeaseError::Storage)?;
    Ok(())
}

fn validate_state(state: &RegistryState) -> Result<(), SecretLeaseError> {
    if state.schema_version != SECRET_LEASE_SCHEMA_VERSION
        || state.leases.len() > MAX_LEASE_RECORDS
        || state.operations.len() > MAX_LEASE_OPERATIONS
    {
        return Err(SecretLeaseError::StateCorrupt);
    }
    for (lease_id, lease) in &state.leases {
        if lease_id != &lease.lease_id
            || !valid_lease_id(lease_id)
            || lease.schema_version != SECRET_LEASE_SCHEMA_VERSION
            || !valid_operation_id(&lease.issued_operation_id)
            || !valid_operation_id(&lease.last_operation_id)
            || lease.rotation_generation == 0
            || lease.request_sha256 == [0; 32]
            || lease.scope_sha256 == [0; 32]
        {
            return Err(SecretLeaseError::StateCorrupt);
        }
    }
    for (operation_id, operation) in &state.operations {
        if operation_id != &operation.operation_id
            || !valid_operation_id(operation_id)
            || operation.request_sha256 == [0; 32]
            || operation
                .lease_id
                .as_ref()
                .is_some_and(|lease_id| !valid_lease_id(lease_id))
            || (operation.state == LeaseOperationState::Reconciled
                && !matches!(operation.kind, LeaseOperationKind::Renew | LeaseOperationKind::Revoke))
        {
            return Err(SecretLeaseError::StateCorrupt);
        }
    }
    Ok(())
}
