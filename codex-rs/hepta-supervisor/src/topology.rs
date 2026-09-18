//! Governed topology/source candidate admission into the real Supervisor.

use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentRecord;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_fleet::RuntimeTopologyCandidateV1;
use codex_hepta_fleet::RuntimeTopologyStageV1;
use codex_hepta_fleet::runtime_module_binding_digest_v1;

use crate::AgentRelease;
use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;
use crate::topology_candidate::append_topology_candidate;

impl<D: ProcessDriver> Supervisor<D> {
    pub fn runtime_topology_snapshot(
        &self,
        agent_id: &AgentId,
    ) -> Result<(u64, String), SupervisorError> {
        let slot = self
            .slots
            .get(agent_id)
            .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))?;
        let modules = slot.runtime_modules.as_ref().ok_or_else(|| {
            SupervisorError::Invalid(format!("agent {agent_id} has no runtime module set"))
        })?;
        Ok((modules.topology_generation(), modules.snapshot_digest()))
    }

    pub fn topology_candidate(
        &self,
        agent_id: &AgentId,
    ) -> Result<Option<RuntimeTopologyCandidateV1>, SupervisorError> {
        Ok(self
            .slots
            .get(agent_id)
            .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))?
            .topology_candidate
            .clone())
    }

    pub fn stage_topology_candidate(
        &mut self,
        agent_id: &AgentId,
        candidate: RuntimeTopologyCandidateV1,
    ) -> Result<(), SupervisorError> {
        candidate
            .validate_recovered()
            .map_err(module_error)?;
        if candidate.stage != RuntimeTopologyStageV1::Proposed {
            return Err(invalid("topology candidate must enter Supervisor at Proposed"));
        }
        let target_id = ReleaseId::parse(candidate.target_release.clone())?;
        let _ = self.registry.resolve_release(agent_id, &target_id)?;

        self.with_slot(agent_id, |supervisor, slot| {
            require_stable_running_runtime(agent_id, slot)?;
            let active = slot
                .active_release
                .as_ref()
                .ok_or_else(|| invalid("topology candidate requires an active release"))?;
            if active.identity() != candidate.predecessor_release {
                return Err(invalid("topology predecessor release does not match active release"));
            }
            if slot.topology_candidate.as_ref().is_some_and(|current| {
                !matches!(
                    current.stage,
                    RuntimeTopologyStageV1::Promoted
                        | RuntimeTopologyStageV1::RolledBack
                        | RuntimeTopologyStageV1::Rejected
                )
            }) {
                return Err(invalid("another topology candidate is still unresolved"));
            }
            let modules = slot
                .runtime_modules
                .as_ref()
                .ok_or_else(|| invalid("runtime module set is unavailable"))?;
            if modules.topology_generation() != candidate.predecessor_generation
                || modules.snapshot_digest() != candidate.predecessor_topology_digest
            {
                return Err(invalid("topology candidate predecessor does not match running snapshot"));
            }
            supervisor.append_candidate(agent_id, &candidate)?;
            slot.topology_candidate = Some(candidate);
            Ok(())
        })
    }

    pub fn enter_topology_shadow(
        &mut self,
        agent_id: &AgentId,
        qualification_digest: String,
    ) -> Result<(), SupervisorError> {
        self.with_slot(agent_id, |supervisor, slot| {
            require_stable_running_runtime(agent_id, slot)?;
            let mut candidate = slot
                .topology_candidate
                .clone()
                .ok_or_else(|| invalid("no topology candidate"))?;
            candidate
                .enter_shadow(qualification_digest)
                .map_err(module_error)?;
            supervisor.append_candidate(agent_id, &candidate)?;
            slot.topology_candidate = Some(candidate);
            Ok(())
        })
    }

    pub fn start_topology_canary(
        &mut self,
        agent_id: &AgentId,
        selection_digest: String,
        observation_digest: String,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        let candidate = self
            .topology_candidate(agent_id)?
            .ok_or_else(|| invalid("no topology candidate"))?;
        if candidate.stage != RuntimeTopologyStageV1::Shadow {
            return Err(invalid("topology canary requires Shadow stage"));
        }
        let target_id = ReleaseId::parse(candidate.target_release.clone())?;
        let target = AgentRelease::try_from(self.registry.resolve_release(agent_id, &target_id)?)?;
        self.preflight_upgrade(agent_id, &target)?;

        self.with_slot(agent_id, |supervisor, slot| {
            let modules = slot
                .runtime_modules
                .as_ref()
                .ok_or_else(|| invalid("runtime module set is unavailable"))?;
            if modules.topology_generation() != candidate.predecessor_generation
                || modules.snapshot_digest() != candidate.predecessor_topology_digest
            {
                return Err(invalid("running topology moved before canary admission"));
            }
            let mut next = candidate.clone();
            next.enter_canary(selection_digest, observation_digest)
                .map_err(module_error)?;
            supervisor.append_candidate(agent_id, &next)?;
            slot.topology_candidate = Some(next);
            supervisor.upgrade_slot(agent_id, slot, target, now, false)
        })
    }

    pub fn confirm_topology_promotion(
        &mut self,
        agent_id: &AgentId,
        confirmation_digest: String,
    ) -> Result<(), SupervisorError> {
        self.with_slot(agent_id, |supervisor, slot| {
            require_stable_running_runtime(agent_id, slot)?;
            if slot.release_change.is_some() {
                return Err(SupervisorError::ReleaseChangePending(agent_id.clone()));
            }
            let mut candidate = slot
                .topology_candidate
                .clone()
                .ok_or_else(|| invalid("no topology candidate"))?;
            if slot
                .active_release
                .as_ref()
                .is_none_or(|release| release.identity() != candidate.target_release)
            {
                return Err(invalid("canary release is not the active release"));
            }
            let modules = slot
                .runtime_modules
                .as_ref()
                .ok_or_else(|| invalid("runtime module set is unavailable"))?;
            if modules.topology_generation() != candidate.candidate_generation {
                return Err(invalid("runtime topology generation does not match canary candidate"));
            }
            candidate.promote(confirmation_digest).map_err(module_error)?;
            supervisor.append_candidate(agent_id, &candidate)?;
            slot.topology_candidate = Some(candidate);
            Ok(())
        })
    }

    pub fn request_topology_rollback(
        &mut self,
        agent_id: &AgentId,
        regression_digest: String,
        rollback_generation: u64,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        let candidate = self
            .topology_candidate(agent_id)?
            .ok_or_else(|| invalid("no topology candidate"))?;
        if !matches!(
            candidate.stage,
            RuntimeTopologyStageV1::Canary | RuntimeTopologyStageV1::Promoted
        ) {
            return Err(invalid("topology rollback requires Canary or Promoted stage"));
        }
        let target = self
            .slots
            .get(agent_id)
            .and_then(|slot| slot.previous_release.clone())
            .ok_or_else(|| SupervisorError::NoPreviousRelease(agent_id.clone()))?;
        if target.identity() != candidate.predecessor_release {
            return Err(invalid("recorded rollback release is not the topology predecessor"));
        }
        self.preflight_upgrade(agent_id, &target)?;

        self.with_slot(agent_id, |supervisor, slot| {
            let mut next = candidate.clone();
            next.request_rollback(regression_digest, rollback_generation)
                .map_err(module_error)?;
            supervisor.append_candidate(agent_id, &next)?;
            slot.topology_candidate = Some(next);
            supervisor.upgrade_slot(agent_id, slot, target, now, true)
        })
    }

    pub fn reject_topology_candidate(
        &mut self,
        agent_id: &AgentId,
        observation_digest: String,
    ) -> Result<(), SupervisorError> {
        self.with_slot(agent_id, |supervisor, slot| {
            if slot.release_change.is_some() {
                return Err(SupervisorError::ReleaseChangePending(agent_id.clone()));
            }
            let mut candidate = slot
                .topology_candidate
                .clone()
                .ok_or_else(|| invalid("no topology candidate"))?;
            if slot
                .active_release
                .as_ref()
                .is_some_and(|release| release.identity() == candidate.target_release)
            {
                return Err(invalid("active canary must be rolled back, not paper-rejected"));
            }
            candidate.reject(observation_digest).map_err(module_error)?;
            supervisor.append_candidate(agent_id, &candidate)?;
            slot.topology_candidate = Some(candidate);
            Ok(())
        })
    }

    pub(crate) fn commit_topology_rollback_if_pending(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
    ) -> Result<(), SupervisorError> {
        let Some(mut candidate) = slot.topology_candidate.clone() else {
            return Ok(());
        };
        if candidate.stage != RuntimeTopologyStageV1::RollbackRequested {
            return Ok(());
        }
        if slot
            .active_release
            .as_ref()
            .is_none_or(|release| release.identity() != candidate.predecessor_release)
        {
            return Err(invalid("rollback became healthy on an unexpected release"));
        }
        let restored = candidate.rollback_predecessor_digest.clone();
        candidate.mark_rolled_back(&restored).map_err(module_error)?;
        self.append_candidate(agent_id, &candidate)?;
        slot.topology_candidate = Some(candidate);
        Ok(())
    }

    pub(crate) fn reject_topology_candidate_after_automatic_rollback(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        failed_release: &str,
        generation: u64,
    ) -> Result<(), SupervisorError> {
        let Some(mut candidate) = slot.topology_candidate.clone() else {
            return Ok(());
        };
        if candidate.stage != RuntimeTopologyStageV1::Canary
            || candidate.target_release != failed_release
        {
            return Ok(());
        }
        if slot
            .active_release
            .as_ref()
            .is_none_or(|release| release.identity() != candidate.predecessor_release)
        {
            return Err(invalid("automatic rollback did not restore topology predecessor release"));
        }
        let generation = generation.to_string();
        let observation = runtime_module_binding_digest_v1(&[
            "topology-canary-automatic-rollback",
            agent_id.as_str(),
            failed_release,
            &generation,
        ]);
        candidate.reject(observation).map_err(module_error)?;
        self.append_candidate(agent_id, &candidate)?;
        slot.topology_candidate = Some(candidate);
        Ok(())
    }

    pub(crate) fn reconcile_topology_candidate_after_recovery(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
    ) -> Result<(), SupervisorError> {
        let Some(candidate) = slot.topology_candidate.as_ref() else {
            return Ok(());
        };
        if candidate.stage != RuntimeTopologyStageV1::RollbackRequested
            || record.lifecycle.lifecycle != AgentLifecycle::Running
        {
            return Ok(());
        }
        let current = record.release_state.current.as_ref().map(ReleaseId::as_str);
        let previous = record.release_state.previous.as_ref().map(ReleaseId::as_str);
        if current == Some(candidate.predecessor_release.as_str())
            && previous == Some(candidate.target_release.as_str())
        {
            self.commit_topology_rollback_if_pending(agent_id, slot)?;
        }
        Ok(())
    }

    fn append_candidate(
        &self,
        agent_id: &AgentId,
        candidate: &RuntimeTopologyCandidateV1,
    ) -> Result<(), SupervisorError> {
        let record = self.record(agent_id)?;
        append_topology_candidate(record.layout.run_root(), candidate)
    }
}

