//! One current-use contract for staged prompt exposure and dispatch claims.
//! A lease is evidence, not authority. Callers hold the registry-owner lock
//! across validation and their local publication/dispatch-record boundary.

use std::collections::BTreeSet;
use std::fmt;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Instant;

use codex_hepta_intelligence::PromptRegistryCompiledContextV2;
use codex_hepta_prompt_optimizer::canonical::SelectedPromptPortfolioV1;
use codex_hepta_prompt_registry::DurablePromptRegistry;
use codex_hepta_prompt_registry::DurableRegistryError;
use codex_hepta_prompt_registry::Lifecycle;
use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_prompt_registry::PromptRegistryFailureV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const LEASE_DOMAIN: &[u8] = b"hepta.prompt-registry.send-final-use-lease.v1";
pub const PROMPT_FINAL_USE_LEASE_SCHEMA: u32 = 1;
const MAX_FINAL_USE_SELECTIONS: usize = 128;

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct PromptFinalUseSelectionV1 {
    pub factor_id: StableId,
    pub realization_id: StableId,
    pub binding_digest: Digest32,
    pub payload_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptFinalUseLeaseV1 {
    pub schema_version: u32,
    pub compilation_id: StableId,
    pub context_attachment_digest: Digest32,
    pub context_payload_digest: Digest32,
    pub registry_snapshot_digest: Digest32,
    pub generation_vector_digest: Digest32,
    pub model_tuple: PromptModelTupleV2,
    pub issued_unix_ms: u64,
    pub valid_until_unix_ms: u64,
    pub selections: Vec<PromptFinalUseSelectionV1>,
    pub lease_digest: Digest32,
}

/// Actual identity observed at the consuming boundary. The clock must come
/// from the trusted host, never solely from a caller-provided dispatch record.
pub struct PromptFinalUseBoundaryV1<'a> {
    pub compilation_id: &'a StableId,
    pub context_attachment_digest: Digest32,
    pub context_payload_digest: Digest32,
    pub now_unix_ms: u64,
}

impl PromptFinalUseLeaseV1 {
    pub fn from_compiled(
        portfolio: &SelectedPromptPortfolioV1,
        compiled: &PromptRegistryCompiledContextV2,
        issued_unix_ms: u64,
        requested_deadline_ms: u64,
    ) -> Result<Self, PromptFinalUseLeaseError> {
        compiled
            .validate()
            .map_err(|error| PromptFinalUseLeaseError::Compiled(error.to_string()))?;
        if issued_unix_ms == 0
            || requested_deadline_ms <= issued_unix_ms
            || compiled.compatible.snapshot_digest.is_zero()
            || compiled.compatible.model_tuple_digest != portfolio.model_tuple.digest()
            || portfolio.generation_vector_digest.is_zero()
            || compiled.selected_deliveries.is_empty()
            || compiled.selected_deliveries.len() > MAX_FINAL_USE_SELECTIONS
        {
            return Err(PromptFinalUseLeaseError::InvalidShape);
        }
        let mut valid_until_unix_ms = requested_deadline_ms;
        let mut selections = Vec::with_capacity(compiled.selected_deliveries.len());
        for delivery in &compiled.selected_deliveries {
            if let Some(expires_unix_ms) = delivery.binding.expires_unix_ms {
                valid_until_unix_ms = valid_until_unix_ms.min(expires_unix_ms);
            }
            selections.push(PromptFinalUseSelectionV1 {
                factor_id: delivery.binding.factor_id.clone(),
                realization_id: delivery.binding.realization_id.clone(),
                binding_digest: delivery.binding.digest(),
                payload_digest: delivery.binding.payload_digest,
            });
        }
        selections.sort();
        let mut lease = Self {
            schema_version: PROMPT_FINAL_USE_LEASE_SCHEMA,
            compilation_id: compiled.compiled.receipt().compilation_id().clone(),
            context_attachment_digest: compiled.attachment.attachment_digest(),
            context_payload_digest: compiled.attachment.payload_digest(),
            registry_snapshot_digest: compiled.compatible.snapshot_digest,
            generation_vector_digest: portfolio.generation_vector_digest,
            model_tuple: portfolio.model_tuple.clone(),
            issued_unix_ms,
            valid_until_unix_ms,
            selections,
            lease_digest: Digest32::ZERO,
        };
        lease.lease_digest = lease.compute_digest();
        lease.validate_shape()?;
        Ok(lease)
    }

