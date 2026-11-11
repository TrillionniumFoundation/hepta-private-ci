//! Bounded iteration records in an already registered protected Root CAS owner.
//!
//! This restores protected data and its exact current head, not an attestation,
//! revoked permission, Chain anchor or proof of training/selection. Existing
//! learning receipt authentication remains a separate obligation of the host.
//! No constructor here registers an owner or opens a root pathname.

use std::error::Error as StdError;
use std::fmt;

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningIterationOwnersV1;
use codex_hepta_learning_artifacts::LearningIterationRequestV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

#[path = "learning_iteration_checkpoint_codec.rs"]
mod codec;

#[path = "learning_iteration_checkpoint_ports.rs"]
mod ports;

#[cfg(target_os = "linux")]
#[path = "authority_host_learning_profile.rs"]
mod profile;
#[cfg(target_os = "linux")]
pub use profile::HOST_AUTHORITY_LEARNING_BOOTSTRAP_V1;
#[cfg(target_os = "linux")]
pub use profile::HOST_AUTHORITY_LEARNING_BOOTSTRAP_V2;
#[cfg(target_os = "linux")]
pub use profile::HostAuthorityLearningBootstrapV1;
#[cfg(target_os = "linux")]
pub use profile::HostAuthorityLearningProfileV1;
#[cfg(target_os = "linux")]
pub use profile::HostAuthorityLearningScopeV2;

#[cfg(target_os = "linux")]
#[path = "learning_iteration_checkpoint_transport.rs"]
mod transport;
#[cfg(target_os = "linux")]
pub use transport::AgentdLearningCheckpointClientV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LearningIterationCheckpointErrorV1 {
    Capacity,
    InvalidRecord,
    WrongScope,
    Conflict,
    Store(AuthorityTrustError),
    CommitUncertain(AuthorityTrustError),
    Snapshot(LearningIterationError),
}
impl fmt::Display for LearningIterationCheckpointErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for LearningIterationCheckpointErrorV1 {}
type Error = LearningIterationCheckpointErrorV1;

/// Data for the original broker's separately authorized registration. Merely
/// constructing or deserializing this value grants no storage or role authority.
/// The complete snapshot is inside the same bounded CAS record as its binding;
/// there is no independently replaceable Agent-writable payload file.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LearningIterationCheckpointRecordV1 {
    schema: u8,
    binding: String,
    predecessor: String,
    snapshot: Option<String>,
}

impl LearningIterationCheckpointRecordV1 {
    /// Separate protected profile. Existing schema-1 records cannot be
    /// reinterpreted as scoped or migrated by reopening them.
    pub fn vacant_scoped_v2(
        request: LearningIterationRequestV1,
        owners: LearningIterationOwnersV1,
        scope: &FrozenLearningScopeV2,
    ) -> Result<Self, Error> {
        scope
            .validate_request(&request, &owners)
            .map_err(Error::Snapshot)?;
        let mut record = Self::vacant(request, owners)?;
        record.schema = 2;
        record.binding = scope.binding().to_string();
        Ok(record)
    }

    /// Describe one not-yet-started iteration. Only the existing authorized
    /// broker may register this data; this function performs no registration.
    pub fn vacant(
        request: LearningIterationRequestV1,
        owners: LearningIterationOwnersV1,
    ) -> Result<Self, Error> {
        let initial =
            LearningIterationCoordinatorV1::new(request, owners).map_err(Error::Snapshot)?;
        Ok(Self {
            schema: 1,
            binding: initial.snapshot().head_digest.to_string(),
            predecessor: Digest32::ZERO.to_string(),
            snapshot: None,
        })
    }
}

enum Store {
    Host(HostAuthorityFrontierStore<LearningIterationCheckpointRecordV1>),
    #[cfg(test)]
    Test(std::sync::Arc<dyn AuthorityFrontierStore<LearningIterationCheckpointRecordV1>>),
}

/// Consumes the original concrete Root CAS capability, pinned to one exact
/// request and owner set. Compose it with the original stage owners through
/// `with_stage_owners`; this capability never issues learning attestations.
pub struct LearningIterationCheckpointOwnerV1 {
    owner_id: String,
    store: Store,
    initial: LearningIterationSnapshotV1,
    scope: Option<FrozenLearningScopeV2>,
}

impl LearningIterationCheckpointOwnerV1 {
    #[cfg(target_os = "linux")]
    pub(crate) fn registered_agent_id(&self) -> &str {
        self.initial.request.agent_id.as_str()
    }

