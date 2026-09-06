//! Explicit host-bound turn/lifecycle identity for local qualification.
//!
//! This module is deliberately a contract only.  It does not register a
//! `TurnLifecycleContributor`, acquire a lease, append an event/outbox row, or
//! grant any production authority.  A host which already owns the exact
//! schema-bound lease and compact executor may construct this envelope and
//! use [`LocalTurnLifecycleBinding::verify_current`] immediately before an
//! explicitly scoped local operation.

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

use crate::CompactFence;
use crate::LocalCompactExecutor;
use crate::LocalLeaseBinding;
use crate::LocalLeaseOutbox;
use crate::LocalLeaseOutboxError;

/// Schema version for the host-bound local turn identity envelope.
pub const LOCAL_TURN_LIFECYCLE_BINDING_SCHEMA_VERSION: u32 = 1;
/// This envelope is qualification metadata, never a runtime authority grant.
pub const LOCAL_TURN_LIFECYCLE_BINDING_NAMESPACE: &str = "local_development_only";
pub const LOCAL_TURN_LIFECYCLE_BINDING_EXTERNAL_EFFECTS: bool = false;
pub const LOCAL_TURN_LIFECYCLE_BINDING_KG_WRITE_AUTHORITY: bool = false;
pub const LOCAL_TURN_LIFECYCLE_BINDING_PRODUCTION_CALLER: bool = false;
/// Constructing or validating this value never installs a lifecycle callback.
pub const LOCAL_TURN_LIFECYCLE_BINDING_LIFECYCLE_REGISTERED: bool = false;

const BINDING_DOMAIN: &[u8] = b"hepta-memory:local-turn-lifecycle-binding:v1";

#[derive(Debug, Error)]
pub enum LocalTurnLifecycleBindingError {
    #[error("invalid local turn lifecycle binding: {0}")]
    Invalid(String),
    #[error("local turn lifecycle binding fence mismatch: {0}")]
    FenceMismatch(String),
    #[error("local turn lifecycle binding lease mismatch: {0}")]
    LeaseMismatch(String),
    #[error("local turn lifecycle binding requires an explicitly bound compact executor")]
    ExecutorUnbound,
    #[error(transparent)]
    Lease(#[from] LocalLeaseOutboxError),
}

/// An immutable identity envelope tying one host turn to one exact local
/// lease/compact fence.  Epochs are copied from explicit caller-owned values;
/// this type never invents or increments authority, owner, or generation.
///
/// The raw fencing token is retained only inside [`CompactFence`] so callers
/// can perform an in-memory equality check.  The digest fields are included
/// in the serialized envelope and in `binding_sha256`, allowing a consumer to
/// reject tampered or cross-turn values before any local write is attempted.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LocalTurnLifecycleBinding {
    pub schema_version: u32,
    pub namespace: String,
    pub turn_id: String,
    pub turn_id_sha256: Sha256Digest,
    pub lease_id: String,
    pub lease_id_sha256: Sha256Digest,
    pub lease_head_sha256: Sha256Digest,
    pub fence: CompactFence,
    pub lease_binding: LocalLeaseBinding,
    pub fencing_token_sha256: Sha256Digest,
    pub binding_sha256: Sha256Digest,
    pub external_effects: bool,
    pub kg_write_authority: bool,
    pub production_caller: bool,
    pub lifecycle_registered: bool,
}