    pub fn validate_shape(&self) -> Result<(), PromptFinalUseLeaseError> {
        if self.schema_version != PROMPT_FINAL_USE_LEASE_SCHEMA
            || self.context_attachment_digest.is_zero()
            || self.context_payload_digest.is_zero()
            || self.registry_snapshot_digest.is_zero()
            || self.generation_vector_digest.is_zero()
            || self.issued_unix_ms == 0
            || self.valid_until_unix_ms <= self.issued_unix_ms
            || self.selections.is_empty()
            || self.selections.len() > MAX_FINAL_USE_SELECTIONS
            || self
                .selections
                .windows(2)
                .any(|window| window[0] >= window[1])
        {
            return Err(PromptFinalUseLeaseError::InvalidShape);
        }
        self.model_tuple
            .validate()
            .map_err(|_| PromptFinalUseLeaseError::InvalidShape)?;
        let mut realization_ids = BTreeSet::new();
        let mut factor_ids = BTreeSet::new();
        if self.selections.iter().any(|selection| {
            !realization_ids.insert(&selection.realization_id)
                || !factor_ids.insert(&selection.factor_id)
        }) {
            return Err(PromptFinalUseLeaseError::InvalidShape);
        }
        if self.selections.iter().any(|selection| {
            selection.binding_digest.is_zero() || selection.payload_digest.is_zero()
        }) || self.lease_digest != self.compute_digest()
        {
            return Err(PromptFinalUseLeaseError::DigestMismatch);
        }
        Ok(())
    }

    pub fn validate_at_boundary(
        &self,
        registry: &DurablePromptRegistry,
        boundary: &PromptFinalUseBoundaryV1<'_>,
    ) -> Result<(), PromptFinalUseLeaseError> {
        self.validate_shape()?;
        if &self.compilation_id != boundary.compilation_id
            || self.context_attachment_digest != boundary.context_attachment_digest
            || self.context_payload_digest != boundary.context_payload_digest
        {
            return Err(PromptFinalUseLeaseError::BoundaryBindingMismatch);
        }
        self.validate_current(registry, boundary.now_unix_ms)
    }

