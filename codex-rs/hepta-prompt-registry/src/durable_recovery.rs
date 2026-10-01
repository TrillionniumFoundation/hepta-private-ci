//! Exact current-cut admission before migration or payload-tail recovery.
//!
//! The host authenticates, retains and establishes the currentness of this cut
//! independently of the owner directory. Deriving it from a suspect backup
//! cannot authenticate that backup. No witness or authority is auto-published.

use std::path::Path;

use serde::Deserialize;
use serde::Serialize;

use super::DurablePromptRegistry;
use super::DurableRegistryError;
use super::OpenPolicy;
use super::Store;
use super::StoredAny;
use super::migrate_v1;
use super::restore_v2;
use crate::PromptRegistry;

/// One exact semantic owner cut. Every subsequent mutation needs a fresh
/// independently retained cut before it may be treated as acknowledged.
///
/// This integrity witness grants no admission or write authority, does not
/// authenticate its provider, and is not a minimum-prefix anchor. This store
/// does not retain enough complete mutation history to prove later extension.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PromptRegistryRecoveryAnchor {
    pub revision: u64,
    pub lifecycle_frontier: u64,
    pub revocation_frontier: u64,
    pub registry_digest: [u8; 32],
}

impl PromptRegistryRecoveryAnchor {
    fn from_registry(registry: &PromptRegistry) -> Self {
        Self {
            revision: registry.revision().get(),
            lifecycle_frontier: registry.lifecycle_frontier(),
            revocation_frontier: registry.revocation_frontier(),
            registry_digest: registry.snapshot_digest().into_array(),
        }
    }

    fn validate(self) -> Result<(), DurableRegistryError> {
        if self.revision == 0
            || self.registry_digest == [0; 32]
            || self.revocation_frontier > self.lifecycle_frontier
            || self.lifecycle_frontier > self.revision
            || (self.revision > 1 && self.lifecycle_frontier != self.revision)
        {
            return Err(DurableRegistryError::InvalidRecoveryAnchor);
        }
        Ok(())
    }
}

impl DurablePromptRegistry {
    /// Observe the currently committed, available semantic image. The host must
    /// independently retain and authenticate this value; observing a backup
    /// cannot prove that the backup is current. Poisoned owners expose no cut.
    pub fn recovery_anchor(&self) -> Result<PromptRegistryRecoveryAnchor, DurableRegistryError> {
        self.ensure_available()?;
        Ok(PromptRegistryRecoveryAnchor::from_registry(&self.registry))
    }

    /// Reopen an existing owner at exactly an independently authenticated cut.
    ///
    /// Shape/configuration rejection precedes filesystem access. The owner lock
    /// is acquired and the selected state is fully validated before comparison;
    /// mismatches never migrate metadata or trim payload bytes. Missing state
    /// never falls back to bootstrap. A matching V1/V2 image may migrate, and a
    /// matching V3 image may trim its unselected tail only after comparison.
    ///
    /// The caller establishes the witness's authentication and currentness in
    /// an independent rollback domain. This method verifies equality only; it
    /// grants no additional effect authority or production recovery acceptance.
    pub fn open_state_dir_with_recovery_anchor(
        directory: &Path,
        maximum_records: usize,
        expected: &PromptRegistryRecoveryAnchor,
    ) -> Result<Self, DurableRegistryError> {
        expected.validate()?;
        PromptRegistry::new(maximum_records).map_err(DurableRegistryError::Core)?;
        let (mut store, stored) =
            Store::open_with_policy(directory, OpenPolicy::ExistingStateRequired)?;
        let registry = match stored {
            Some(StoredAny::V2(stored)) => restore_v2(stored, maximum_records)?,
            Some(StoredAny::V1(stored)) => migrate_v1(stored, maximum_records)?,
            None => return Err(DurableRegistryError::RecoveryStateMissing),
        };
        if PromptRegistryRecoveryAnchor::from_registry(&registry) != *expected {
            return Err(DurableRegistryError::RecoveryAnchorMismatch);
        }
        if store.payloads.is_initialized() {
            store.payloads.discard_unselected_tail(&store.root)?;
        } else {
            store = store.initialize(&registry)?;
        }
        Ok(Self {
            registry,
            store,
            poisoned: false,
        })
    }
}

#[cfg(all(test, unix))]
#[path = "durable_recovery_tests.rs"]
mod tests;
