//! Release admission after exact process adoption retains ownership on failure.

use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentRecord;
use codex_hepta_fleet::FleetRegistryError;
use codex_hepta_fleet::RegisteredRelease;

use crate::AgentRelease;
use crate::ManagedProcess;
use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;
use crate::SupervisorEventKind;
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;
use crate::runtime::is_live_lifecycle;

impl<D: ProcessDriver> Supervisor<D> {
    /// Consume the catalog result only after the caller installed the owned handle.
    /// A rejected release grants termination of that handle, never replacement.
    pub(super) fn bind_adopted_release(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
        resolved: Result<RegisteredRelease, FleetRegistryError>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        let runtime = slot.runtime.as_ref().ok_or_else(|| {
            SupervisorError::Invalid("release recovery requires an owned process".to_string())
        })?;
        if runtime.fenced {
            return Err(SupervisorError::Invalid(
                "a fenced adopted process cannot regain release admission".to_string(),
            ));
        }
        let expected_release = runtime.release_id.clone();
        let admitted = resolved.map_err(SupervisorError::from).and_then(|release| {
            if release.release_id != expected_release {
                return Err(SupervisorError::CorruptLease(
                    "resolved release differs from the adopted process lease".to_string(),
                ));
            }
            AgentRelease::try_from(release)
        });
        match admitted {
            Ok(release) => {
                // Conversion of the whole bundle succeeds before any metadata changes.
                slot.previous_release = slot.active_release.take();
                slot.last_command = Some(release.command().clone());
                slot.active_release = Some(release);
                Ok(())
            }
            Err(error) => {
                let runtime = slot.runtime.as_mut().ok_or_else(|| {
                    SupervisorError::Invalid("adopted process ownership was lost".to_string())
                })?;
                runtime.healthy = false;
                runtime.fenced = true;
                let generation = runtime.generation;
                let kill_requested = runtime.process.kill().is_ok();
                runtime.phase = if kill_requested {
                    RuntimePhase::Killing
                } else {
                    RuntimePhase::Stopping { deadline: now }
                };
                slot.pending_control = None;
                if kill_requested {
                    slot.event(generation, SupervisorEventKind::KillRequested);
                }
                // Neither signal failure nor a subsequent registry CAS failure
                // may drop the process or remove its lease before observed exit.
                if is_live_lifecycle(record.lifecycle.lifecycle) {
                    let failed = self.transition_without_runtime(
                        agent_id,
                        slot,
                        record.lifecycle.generation,
                        AgentLifecycle::Failed,
                    )?;
                    if let Some(runtime) = slot.runtime.as_mut() {
                        runtime.generation = failed;
                    }
                }
                Err(error)
            }
        }
    }
}

#[cfg(test)]
#[path = "adopted_release_tests.rs"]
mod tests;
