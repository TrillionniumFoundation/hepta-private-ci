//! Constructor settlement runs the real recovery and denial orchestration over
//! actual Fleet files; process owners are the existing explicit driver doubles.

use super::*;
use crate::supervisor::constructor_hydration::ConstructorHydrationObservation;
use pretty_assertions::assert_eq;

struct CountedDriver {
    inner: FakeDriver,
    adoptions: usize,
}

impl ProcessDriver for CountedDriver {
    type Process = FakeProcess;

    fn spawn(
        &mut self,
        spec: &SpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        self.inner.spawn(spec)
    }

    fn adopt(&mut self, spec: &AdoptSpec) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        self.adoptions += 1;
        self.inner.adopt(spec)
    }

    fn spawn_matrixd(
        &mut self,
        spec: &MatrixSpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        self.inner.spawn_matrixd(spec)
    }

    fn adopt_matrixd(
        &mut self,
        spec: &MatrixAdoptSpec,
    ) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        self.adoptions += 1;
        self.inner.adopt_matrixd(spec)
    }
}

fn observed_paired_owner() -> Result<
    (
        TestFleet,
        FakeControl,
        Supervisor<CountedDriver>,
        Instant,
        ConstructorHydrationObservation,
    ),
    SupervisorError,
> {
    let fleet = TestFleet::new()?;
    let initial = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .expect("first Agent")
        .clone();
    let mut observation = ConstructorHydrationObservation::default();
    assert!(observation.record_if_idle(&fleet.first, &initial));
    let release_id = ReleaseId::parse("constructor-settlement-pair")?;
    let source = fleet.write_release_source()?;
    fleet.registry.install_release_bundle(
        release_id.clone(),
        &source,
        Vec::new(),
        Some(&source),
        Vec::new(),
    )?;
    fleet.registry.allow_release(&fleet.first, &release_id)?;
    write_matrix_binding(&fleet.registry, &fleet.first, /*revision*/ 1)?;
    let release =
        AgentRelease::try_from(fleet.registry.resolve_release(&fleet.first, &release_id)?)?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, report) = Supervisor::recover(
        fleet.registry.clone(),
        CountedDriver {
            inner: control.driver(),
            adoptions: 0,
        },
        config(),
        now,
    )?;
    assert_eq!(report, TickReport::default());
    supervisor.start_release(&fleet.first, release, now)?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    control.set_matrix_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(supervisor.driver.adoptions, 0);
    Ok((fleet, control, supervisor, now, observation))
}

fn assert_retained_pair(
    fleet: &TestFleet,
    control: &FakeControl,
    supervisor: &Supervisor<CountedDriver>,
    before: &crate::AgentSupervisorSnapshot,
) -> Result<(), SupervisorError> {
    let after = supervisor
        .snapshot(&fleet.first)
        .expect("retained first Agent");
    assert!(after.active && after.matrix.active);
    assert!(!after.healthy && !after.matrix.healthy);
    assert!(after.runtime_fenced);
    assert_eq!(after.process_system_id, before.process_system_id);
    assert_eq!(
        after.matrix.process_system_id,
        before.matrix.process_system_id
    );
    assert_eq!(supervisor.driver.adoptions, 0);
    assert_eq!(control.counts(&fleet.first), (0, 0, 1));
    assert_eq!(control.matrix_counts(&fleet.first), (0, 0, 1));
    assert_eq!(control.spawn_count(&fleet.first), 1);
    assert_eq!(control.matrix_spawn_count(&fleet.first), 1);
    assert!(supervisor.production_recovery_required(&fleet.first)?);
    Ok(())
}

#[test]
fn final_fleet_error_retains_and_fences_previously_owned_main_and_matrix()
-> Result<(), SupervisorError> {
    let (fleet, control, mut supervisor, now, observation) = observed_paired_owner()?;
    let before = supervisor.snapshot(&fleet.first).expect("owned pair");
    assert!(before.healthy && before.matrix.healthy);
    let layout = fleet.registry.layout().agent(&fleet.first);
    let main_lease = layout.run_root().join(crate::lease::PROCESS_LEASE_FILE);
    let main_before = std::fs::read(&main_lease)?;
    let matrix_before = std::fs::read(layout.matrixd_process_lease())?;
    std::fs::write(
        fleet.registry.layout().agent(&fleet.second).agent_config(),
        b"not = [",
    )?;
    let mut report = TickReport::default();
    supervisor.settle_constructor_hydration(observation, now, &mut report);
    assert_eq!(report.faults.len(), 1);
    assert_eq!(report.faults[0].agent_id, fleet.first);
    assert_retained_pair(&fleet, &control, &supervisor, &before)?;
    assert_eq!(std::fs::read(main_lease)?, main_before);
    assert_eq!(
        std::fs::read(layout.matrixd_process_lease())?,
        matrix_before
    );
    Ok(())
}

#[test]
fn changed_observation_never_readopts_an_already_owned_pair() -> Result<(), SupervisorError> {
    let (fleet, control, mut supervisor, now, observation) = observed_paired_owner()?;
    let before = supervisor.snapshot(&fleet.first).expect("owned pair");
    let mut report = TickReport::default();
    supervisor.settle_constructor_hydration(observation, now, &mut report);
    assert_eq!(report.faults.len(), 1);
    assert_retained_pair(&fleet, &control, &supervisor, &before)?;
    Ok(())
}

#[test]
fn generation_only_release_change_runs_fresh_fallback_and_updates_snapshot()
-> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let initial = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .expect("first Agent")
        .clone();
    let mut observation = ConstructorHydrationObservation::default();
    assert!(observation.record_if_idle(&fleet.first, &initial));
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    fleet.registry.compare_and_set_release_state(
        &fleet.first,
        /*expected_generation*/ 0,
        /*current*/ None,
        /*previous*/ None,
    )?;
    let mut report = TickReport::default();
    supervisor.settle_constructor_hydration(observation, now, &mut report);
    assert_eq!(report, TickReport::default());
    let after = supervisor
        .snapshot(&fleet.first)
        .expect("updated first Agent");
    assert_eq!(after.release_state_generation, 1);
    assert!(!after.active && !after.matrix.active && !after.restart_pending);
    assert_eq!(control.spawn_count(&fleet.first), 0);
    assert!(!supervisor.production_recovery_required(&fleet.first)?);
    Ok(())
}

#[test]
fn new_corrupt_signed_witness_runs_fresh_validation_and_denies_recovery()
-> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let initial = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .expect("first Agent")
        .clone();
    let mut observation = ConstructorHydrationObservation::default();
    assert!(observation.record_if_idle(&fleet.first, &initial));
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    let witness = initial
        .layout
        .run_root()
        .join(crate::signed_intent::SIGNED_INTENT_FILE);
    let damaged = b"{not-json}";
    std::fs::write(&witness, damaged)?;
    let mut report = TickReport::default();
    supervisor.settle_constructor_hydration(observation, now, &mut report);
    assert_eq!(report.faults.len(), 1);
    assert!(supervisor.production_recovery_required(&fleet.first)?);
    assert!(supervisor.ensure_mutation_admitted(&fleet.first).is_err());
    assert_eq!(control.spawn_count(&fleet.first), 0);
    assert_eq!(std::fs::read(witness)?, damaged);
    Ok(())
}
