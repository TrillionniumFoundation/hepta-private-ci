//! Durable Fleet publication owner backed by M15 and an independently retained
//! PQ-authenticated frontier. Custody/deployment independence is a host premise,
//! not something this adapter can manufacture from local files.

use std::fs::File;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::ReleaseFrontierV1;
use codex_hepta_contracts::authority_trust_unix::UnixPqAuthorityClock;
use codex_hepta_contracts::authority_trust_unix::UnixPqReleaseFrontier;
use codex_hepta_contracts::authority_trust_unix::UnixPqTrustEndpointConfig;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use trnm_release_bundle::pq_release::PqReleaseAuthorityV1;
use trnm_release_bundle::pq_release::PqReleaseRoleV1;
use trnm_release_bundle::pq_release::PqReleaseRootV1;

use crate::FleetRegistryError;
use crate::ReleaseMetadata;
use crate::release_authority_state::Journal;
use crate::release_authority_state::LoadedState;
use crate::release_authority_store::AuthorityFiles;
use crate::release_authority_wire::RootRecord;

#[path = "release_authority_current.rs"]
mod current;
#[path = "release_authority_decision_window.rs"]
mod decision_window;
#[path = "release_authority_intents.rs"]
mod intents;
pub(crate) use decision_window::VerifiedDecisionWindow;
#[path = "release_authority_reconciliation.rs"]
mod reconciliation;
pub(crate) use reconciliation::PendingIntentReconciliation;
#[path = "release_authority_update.rs"]
mod update;

const TRUST_PROFILE: &str = "hepta.fleet.release-trust.pq.v1";

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FleetReleaseTrustConfig {
    pub schema_version: u32,
    pub profile: String,
    pub owner_id: String,
    pub initial_root_sha256: [u8; 32],
    pub network_id: [u8; 32],
    pub platform_sha256: [u8; 32],
    pub clock: UnixPqTrustEndpointConfig,
    pub frontier: UnixPqTrustEndpointConfig,
}

impl FleetReleaseTrustConfig {
    pub fn validate(&self) -> Result<(), FleetRegistryError> {
        if self.schema_version != 1
            || self.profile != TRUST_PROFILE
            || self.owner_id.len() > 128
            || !self
                .owner_id
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:/".contains(&byte))
            || self
                .owner_id
                .strip_prefix("hepta.fleet.release.")
                .is_none_or(str::is_empty)
            || self.initial_root_sha256 == [0; 32]
            || self.network_id == [0; 32]
            || self.platform_sha256 == [0; 32]
        {
            return Err(invalid(
                "unsupported or incomplete out-of-band release trust configuration",
            ));
        }
        Ok(())
    }
}

pub(crate) struct ReleaseAuthority {
    config: FleetReleaseTrustConfig,
    files: AuthorityFiles,
    clock: Arc<dyn AuthorityClock>,
    frontier: Arc<dyn AuthorityFrontierStore<Option<ReleaseFrontierV1>>>,
    fenced: AtomicBool,
    intent_reconciliation_only: bool,
}

impl std::fmt::Debug for ReleaseAuthority {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("ReleaseAuthority")
            .field("owner_id", &self.config.owner_id)
            .finish_non_exhaustive()
    }
}

/// Holds the local publication-owner lock through the actual process dispatch.
/// The metadata itself is still a description; dropping the guard ends this
/// current-use check. Subsequent starts/adoptions require another check.
pub(crate) struct ReleaseUse {
    pub metadata: ReleaseMetadata,
    pub publication: CurrentPublication,
    pub agent_id: Option<AgentId>,
    pub permission_sha256: Option<[u8; 32]>,
}

pub(crate) struct CurrentPublication {
    pub _lock: File,
    pub frontier: ReleaseFrontierV1,
    // Validated state belongs only to this held owner lock. Current-use
    // projection must recheck the fresh frontier, journal hash and clock.
    state: LoadedState,
    role: PqReleaseRoleV1,
    content: [u8; 32],
    pub decision_window: Option<VerifiedDecisionWindow>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PendingUpdate {
    pub schema_version: u32,
    pub expected: Option<ReleaseFrontierV1>,
    pub proposed: ReleaseFrontierV1,
}

impl ReleaseAuthority {
    pub fn open(
        state_root: &Path,
        config: FleetReleaseTrustConfig,
    ) -> Result<Self, FleetRegistryError> {
        let owner = Self::configured(
            AuthorityFiles::open(state_root.join("pq-release-authority-v1"))?,
            config,
        )?;
        let _ = owner.load()?;
        Ok(owner)
    }

    /// Explicit initialization only. Ordinary open never invokes this path and
    /// cannot use an absent frontier to replace an existing journal/history.
    pub fn initialize(
        state_root: &Path,
        config: FleetReleaseTrustConfig,
        root_json: &[u8],
    ) -> Result<Self, FleetRegistryError> {
        if root_json.len() > 256 * 1024 {
            return Err(invalid("release bootstrap root exceeds its bound"));
        }
        config.validate()?;
        let root: RootRecord = serde_json::from_slice(root_json)
            .map_err(|_| invalid("invalid release bootstrap root"))?;
        if root.network_id != config.network_id {
            return Err(invalid("bootstrap root belongs to another network"));
        }
        let owner = Self::configured(
            AuthorityFiles::create(state_root.join("pq-release-authority-v1"))?,
            config,
        )?;
        let _lock = owner.files.lock()?;
        if owner.files.journal_exists()?
            || owner
                .frontier
                .load(&owner.config.owner_id)
                .map_err(|error| invalid(format!("release frontier unavailable: {error}")))?
                .is_some()
        {
            return Err(invalid("release owner is already initialized"));
        }
        let now = owner.now()?;
        let authority = PqReleaseAuthorityV1::bootstrap_pinned(
            PqReleaseRootV1::try_from(&root)?,
            owner.config.initial_root_sha256,
            now,
        )
        .map_err(|error| invalid(format!("M15 bootstrap rejected: {error}")))?;
        let journal = Journal::initial(&owner.config, root, now);
        owner.commit(/*expected*/ None, &journal, authority.checkpoint())?;
        Ok(owner)
    }

