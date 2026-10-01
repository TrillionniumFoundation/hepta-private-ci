use std::path::PathBuf;
use std::time::Instant;

use anyhow::Result;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

use super::MatrixRestartRecovery;
use crate::AdoptSpec;
use crate::Adoption;
use crate::ManagedProcess;
use crate::ProcessDriver;
use crate::ProcessDriverError;
use crate::ProcessObservation;
use crate::SpawnSpec;
use crate::SpawnedProcess;
use crate::Supervisor;
use crate::SupervisorConfig;
use crate::SupervisorError;
use crate::restart_budget::RestartBudgetState;
use crate::restart_journal::DurableRestartWindow;
use crate::restart_journal::RESTART_JOURNAL_FILE;
use crate::restart_journal::RestartBudgetJournal;
use crate::restart_journal::read_main_restart_budget;
use crate::restart_journal::read_restart_journal;
use crate::restart_journal::unix_millis_now;
use crate::restart_journal::write_main_restart_budget;
use crate::restart_journal::write_restart_journal;
use crate::restart_policy::RESTART_ATTEMPT_BUDGET;
use crate::restart_policy::RESTART_BACKOFF_MAX;
use crate::restart_policy::RESTART_BACKOFF_MIN;
use crate::restart_policy::RESTART_RECOVERY_WINDOW;
use crate::runtime::AgentSlot;

// These storage/recovery tests intentionally cannot spawn a process. They
// exercise the real registry and public Supervisor::recover entry point.
enum NoProcess {}

impl ManagedProcess for NoProcess {
    fn poll(&mut self, _max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        match *self {}
    }

    fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
        match *self {}
    }

    fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
        match *self {}
    }

    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        match *self {}
    }
}

struct NoDriver;

impl ProcessDriver for NoDriver {
    type Process = NoProcess;

    fn spawn(
        &mut self,
        _spec: &SpawnSpec,
    ) -> Result<SpawnedProcess<NoProcess>, ProcessDriverError> {
        Err(ProcessDriverError::new(
            "unexpected process spawn in recovery-only test",
        ))
    }

    fn adopt(&mut self, _spec: &AdoptSpec) -> Result<Adoption<NoProcess>, ProcessDriverError> {
        Err(ProcessDriverError::new(
            "unexpected process adoption in recovery-only test",
        ))
    }
}

struct Fixture {
    _temp: tempfile::TempDir,
    registry: FleetRegistry,
    agent: AgentId,
    run_root: PathBuf,
}

impl Fixture {
    fn new() -> Result<Self> {
        let temp = tempfile::tempdir()?;
        let root = HeptaFleetRoot::parse(temp.path().join("fleet"))?;
        let registry = FleetRegistry::initialize(root.clone())?;
        let workspace = temp.path().join("workspace");
        std::fs::create_dir(&workspace)?;
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
        registry.register(AgentManifest::new(
            agent.clone(),
            WorkspaceBinding::new(workspace.canonicalize()?, &root)?,
            ResourceBudget::local_default(),
        )?)?;
        let run_root = registry
            .layout()
            .agent(&agent)
            .owner_run_root()
            .to_path_buf();
        std::fs::create_dir_all(&run_root)?;
        Ok(Self {
            _temp: temp,
            registry,
            agent,
            run_root,
        })
    }

    fn write_window(&self, attempts: u32, started: u64) -> Result<()> {
        let journal = RestartBudgetJournal::new(
            self.agent.clone(),
            ReleaseId::parse("persisted-companion-release")?,
            DurableRestartWindow::empty(),
            DurableRestartWindow {
                attempts,
                window_started_unix_millis: Some(started),
            },
        )?;
        write_restart_journal(&self.run_root, &journal)?;
        Ok(())
    }

    fn recover(&self) -> Result<Supervisor<NoDriver>> {
        let (supervisor, report) = Supervisor::recover(
            self.registry.clone(),
            NoDriver,
            SupervisorConfig::local_default(),
            Instant::now(),
        )?;
        assert!(
            report.faults.is_empty(),
            "unexpected process faults: {:?}",
            report.faults
        );
        Ok(supervisor)
    }
}

#[test]
fn public_recovery_preserves_matrix_attempts_without_overwriting_main_projection() -> Result<()> {
    let fixture = Fixture::new()?;
    fixture.write_window(/*attempts*/ 2, unix_millis_now()?)?;
    let supervisor = fixture.recover()?;
    let snapshot = supervisor
        .snapshot(&fixture.agent)
        .expect("registered agent");
    assert_eq!(
        (snapshot.matrix.restart_attempt, snapshot.restart_attempt),
        (2, 0)
    );
    Ok(())
}