    /// An isolated research test's file owner, never a production Root grant.
    #[cfg(test)]
    pub(crate) fn from_research_store(
        store: std::sync::Arc<dyn AuthorityFrontierStore<LearningIterationCheckpointRecordV1>>,
        original_owner_id: String,
        request: LearningIterationRequestV1,
        owners: LearningIterationOwnersV1,
    ) -> Result<Self, Error> {
        let initial =
            LearningIterationCoordinatorV1::new(request, owners).map_err(Error::Snapshot)?;
        let owner = Self {
            owner_id: original_owner_id,
            store: Store::Test(store),
            initial: initial.snapshot().clone(),
            scope: None,
        };
        owner.load()?;
        Ok(owner)
    }

    /// Load the already registered original owner and verify its current data.
    /// Missing, foreign, corrupt or uncertain records never initialize genesis.
    /// The host supplies custody; Device/Notes owners are not interchangeable.
    pub fn from_registered(
        store: HostAuthorityFrontierStore<LearningIterationCheckpointRecordV1>,
        original_owner_id: String,
        request: LearningIterationRequestV1,
        owners: LearningIterationOwnersV1,
    ) -> Result<Self, Error> {
        let initial =
            LearningIterationCoordinatorV1::new(request, owners).map_err(Error::Snapshot)?;
        let owner = Self {
            owner_id: original_owner_id,
            store: Store::Host(store),
            initial: initial.snapshot().clone(),
            scope: None,
        };
        owner.load()?;
        Ok(owner)
    }

    /// Open only a registered schema-2 record with this exact frozen scope.
    /// No schema-1 conversion, migration or re-registration occurs here.
    pub fn from_registered_scoped_v2(
        store: HostAuthorityFrontierStore<LearningIterationCheckpointRecordV1>,
        original_owner_id: String,
        request: LearningIterationRequestV1,
        owners: LearningIterationOwnersV1,
        scope: FrozenLearningScopeV2,
    ) -> Result<Self, Error> {
        scope
            .validate_request(&request, &owners)
            .map_err(Error::Snapshot)?;
        let initial =
            LearningIterationCoordinatorV1::new(request, owners).map_err(Error::Snapshot)?;
        let owner = Self {
            owner_id: original_owner_id,
            store: Store::Host(store),
            initial: initial.snapshot().clone(),
            scope: Some(scope),
        };
        owner.load()?;
        Ok(owner)
    }

    /// Isolated file-backed test custody for the same schema-2 checks.
    #[cfg(test)]
    pub(crate) fn from_research_store_scoped_v2(
        store: std::sync::Arc<dyn AuthorityFrontierStore<LearningIterationCheckpointRecordV1>>,
        original_owner_id: String,
        request: LearningIterationRequestV1,
        owners: LearningIterationOwnersV1,
        scope: FrozenLearningScopeV2,
    ) -> Result<Self, Error> {
        scope
            .validate_request(&request, &owners)
            .map_err(Error::Snapshot)?;
        let initial =
            LearningIterationCoordinatorV1::new(request, owners).map_err(Error::Snapshot)?;
        let owner = Self {
            owner_id: original_owner_id,
            store: Store::Test(store),
            initial: initial.snapshot().clone(),
            scope: Some(scope),
        };
        owner.load()?;
        Ok(owner)
    }

    pub fn frozen_scope_binding(&self) -> Option<Digest32> {
        self.scope.as_ref().map(FrozenLearningScopeV2::binding)
    }

    fn profile_identity(&self) -> (u8, String) {
        match self.frozen_scope_binding() {
            Some(binding) => (2, binding.to_string()),
            None => (1, self.initial.head_digest.to_string()),
        }
    }

    /// Recover only this exact iteration from a fresh durable CURRENT read.
    /// A returned snapshot preserves receipt data, not its separate signatures
    /// or current revocation qualification. The host must still authenticate
    /// through the existing receipt owner interfaces before authorized use.
    pub fn restore(
        &self,
        request: &LearningIterationRequestV1,
    ) -> Result<Option<LearningIterationSnapshotV1>, Error> {
        if request != &self.initial.request {
            return Err(Error::WrongScope);
        }
        self.load().map(|(_, snapshot)| snapshot)
    }

