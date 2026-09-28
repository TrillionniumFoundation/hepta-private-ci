//! Existing journal/registry owners exercised with filesystem cuts and explicit
//! process doubles. These tests do not constitute target-host fault evidence.

use super::*;
use std::sync::Arc;
use std::sync::Mutex;

use anyhow::Result;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::AgentRecord;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;

use crate::AdoptSpec;
use crate::Adoption;
use crate::AgentCommand;
use crate::AgentRelease;
use crate::ManagedProcess;
use crate::ProcessDriver;
use crate::ProcessDriverError;
use crate::ProcessObservation;
use crate::ProcessState;
use crate::SpawnSpec;
use crate::SpawnedProcess;
use crate::Supervisor;
use crate::SupervisorConfig;
use crate::lease::PROCESS_LEASE_SCHEMA_VERSION;
use crate::lease::ProcessLease;
use crate::lease::write_lease;
use crate::restart_budget::claim_restart;
use crate::restart_budget::pending_restart;
use crate::restart_journal::DurableRestartWindow;
use crate::restart_journal::RESTART_JOURNAL_FILE;
use crate::restart_journal::RestartBudgetJournal;
use crate::restart_journal::read_main_restart_budget;
use crate::restart_journal::read_restart_journal;
use crate::restart_journal::write_restart_journal;
use crate::runtime::AgentRuntime;
use crate::runtime::AgentSlot;
use crate::runtime::MatrixRuntime;
use crate::runtime::MatrixRuntimePhase;
use crate::runtime::RuntimePhase;

fn agent() -> AgentId {
    AgentId::parse("00000000-0000-4000-8000-000000000001").expect("agent")
}

fn identity() -> ProcessIdentity {
    ProcessIdentity::new(41, "exact-main-lifetime").expect("identity")
}

fn pending(root: &Path) -> Result<()> {
    claim_restart(root, 3, Duration::from_secs(300), Duration::from_millis(250))?;
    Ok(())
}

fn prepare_override(root: &Path, kind: DurableControlKind) -> Result<()> {
    match kind {
        DurableControlKind::Stop => {
            prepare_stop(root, &agent(), 7, &identity(), 8, Duration::from_secs(5))?;
        }
        DurableControlKind::Kill => prepare_kill(root, &agent(), 7, &identity(), 8)?,
    }
    Ok(())
}

#[test]
fn prepare_cancellation_cut_is_closed_before_stop_or_kill_completion() -> Result<()> {
    for kind in [DurableControlKind::Stop, DurableControlKind::Kill] {
        let dir = tempfile::tempdir()?;
        pending(dir.path())?;
        let before = read_main_restart_budget(dir.path())?.expect("pending budget");
        prepare_override(dir.path(), kind)?;
        // Construct the crash cut: override exists, cancellation has not run,
        // and the already-exited process has no lease after owner cleanup.
        assert!(pending_restart(dir.path(), 3)?.is_some());
        reconcile_absent(dir.path(), &agent(), AgentLifecycle::Stopped)?;
        assert!(!has_unresolved(dir.path())?);
        assert!(pending_restart(dir.path(), 3)?.is_none());
        let after = read_main_restart_budget(dir.path())?.expect("history retained");
        assert_eq!(after.attempts, before.attempts);
        assert_eq!(after.window_started_unix_ms, before.window_started_unix_ms);
        assert_eq!(after.next_eligible_unix_ms, before.next_eligible_unix_ms);
    }
    Ok(())
}

#[test]
fn terminal_control_preserves_the_companion_restart_domain() -> Result<()> {
    let dir = tempfile::tempdir()?;
    pending(dir.path())?;
    let companion = RestartBudgetJournal::new(
        agent(), ReleaseId::parse("release-a")?, DurableRestartWindow::empty(),
        DurableRestartWindow {
            attempts: 1,
            window_started_unix_millis: Some(crate::restart_journal::unix_millis_now()?),
        },
    )?;
    write_restart_journal(dir.path(), &companion)?;
    prepare_override(dir.path(), DurableControlKind::Kill)?;
    reconcile_absent(dir.path(), &agent(), AgentLifecycle::Failed)?;
    assert_eq!(read_restart_journal(dir.path())?, Some(companion));
    assert!(pending_restart(dir.path(), 3)?.is_none());
    Ok(())
}

#[test]
fn failed_restart_cancellation_does_not_publish_control_completion() -> Result<()> {
    let dir = tempfile::tempdir()?;
    pending(dir.path())?;
    prepare_override(dir.path(), DurableControlKind::Stop)?;
    let control = read_control_intent(dir.path())?.expect("intent");
    let path = dir.path().join(RESTART_JOURNAL_FILE);
    let saved = std::fs::read(&path)?;
    std::fs::remove_file(&path)?;
    std::fs::create_dir(&path)?;
    assert!(reconcile_absent(dir.path(), &agent(), AgentLifecycle::Stopped).is_err());
    assert_eq!(read_control_intent(dir.path())?.expect("still prepared"), control);
    std::fs::remove_dir(&path)?;
    std::fs::write(path, saved)?;
    reconcile_absent(dir.path(), &agent(), AgentLifecycle::Stopped)?;
    assert!(pending_restart(dir.path(), 3)?.is_none());
    assert!(!has_unresolved(dir.path())?);
    Ok(())
}

