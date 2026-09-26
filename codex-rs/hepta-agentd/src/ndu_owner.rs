#[path = "ndu_control.rs"]
mod control;
#[path = "ndu_replay.rs"]
mod replay;

use std::error::Error as StdError;
use std::fmt;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::MutexGuard;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_ndu::ContributionSet;
use codex_hepta_ndu::NduAuthenticatedEvaluationReceiptV1;
use codex_hepta_ndu::NduAuthenticatedOwnerV1;
use codex_hepta_ndu::NduOwnerContextV1;
use codex_hepta_ndu::NduOwnerError;
use codex_hepta_ndu::NduOwnerMutationV1;
use codex_hepta_ndu::NduProductionPolicyV1;
use codex_hepta_ndu::NduProjectionEntryV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use replay::NduExternalReplayStoreV2;

pub struct AgentdNduOwnerBootstrapV1 {
    pub store_root: PathBuf,
    pub authority: FinalUseAuthority,
    pub policy: NduProductionPolicyV1,
}

#[derive(Debug)]
pub enum AgentdNduOwnerErrorV1 {
    InvalidStoreRoot,
    InvalidIdentity,
    IdentityMismatch,
    RevocationAdvanced,
    Poisoned,
    Bootstrap(String),
    Admission(&'static str),
    NotReady,
    Authority(FinalUseError),
    Owner(NduOwnerError),
}

impl fmt::Display for AgentdNduOwnerErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for AgentdNduOwnerErrorV1 {}

impl From<FinalUseError> for AgentdNduOwnerErrorV1 {
    fn from(error: FinalUseError) -> Self {
        Self::Authority(error)
    }
}

impl From<NduOwnerError> for AgentdNduOwnerErrorV1 {
    fn from(error: NduOwnerError) -> Self {
        Self::Owner(error)
    }
}

/// Sole authenticated utility.ndu writer for one Agentd generation.
///
/// Identity, fence, revocation head and production policy are host-owned.
/// Request/wire callers can neither manufacture nor replace them. External V2
/// ingress also passes a durable bounded replay store under the projection
/// owner's process lock before the existing final-use and mutation fences.
pub struct AgentdNduOwnerHostV1 {
    agent_id: AgentId,
    spawn_generation: u64,
    authority: FinalUseAuthority,
    owner: Mutex<NduAuthenticatedOwnerV1>,
    admission_replay: Mutex<NduExternalReplayStoreV2>,
    feed: Option<crate::ndu_process_bootstrap::NduRevocationSourceV1>,
}

impl AgentdNduOwnerHostV1 {
    pub fn open(
        agent_id: AgentId,
        spawn_generation: u64,
        bootstrap: AgentdNduOwnerBootstrapV1,
    ) -> Result<Arc<Self>, AgentdNduOwnerErrorV1> {
        Self::open_with_feed(agent_id, spawn_generation, bootstrap, None)
    }

    pub(crate) fn open_with_feed(
        agent_id: AgentId,
        spawn_generation: u64,
        bootstrap: AgentdNduOwnerBootstrapV1,
        feed: Option<crate::ndu_process_bootstrap::NduRevocationSourceV1>,
    ) -> Result<Arc<Self>, AgentdNduOwnerErrorV1> {
        if spawn_generation == 0 || !bootstrap.store_root.is_absolute() {
            return Err(AgentdNduOwnerErrorV1::InvalidStoreRoot);
        }
        let principal_id = StableId::new(format!("agentd:{}", agent_id.as_str()))
            .map_err(|_| AgentdNduOwnerErrorV1::InvalidIdentity)?;
        let owner_id =
            StableId::new("utility.ndu").map_err(|_| AgentdNduOwnerErrorV1::InvalidIdentity)?;
        let generation = spawn_generation.to_be_bytes();
        let trust_digest = feed
            .as_ref()
            .map_or(Digest32::ZERO, |source| source.trust_digest);
        let principal_scope_digest = Digest32::of_parts(&[
            b"hepta.agentd.ndu.principal-scope.v1\0",
            agent_id.as_str().as_bytes(),
            trust_digest.as_array(),
        ]);
        let fence_digest = Digest32::of_parts(&[
            b"hepta.agentd.ndu.owner-fence.v1\0",
            agent_id.as_str().as_bytes(),
            &generation,
        ]);
        let revocation_frontier_digest = current_frontier(&bootstrap.authority)?;
        let owner = NduAuthenticatedOwnerV1::open(
            &bootstrap.store_root,
            bootstrap.authority.clone(),
            NduOwnerContextV1 {
                principal_id,
                owner_id,
                host_generation: spawn_generation,
                principal_scope_digest,
                fence_digest,
                revocation_frontier_digest,
            },
            bootstrap.policy,
        )?;
        let admission_replay = NduExternalReplayStoreV2::open(&bootstrap.store_root)
            .map_err(|error| {
                AgentdNduOwnerErrorV1::Bootstrap(format!(
                    "external admission replay store: {error}"
                ))
            })?;
        Ok(Arc::new(Self {
            agent_id,
            spawn_generation,
            authority: bootstrap.authority,
            owner: Mutex::new(owner),
            admission_replay: Mutex::new(admission_replay),
            feed,
        }))
    }