#[test]
fn repeated_public_recovery_cannot_buy_a_fresh_matrix_restart_budget() -> Result<()> {
    let fixture = Fixture::new()?;
    fixture.write_window(RESTART_ATTEMPT_BUDGET, unix_millis_now()?)?;
    for _ in 0..3 {
        let supervisor = fixture.recover()?;
        let snapshot = supervisor.snapshot(&fixture.agent).expect("agent");
        assert_eq!(snapshot.matrix.restart_attempt, RESTART_ATTEMPT_BUDGET);
    }
    Ok(())
}

#[test]
fn foreign_companion_journal_is_a_fatal_startup_error() -> Result<()> {
    let fixture = Fixture::new()?;
    let journal = RestartBudgetJournal::new(
        AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dd3")?,
        ReleaseId::parse("foreign-release")?,
        DurableRestartWindow::empty(),
        DurableRestartWindow {
            attempts: 1,
            window_started_unix_millis: Some(unix_millis_now()?),
        },
    )?;
    write_restart_journal(&fixture.run_root, &journal)?;
    let before = std::fs::read(fixture.run_root.join(RESTART_JOURNAL_FILE))?;
    assert!(matches!(
        Supervisor::recover(
            fixture.registry.clone(),
            NoDriver,
            SupervisorConfig::local_default(),
            Instant::now()
        ),
        Err(SupervisorError::CorruptLease(_))
    ));
    assert_eq!(
        std::fs::read(fixture.run_root.join(RESTART_JOURNAL_FILE))?,
        before
    );
    Ok(())
}

#[test]
fn clock_rollback_is_normalized_durably_without_erasing_main_budget() -> Result<()> {
    let fixture = Fixture::new()?;
    let wall = unix_millis_now()?;
    fixture.write_window(/*attempts*/ 1, wall + 600_000)?;
    let main = RestartBudgetState {
        schema_version: 1,
        window_started_unix_ms: wall,
        attempts: 2,
        pending: false,
        next_eligible_unix_ms: wall,
    };
    write_main_restart_budget(&fixture.run_root, &main)?;
    fixture.recover()?;
    let normalized = read_restart_journal(&fixture.run_root)?.expect("durable companion");
    assert_eq!(normalized.matrix.attempts, RESTART_ATTEMPT_BUDGET);
    assert!(
        normalized
            .matrix
            .window_started_unix_millis
            .expect("normalized clock")
            < wall + 600_000
    );
    assert_eq!(read_main_restart_budget(&fixture.run_root)?, Some(main));
    let snapshot = fixture.recover()?.snapshot(&fixture.agent).expect("agent");
    assert_eq!(snapshot.matrix.restart_attempt, RESTART_ATTEMPT_BUDGET);
    Ok(())
}

#[test]
fn expired_matrix_window_is_cleared_durably() -> Result<()> {
    let fixture = Fixture::new()?;
    let expired = unix_millis_now()? - u64::try_from(RESTART_RECOVERY_WINDOW.as_millis())? - 1_000;
    fixture.write_window(RESTART_ATTEMPT_BUDGET, expired)?;
    let supervisor = fixture.recover()?;
    let snapshot = supervisor.snapshot(&fixture.agent).expect("agent");
    assert_eq!(snapshot.matrix.restart_attempt, 0);
    assert_eq!(
        read_restart_journal(&fixture.run_root)?
            .expect("journal")
            .matrix,
        DurableRestartWindow::empty()
    );
    Ok(())
}

#[test]
fn staged_matrix_recovery_reapplies_backoff_once_without_touching_main_state() {
    let mut slot = AgentSlot::<NoProcess>::new(&SupervisorConfig::local_default());
    slot.restart_attempt = 2;
    slot.restart_pending = true;
    let now = Instant::now();
    slot.restart_not_before = Some(now);
    slot.matrix.recovery_budget = Some(MatrixRestartRecovery {
        window: DurableRestartWindow {
            attempts: 2,
            window_started_unix_millis: Some(1_000),
        },
        observed_unix_millis: 1_000,
    });
    slot.matrix.apply_restart_recovery(now);
    assert_eq!(
        (
            slot.restart_attempt,
            slot.restart_pending,
            slot.restart_not_before
        ),
        (2, true, Some(now))
    );
    assert_eq!(
        (
            slot.matrix.restart_attempt,
            slot.matrix.retry_at,
            slot.matrix.restart_exhausted
        ),
        (2, Some(now + RESTART_BACKOFF_MIN * 2), false)
    );
    slot.matrix.restart_attempt = 3;
    slot.matrix
        .apply_restart_recovery(now + RESTART_BACKOFF_MAX);
    assert_eq!(
        (slot.matrix.restart_attempt, slot.matrix.retry_at),
        (3, Some(now + RESTART_BACKOFF_MIN * 2))
    );
}

