//! Constructor orchestration and settlement of deferred pure hydration.
//! A final validation fault denies serving without discarding acquired owners.

use std::collections::BTreeSet;
use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentRecord;

use super::constructor_hydration::ConstructorHydration;
use super::constructor_hydration::ConstructorHydrationObservation;
use super::constructor_hydration::idle_slot;
use super::recovery_probe;
use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;
use crate::TickReport;
use crate::runtime::AgentSlot;
use crate::runtime::bounded_message;

impl<D: ProcessDriver> Supervisor<D> {
    pub(super) fn recover_constructor_slot(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        record: &AgentRecord,
        now: Instant,
        hydration: ConstructorHydration<'_>,
    ) -> Vec<SupervisorError> {
        let mut faults = self.validate_durable_recovery(agent_id, record);
        if let Err(error) = self.restore_release_state(agent_id, slot, record) {
            faults.push(error);
        }
        // Decode and bind signed denial before adoption can replay a control
        // or an unsigned transaction/restart can drive another process effect.
        // This read performs no CAS, journal publication or process operation.
        if let Err(error) = self.prime_signed_recovery_denial(agent_id, slot, record) {
            faults.push(error);
        }
        if let Some(error) = faults.first() {
            // Deny semantic replay before acquisition, while leaving
            // both independent lease-bound adoption attempts enabled.
            slot.recovery_blocker = Some(bounded_message(error.to_string()));
        }
        // Even failed semantic preparation cannot skip independent
        // lease-bound acquisition of main and Matrix ownership.
        if let Err(error) = self.recover_slot(agent_id, slot, record, now, hydration) {
            faults.push(error);
        }
        // A failed signal on an admitted, exact owned incarnation is
        // a control retry, not corrupt durable recovery evidence.
        // recover_slot marks all admission/hydration failures itself.
        for (restore, evidence_present) in [
            Self::recover_restart_budget,
            Self::recover_release_transaction,
        ]
        .into_iter()
        .zip([
            recovery_probe::restart_required(record.layout.run_root()),
            recovery_probe::release_required(record.layout.run_root()),
        ]) {
            if slot.recovery_blocker.is_some() {
                break;
            }
            if !evidence_present {
                continue;
            }
            if let Err(error) = restore(self, agent_id, slot, now) {
                if !Self::recovery_control_fault_is_retryable(slot, &error) {
                    slot.recovery_blocker = Some(bounded_message(error.to_string()));
                }
                faults.push(error);
            }
        }
        // A retryable release Drain must not hide independent signed
        // authority recovery. Its exact staged control remains owned.
        if slot.recovery_blocker.is_none()
            && let Err(error) = self.recover_signed_intent(agent_id, slot, record)
        {
            slot.recovery_blocker = Some(bounded_message(error.to_string()));
            faults.push(error);
        }
        if slot.recovery_blocker.is_some()
            && let Some(error) = faults.first()
        {
            self.deny_failed_recovery(agent_id, slot, error, now);
        }
        faults
    }

    pub(super) fn settle_constructor_hydration(
        &mut self,
        observation: ConstructorHydrationObservation,
        now: Instant,
        report: &mut TickReport,
    ) {
        let changed = match observation.changed_agents(&self.registry) {
            Ok(changed) => changed,
            Err(error) => {
                // A failed global consistency check cannot return Err and drop
                // any main or Matrix owner already acquired during recovery.
                for agent_id in observation.agents() {
                    self.deny_constructor_observation(agent_id, &error, now, report);
                }
                return;
            }
        };
        let mut changed: BTreeSet<_> = changed.into_iter().collect();
        for agent_id in observation.agents() {
            if self.slots.get(agent_id).is_none_or(|slot| !idle_slot(slot)) {
                changed.insert(agent_id.clone());
            }
        }
        for agent_id in changed {
            // A new lease may have been acquired after the absence observation.
            // Re-adoption would replace the only owned handle. Retain it and
            // deny this constructor instead of replaying ownership acquisition.
            if self
                .slots
                .get(&agent_id)
                .is_none_or(|slot| !idle_slot(slot))
            {
                let error = SupervisorError::Invalid(
                    "constructor idle observation changed after process recovery; fresh recovery required"
                        .to_string(),
                );
                self.deny_constructor_observation(&agent_id, &error, now, report);
                continue;
            }
            let record = match self.record(&agent_id) {
                Ok(record) => record,
                Err(error) => {
                    self.deny_constructor_observation(&agent_id, &error, now, report);
                    continue;
                }
            };
            let result = self.with_slot(&agent_id, |supervisor, slot| {
                Ok(supervisor.recover_constructor_slot(
                    &agent_id,
                    slot,
                    &record,
                    now,
                    ConstructorHydration::Fresh,
                ))
            });
            match result {
                Ok(faults) => {
                    for error in faults {
                        self.record_fault(&agent_id, &error, report);
                    }
                }
                Err(error) => self.record_fault(&agent_id, &error, report),
            }
        }
    }

    fn deny_constructor_observation(
        &mut self,
        agent_id: &AgentId,
        error: &SupervisorError,
        now: Instant,
        report: &mut TickReport,
    ) {
        let result = self.with_slot(agent_id, |supervisor, slot| {
            supervisor.deny_failed_recovery(agent_id, slot, error, now);
            Ok(())
        });
        self.record_fault(agent_id, error, report);
        if let Err(error) = result {
            self.record_fault(agent_id, &error, report);
        }
    }
}