    pub fn require_identity(
        &self,
        agent_id: &AgentId,
        spawn_generation: u64,
    ) -> Result<(), AgentdNduOwnerErrorV1> {
        if &self.agent_id != agent_id || self.spawn_generation != spawn_generation {
            return Err(AgentdNduOwnerErrorV1::IdentityMismatch);
        }
        Ok(())
    }

    pub fn context(&self) -> Result<NduOwnerContextV1, AgentdNduOwnerErrorV1> {
        let before = current_frontier(&self.authority)?;
        let mut owner = self.lock_owner()?;
        owner.refresh_revocation_frontier(before)?;
        let context = owner.context().clone();
        drop(owner);
        require_stable_frontier(&self.authority, before)?;
        Ok(context)
    }

    pub fn evaluate(
        &self,
        contributions: ContributionSet,
    ) -> Result<NduAuthenticatedEvaluationReceiptV1, AgentdNduOwnerErrorV1> {
        let before = current_frontier(&self.authority)?;
        let mut owner = self.lock_owner()?;
        owner.refresh_revocation_frontier(before)?;
        let receipt = owner.evaluate(contributions)?;
        drop(owner);
        require_stable_frontier(&self.authority, before)?;
        Ok(receipt)
    }

    pub fn final_use_binding(
        &self,
        mutation: &NduOwnerMutationV1,
    ) -> Result<FinalUseBinding, AgentdNduOwnerErrorV1> {
        let before = current_frontier(&self.authority)?;
        let mut owner = self.lock_owner()?;
        owner.refresh_revocation_frontier(before)?;
        let binding = owner.final_use_binding(mutation)?;
        drop(owner);
        require_stable_frontier(&self.authority, before)?;
        Ok(binding)
    }

    pub fn apply_mutation(
        &self,
        signed: &SignedFinalUseGrant,
        mutation: NduOwnerMutationV1,
    ) -> Result<NduProjectionEntryV1, AgentdNduOwnerErrorV1> {
        let frontier = current_frontier(&self.authority)?;
        let mut owner = self.lock_owner()?;
        owner.refresh_revocation_frontier(frontier)?;
        owner.apply_mutation(signed, mutation).map_err(Into::into)
    }

    pub fn selected_projection_digest(
        &self,
        objective_digest: Digest32,
        subject_digest: Digest32,
    ) -> Result<Option<Digest32>, AgentdNduOwnerErrorV1> {
        let before = current_frontier(&self.authority)?;
        let mut owner = self.lock_owner()?;
        owner.refresh_revocation_frontier(before)?;
        let selected = owner.selected_projection_digest(objective_digest, subject_digest)?;
        drop(owner);
        require_stable_frontier(&self.authority, before)?;
        Ok(selected)
    }

    fn lock_owner(&self) -> Result<MutexGuard<'_, NduAuthenticatedOwnerV1>, AgentdNduOwnerErrorV1> {
        self.owner
            .lock()
            .map_err(|_| AgentdNduOwnerErrorV1::Poisoned)
    }

    fn lock_admission_replay(
        &self,
    ) -> Result<MutexGuard<'_, NduExternalReplayStoreV2>, AgentdNduOwnerErrorV1> {
        self.admission_replay
            .lock()
            .map_err(|_| AgentdNduOwnerErrorV1::Poisoned)
    }
}

fn current_frontier(authority: &FinalUseAuthority) -> Result<Digest32, AgentdNduOwnerErrorV1> {
    Ok(Digest32::from_array(authority.revocation_head_sha256()?))
}

fn require_stable_frontier(
    authority: &FinalUseAuthority,
    expected: Digest32,
) -> Result<(), AgentdNduOwnerErrorV1> {
    if current_frontier(authority)? != expected {
        return Err(AgentdNduOwnerErrorV1::RevocationAdvanced);
    }
    Ok(())
}

#[cfg(all(test, unix))]
#[path = "ndu_owner_tests.rs"]
mod tests;
