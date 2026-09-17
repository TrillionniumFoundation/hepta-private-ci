use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentRecord;

use crate::AgentFault;
use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;
use crate::SupervisorEventKind;
use crate::TickReport;
use crate::runtime::bounded_message;

impl<D: ProcessDriver> Supervisor<D> {
    /// Read exactly one Agent's durable registry state for tick/status hot paths.
    /// Unlike FleetRegistry::load(), this does not enumerate every owner-local
    /// Agent on every process observation.
    pub(crate) fn hot_record(&self, agent_id: &AgentId) -> Result<AgentRecord, SupervisorError> {
        self.registry.load_agent(agent_id).map_err(Into::into)
    }

    /// Advance exactly one Agent supervision slot.
    ///
    /// The public/library `tick()` continues to provide deterministic
    /// whole-fleet advancement. The daemon uses this sliced form so it can
    /// release its global supervisor mutex between Agents; a 256-Agent fleet
    /// therefore does not turn one periodic tick into one monolithic critical
    /// section. Generation and release fences still serialize each selected
    /// Agent before its state can advance.
    pub(crate) fn tick_agent(&mut self, agent_id: &AgentId, now: Instant) -> TickReport {
        let mut report = TickReport::default();
        let Some(mut slot) = self.slots.remove(agent_id) else {
            let error = SupervisorError::UnknownAgent(agent_id.clone());
            report.faults.push(AgentFault {
                agent_id: agent_id.clone(),
                message: bounded_message(error.to_string()),
            });
            return report;
        };

        let result = self.tick_slot(agent_id, &mut slot, now);
        if let Err(error) = result {
            let message = bounded_message(error.to_string());
            let generation = slot
                .runtime
                .as_ref()
                .map(|runtime| runtime.generation)
                .unwrap_or(0);
            slot.event(
                generation,
                SupervisorEventKind::DriverFault(message.clone()),
            );
            report.faults.push(AgentFault {
                agent_id: agent_id.clone(),
                message,
            });
        }
        self.slots.insert(agent_id.clone(), slot);
        report
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;
    use std::time::Duration;

    use codex_hepta_contracts::AgentId;
    use codex_hepta_fleet::FleetRegistry;
    use codex_hepta_paths::HeptaFleetRoot;

    use super::*;
    use crate::AdoptSpec;
    use crate::Adoption;
    use crate::ManagedProcess;
    use crate::MatrixAdoptSpec;
    use crate::MatrixSpawnSpec;
    use crate::ProcessDriverError;
    use crate::ProcessObservation;
    use crate::SpawnSpec;
    use crate::SpawnedProcess;
    use crate::SupervisorConfig;
    use crate::runtime::AgentSlot;

    struct NoopProcess;

    impl ManagedProcess for NoopProcess {
        fn poll(&mut self, _max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
            panic!("no process is created in sliced-tick qualification")
        }

        fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
            Ok(())
        }

        fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
            Ok(())
        }

        fn kill(&mut self) -> Result<(), ProcessDriverError> {
            Ok(())
        }
    }

    #[derive(Default)]
    struct NoopDriver;

    impl ProcessDriver for NoopDriver {
        type Process = NoopProcess;

        fn spawn(
            &mut self,
            _spec: &SpawnSpec,
        ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
            Err(ProcessDriverError::new("unexpected spawn"))
        }

        fn adopt(
            &mut self,
            _spec: &AdoptSpec,
        ) -> Result<Adoption<Self::Process>, ProcessDriverError> {
            Ok(Adoption::Missing)
        }

        fn spawn_matrixd(
            &mut self,
            _spec: &MatrixSpawnSpec,
        ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
            Err(ProcessDriverError::new("unexpected Matrix spawn"))
        }

        fn adopt_matrixd(
            &mut self,
            _spec: &MatrixAdoptSpec,
        ) -> Result<Adoption<Self::Process>, ProcessDriverError> {
            Ok(Adoption::Missing)
        }
    }

    #[test]
    fn sliced_tick_touches_only_the_selected_slot() {
        let temp = tempfile::tempdir().expect("temp fleet");
        let root = HeptaFleetRoot::parse(temp.path().join("fleet")).expect("fleet root");
        let registry = FleetRegistry::initialize(root).expect("registry");
        let config = SupervisorConfig {
            health_timeout: Duration::from_secs(1),
            drain_timeout: Duration::from_secs(1),
            stop_grace: Duration::from_secs(1),
            event_capacity: 8,
            log_capacity: 8,
            max_log_bytes: 128,
            driver_poll_batch: 8,
        };
        let first = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("id");
        let second = AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dd3").expect("id");
        let mut slots = BTreeMap::new();
        slots.insert(first.clone(), AgentSlot::new(&config));
        slots.insert(second.clone(), AgentSlot::new(&config));
        let mut supervisor = Supervisor {
            registry,
            driver: NoopDriver,
            config,
            slots,
            recovery_blocked: Default::default(),
        };
        let second_before = supervisor.snapshot(&second).expect("second slot");
        assert_eq!(
            supervisor.tick_agent(&first, Instant::now()),
            TickReport::default()
        );
        assert_eq!(
            supervisor.snapshot(&second).expect("second slot"),
            second_before,
            "one daemon tick slice must not mutate peer state"
        );
    }
}
