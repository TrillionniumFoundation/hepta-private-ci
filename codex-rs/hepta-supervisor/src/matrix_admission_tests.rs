//! Real Fleet policy changes across companion cleanup, charging and dispatch.

use super::*;

use std::io::ErrorKind;

use codex_hepta_fleet::AgentRecord;
use pretty_assertions::assert_eq;

use crate::AgentSupervisorSnapshot;
use crate::restart_journal::RESTART_JOURNAL_FILE;
use crate::restart_journal::read_restart_journal;
use crate::restart_policy::RESTART_BACKOFF_MIN;

#[derive(Clone, Copy, Debug)]
enum Denial {
    Revoked,
    NotAllowed,
}

fn deny(fleet: &TestFleet, release_id: &ReleaseId, denial: Denial) -> Result<(), SupervisorError> {
    match denial {
        Denial::Revoked => fleet.registry.revoke_release(&fleet.first, release_id)?,
        Denial::NotAllowed => std::fs::remove_file(
            fleet
                .registry
                .load_agent(&fleet.first)?
                .layout
                .releases_root()
                .join(format!("allow-{release_id}.json")),
        )?,
    }
    Ok(())
}

fn journal_bytes(fleet: &TestFleet) -> Result<Option<Vec<u8>>, SupervisorError> {
    let path = fleet
        .registry
        .load_agent(&fleet.first)?
        .layout
        .run_root()
        .join(RESTART_JOURNAL_FILE);
    match std::fs::read(path) {
        Ok(bytes) => Ok(Some(bytes)),
        Err(error) if error.kind() == ErrorKind::NotFound => Ok(None),
        Err(error) => Err(error.into()),
    }
}

#[derive(Debug, Eq, PartialEq)]
struct BudgetObservation {
    attempt: u32,
    window: Option<Instant>,
    wall: Option<u64>,
    retry_at: Option<Instant>,
    exhausted: bool,
}

fn budget(
    supervisor: &mut Supervisor<FakeDriver>,
    agent: &AgentId,
) -> Result<BudgetObservation, SupervisorError> {
    supervisor.with_slot(agent, |_supervisor, slot| {
        Ok(BudgetObservation {
            attempt: slot.matrix.restart_attempt,
            window: slot.matrix.restart_window_started_at,
            wall: slot.matrix.restart_window_started_unix_millis,
            retry_at: slot.matrix.retry_at,
            exhausted: slot.matrix.restart_exhausted,
        })
    })
}

struct RetainedOwners {
    main: AgentSupervisorSnapshot,
    record: AgentRecord,
    peer: AgentSupervisorSnapshot,
    main_lease: crate::lease::ProcessLease,
    peer_main_lease: crate::lease::ProcessLease,
    peer_matrix_lease: crate::lease::MatrixProcessLease,
}

impl RetainedOwners {
    fn capture(
        fleet: &TestFleet,
        supervisor: &Supervisor<FakeDriver>,
    ) -> Result<Self, SupervisorError> {
        let record = fleet.registry.load_agent(&fleet.first)?;
        let peer_record = fleet.registry.load_agent(&fleet.second)?;
        Ok(Self {
            main: supervisor.snapshot(&fleet.first).expect("main snapshot"),
            main_lease: crate::lease::read_lease(record.layout.run_root())?.expect("main lease"),
            peer_main_lease: crate::lease::read_lease(peer_record.layout.run_root())?
                .expect("peer main lease"),
            peer_matrix_lease: crate::lease::read_matrix_lease(
                peer_record.layout.matrixd_process_lease(),
            )?
            .expect("peer Matrix lease"),
            record,
            peer: supervisor.snapshot(&fleet.second).expect("peer snapshot"),
        })
    }

