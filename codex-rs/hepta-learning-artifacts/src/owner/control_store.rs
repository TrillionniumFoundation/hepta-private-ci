//! Narrow durable control-state port for drain and withdrawal floors.
//!
//! The owner service does not depend on marker filenames or synchronization
//! ordering. Implementations persist one immutable, scope-bound control history
//! and may never repair or overwrite an uncertain record in place.

use std::fmt;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::DatasetWithdrawalRegistry;

use super::durable_control::DurableDrain;
use super::durable_withdrawals::DurableWithdrawalFloor;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OwnerControlStoreIdentityV1 {
    root: PathBuf,
    registry_id: StableId,
    withdrawal_scope_digest: Digest32,
    storage_binding: Digest32,
}

impl OwnerControlStoreIdentityV1 {
    #[must_use]
    pub fn root(&self) -> &Path {
        &self.root
    }

    #[must_use]
    pub fn registry_id(&self) -> &StableId {
        &self.registry_id
    }

    #[must_use]
    pub const fn withdrawal_scope_digest(&self) -> Digest32 {
        self.withdrawal_scope_digest
    }

    #[must_use]
    pub const fn storage_binding(&self) -> Digest32 {
        self.storage_binding
    }
}

pub trait OwnerControlStoreV1: Send {
    fn identity(&self) -> &OwnerControlStoreIdentityV1;
    fn drain_requested(&self) -> Result<bool, std::io::Error>;
    fn persist_drain(&self) -> Result<(), std::io::Error>;
    fn persist_withdrawal_frontier(
        &self,
        registry: &DatasetWithdrawalRegistry,
    ) -> Result<(), std::io::Error>;
}

pub struct FsOwnerControlStoreV1 {
    identity: OwnerControlStoreIdentityV1,
    drain: DurableDrain,
    withdrawals: DurableWithdrawalFloor,
}

impl fmt::Debug for FsOwnerControlStoreV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("FsOwnerControlStoreV1")
            .field("identity", &self.identity)
            .finish_non_exhaustive()
    }
}

impl FsOwnerControlStoreV1 {
    #[must_use]
    pub fn new(
        root: PathBuf,
        registry_id: StableId,
        withdrawal_scope_digest: Digest32,
        storage_binding: Digest32,
    ) -> Self {
        Self {
            drain: DurableDrain::new(
                &root,
                &registry_id,
                withdrawal_scope_digest,
                storage_binding,
            ),
            withdrawals: DurableWithdrawalFloor::new(
                &root,
                &registry_id,
                withdrawal_scope_digest,
                storage_binding,
            ),
            identity: OwnerControlStoreIdentityV1 {
                root,
                registry_id,
                withdrawal_scope_digest,
                storage_binding,
            },
        }
    }
}

impl OwnerControlStoreV1 for FsOwnerControlStoreV1 {
    fn identity(&self) -> &OwnerControlStoreIdentityV1 {
        &self.identity
    }

    fn drain_requested(&self) -> Result<bool, std::io::Error> {
        self.drain.requested()
    }

    fn persist_drain(&self) -> Result<(), std::io::Error> {
        self.drain.persist()
    }

    fn persist_withdrawal_frontier(
        &self,
        registry: &DatasetWithdrawalRegistry,
    ) -> Result<(), std::io::Error> {
        self.withdrawals.persist(registry)
    }
}
