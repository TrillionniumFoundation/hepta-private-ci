//! The existing root-owned Control CAS backend, with no untrusted store input.

use std::sync::Arc;

use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_neuron::CellGenerationScopeV2;

use super::types::CurrentHead;
use super::types::invalid;
use super::types::scope_digest;
use crate::AgentdError;

pub(super) struct CurrentStore {
    owner_id: String,
    store: Store,
}

enum Store {
    #[cfg(target_os = "linux")]
    RootInitial(crate::root_generation_initial_client::RootGenerationInitialClient),
    #[cfg(target_os = "linux")]
    Root(crate::root_generation_current_client::RootGenerationCurrentClient),
    Host(HostAuthorityFrontierStore<CurrentHead>),
    #[cfg(test)]
    Test {
        store: Arc<dyn AuthorityFrontierStore<CurrentHead>>,
    },
}

impl CurrentStore {
    pub(super) fn initialize(
        root: Arc<RootAuthorityDirectory>,
        head: CurrentHead,
    ) -> Result<Self, AgentdError> {
        let owner_id = owner_id(head.current.scope())?;
        let store = HostAuthorityFrontierStore::initialize(root, owner_id.clone(), head)
            .map_err(invalid)?;
        Ok(Self {
            owner_id,
            store: Store::Host(store),
        })
    }

    pub(super) fn open(
        root: Arc<RootAuthorityDirectory>,
        scope: &CellGenerationScopeV2,
    ) -> Result<Self, AgentdError> {
        let owner_id = owner_id(scope)?;
        let store = HostAuthorityFrontierStore::open(root, owner_id.clone()).map_err(invalid)?;
        Ok(Self {
            owner_id,
            store: Store::Host(store),
        })
    }

    #[cfg(target_os = "linux")]
    pub(super) fn from_original_root(
        original: crate::root_generation_current_client::RootGenerationCurrentClient,
    ) -> Result<Self, AgentdError> {
        Ok(Self {
            owner_id: owner_id(original.scope())?,
            store: Store::Root(original),
        })
    }

    #[cfg(target_os = "linux")]
    pub(super) fn from_original_initial(
        original: crate::root_generation_initial_client::RootGenerationInitialClient,
    ) -> Result<Self, AgentdError> {
        Ok(Self {
            owner_id: owner_id(original.scope())?,
            store: Store::RootInitial(original),
        })
    }

    #[cfg(target_os = "linux")]
    pub(super) fn is_original_host(&self) -> bool {
        matches!(&self.store, Store::Host(_))
    }

    #[cfg(target_os = "linux")]
    pub(super) fn require_original_root_selection(
        &self,
        decision: &codex_hepta_learning_artifacts::LearningIterationSnapshotV1,
        operation: &codex_hepta_types::StableId,
        selection: codex_hepta_types::Digest32,
    ) -> Result<(), AgentdError> {
        match &self.store {
            Store::Root(original) => original.require_selection(decision, operation, selection),
            _ => Err(invalid("original Root publication client required")),
        }
    }

    #[cfg(target_os = "linux")]
    pub(super) fn require_original_root_successor(
        &self,
        session: &crate::root_production_inputs::OriginalQ24SuccessorSession,
        initial: &codex_hepta_learning_artifacts::LearningIterationSnapshotV1,
        scope: &codex_hepta_learning_artifacts::FrozenLearningScopeV2,
    ) -> Result<(), AgentdError> {
        match &self.store {
            Store::Root(original) => original.require_successor_context(session, initial, scope),
            _ => Err(invalid(
                "successor requires the same actual Root update client",
            )),
        }
    }

    pub(super) fn load(&self) -> Result<CurrentHead, AgentdError> {
        let head = match &self.store {
            Store::Host(store) => store.load(&self.owner_id).map_err(invalid)?,
            #[cfg(target_os = "linux")]
            Store::Root(original) => original.observe()?,
            #[cfg(target_os = "linux")]
            Store::RootInitial(original) => original.observe_initial_current()?,
            #[cfg(test)]
            Store::Test { store } => store.load(&self.owner_id).map_err(invalid)?,
        };
        if head.schema_version != 1 || owner_id(head.current.scope())? != self.owner_id {
            return Err(invalid("generation current scope or schema differs"));
        }
        head.current.digest().map_err(invalid)?;
        head.validate_initial()?;
        Ok(head)
    }

    pub(super) fn replace(
        &self,
        expected: &CurrentHead,
        next: &CurrentHead,
    ) -> Result<(), AgentdError> {
        match &self.store {
            Store::Host(store) => store
                .compare_and_set(&self.owner_id, expected, next)
                .map_err(invalid),
            #[cfg(target_os = "linux")]
            Store::Root(original) => original.replace(expected, next),
            #[cfg(target_os = "linux")]
            Store::RootInitial(original) => original.publish_initial_current(expected, next),
            #[cfg(test)]
            Store::Test { store } => store
                .compare_and_set(&self.owner_id, expected, next)
                .map_err(invalid),
        }
    }

    #[cfg(test)]
    pub(super) fn from_test_store(
        scope: &CellGenerationScopeV2,
        store: Arc<dyn AuthorityFrontierStore<CurrentHead>>,
    ) -> Result<Self, AgentdError> {
        Ok(Self {
            owner_id: owner_id(scope)?,
            store: Store::Test { store },
        })
    }
}

fn owner_id(scope: &CellGenerationScopeV2) -> Result<String, AgentdError> {
    let digest = scope_digest(scope)?;
    let hex: String = digest
        .as_array()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    Ok(format!("cell-generation/{hex}"))
}