    fn assert_unchanged(
        &self,
        fleet: &TestFleet,
        control: &FakeControl,
        supervisor: &Supervisor<FakeDriver>,
    ) -> Result<(), SupervisorError> {
        let record = fleet.registry.load_agent(&fleet.first)?;
        // Only companion diagnostics/ownership and their bounded events change.
        let mut main = supervisor.snapshot(&fleet.first).expect("main snapshot");
        main.matrix = self.main.matrix.clone();
        main.events = self.main.events.clone();
        assert_eq!(main, self.main);
        assert_eq!(record, self.record);
        assert_eq!(
            crate::lease::read_lease(record.layout.run_root())?,
            Some(self.main_lease.clone())
        );
        assert_eq!(
            supervisor.snapshot(&fleet.second).expect("peer snapshot"),
            self.peer
        );
        let peer_record = fleet.registry.load_agent(&fleet.second)?;
        assert_eq!(
            crate::lease::read_lease(peer_record.layout.run_root())?,
            Some(self.peer_main_lease.clone())
        );
        assert_eq!(
            crate::lease::read_matrix_lease(peer_record.layout.matrixd_process_lease())?,
            Some(self.peer_matrix_lease.clone())
        );
        assert_eq!(control.counts(&fleet.first), (0, 0, 0));
        assert_eq!(control.counts(&fleet.second), (0, 0, 0));
        assert_eq!(control.matrix_counts(&fleet.second), (0, 0, 0));
        assert_eq!(control.spawn_count(&fleet.first), 1);
        assert_eq!(control.spawn_count(&fleet.second), 1);
        assert_eq!(control.matrix_spawn_count(&fleet.second), 1);
        Ok(())
    }
}

fn exit_matrix(
    fleet: &TestFleet,
    control: &FakeControl,
    supervisor: &mut Supervisor<FakeDriver>,
    now: Instant,
) -> Result<Instant, SupervisorError> {
    control.set_matrix_unhealthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(
        supervisor.tick(now + Duration::from_millis(11)),
        TickReport::default()
    );
    assert_eq!(
        supervisor.tick(now + Duration::from_millis(22)),
        TickReport::default()
    );
    assert_eq!(control.matrix_counts(&fleet.first), (0, 1, 1));
    control.set_matrix_exit(&fleet.first);
    let cleanup = now + Duration::from_millis(23);
    assert_eq!(supervisor.tick(cleanup), TickReport::default());
    assert!(
        crate::lease::read_matrix_lease(
            fleet
                .registry
                .load_agent(&fleet.first)?
                .layout
                .matrixd_process_lease()
        )?
        .is_none()
    );
    assert!(
        !supervisor
            .snapshot(&fleet.first)
            .expect("snapshot")
            .matrix
            .active
    );
    Ok(cleanup)
}

// Simulate the real Fleet CAS cut between a main health observation and the
// independent companion continuation. No cached runtime state is fabricated.
fn assert_stale_main_cannot_admit_matrix(
    fleet: &TestFleet,
    control: &FakeControl,
    supervisor: &mut Supervisor<FakeDriver>,
    now: Instant,
) -> Result<(), SupervisorError> {
    let before_budget = budget(supervisor, &fleet.first)?;
    let before_bytes = journal_bytes(fleet)?;
    let before_spawn = control.matrix_spawn_count(&fleet.first);
    let record = fleet.registry.load_agent(&fleet.first)?;
    fleet.registry.compare_and_transition(
        &fleet.first,
        record.lifecycle.generation,
        AgentLifecycle::Draining,
    )?;
    let owners = RetainedOwners::capture(fleet, supervisor)?;
    let mut report = TickReport::default();
    supervisor.with_slot(&fleet.first, |supervisor, slot| {
        supervisor.tick_matrix_companion(&fleet.first, slot, now, &mut report)
    })?;
    assert_eq!(report, TickReport::default());
    assert_eq!(budget(supervisor, &fleet.first)?, before_budget);
    assert_eq!(journal_bytes(fleet)?, before_bytes);
    assert_eq!(control.matrix_spawn_count(&fleet.first), before_spawn);
    owners.assert_unchanged(fleet, control, supervisor)?;
    assert!(
        supervisor
            .snapshot(&fleet.first)
            .expect("snapshot")
            .matrix
            .last_error
            .as_ref()
            .expect("owner admission diagnostic")
            .contains("no longer current and serving")
    );
    // Ordinary next-tick generation fencing still contains the exact owner;
    // the admission rejection itself never signals or grants a new owner.
    assert_eq!(supervisor.tick(now), TickReport::default());
    let main = supervisor
        .snapshot(&fleet.first)
        .expect("retained fenced main");
    assert!(main.active && main.runtime_fenced);
    assert_eq!(main.process_system_id, owners.main.process_system_id);
    assert_eq!(control.counts(&fleet.first), (0, 0, 1));
    assert_eq!(
        crate::lease::read_lease(record.layout.run_root())?,
        Some(owners.main_lease)
    );
    assert_eq!(
        supervisor.snapshot(&fleet.second).expect("peer snapshot"),
        owners.peer
    );
    assert_eq!(budget(supervisor, &fleet.first)?, before_budget);
    assert_eq!(journal_bytes(fleet)?, before_bytes);
    assert_eq!(control.matrix_spawn_count(&fleet.first), before_spawn);
    Ok(())
}