impl LocalTurnLifecycleBinding {
    /// Build a binding from the exact handles already owned by a host.
    ///
    /// This is a pure identity operation.  It refuses legacy/unbound leases,
    /// unbound compact executors, mismatched fences, and handles from a
    /// different local store.  No database operation is performed here.
    pub fn from_handles(
        turn_id: impl AsRef<str>,
        lease: &LocalLeaseOutbox,
        executor: &LocalCompactExecutor,
    ) -> Result<Self, LocalTurnLifecycleBindingError> {
        let turn_id = turn_id.as_ref();
        validate_turn_id(turn_id)?;
        if !executor.is_bound() {
            return Err(LocalTurnLifecycleBindingError::ExecutorUnbound);
        }
        if !executor.is_bound_to_lease(lease) {
            return Err(LocalTurnLifecycleBindingError::LeaseMismatch(
                "lease handle does not match the executor's bound store/lease".to_string(),
            ));
        }
        let fence = executor.fence().clone();
        let lease_binding = lease.binding().ok_or_else(|| {
            LocalTurnLifecycleBindingError::LeaseMismatch(
                "legacy lease has no authority/owner/expiry binding".to_string(),
            )
        })?;
        let compact_binding = executor
            .lease_binding()
            .ok_or(LocalTurnLifecycleBindingError::ExecutorUnbound)?;
        if compact_binding.lease_id != lease.lease_id()
            || compact_binding.authority_epoch != lease_binding.authority_epoch
            || compact_binding.owner_epoch != lease_binding.owner_epoch
            || compact_binding.lease_expires_at_unix_seconds
                != lease_binding.lease_expires_at_unix_seconds
        {
            return Err(LocalTurnLifecycleBindingError::LeaseMismatch(
                "compact journal lease descriptor does not match lease binding".to_string(),
            ));
        }
        if lease.generation() != fence.generation
            || lease.fencing_token() != fence.fencing_token
            || lease_binding.authority_epoch != fence.authority_epoch
            || lease_binding.owner_epoch != fence.owner_epoch
        {
            return Err(LocalTurnLifecycleBindingError::FenceMismatch(
                "lease identity does not match compact fence".to_string(),
            ));
        }
        let mut binding = Self {
            schema_version: LOCAL_TURN_LIFECYCLE_BINDING_SCHEMA_VERSION,
            namespace: LOCAL_TURN_LIFECYCLE_BINDING_NAMESPACE.to_string(),
            turn_id: turn_id.to_string(),
            turn_id_sha256: identity_digest(b"turn", turn_id),
            lease_id: lease.lease_id().to_string(),
            lease_id_sha256: identity_digest(b"lease", lease.lease_id()),
            lease_head_sha256: compact_binding.lease_head_sha256.clone(),
            fencing_token_sha256: identity_digest(b"fencing-token", lease.fencing_token()),
            fence,
            lease_binding,
            binding_sha256: Sha256Digest::for_bytes(b"pending"),
            external_effects: LOCAL_TURN_LIFECYCLE_BINDING_EXTERNAL_EFFECTS,
            kg_write_authority: LOCAL_TURN_LIFECYCLE_BINDING_KG_WRITE_AUTHORITY,
            production_caller: LOCAL_TURN_LIFECYCLE_BINDING_PRODUCTION_CALLER,
            lifecycle_registered: LOCAL_TURN_LIFECYCLE_BINDING_LIFECYCLE_REGISTERED,
        };
        binding.binding_sha256 = binding_digest(&binding);
        binding.validate()?;
        Ok(binding)
    }

    /// Validate the immutable envelope without consulting storage.
    pub fn validate(&self) -> Result<(), LocalTurnLifecycleBindingError> {
        if self.schema_version != LOCAL_TURN_LIFECYCLE_BINDING_SCHEMA_VERSION
            || self.namespace != LOCAL_TURN_LIFECYCLE_BINDING_NAMESPACE
        {
            return Err(LocalTurnLifecycleBindingError::Invalid(
                "unsupported schema or namespace".to_string(),
            ));
        }
        if self.external_effects
            || self.kg_write_authority
            || self.production_caller
            || self.lifecycle_registered
        {
            return Err(LocalTurnLifecycleBindingError::Invalid(
                "binding crosses the local-development boundary".to_string(),
            ));
        }
        validate_turn_id(&self.turn_id)?;
        if self.turn_id_sha256 != identity_digest(b"turn", &self.turn_id) {
            return Err(LocalTurnLifecycleBindingError::Invalid(
                "turn identity digest does not match turn id".to_string(),
            ));
        }
        validate_digest(&self.turn_id_sha256, "turn identity")?;
        validate_text(&self.lease_id, "lease id", 512)?;
        if self.lease_id_sha256 != identity_digest(b"lease", &self.lease_id) {
            return Err(LocalTurnLifecycleBindingError::Invalid(
                "lease identity digest does not match lease id".to_string(),
            ));
        }
        validate_digest(&self.lease_head_sha256, "lease head")?;
        validate_digest(&self.fencing_token_sha256, "fencing token identity")?;
        validate_text(&self.fence.fencing_token, "fencing token", 256)?;
        if self.fencing_token_sha256 != identity_digest(b"fencing-token", &self.fence.fencing_token)
        {
            return Err(LocalTurnLifecycleBindingError::FenceMismatch(
                "fencing token identity digest does not match fence".to_string(),
            ));
        }
        let expected_binding = LocalLeaseBinding::new(
            self.fence.authority_epoch,
            self.fence.owner_epoch,
            self.lease_binding.lease_expires_at_unix_seconds,
        )
        .map_err(|error| LocalTurnLifecycleBindingError::Invalid(error.to_string()))?;
        if self.lease_binding != expected_binding {
            return Err(LocalTurnLifecycleBindingError::FenceMismatch(
                "lease binding contains invalid authority/owner/expiry values".to_string(),
            ));
        }
        if self.fence.generation == 0 {
            return Err(LocalTurnLifecycleBindingError::FenceMismatch(
                "compact fence generation must be non-zero".to_string(),
            ));
        }
        if self.binding_sha256 != binding_digest(self) {
            return Err(LocalTurnLifecycleBindingError::Invalid(
                "binding digest does not match immutable fields".to_string(),
            ));
        }
        Ok(())
    }