    /// Completes only a transaction which the independent owner now proves
    /// committed. An old or different frontier leaves all pending bytes intact;
    /// it never authorizes retrying the CAS or discarding a possible effect.
    pub fn recover_completed(
        state_root: &Path,
        config: FleetReleaseTrustConfig,
    ) -> Result<Self, FleetRegistryError> {
        let owner = Self::configured(
            AuthorityFiles::open(state_root.join("pq-release-authority-v1"))?,
            config,
        )?;
        {
            let _lock = owner.files.recovery_lock()?;
            if owner.files.has_intent_reconciliation()? {
                owner.complete_intent_reconciliation_locked(&_lock)?;
            } else {
                let attempt: PendingUpdate = serde_json::from_slice(&owner.files.attempt()?)
                    .map_err(|_| invalid("invalid retained release attempt"))?;
                let frontier = owner
                    .frontier
                    .load(&owner.config.owner_id)
                    .map_err(|_| FleetRegistryError::ReleaseAuthorityRecoveryRequired)?;
                if attempt.schema_version != 1
                    || frontier != Some(attempt.proposed)
                    || attempt.proposed.initial_root_sha256 != owner.config.initial_root_sha256
                {
                    return Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired);
                }
                let (bytes, proposal_exists) = owner.files.proposed_journal()?;
                if attempt.proposed.state_sha256 != <[u8; 32]>::from(Sha256::digest(&bytes)) {
                    return Err(FleetRegistryError::ReleaseAuthorityRollback);
                }
                let journal: Journal = serde_json::from_slice(&bytes)
                    .map_err(|_| invalid("invalid proposed release journal"))?;
                if journal.previous_frontier != attempt.expected {
                    return Err(FleetRegistryError::ReleaseAuthorityRollback);
                }
                let state = journal.rebuild(&owner.config, attempt.proposed)?;
                if owner.now()? < state.time_floor {
                    return Err(invalid(
                        "release clock regressed behind the committed proposal",
                    ));
                }
                owner.files.finish_completed(proposal_exists)?;
            }
        }
        let _ = owner.load()?;
        Ok(owner)
    }

    fn configured(
        files: AuthorityFiles,
        config: FleetReleaseTrustConfig,
    ) -> Result<Self, FleetRegistryError> {
        config.validate()?;
        let clock = UnixPqAuthorityClock::new(config.clock.clone())
            .map_err(|error| invalid(format!("release clock configuration rejected: {error}")))?;
        let frontier = UnixPqReleaseFrontier::new(config.frontier.clone()).map_err(|error| {
            invalid(format!("release frontier configuration rejected: {error}"))
        })?;
        Ok(Self {
            config,
            files,
            clock: Arc::new(clock),
            frontier: Arc::new(frontier),
            fenced: AtomicBool::new(false),
            intent_reconciliation_only: false,
        })
    }

    fn now(&self) -> Result<u64, FleetRegistryError> {
        Ok(self.now_unix_ms()? / 1000)
    }

    fn now_unix_ms(&self) -> Result<u64, FleetRegistryError> {
        let millis = self
            .clock
            .now_unix_ms()
            .map_err(|error| invalid(format!("release clock unavailable: {error}")))?;
        if millis < 1000 {
            return Err(invalid("release clock is unavailable"));
        }
        Ok(millis)
    }

    fn load(&self) -> Result<(File, LoadedState, u64), FleetRegistryError> {
        if self.fenced.load(Ordering::Acquire) {
            return Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired);
        }
        let lock = self.files.lock()?;
        let (state, now) = self.load_locked(&lock)?;
        Ok((lock, state, now))
    }

    /// The caller retains the actual owner lock, including while refreshing a
    /// consumed admission after its successful external anchor CAS.
    fn load_locked(&self, _lock: &File) -> Result<(LoadedState, u64), FleetRegistryError> {
        if self.fenced.load(Ordering::Acquire) {
            return Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired);
        }
        let external = self
            .frontier
            .load(&self.config.owner_id)
            .map_err(|error| invalid(format!("release frontier unavailable: {error}")))?
            .ok_or(FleetRegistryError::ReleaseAuthorityRollback)?;
        let bytes = self.files.journal()?;
        if external.initial_root_sha256 != self.config.initial_root_sha256
            || external.state_sha256 != <[u8; 32]>::from(Sha256::digest(&bytes))
        {
            return Err(FleetRegistryError::ReleaseAuthorityRollback);
        }
        let journal: Journal = serde_json::from_slice(&bytes)
            .map_err(|_| invalid("invalid release authority journal"))?;
        let state = journal.rebuild(&self.config, external)?;
        let now = self.now()?;
        if now < state.time_floor {
            return Err(invalid("release clock regressed behind committed history"));
        }
        Ok((state, now))
    }
}

pub(crate) fn invalid(message: impl Into<String>) -> FleetRegistryError {
    FleetRegistryError::Invalid(format!("PQ release authority: {}", message.into()))
}