#[test]
fn matrix_exit_policy_denial_preserves_budget_and_readmission_charges_once()
-> Result<(), SupervisorError> {
    for denial in [Denial::Revoked, Denial::NotAllowed] {
        for prior_attempt in [0, 1] {
            let release_id = ReleaseId::parse("matrix-exit-admission")?;
            let (fleet, control, mut supervisor, mut now) =
                ready_paired_supervisor(release_id.as_str())?;
            if prior_attempt == 1 {
                control.set_matrix_exit(&fleet.first);
                assert_eq!(supervisor.tick(now), TickReport::default());
                now += RESTART_BACKOFF_MIN;
                assert_eq!(supervisor.tick(now), TickReport::default());
                control.set_matrix_healthy(&fleet.first);
                assert_eq!(supervisor.tick(now), TickReport::default());
            }
            let owners = RetainedOwners::capture(&fleet, &supervisor)?;
            let before_budget = budget(&mut supervisor, &fleet.first)?;
            assert_eq!(before_budget.attempt, prior_attempt);
            assert_eq!(before_budget.retry_at, None);
            let before_bytes = journal_bytes(&fleet)?;
            let before_spawn = control.matrix_spawn_count(&fleet.first);
            deny(&fleet, &release_id, denial)?;
            // Live companion observations do not ask permission to retain owners.
            assert_eq!(supervisor.tick(now), TickReport::default());
            assert_eq!(
                supervisor.snapshot(&fleet.first).expect("snapshot"),
                owners.main
            );
            let cleanup = exit_matrix(&fleet, &control, &mut supervisor, now)?;
            assert_eq!(budget(&mut supervisor, &fleet.first)?, before_budget);
            assert_eq!(journal_bytes(&fleet)?, before_bytes);
            let retry = cleanup + Duration::from_millis(500);
            assert_eq!(supervisor.tick(retry), TickReport::default());
            assert_eq!(control.matrix_spawn_count(&fleet.first), before_spawn);
            assert_eq!(budget(&mut supervisor, &fleet.first)?, before_budget);
            assert_eq!(journal_bytes(&fleet)?, before_bytes);
            supervisor.with_slot(&fleet.first, |_supervisor, slot| {
                let pending = slot
                    .matrix
                    .retry_admission
                    .as_ref()
                    .expect("uncharged failure");
                assert_eq!(
                    pending.spawn_generation,
                    owners.main.spawn_generation.expect("main generation")
                );
                assert_eq!(pending.release_id, release_id);
                assert!(
                    slot.matrix
                        .last_error
                        .as_ref()
                        .expect("admission diagnostic")
                        .contains("admission rejected")
                );
                Ok(())
            })?;
            owners.assert_unchanged(&fleet, &control, &supervisor)?;
            if matches!(denial, Denial::NotAllowed) {
                fleet.registry.allow_release(&fleet.first, &release_id)?;
                assert_eq!(supervisor.tick(retry), TickReport::default());
                let charged = budget(&mut supervisor, &fleet.first)?;
                let delay = RESTART_BACKOFF_MIN * (1_u32 << prior_attempt);
                assert_eq!(charged.attempt, prior_attempt + 1);
                assert_eq!(charged.retry_at, Some(retry + delay));
                assert_eq!(control.matrix_spawn_count(&fleet.first), before_spawn);
                let journal = read_restart_journal(
                    fleet.registry.load_agent(&fleet.first)?.layout.run_root(),
                )?
                .expect("new retry charge");
                assert_eq!(journal.matrix.attempts, prior_attempt + 1);
                assert_eq!(
                    journal.main,
                    crate::restart_journal::DurableRestartWindow::empty()
                );
                let charged_bytes = journal_bytes(&fleet)?;
                assert_eq!(
                    supervisor.tick(retry + delay - Duration::from_millis(1)),
                    TickReport::default()
                );
                assert_eq!(control.matrix_spawn_count(&fleet.first), before_spawn);
                assert_eq!(supervisor.tick(retry + delay), TickReport::default());
                assert_eq!(control.matrix_spawn_count(&fleet.first), before_spawn + 1);
                assert_eq!(journal_bytes(&fleet)?, charged_bytes);
                assert_eq!(
                    budget(&mut supervisor, &fleet.first)?.attempt,
                    prior_attempt + 1
                );
                owners.assert_unchanged(&fleet, &control, &supervisor)?;
            }
        }
    }
    // An uncharged failure belongs to gen A; fresh gen B's first companion is
    // initialization, not another retry of A. Existing durable claims stay put.
    let release_id = ReleaseId::parse("matrix-pending-owner-change")?;
    let (fleet, control, mut supervisor, now) = ready_paired_supervisor(release_id.as_str())?;
    deny(&fleet, &release_id, Denial::NotAllowed)?;
    let cleanup = exit_matrix(&fleet, &control, &mut supervisor, now)?;
    supervisor.config.stop_grace = Duration::from_secs(5);
    let peer_before = supervisor.snapshot(&fleet.second).expect("peer snapshot");
    let old_generation = supervisor
        .snapshot(&fleet.first)
        .expect("snapshot")
        .spawn_generation;
    supervisor.stop(&fleet.first, cleanup)?;
    control.set_exit(&fleet.first);
    assert_eq!(supervisor.tick(cleanup), TickReport::default());
    fleet.registry.allow_release(&fleet.first, &release_id)?;
    let release =
        AgentRelease::try_from(fleet.registry.resolve_release(&fleet.first, &release_id)?)?;
    let before_bytes = journal_bytes(&fleet)?;
    supervisor.start_release(&fleet.first, release, cleanup)?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(cleanup), TickReport::default());
    let snapshot = supervisor.snapshot(&fleet.first).expect("fresh owner");
    assert_ne!(snapshot.spawn_generation, old_generation);
    assert!(snapshot.matrix.active);
    assert_eq!(snapshot.matrix.restart_attempt, 0);
    assert_eq!(journal_bytes(&fleet)?, before_bytes);
    assert_eq!(control.matrix_spawn_count(&fleet.first), 2);
    assert_eq!(
        supervisor.snapshot(&fleet.second).expect("peer snapshot"),
        peer_before
    );
    assert_eq!(control.counts(&fleet.second), (0, 0, 0));
    assert_eq!(control.matrix_counts(&fleet.second), (0, 0, 0));
    supervisor.with_slot(&fleet.first, |_supervisor, slot| {
        assert!(slot.matrix.retry_admission.is_none());
        Ok(())
    })?;
    let release_id = ReleaseId::parse("matrix-pending-main-fence")?;
    let (fleet, control, mut supervisor, now) = ready_paired_supervisor(release_id.as_str())?;
    deny(&fleet, &release_id, Denial::NotAllowed)?;
    let cleanup = exit_matrix(&fleet, &control, &mut supervisor, now)?;
    fleet.registry.allow_release(&fleet.first, &release_id)?;
    assert_stale_main_cannot_admit_matrix(
        &fleet,
        &control,
        &mut supervisor,
        cleanup + RESTART_BACKOFF_MIN,
    )?;
    assert_eq!(budget(&mut supervisor, &fleet.first)?.attempt, 0);
    Ok(())
}