    /// Revalidate this binding against the exact handles and current
    /// append-only lease/event/outbox chains.  This remains an explicit host
    /// call; no callback, scheduler, or writer is installed by this method.
    pub async fn verify_current(
        &self,
        lease: &LocalLeaseOutbox,
        executor: &LocalCompactExecutor,
    ) -> Result<(), LocalTurnLifecycleBindingError> {
        self.validate()?;
        let current = Self::from_handles(&self.turn_id, lease, executor)?;
        if current != *self {
            return Err(LocalTurnLifecycleBindingError::LeaseMismatch(
                "current lease/compact handles no longer match binding".to_string(),
            ));
        }
        lease.verify_current().await?;
        Ok(())
    }
}

fn validate_turn_id(value: &str) -> Result<(), LocalTurnLifecycleBindingError> {
    validate_text(value, "turn id", 256)?;
    if value.starts_with("auto-compact-") {
        return Err(LocalTurnLifecycleBindingError::Invalid(
            "process-local auto-compaction ids are not durable turn identities".to_string(),
        ));
    }
    Ok(())
}

fn validate_text(
    value: &str,
    label: &str,
    max_bytes: usize,
) -> Result<(), LocalTurnLifecycleBindingError> {
    if value.trim().is_empty() || value.len() > max_bytes || value.as_bytes().contains(&0) {
        return Err(LocalTurnLifecycleBindingError::Invalid(format!(
            "{label} must contain 1..={max_bytes} non-NUL bytes"
        )));
    }
    Ok(())
}

fn validate_digest(
    digest: &Sha256Digest,
    label: &str,
) -> Result<(), LocalTurnLifecycleBindingError> {
    Sha256Digest::parse(digest.as_str().to_string()).map_err(|_| {
        LocalTurnLifecycleBindingError::Invalid(format!(
            "{label} must be a lowercase SHA-256 digest"
        ))
    })?;
    Ok(())
}

fn identity_digest(kind: &[u8], value: &str) -> Sha256Digest {
    let mut hasher = Sha256::new();
    hash_part(&mut hasher, BINDING_DOMAIN);
    hash_part(&mut hasher, kind);
    hash_part(&mut hasher, value.as_bytes());
    Sha256Digest::for_bytes(&hasher.finalize())
}

fn binding_digest(binding: &LocalTurnLifecycleBinding) -> Sha256Digest {
    let mut hasher = Sha256::new();
    hash_part(&mut hasher, BINDING_DOMAIN);
    for digest in [
        &binding.turn_id_sha256,
        &binding.lease_id_sha256,
        &binding.lease_head_sha256,
        &binding.fencing_token_sha256,
    ] {
        hash_part(&mut hasher, digest.as_str().as_bytes());
    }
    hash_part(&mut hasher, binding.lease_id.as_bytes());
    for value in [
        binding.fence.authority_epoch,
        binding.fence.owner_epoch,
        binding.fence.generation,
        binding.lease_binding.lease_expires_at_unix_seconds,
    ] {
        hash_part(&mut hasher, value.to_be_bytes().as_slice());
    }
    hash_part(&mut hasher, binding.fence.fencing_token.as_bytes());
    Sha256Digest::for_bytes(&hasher.finalize())
}

