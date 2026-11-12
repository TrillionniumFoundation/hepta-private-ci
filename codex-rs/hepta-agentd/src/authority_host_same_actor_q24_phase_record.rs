//! Durable once-only claim for the original same-actor A operation.
//! This is Root metadata, never a replacement source, outcome or live owner.

use std::sync::Arc;

use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use std::io;

const RECORD_BOUND: u64 = 64 * 1024;

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PhaseIdentity {
    pub(crate) root: codex_hepta_memory::CognitiveCheckpointPeerLifetime,
    pub(crate) consumer: codex_hepta_memory::CognitiveCheckpointPeerLifetime,
    pub(crate) identity: String,
    pub(crate) writer: String,
    pub(crate) initial: crate::HostGenerationInitialDeploymentV1,
    pub(crate) model_reservation: String,
    pub(crate) root_end_boottime_ns: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PhaseClaim {
    /// Canonical encoding of the real prepared profile, not a new authority.
    pub(crate) learning_profile: String,
    pub(crate) initial_learning_head: String,
    pub(crate) scope: String,
    pub(crate) initial_publication: String,
    pub(crate) current_head: String,
    pub(crate) source_files: String,
    pub(crate) source_binding: CellGenerationOwnerBindingV1,
    pub(crate) source_checkpoint: String,
    pub(crate) source_observation: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
enum PhaseState {
    Reserved,
    Claimed { claim: PhaseClaim },
    Scoped { claim: PhaseClaim, factory: String },
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct PhaseRecord {
    schema_version: u32,
    identity: PhaseIdentity,
    state: PhaseState,
}

/// A failed CAS discards the expected value permanently. It is not retried,
/// and opening the existing record never creates a fresh capability.
pub(crate) struct OriginalPhaseRecord {
    store: HostAuthorityFrontierStore<PhaseRecord>,
    owner: String,
    expected: Option<PhaseRecord>,
}

impl OriginalPhaseRecord {
    pub(crate) fn reserve(
        root: Arc<RootAuthorityDirectory>,
        identity: PhaseIdentity,
    ) -> io::Result<Self> {
        // The key uses the actual A owner, not a caller attempt identifier.
        // A different Root PID or a new scope cannot bypass an existing claim.
        let owner = format!(
            "same-actor-q24-phase/{}",
            Digest32::of_parts(&[
                b"hepta.same-actor-q24-phase.original-a.v1\0",
                &identity.initial.target.digest().map_err(io::Error::other)?,
            ]),
        );
        let initial = PhaseRecord {
            schema_version: 1,
            identity,
            state: PhaseState::Reserved,
        };
        let store = HostAuthorityFrontierStore::initialize_bounded(
            root,
            owner.clone(),
            initial.clone(),
            RECORD_BOUND,
        )
        .map_err(io::Error::other)?;
        if store.load(&owner).map_err(io::Error::other)? != initial {
            return Err(io::Error::other(
                "original phase reservation readback differs",
            ));
        }
        Ok(Self {
            store,
            owner,
            expected: Some(initial),
        })
    }

    pub(crate) fn identity(&self) -> io::Result<&PhaseIdentity> {
        self.expected
            .as_ref()
            .map(|record| &record.identity)
            .ok_or_else(|| io::Error::other("original phase record is uncertain"))
    }

    pub(crate) fn binding(&self) -> io::Result<String> {
        let bytes = serde_json::to_vec(self.identity()?).map_err(io::Error::other)?;
        Ok(
            Digest32::of_parts(&[b"hepta.same-actor-q24-phase.original-session.v1\0", &bytes])
                .to_string(),
        )
    }

    pub(crate) fn claim_before_namespaces(&mut self, claim: PhaseClaim) -> io::Result<()> {
        let before = self
            .expected
            .take()
            .ok_or_else(|| io::Error::other("original phase claim is already uncertain"))?;
        if !matches!(before.state, PhaseState::Reserved) {
            return Err(io::Error::other("original phase was already claimed"));
        }
        if self.store.load(&self.owner).map_err(io::Error::other)? != before {
            return Err(io::Error::other("original phase reservation changed"));
        }
        let next = PhaseRecord {
            schema_version: 1,
            identity: before.identity.clone(),
            state: PhaseState::Claimed { claim },
        };
        self.store
            .compare_and_set(&self.owner, &before, &next)
            .map_err(io::Error::other)?;
        if self.store.load(&self.owner).map_err(io::Error::other)? != next {
            return Err(io::Error::other(
                "original phase claim acknowledgement uncertain",
            ));
        }
        self.expected = Some(next);
        Ok(())
    }

    pub(crate) fn claimed(&self) -> io::Result<&PhaseClaim> {
        match self.expected.as_ref().map(|record| &record.state) {
            Some(PhaseState::Claimed { claim } | PhaseState::Scoped { claim, .. }) => Ok(claim),
            _ => Err(io::Error::other("original durable phase claim is absent")),
        }
    }

    pub(crate) fn require_claimed(&self) -> io::Result<()> {
        let expected = self
            .expected
            .as_ref()
            .ok_or_else(|| io::Error::other("original phase record is uncertain"))?;
        if !matches!(expected.state, PhaseState::Claimed { .. })
            || self.store.load(&self.owner).map_err(io::Error::other)? != *expected
        {
            return Err(io::Error::other(
                "original durable phase claim changed before namespace",
            ));
        }
        Ok(())
    }

    pub(crate) fn mark_scoped_before_rights(&mut self, factory: String) -> io::Result<()> {
        let before = self
            .expected
            .take()
            .ok_or_else(|| io::Error::other("original phase scope is uncertain"))?;
        let PhaseState::Claimed { claim } = &before.state else {
            return Err(io::Error::other("original durable phase claim required"));
        };
        if self.store.load(&self.owner).map_err(io::Error::other)? != before {
            return Err(io::Error::other("original durable phase claim changed"));
        }
        let next = PhaseRecord {
            schema_version: 1,
            identity: before.identity.clone(),
            state: PhaseState::Scoped {
                claim: claim.clone(),
                factory,
            },
        };
        self.store
            .compare_and_set(&self.owner, &before, &next)
            .map_err(io::Error::other)?;
        if self.store.load(&self.owner).map_err(io::Error::other)? != next {
            return Err(io::Error::other(
                "original phase scope acknowledgement uncertain",
            ));
        }
        self.expected = Some(next);
        Ok(())
    }

    pub(crate) fn require_scoped(&self) -> io::Result<()> {
        let expected = self
            .expected
            .as_ref()
            .ok_or_else(|| io::Error::other("original phase record is uncertain"))?;
        if !matches!(expected.state, PhaseState::Scoped { .. })
            || self.store.load(&self.owner).map_err(io::Error::other)? != *expected
        {
            return Err(io::Error::other("original once-only phase scope changed"));
        }
        Ok(())
    }
}