#[test]
fn cancellation_to_terminal_publication_cut_replays_idempotently() -> Result<()> {
    let dir = tempfile::tempdir()?;
    pending(dir.path())?;
    prepare_override(dir.path(), DurableControlKind::Kill)?;
    crate::restart_budget::cancel_restart(dir.path())?;
    let cancelled = std::fs::read(dir.path().join(RESTART_JOURNAL_FILE))?;
    assert!(has_unresolved(dir.path())?);
    reconcile_absent(dir.path(), &agent(), AgentLifecycle::Stopped)?;
    assert_eq!(std::fs::read(dir.path().join(RESTART_JOURNAL_FILE))?, cancelled);
    let terminal = std::fs::read(dir.path().join(CONTROL_INTENT_FILE))?;
    reconcile_absent(dir.path(), &agent(), AgentLifecycle::Stopped)?;
    assert_eq!(std::fs::read(dir.path().join(CONTROL_INTENT_FILE))?, terminal);
    Ok(())
}

#[test]
fn completed_control_does_not_cancel_a_later_restart() -> Result<()> {
    let dir = tempfile::tempdir()?;
    pending(dir.path())?;
    prepare_override(dir.path(), DurableControlKind::Stop)?;
    reconcile_absent(dir.path(), &agent(), AgentLifecycle::Stopped)?;
    pending(dir.path())?;
    let later = std::fs::read(dir.path().join(RESTART_JOURNAL_FILE))?;
    reconcile_absent(dir.path(), &agent(), AgentLifecycle::Stopped)?;
    assert!(!cancel_restart_if_unresolved(dir.path(), &agent())?);
    assert_eq!(std::fs::read(dir.path().join(RESTART_JOURNAL_FILE))?, later);
    assert!(pending_restart(dir.path(), 3)?.is_some());
    Ok(())
}

#[test]
fn a_present_lease_prevents_terminal_completion_and_budget_mutation() -> Result<()> {
    let dir = tempfile::tempdir()?;
    pending(dir.path())?;
    prepare_override(dir.path(), DurableControlKind::Stop)?;
    write_lease(dir.path(), &ProcessLease {
        schema_version: PROCESS_LEASE_SCHEMA_VERSION,
        agent_id: agent(),
        spawn_generation: 7,
        release_id: ReleaseId::parse("release-a")?,
        identity: identity(),
    })?;
    let before = std::fs::read(dir.path().join(RESTART_JOURNAL_FILE))?;
    assert!(reconcile_absent(dir.path(), &agent(), AgentLifecycle::Stopped).is_err());
    assert_eq!(std::fs::read(dir.path().join(RESTART_JOURNAL_FILE))?, before);
    assert!(has_unresolved(dir.path())?);
    Ok(())
}

#[test]
fn another_agent_cannot_use_a_control_override_to_cancel_this_budget() -> Result<()> {
    let dir = tempfile::tempdir()?;
    pending(dir.path())?;
    prepare_override(dir.path(), DurableControlKind::Kill)?;
    let other = AgentId::parse("00000000-0000-4000-8000-000000000002")?;
    let before = std::fs::read(dir.path().join(RESTART_JOURNAL_FILE))?;
    assert!(cancel_restart_if_unresolved(dir.path(), &other).is_err());
    assert!(reconcile_absent(dir.path(), &other, AgentLifecycle::Stopped).is_err());
    assert_eq!(std::fs::read(dir.path().join(RESTART_JOURNAL_FILE))?, before);
    Ok(())
}

#[test]
fn bounded_control_reader_rejects_oversize_and_non_regular_files() -> Result<()> {
    let dir = tempfile::tempdir()?;
    let path = dir.path().join(CONTROL_INTENT_FILE);
    std::fs::write(&path, vec![b'x'; MAX_CONTROL_INTENT_BYTES + 1])?;
    assert!(read_control_intent(dir.path()).is_err());
    std::fs::remove_file(&path)?;
    std::fs::create_dir(&path)?;
    assert!(read_control_intent(dir.path()).is_err());
    Ok(())
}