    /// Persist the original initial checkpoint or exactly one following receipt.
    /// An exact retry reads the already committed record without another CAS.
    /// Mutation uncertainty is never converted to an acknowledgement from cache.
    pub fn checkpoint(
        &self,
        expected_head: Digest32,
        next: &LearningIterationSnapshotV1,
    ) -> Result<Digest32, Error> {
        if next.receipts.len() > codec::MAX_RECEIPTS {
            return Err(Error::Capacity);
        }
        if next.request != self.initial.request || next.owners != self.initial.owners {
            return Err(Error::WrongScope);
        }
        LearningIterationCoordinatorV1::from_snapshot(next.clone()).map_err(Error::Snapshot)?;
        if let Some(scope) = &self.scope {
            scope.validate_snapshot(next).map_err(Error::Snapshot)?;
        } else if next.training_no_update_v2().is_some() {
            return Err(Error::WrongScope);
        }
        let predecessor = next
            .receipts
            .last()
            .map_or(Digest32::ZERO, |receipt| receipt.predecessor);
        if predecessor != expected_head {
            return Err(Error::Conflict);
        }
        let (schema, binding) = self.profile_identity();
        let record = LearningIterationCheckpointRecordV1 {
            schema,
            binding,
            predecessor: expected_head.to_string(),
            snapshot: Some(STANDARD_NO_PAD.encode(codec::encode(next)?)),
        };
        let (current, snapshot) = self.load()?;
        if current == record {
            return Ok(next.head_digest);
        }
        match snapshot {
            None if !expected_head.is_zero() || next != &self.initial => {
                return Err(Error::Conflict);
            }
            Some(previous)
                if previous.head_digest != expected_head
                    || next.receipts.len() != previous.receipts.len() + 1
                    || !next.receipts.starts_with(&previous.receipts) =>
            {
                return Err(Error::Conflict);
            }
            None | Some(_) => {}
        }
        // The existing backend serializes and bounds the complete outer Root
        // record before replacement, then fsyncs and reads back under its lock.
        let committed = match &self.store {
            Store::Host(store) => store.compare_and_set(&self.owner_id, &current, &record),
            #[cfg(test)]
            Store::Test(store) => {
                // Keep isolated test custody in its own item for source closure.
                store.compare_and_set(&self.owner_id, &current, &record)
            }
        };
        match committed {
            Ok(()) => Ok(next.head_digest),
            Err(AuthorityTrustError::Conflict) => Err(Error::Conflict),
            Err(error) => Err(Error::CommitUncertain(error)),
        }
    }

    fn load(
        &self,
    ) -> Result<
        (
            LearningIterationCheckpointRecordV1,
            Option<LearningIterationSnapshotV1>,
        ),
        Error,
    > {
        let record = match &self.store {
            Store::Host(store) => store.load(&self.owner_id),
            #[cfg(test)]
            Store::Test(store) => {
                // Keep isolated test custody in its own item for source closure.
                store.load(&self.owner_id)
            }
        }
        .map_err(Error::Store)?;
        let (schema, binding) = self.profile_identity();
        if record.schema != schema || record.binding != binding {
            return Err(Error::WrongScope);
        }
        let Some(encoded) = &record.snapshot else {
            if record.predecessor != Digest32::ZERO.to_string() {
                return Err(Error::InvalidRecord);
            }
            return Ok((record, None));
        };
        if encoded.len() > codec::MAX_BYTES.div_ceil(3) * 4 {
            return Err(Error::Capacity);
        }
        let mut bytes = [0_u8; codec::MAX_BYTES];
        let length = STANDARD_NO_PAD
            .decode_slice(encoded, &mut bytes)
            .map_err(|_| Error::InvalidRecord)?;
        let bytes = &bytes[..length];
        if STANDARD_NO_PAD.encode(bytes) != *encoded {
            return Err(Error::InvalidRecord);
        }
        let snapshot = codec::decode(bytes)?;
        if let Some(scope) = &self.scope {
            scope
                .validate_snapshot(&snapshot)
                .map_err(Error::Snapshot)?;
        } else if snapshot.training_no_update_v2().is_some() {
            return Err(Error::WrongScope);
        }
        if snapshot.request != self.initial.request || snapshot.owners != self.initial.owners {
            return Err(Error::WrongScope);
        }
        let predecessor = snapshot
            .receipts
            .last()
            .map_or(Digest32::ZERO, |receipt| receipt.predecessor);
        if record.predecessor != predecessor.to_string() {
            return Err(Error::InvalidRecord);
        }
        Ok((record, Some(snapshot)))
    }
}

#[cfg(test)]
#[path = "learning_iteration_checkpoint_test_support.rs"]
mod test_support;

#[cfg(test)]
#[path = "learning_iteration_checkpoint_tests.rs"]
mod tests;

#[cfg(all(test, target_os = "linux"))]
#[path = "authority_host_learning_test_support.rs"]
pub(crate) mod learning_test_support;

#[cfg(test)]
#[path = "learning_iteration_checkpoint_ports_tests.rs"]
mod ports_tests;

#[cfg(test)]
#[path = "learning_iteration_checkpoint_profile_tests.rs"]
mod profile_tests;
