//! A single historical operation keeps its actual owner lock and verified state.
//! Every subsequent observation still checks the complete fresh trust boundary.
use std::fs::File;
use std::sync::Arc;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::AgentId;

use super::ReleaseAuthority;
use super::invalid;
use crate::FleetRegistry;
use crate::FleetRegistryError;
use crate::ReleaseIntentAnchorV1;
use crate::ReleaseIntentPhaseV1;
use crate::release_authority_state::LoadedState;
use crate::release_intent_anchor::AnchorMutation;
use crate::release_registry::ReleaseMode;

/// One non-cloneable historical observation, bound to this agent and owner.
/// It has no current-publication, policy, or process-dispatch capability.
/// Consume it for one historical append, or drop it before another operation.
pub struct ReleaseIntentHistory {
    owner: Arc<ReleaseAuthority>,
    lock: File,
    state: LoadedState,
    agent_id: AgentId,
}

impl FleetRegistry {
    /// Fully replay the authenticated journal and retain its actual File lock.
    /// A missing intent still requires this fresh complete history observation.
    pub fn observe_release_intent_history(
        &self,
        agent_id: &AgentId,
    ) -> Result<ReleaseIntentHistory, FleetRegistryError> {
        let ReleaseMode::Pq(owner) = &self.release_authority else {
            return Err(FleetRegistryError::ReleaseAuthorityRequired);
        };
        let (lock, state, _) = owner.load()?;
        Ok(ReleaseIntentHistory {
            owner: Arc::clone(owner),
            lock,
            state,
            agent_id: agent_id.clone(),
        })
    }
}

impl ReleaseIntentHistory {
    /// Description from this operation's initial full replay, not current use.
    pub fn observed_anchor(&self) -> Option<&ReleaseIntentAnchorV1> {
        self.state.intent_anchors.get(&self.agent_id)
    }

    /// Authenticate fresh frontier, complete journal bytes and trusted time at
    /// the next history boundary, without replaying unchanged signed history.
    pub fn refresh_anchor(&self) -> Result<Option<ReleaseIntentAnchorV1>, FleetRegistryError> {
        self.recheck()?;
        Ok(self.observed_anchor().cloned())
    }

    /// Consume this observation only for strict cold quarantine. It cannot
    /// publish a hot completion, abort, new grant or idempotent terminal state.
    /// The original transition and uncertain-CAS rules still apply.
    pub fn record_quarantine(
        self,
        expected: &ReleaseIntentAnchorV1,
        next: &ReleaseIntentAnchorV1,
    ) -> Result<(), FleetRegistryError> {
        let now = self.recheck()?;
        if expected.agent_id != self.agent_id || next.agent_id != self.agent_id {
            return Err(invalid("historical intent belongs to another agent"));
        }
        if !matches!(
            expected.phase,
            ReleaseIntentPhaseV1::Prepared | ReleaseIntentPhaseV1::Queued
        ) || next.phase != ReleaseIntentPhaseV1::RecoveryRequired
            || next.terminal_witness.is_some()
        {
            return Err(invalid(
                "historical owner only records strict cold quarantine",
            ));
        }
        let Self {
            owner,
            lock: _lock,
            state,
            agent_id: _,
        } = self;
        owner.append_intent(
            state,
            Some(expected),
            next,
            AnchorMutation::Historical,
            now,
            || Ok(()),
        )
    }

    fn recheck(&self) -> Result<u64, FleetRegistryError> {
        if self.owner.fenced.load(Ordering::Acquire) {
            return Err(FleetRegistryError::ReleaseAuthorityRecoveryRequired);
        }
        self.owner.files.recheck_held_lock(&self.lock)?;
        self.owner.recheck_history_state(
            &self.state.frontier,
            self.state.time_floor,
            /*expected_bytes*/ None,
        )
    }
}

#[cfg(all(test, unix))]
#[path = "release_authority_history_owner_tests.rs"]
mod tests;