#[test]
fn staged_exhaustion_blocks_replacement_even_without_a_live_companion() {
    let mut slot = AgentSlot::<NoProcess>::new(&SupervisorConfig::local_default());
    slot.matrix.recovery_budget = Some(MatrixRestartRecovery {
        window: DurableRestartWindow {
            attempts: RESTART_ATTEMPT_BUDGET,
            window_started_unix_millis: Some(1_000),
        },
        observed_unix_millis: 1_000,
    });
    slot.matrix.apply_restart_recovery(Instant::now());
    assert_eq!(
        (
            slot.matrix.restart_attempt,
            slot.matrix.retry_at,
            slot.matrix.restart_exhausted,
            slot.matrix.degraded
        ),
        (RESTART_ATTEMPT_BUDGET, None, true, true)
    );
}

#[cfg(unix)]
#[test]
fn no_matrix_idle_ticks_preserve_bytes_inode_and_main_budget_after_durable_ack() -> Result<()> {
    use std::os::unix::fs::MetadataExt;
    let fixture = Fixture::new()?;
    let main = RestartBudgetState {
        schema_version: crate::restart_budget::RESTART_BUDGET_SCHEMA_VERSION,
        window_started_unix_ms: 1_000,
        attempts: 1,
        pending: false,
        next_eligible_unix_ms: 1_010,
    };
    write_main_restart_budget(&fixture.run_root, &main)?;
    let mut supervisor = fixture.recover()?;
    let config = SupervisorConfig::local_default();
    let mut slot = AgentSlot::<NoProcess>::new(&config);
    slot.active_release = Some(crate::AgentRelease::unversioned(crate::AgentCommand::new(
        "/bin/true",
        Vec::new(),
    )?)?);
    supervisor.start_matrix_companion(&fixture.agent, &mut slot, Instant::now());
    assert!(slot.matrix.durable_restart_ack.is_some());
    let path = fixture.run_root.join(RESTART_JOURNAL_FILE);
    let bytes = std::fs::read(&path)?;
    let inode = std::fs::metadata(&path)?.ino();
    for _ in 0..16 {
        supervisor.start_matrix_companion(&fixture.agent, &mut slot, Instant::now());
    }
    assert_eq!(
        (std::fs::read(&path)?, std::fs::metadata(&path)?.ino()),
        (bytes, inode)
    );
    assert_eq!(read_main_restart_budget(&fixture.run_root)?, Some(main));
    // A new owner cannot infer a directory-sync acknowledgement from bytes.
    let mut cold = AgentSlot::<NoProcess>::new(&config);
    cold.active_release = slot.active_release.clone();
    supervisor.start_matrix_companion(&fixture.agent, &mut cold, Instant::now());
    assert!(cold.matrix.durable_restart_ack.is_some());
    assert_ne!(std::fs::metadata(&path)?.ino(), inode);
    Ok(())
}

#[cfg(unix)]
#[test]
fn visible_matrix_budget_after_failed_directory_sync_keeps_native_retry_obligation() -> Result<()> {
    use std::os::unix::fs::MetadataExt;
    let fixture = Fixture::new()?;
    let mut supervisor = fixture.recover()?;
    let mut slot = AgentSlot::<NoProcess>::new(&SupervisorConfig::local_default());
    slot.active_release = Some(crate::AgentRelease::unversioned(crate::AgentCommand::new(
        "/bin/true",
        Vec::new(),
    )?)?);
    crate::durability::with_qualification_fault(
        "restart_journal.directory_sync",
        std::io::ErrorKind::Other,
        || {
            supervisor.start_matrix_companion(&fixture.agent, &mut slot, Instant::now());
        },
    );
    let path = fixture.run_root.join(RESTART_JOURNAL_FILE);
    let visible = std::fs::read(&path)?;
    assert!(slot.matrix.durable_restart_ack.is_none());
    let retry = crate::durability::with_qualification_fault(
        "restart_journal.file_write",
        std::io::ErrorKind::Other,
        || supervisor.persist_matrix_restart_budget(&fixture.agent, &mut slot),
    );
    assert!(
        retry.is_err(),
        "identical visible bytes must still retry publication"
    );
    assert!(slot.matrix.durable_restart_ack.is_none());
    assert_eq!(std::fs::read(&path)?, visible);
    supervisor.persist_matrix_restart_budget(&fixture.agent, &mut slot)?;
    assert!(slot.matrix.durable_restart_ack.is_some());
    let inode = std::fs::metadata(&path)?.ino();
    supervisor.persist_matrix_restart_budget(&fixture.agent, &mut slot)?;
    assert_eq!(std::fs::metadata(&path)?.ino(), inode);
    // A real release/budget change invalidates the acknowledgement.
    slot.active_release = Some(crate::AgentRelease::new(
        "changed-release",
        crate::AgentCommand::new("/bin/true", Vec::new())?,
    )?);
    slot.matrix.restart_attempt = 1;
    slot.matrix.restart_window_started_unix_millis = Some(unix_millis_now()?);
    supervisor.persist_matrix_restart_budget(&fixture.agent, &mut slot)?;
    assert_ne!(std::fs::metadata(&path)?.ino(), inode);
    assert_eq!(
        read_restart_journal(&fixture.run_root)?,
        slot.matrix.durable_restart_ack
    );
    Ok(())
}