fn hash_part(hasher: &mut Sha256, value: &[u8]) {
    hasher.update((value.len() as u64).to_be_bytes());
    hasher.update(value);
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    use crate::CognitiveStore;
    use crate::CompactFence;
    use crate::LocalLeaseAcquire;
    use codex_hepta_contracts::AgentId;
    use codex_hepta_paths::HeptaFleetRoot;
    use tempfile::TempDir;

    use super::*;

    async fn prepared(temp: &TempDir, bound: bool) -> (LocalLeaseOutbox, LocalCompactExecutor) {
        let fleet_root = temp.path().join("fleet");
        fs::create_dir_all(&fleet_root).expect("fleet root");
        let fleet = HeptaFleetRoot::parse(fleet_root).expect("fleet root");
        let owner = AgentId::parse("00000000-0000-4000-8000-000000000931").expect("owner");
        let store = CognitiveStore::open(&fleet.layout().agent(&owner))
            .await
            .expect("store");
        let fence = CompactFence::new(11, 13, 1, "turn-binding-fence").expect("fence");
        let lease = if bound {
            let expires = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .expect("clock")
                .as_secs()
                + 3_600;
            match store
                .acquire_local_lease_bound(
                    "lease:turn-binding",
                    fence.authority_epoch,
                    fence.owner_epoch,
                    fence.generation,
                    fence.fencing_token.clone(),
                    expires,
                )
                .await
                .expect("bound lease")
            {
                LocalLeaseAcquire::Acquired(lease) | LocalLeaseAcquire::Replay(lease) => lease,
            }
        } else {
            match store
                .acquire_local_lease(
                    "lease:turn-binding",
                    fence.generation,
                    fence.fencing_token.clone(),
                )
                .await
                .expect("legacy lease")
            {
                LocalLeaseAcquire::Acquired(lease) | LocalLeaseAcquire::Replay(lease) => lease,
            }
        };
        let executor = if bound {
            store
                .open_local_compact_executor_bound("journal:turn-binding", fence, &lease)
                .await
                .expect("bound executor")
        } else {
            store
                .open_local_compact_executor(
                    "journal:turn-binding",
                    CompactFence::new(11, 13, 1, "turn-binding-fence").expect("fence"),
                )
                .await
                .expect("legacy executor")
        };
        (lease, executor)
    }

    #[tokio::test]
    async fn exact_bound_handles_form_a_local_only_contract() {
        let temp = TempDir::new().expect("temp");
        let (lease, executor) = prepared(&temp, true).await;
        let binding = LocalTurnLifecycleBinding::from_handles("turn:931", &lease, &executor)
            .expect("binding");
        binding.validate().expect("valid binding");
        binding
            .verify_current(&lease, &executor)
            .await
            .expect("current binding");
        assert!(!binding.external_effects);
        assert!(!binding.kg_write_authority);
        assert!(!binding.production_caller);
        assert!(!binding.lifecycle_registered);
    }

    #[tokio::test]
    async fn legacy_lease_or_executor_is_rejected_fail_closed() {
        let temp = TempDir::new().expect("temp");
        let (lease, executor) = prepared(&temp, false).await;
        assert!(matches!(
            LocalTurnLifecycleBinding::from_handles("turn:931", &lease, &executor),
            Err(LocalTurnLifecycleBindingError::ExecutorUnbound)
                | Err(LocalTurnLifecycleBindingError::LeaseMismatch(_))
        ));
    }

    #[tokio::test]
    async fn mismatched_store_or_fence_is_rejected() {
        let temp = TempDir::new().expect("temp");
        let (lease, executor) = prepared(&temp, true).await;
        let other_temp = TempDir::new().expect("other temp");
        let (other_lease, _other_executor) = prepared(&other_temp, true).await;
        assert!(matches!(
            LocalTurnLifecycleBinding::from_handles("turn:931", &other_lease, &executor),
            Err(LocalTurnLifecycleBindingError::LeaseMismatch(_))
        ));
        let mut tampered = LocalTurnLifecycleBinding::from_handles("turn:931", &lease, &executor)
            .expect("binding");
        tampered.fence.authority_epoch += 1;
        assert!(matches!(
            tampered.validate(),
            Err(LocalTurnLifecycleBindingError::FenceMismatch(_))
                | Err(LocalTurnLifecycleBindingError::Invalid(_))
        ));
    }

    #[tokio::test]
    async fn turn_identity_and_digest_tampering_fail_closed() {
        let temp = TempDir::new().expect("temp");
        let (lease, executor) = prepared(&temp, true).await;
        let mut binding = LocalTurnLifecycleBinding::from_handles("turn:931", &lease, &executor)
            .expect("binding");
        binding.turn_id_sha256 = Sha256Digest::for_bytes(b"other-turn");
        assert!(binding.validate().is_err());
        let mut binding = LocalTurnLifecycleBinding::from_handles("turn:931", &lease, &executor)
            .expect("binding");
        binding.binding_sha256 = Sha256Digest::for_bytes(b"tampered");
        assert!(binding.validate().is_err());
    }
}