#[cfg(unix)]
#[test]
fn control_reader_rejects_symlinks_hardlinks_and_writable_files() -> Result<()> {
    use std::os::unix::fs::PermissionsExt;
    let dir = tempfile::tempdir()?;
    prepare_override(dir.path(), DurableControlKind::Stop)?;
    let path = dir.path().join(CONTROL_INTENT_FILE);
    let other = dir.path().join("other");
    std::fs::hard_link(&path, &other)?;
    assert!(read_control_intent(dir.path()).is_err());
    std::fs::remove_file(&other)?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o666))?;
    assert!(read_control_intent(dir.path()).is_err());
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;
    std::fs::rename(&path, &other)?;
    std::os::unix::fs::symlink(&other, &path)?;
    assert!(read_control_intent(dir.path()).is_err());
    Ok(())
}

#[cfg(unix)]
#[test]
fn fifo_control_path_is_rejected_without_waiting_for_a_writer() -> Result<()> {
    use std::os::unix::ffi::OsStrExt;
    let dir = tempfile::tempdir()?;
    let path = dir.path().join(CONTROL_INTENT_FILE);
    let name = std::ffi::CString::new(path.as_os_str().as_bytes())?;
    // SAFETY: name is a live NUL-terminated path; mkfifo acquires no process handle.
    assert_eq!(unsafe { libc::mkfifo(name.as_ptr(), 0o600) }, 0);
    assert!(read_control_intent(dir.path()).is_err());
    Ok(())
}

struct Process {
    label: &'static str,
    fail: bool,
    calls: Arc<Mutex<Vec<&'static str>>>,
}

impl ManagedProcess for Process {
    fn poll(&mut self, _max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        Ok(ProcessObservation {
            state: ProcessState::Running { healthy: true, drained: false },
            logs: Vec::new(),
        })
    }

    fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
        self.calls.lock().expect("calls").push("drain");
        Ok(())
    }

    fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
        self.calls.lock().expect("calls").push("stop");
        Ok(())
    }

    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        self.calls.lock().expect("calls").push(self.label);
        if self.fail {
            Err(ProcessDriverError::new("injected companion kill failure"))
        } else {
            Ok(())
        }
    }
}

struct Driver;

impl ProcessDriver for Driver {
    type Process = Process;

    fn spawn(&mut self, _spec: &SpawnSpec) -> Result<SpawnedProcess<Process>, ProcessDriverError> {
        panic!("termination must not spawn");
    }

    fn adopt(&mut self, _spec: &AdoptSpec) -> Result<Adoption<Process>, ProcessDriverError> {
        Ok(Adoption::Missing)
    }
}

struct Fixture {
    _temp: tempfile::TempDir,
    registry: FleetRegistry,
    supervisor: Supervisor<Driver>,
    slot: AgentSlot<Process>,
    now: Instant,
    calls: Arc<Mutex<Vec<&'static str>>>,
}

impl Fixture {
    fn new(active: bool) -> Result<Self> {
        let temp = tempfile::tempdir()?;
        let root = HeptaFleetRoot::parse(temp.path().join("fleet"))?;
        let registry = FleetRegistry::initialize(root.clone())?;
        let workspace = temp.path().join("workspace");
        std::fs::create_dir(&workspace)?;
        registry.register(AgentManifest::new(
            agent(), WorkspaceBinding::new(workspace.canonicalize()?, &root)?,
            ResourceBudget::local_default(),
        )?)?;
        let config = SupervisorConfig::local_default();
        let now = Instant::now();
        let (supervisor, report) = Supervisor::recover(registry.clone(), Driver, config.clone(), now)?;
        assert!(report.faults.is_empty());
        let calls = Arc::new(Mutex::new(Vec::new()));
        let mut slot = AgentSlot::new(&config);
        if active {
            let record = registry.load_agent(&agent())?;
            let starting = registry.compare_and_transition(
                &agent(), record.lifecycle.generation, AgentLifecycle::Starting,
            )?;
            let running = registry.compare_and_transition(
                &agent(), starting.generation, AgentLifecycle::Running,
            )?;
            let release = AgentRelease::new(
                "unversioned", AgentCommand::new(temp.path().join("mock-program"), Vec::new())?,
            )?;
            let lease = ProcessLease {
                schema_version: PROCESS_LEASE_SCHEMA_VERSION,
                agent_id: agent(),
                spawn_generation: starting.generation,
                release_id: ReleaseId::parse("unversioned")?,
                identity: identity(),
            };
            write_lease(record.layout.run_root(), &lease)?;
            slot.runtime = Some(AgentRuntime {
                process: Process { label: "main.kill", fail: false, calls: Arc::clone(&calls) },
                identity: identity(),
                spawn_generation: starting.generation,
                release_id: lease.release_id,
                generation: running.generation,
                phase: RuntimePhase::Running,
                healthy: true,
                fenced: false,
            });
            slot.active_release = Some(release);
        }
        Ok(Self { _temp: temp, registry, supervisor, slot, now, calls })
    }

    fn record(&self) -> Result<AgentRecord> {
        Ok(self.registry.load_agent(&agent())?)
    }

