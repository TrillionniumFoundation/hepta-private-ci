//! Strict version selection. V1 keeps its original serialized object and
//! exact live binding; only explicit V2 reservations separate durable data.

use codex_hepta_types::Generation;

use super::v2::DIRECTORY_V2;
use super::v2::DurableQ24ModelFactoryProfileV2;
use super::v2::LiveQ24ModelFactoryProfileV2;
use super::v2::OWNER_V2;
use super::v2::PURPOSE_V2;
use super::v2::SOCKET_FILENAME_V2;
use super::v2::WITNESS_FILENAME_V2;
use super::*;

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(untagged)]
pub(crate) enum ReservedFactoryProfile {
    LegacyV1(HostAuthorityQ24ModelFactoryProfileV1),
    DurableV2(DurableQ24ModelFactoryProfileV2),
}

impl ReservedFactoryProfile {
    pub(crate) fn expiry(&self) -> u64 {
        match self {
            Self::LegacyV1(profile) => profile.expiry(),
            Self::DurableV2(profile) => profile.expiry(),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(untagged)]
pub(crate) enum LiveFactoryProfile {
    LegacyV1(HostAuthorityQ24ModelFactoryProfileV1),
    SessionV2(LiveQ24ModelFactoryProfileV2),
}

impl LiveFactoryProfile {
    pub(crate) fn require_context(
        &self,
        identity: &AgentdIdentity,
        proof: &str,
        initial: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
    ) -> io::Result<()> {
        match self {
            Self::LegacyV1(profile) => profile.require_context(identity, proof, initial, scope),
            Self::SessionV2(profile) => LiveQ24ModelFactoryProfileV2::require_live_context(
                profile, identity, proof, initial, scope,
            ),
        }
    }

    pub(crate) fn reserved(&self) -> ReservedFactoryProfile {
        match self {
            Self::LegacyV1(profile) => ReservedFactoryProfile::LegacyV1(profile.clone()),
            Self::SessionV2(profile) => {
                ReservedFactoryProfile::DurableV2(profile.reservation.clone())
            }
        }
    }

    pub(crate) fn require_files(&self, journal: &File, witness: &File) -> io::Result<()> {
        match self {
            Self::LegacyV1(profile) => profile.require_files(journal, witness),
            Self::SessionV2(profile) => profile.reservation.require_files(journal, witness),
        }
    }

    pub(crate) fn require_observers(&self, journal: &File, witness: &File) -> io::Result<()> {
        match self {
            Self::LegacyV1(profile) => profile.require_observers(journal, witness),
            Self::SessionV2(profile) => profile.reservation.require_observers(journal, witness),
        }
    }

    pub(crate) fn require_local_policy(&self, policy: Digest32) -> io::Result<()> {
        match self {
            Self::LegacyV1(profile) => profile.require_local_policy(policy),
            Self::SessionV2(profile) => profile.reservation.require_local_policy(policy),
        }
    }

    pub(crate) fn binding(&self) -> &str {
        match self {
            Self::LegacyV1(profile) => profile.binding(),
            Self::SessionV2(profile) => profile.admission_binding(),
        }
    }

    pub(crate) fn witness_binding(&self) -> &str {
        match self {
            Self::LegacyV1(profile) => profile.binding(),
            Self::SessionV2(profile) => profile.reservation.durable_binding(),
        }
    }

    pub(crate) fn witness_generation(
        &self,
        current_spawn_generation: u64,
    ) -> io::Result<Generation> {
        match self {
            Self::LegacyV1(_) => {
                Generation::new(current_spawn_generation).map_err(io::Error::other)
            }
            Self::SessionV2(profile) => profile.reservation.original_generation(),
        }
    }

    pub(crate) fn expiry(&self) -> u64 {
        match self {
            Self::LegacyV1(profile) => profile.expiry(),
            Self::SessionV2(profile) => profile.reservation.expiry(),
        }
    }

    pub(crate) fn wire_schema(&self) -> u8 {
        match self {
            Self::LegacyV1(_) => 1,
            Self::SessionV2(_) => 2,
        }
    }

    pub(crate) fn purpose(&self) -> &'static str {
        match self {
            Self::LegacyV1(_) => PURPOSE,
            Self::SessionV2(_) => PURPOSE_V2,
        }
    }

    pub(crate) fn directory(&self) -> &'static str {
        match self {
            Self::LegacyV1(_) => DIRECTORY,
            Self::SessionV2(_) => DIRECTORY_V2,
        }
    }

    pub(crate) fn store_owner(&self) -> &'static str {
        match self {
            Self::LegacyV1(_) => OWNER,
            Self::SessionV2(_) => OWNER_V2,
        }
    }

    pub(crate) fn witness_filename(&self) -> &'static str {
        match self {
            Self::LegacyV1(_) => "q24-model-proposal-factory-v1.witness",
            Self::SessionV2(_) => WITNESS_FILENAME_V2,
        }
    }

    pub(crate) fn socket_filename(&self) -> &'static str {
        match self {
            Self::LegacyV1(_) => "q24-model-proposal-factory-v1.sock",
            Self::SessionV2(_) => SOCKET_FILENAME_V2,
        }
    }
}

#[cfg(test)]
#[path = "authority_host_q24_model_profile_variants_tests.rs"]
mod tests;