    pub fn validate_current(
        &self,
        registry: &DurablePromptRegistry,
        now_unix_ms: u64,
    ) -> Result<(), PromptFinalUseLeaseError> {
        self.validate_shape()?;
        let current = registry
            .registry()
            .map_err(PromptFinalUseLeaseError::from_registry)?;
        if now_unix_ms < self.issued_unix_ms || now_unix_ms >= self.valid_until_unix_ms {
            return Err(PromptFinalUseLeaseError::Expired);
        }
        // Diagnose terminal withdrawal before a generic snapshot mismatch. No
        // string parsing and no blind retry of a withdrawn selection.
        for selection in &self.selections {
            let factor = current
                .factor(&selection.factor_id)
                .ok_or(PromptFinalUseLeaseError::SelectionChanged)?;
            match factor.lifecycle {
                Lifecycle::Revoked => return Err(PromptFinalUseLeaseError::Revoked),
                Lifecycle::Retired => return Err(PromptFinalUseLeaseError::Retired),
                Lifecycle::Draft => return Err(PromptFinalUseLeaseError::NotAdmitted),
                Lifecycle::Admitted => {}
            }
        }
        let snapshot = registry
            .snapshot_v2(self.generation_vector_digest, &self.model_tuple)
            .map_err(PromptFinalUseLeaseError::from_registry)?;
        if snapshot.snapshot_digest != self.registry_snapshot_digest {
            return Err(PromptFinalUseLeaseError::RegistrySnapshotChanged);
        }
        for selection in &self.selections {
            let delivery = registry
                .dereference_realization_v2(
                    &selection.realization_id,
                    &snapshot,
                    self.generation_vector_digest,
                    &self.model_tuple,
                    now_unix_ms,
                )
                .map_err(PromptFinalUseLeaseError::from_registry)?;
            if delivery.binding.factor_id != selection.factor_id
                || delivery.binding.digest() != selection.binding_digest
                || delivery.binding.payload_digest != selection.payload_digest
                || Digest32::of_bytes(&delivery.payload) != selection.payload_digest
            {
                return Err(PromptFinalUseLeaseError::SelectionChanged);
            }
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_digest(&self) -> Digest32 {
        let mut bytes = LEASE_DOMAIN.to_vec();
        bytes.extend_from_slice(&self.schema_version.to_be_bytes());
        push_id(&mut bytes, &self.compilation_id);
        for digest in [
            self.context_attachment_digest,
            self.context_payload_digest,
            self.registry_snapshot_digest,
            self.generation_vector_digest,
            self.model_tuple.digest(),
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.issued_unix_ms.to_be_bytes());
        bytes.extend_from_slice(&self.valid_until_unix_ms.to_be_bytes());
        bytes.extend_from_slice(
            &u64::try_from(self.selections.len())
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        );
        for selection in &self.selections {
            push_id(&mut bytes, &selection.factor_id);
            push_id(&mut bytes, &selection.realization_id);
            bytes.extend_from_slice(selection.binding_digest.as_array());
            bytes.extend_from_slice(selection.payload_digest.as_array());
        }
        Digest32::of_bytes(&bytes)
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u64::try_from(raw.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptFinalUseRecovery {
    Reject,
    Recompile,
    ReopenAndReconcile,
    RelieveCapacity,
    RetryAfterAvailability,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptFinalUseLeaseError {
    InvalidShape,
    DigestMismatch,
    Expired,
    BoundaryBindingMismatch,
    RegistrySnapshotChanged,
    SelectionChanged,
    Revoked,
    Retired,
    NotAdmitted,
    StoreUnavailable,
    ReopenRequired,
    IndeterminateDurability,
    CapacityExceeded,
    IntegrityRejected,
    Registry(String),
    Compiled(String),
}

impl PromptFinalUseLeaseError {
    fn from_registry(error: DurableRegistryError) -> Self {
        match error.failure() {
            PromptRegistryFailureV1::ReopenRequired => Self::ReopenRequired,
            PromptRegistryFailureV1::IndeterminateDurability => Self::IndeterminateDurability,
            PromptRegistryFailureV1::CapacityExceeded => Self::CapacityExceeded,
            PromptRegistryFailureV1::StoreUnavailable | PromptRegistryFailureV1::OwnerBusy => {
                Self::StoreUnavailable
            }
            PromptRegistryFailureV1::SnapshotChanged => Self::RegistrySnapshotChanged,
            PromptRegistryFailureV1::SelectionUnavailable => Self::SelectionChanged,
            PromptRegistryFailureV1::IntegrityRejected => Self::IntegrityRejected,
            PromptRegistryFailureV1::Withdrawn => Self::Revoked,
            PromptRegistryFailureV1::AuthorizationExpired => Self::Expired,
            PromptRegistryFailureV1::IdentityConflict
            | PromptRegistryFailureV1::AuthorizationRejected
            | PromptRegistryFailureV1::InvalidInput
            | PromptRegistryFailureV1::ConfigurationRejected
            | PromptRegistryFailureV1::UnsafeStorage => {
                Self::Registry("registry integrity or configuration rejected".to_owned())
            }
        }
    }

    #[must_use]
    pub const fn code(&self) -> &'static str {
        match self {
            Self::InvalidShape => "prompt_final_use_invalid_shape",
            Self::DigestMismatch => "prompt_final_use_digest_mismatch",
            Self::Expired => "prompt_final_use_expired",
            Self::BoundaryBindingMismatch => "prompt_final_use_binding_mismatch",
            Self::RegistrySnapshotChanged => "prompt_final_use_snapshot_changed",
            Self::SelectionChanged => "prompt_final_use_selection_changed",
            Self::Revoked => "prompt_final_use_revoked",
            Self::Retired => "prompt_final_use_retired",
            Self::NotAdmitted => "prompt_final_use_not_admitted",
            Self::StoreUnavailable => "prompt_final_use_store_unavailable",
            Self::ReopenRequired => "prompt_final_use_reopen_required",
            Self::IndeterminateDurability => "prompt_final_use_indeterminate_durability",
            Self::CapacityExceeded => "prompt_final_use_capacity_exceeded",
            Self::IntegrityRejected => "prompt_final_use_integrity_rejected",
            Self::Registry(_) => "prompt_final_use_registry_rejected",
            Self::Compiled(_) => "prompt_final_use_compilation_rejected",
        }
    }

    #[must_use]
    pub const fn recovery(&self) -> PromptFinalUseRecovery {
        match self {
            Self::Expired | Self::RegistrySnapshotChanged | Self::SelectionChanged => {
                PromptFinalUseRecovery::Recompile
            }
            Self::ReopenRequired | Self::IndeterminateDurability => {
                PromptFinalUseRecovery::ReopenAndReconcile
            }
            Self::CapacityExceeded => PromptFinalUseRecovery::RelieveCapacity,
            Self::StoreUnavailable => PromptFinalUseRecovery::RetryAfterAvailability,
            _ => PromptFinalUseRecovery::Reject,
        }
    }
}

impl fmt::Display for PromptFinalUseLeaseError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        // Do not leak registry identifiers, raw payloads or compiler diagnostics
        // through the externally visible host error message.
        write!(formatter, "{}; recovery={:?}", self.code(), self.recovery())
    }
}

impl std::error::Error for PromptFinalUseLeaseError {}

/// Owner-local, bounded, process-generation diagnostics; no mutable singleton.
#[derive(Debug, Default)]
pub struct PromptFinalUseValidator {
    checked: AtomicU64,
    rejected: AtomicU64,
    expired: AtomicU64,
    withdrawn: AtomicU64,
    identity_conflicts: AtomicU64,
    reopen_required: AtomicU64,
    total_nanos: AtomicU64,
    maximum_nanos: AtomicU64,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct PromptFinalUseMetrics {
    pub checked: u64,
    pub rejected: u64,
    pub expired: u64,
    pub withdrawn: u64,
    pub identity_conflicts: u64,
    pub reopen_required: u64,
    pub total_nanos: u64,
    pub maximum_nanos: u64,
}

impl PromptFinalUseValidator {
    pub fn validate(
        &self,
        lease: &PromptFinalUseLeaseV1,
        registry: &DurablePromptRegistry,
        boundary: &PromptFinalUseBoundaryV1<'_>,
    ) -> Result<(), PromptFinalUseLeaseError> {
        let started = Instant::now();
        let result = lease.validate_at_boundary(registry, boundary);
        increment(&self.checked, 1);
        if let Err(error) = &result {
            increment(&self.rejected, 1);
            match error {
                PromptFinalUseLeaseError::Expired => increment(&self.expired, 1),
                PromptFinalUseLeaseError::Revoked | PromptFinalUseLeaseError::Retired => {
                    increment(&self.withdrawn, 1)
                }
                PromptFinalUseLeaseError::BoundaryBindingMismatch
                | PromptFinalUseLeaseError::RegistrySnapshotChanged
                | PromptFinalUseLeaseError::SelectionChanged => {
                    increment(&self.identity_conflicts, 1)
                }
                PromptFinalUseLeaseError::ReopenRequired
                | PromptFinalUseLeaseError::IndeterminateDurability => {
                    increment(&self.reopen_required, 1)
                }
                _ => {}
            }
        }
        let elapsed = u64::try_from(started.elapsed().as_nanos()).unwrap_or(u64::MAX);
        increment(&self.total_nanos, elapsed);
        self.maximum_nanos.fetch_max(elapsed, Ordering::Relaxed);
        result
    }

    /// Concurrent reads are approximate; these counters never make decisions.
    #[must_use]
    pub fn metrics(&self) -> PromptFinalUseMetrics {
        PromptFinalUseMetrics {
            checked: self.checked.load(Ordering::Relaxed),
            rejected: self.rejected.load(Ordering::Relaxed),
            expired: self.expired.load(Ordering::Relaxed),
            withdrawn: self.withdrawn.load(Ordering::Relaxed),
            identity_conflicts: self.identity_conflicts.load(Ordering::Relaxed),
            reopen_required: self.reopen_required.load(Ordering::Relaxed),
            total_nanos: self.total_nanos.load(Ordering::Relaxed),
            maximum_nanos: self.maximum_nanos.load(Ordering::Relaxed),
        }
    }
}

fn increment(counter: &AtomicU64, amount: u64) {
    let _ = counter.fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
        Some(value.saturating_add(amount))
    });
}

#[cfg(all(test, unix))]
#[path = "prompt_final_use_tests.rs"]
mod tests;