    fn stop_intent(&self, expired: bool) -> Result<()> {
        let record = self.record()?;
        let runtime = self.slot.runtime.as_ref().expect("active");
        let requested = if expired { 1 } else { unix_ms_now()? };
        let intent = DurableControlIntent::new(
            agent(), DurableControlKind::Stop, runtime.spawn_generation, identity(),
            record.lifecycle.generation, requested, Some(requested + 5_000),
        )?;
        write_control_intent(record.layout.run_root(), &intent)?;
        Ok(())
    }
}

#[test]
fn idle_stop_and_kill_cancel_the_persisted_restart_without_a_fake_process() -> Result<()> {
    for kill in [false, true] {
        let mut fixture = Fixture::new(false)?;
        let record = fixture.record()?;
        pending(record.layout.run_root())?;
        fixture.slot.restart_pending = true;
        if kill {
            fixture.supervisor.kill_slot(&agent(), &mut fixture.slot)?;
        } else {
            fixture.supervisor.stop_slot(&agent(), &mut fixture.slot, fixture.now)?;
        }
        assert!(!fixture.slot.restart_pending);
        assert!(pending_restart(record.layout.run_root(), 3)?.is_none());
        assert_eq!(read_main_restart_budget(record.layout.run_root())?.expect("history").attempts, 1);
        assert!(fixture.calls.lock().expect("calls").is_empty());
    }
    Ok(())
}

#[test]
fn live_stop_continuation_uses_original_deadline_not_the_current_grace() -> Result<()> {
    let mut fixture = Fixture::new(true)?;
    fixture.stop_intent(false)?;
    fixture.supervisor.config.stop_grace = Duration::from_secs(3_600);
    fixture.supervisor.stop_runtime_slot(&agent(), &mut fixture.slot, fixture.now)?;
    let phase = fixture.slot.runtime.as_ref().expect("owner").phase;
    let RuntimePhase::Stopping { deadline } = phase else { panic!("expected Stop"); };
    assert!(deadline.saturating_duration_since(fixture.now) <= Duration::from_secs(5));
    assert_eq!(*fixture.calls.lock().expect("calls"), vec!["stop"]);
    Ok(())
}

#[test]
fn expired_stop_kills_main_before_a_failing_companion_without_more_grace() -> Result<()> {
    let mut fixture = Fixture::new(true)?;
    fixture.stop_intent(true)?;
    let generation = fixture.slot.runtime.as_ref().expect("owner").spawn_generation;
    fixture.slot.matrix.runtime = Some(MatrixRuntime {
        process: Process { label: "matrix.kill", fail: true, calls: Arc::clone(&fixture.calls) },
        identity: ProcessIdentity::new(42, "matrix-lifetime")?,
        attached_agent_generation: generation,
        release_id: ReleaseId::parse("unversioned")?,
        binding_revision: 1,
        binding_digest: Sha256Digest::for_bytes(b"binding"),
        process_incarnation: "matrix-fixture".to_string(),
        plane_epoch: 1,
        phase: MatrixRuntimePhase::Running,
        healthy: true,
        fenced: false,
    });
    assert!(fixture.supervisor.stop_runtime_slot(&agent(), &mut fixture.slot, fixture.now).is_err());
    assert_eq!(*fixture.calls.lock().expect("calls"), vec!["main.kill", "matrix.kill"]);
    assert!(matches!(fixture.slot.runtime.as_ref().expect("main owner").phase, RuntimePhase::Killing));
    assert!(fixture.slot.matrix.runtime.is_some());
    Ok(())
}

#[test]
fn pending_termination_blocks_a_new_restart_claim() -> Result<()> {
    let mut fixture = Fixture::new(true)?;
    fixture.stop_intent(false)?;
    let record = fixture.record()?;
    assert!(fixture.supervisor.restart_slot(&agent(), &mut fixture.slot, fixture.now).is_err());
    assert!(read_main_restart_budget(record.layout.run_root())?.is_none());
    assert!(fixture.calls.lock().expect("calls").is_empty());
    Ok(())
}

#[test]
fn live_recovery_cancels_restart_before_restoring_the_pending_claim() -> Result<()> {
    let mut fixture = Fixture::new(true)?;
    let record = fixture.record()?;
    pending(record.layout.run_root())?;
    fixture.stop_intent(false)?;
    fixture.slot.restart_pending = true;
    fixture.supervisor.recover_restart_budget(&agent(), &mut fixture.slot, fixture.now)?;
    assert!(!fixture.slot.restart_pending);
    assert!(fixture.slot.restart_not_before.is_none());
    assert!(pending_restart(record.layout.run_root(), 3)?.is_none());
    assert!(has_unresolved(record.layout.run_root())?);
    assert!(fixture.slot.runtime.is_some());
    Ok(())
}
