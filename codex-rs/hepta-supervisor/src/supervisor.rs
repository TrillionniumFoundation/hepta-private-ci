use std::collections::BTreeMap;
use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentRecord;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_memory::H7SignedArtifactEnvelope;

use crate::AgentCommand;
use crate::AgentFault;
use crate::AgentRelease;
use crate::AgentSupervisorSnapshot;
use crate::ControlReleaseChange;
use crate::ControlReleaseChangePhase;
use crate::ControlRuntimePhase;
use crate::ManagedProcess;
use crate::MatrixSupervisorSnapshot;
use crate::ProcessDriver;
use crate::SupervisorConfig;
use crate::SupervisorError;
use crate::SupervisorEventKind;
use crate::TickReport;
use crate::release_transaction::DurableReleaseTransaction;
use crate::release_transaction::ReleaseTransactionKind;
use crate::release_transaction::ReleaseTransactionPhase;
use crate::release_transaction::read_release_transaction;
use crate::release_transaction::write_release_transaction;
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;
use crate::runtime::bounded_message;
use crate::signed_authority::H7H89ProductionGrant;
use crate::signed_authority::H7H89ProductionGrantVerifier;
use crate::signed_authority::H7H89ProductionTransition;
use crate::signed_authority::ProductionMutationReceipt;
use crate::signed_authority::ProductionMutationState;
use crate::signed_authority::ProductionRecoveryDecision;
use crate::signed_authority::ProductionRecoveryOutcome;
use crate::signed_intent::SignedIntentRecoveryAction;
use crate::signed_intent::SignedIntentStatus;
use crate::signed_intent::SignedSupervisorIntent;
use crate::signed_intent::read_intent;
use crate::signed_intent::read_recovery_directive;
use crate::signed_intent::write_intent;

/// Lifecycle-only controller with one process handle and bounded buffers per agent.
pub struct Supervisor<D: ProcessDriver> {
    pub(crate) registry: FleetRegistry,
    pub(crate) driver: D,
    pub(crate) config: SupervisorConfig,
    slots: BTreeMap<AgentId, AgentSlot<D::Process>>,
}

#[cfg(test)]
#[path = "supervisor_tests.rs"]
mod tests;

impl<D: ProcessDriver> Supervisor<D> {
    pub fn recover(
        registry: FleetRegistry,
        driver: D,
        config: SupervisorConfig,
        now: Instant,
    ) -> Result<(Self, TickReport), SupervisorError> {
        config.validate()?;
        let snapshot = registry.load()?;
        let slots = snapshot
            .agents
            .keys()
            .cloned()
            .map(|agent_id| (agent_id, AgentSlot::new(&config)))
            .collect();
        let mut supervisor = Self {
            registry,
            driver,
            config,
            slots,
        };
        let mut report = TickReport::default();
        for (agent_id, record) in snapshot.agents {
            let result = supervisor.with_slot(&agent_id, |supervisor, slot| {
                // Durable control state is safety-critical and must always be
                // hydrated even when exact process adoption/revalidation
                // reports a per-Agent fault. Otherwise an adoption error could
                // hide a recovery-required signed intent or restart/release
                // fence and incorrectly make the daemon appear ready.
                supervisor.restore_release_state(&agent_id, slot, &record)?;
                let process_fault = supervisor.recover_slot(&agent_id, slot, &record, now).err();
                supervisor.recover_restart_budget(&agent_id, slot, now)?;
                supervisor.recover_release_transaction(&agent_id, slot, now)?;
                supervisor.recover_signed_intent(&agent_id, slot, &record)?;
                Ok(process_fault)
            });
            match result {
                Ok(Some(error)) => supervisor.record_fault(&agent_id, &error, &mut report),
                Ok(None) => {}
                // Corrupt/unreadable durable restart, release or signed-intent
                // state is not an ordinary process fault. Starting without
                // those fences could widen mutation authority, so fail closed.