pub(crate) fn topology_generation_for_release<P>(
    slot: &AgentSlot<P>,
    release: &str,
    fallback: u64,
) -> u64 {
    let Some(candidate) = slot.topology_candidate.as_ref() else {
        return fallback;
    };
    if release == candidate.target_release
        && matches!(
            candidate.stage,
            RuntimeTopologyStageV1::Canary | RuntimeTopologyStageV1::Promoted
        )
    {
        return candidate.candidate_generation;
    }
    if release == candidate.predecessor_release
        && matches!(
            candidate.stage,
            RuntimeTopologyStageV1::RollbackRequested | RuntimeTopologyStageV1::RolledBack
        )
    {
        return candidate.rollback_generation.unwrap_or(fallback);
    }
    fallback
}

fn require_stable_running_runtime<P>(
    agent_id: &AgentId,
    slot: &AgentSlot<P>,
) -> Result<(), SupervisorError> {
    let runtime = slot
        .runtime
        .as_ref()
        .ok_or_else(|| invalid(format!("agent {agent_id} has no active runtime")))?;
    if !runtime.healthy || runtime.fenced || !matches!(runtime.phase, RuntimePhase::Running) {
        return Err(invalid("topology operation requires a healthy unfenced running runtime"));
    }
    Ok(())
}

fn module_error(error: codex_hepta_fleet::RuntimeModuleErrorV1) -> SupervisorError {
    invalid(format!("topology candidate: {error}"))
}

fn invalid(message: impl Into<String>) -> SupervisorError {
    SupervisorError::Invalid(message.into())
}
