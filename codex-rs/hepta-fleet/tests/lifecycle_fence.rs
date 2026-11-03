use std::io::Read;
use std::io::Write;
use std::net::TcpListener;
use std::net::TcpStream;
use std::process::Child;
use std::process::Command;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::FleetRegistryError;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

const AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
type Result<T = ()> = std::result::Result<T, Box<dyn std::error::Error>>;

struct TestFleet {
    directory: tempfile::TempDir,
    registry: FleetRegistry,
    agent: AgentId,
}

impl TestFleet {
    fn running() -> Result<Self> {
        let directory = tempfile::tempdir()?;
        let root = HeptaFleetRoot::parse(directory.path().join("fleet"))?;
        let registry = FleetRegistry::initialize(root.clone())?;
        let workspace = directory.path().join("workspace");
        std::fs::create_dir(&workspace)?;
        let agent = AgentId::parse(AGENT)?;
        registry.register(AgentManifest::new(
            agent.clone(), WorkspaceBinding::new(&workspace, &root)?, ResourceBudget::local_default(),
        )?)?;
        registry.compare_and_transition(&agent, /*expected_generation*/ 0, AgentLifecycle::Starting)?;
        registry.compare_and_transition(&agent, /*expected_generation*/ 1, AgentLifecycle::Running)?;
        Ok(Self { directory, registry, agent })
    }

    fn child(&self, mode: &str) -> Result<(ChildProcess, TcpStream)> {
        let listener = TcpListener::bind("127.0.0.1:0")?;
        listener.set_nonblocking(true)?;
        let child = ChildProcess(Command::new(std::env::current_exe()?)
            .args(["--exact", "lifecycle_fence_child", "--nocapture", "--test-threads=1"])
            .env("HEPTA_LIFECYCLE_TEST_ROOT", self.directory.path().join("fleet"))
            .env("HEPTA_LIFECYCLE_TEST_PEER", listener.local_addr()?.to_string())
            .env("HEPTA_LIFECYCLE_TEST_MODE", mode)
            .spawn()?);
        let deadline = Instant::now() + Duration::from_secs(10);
        let stream = loop {
            match listener.accept() {
                Ok((stream, _)) => break stream,
                Err(error) if error.kind() == std::io::ErrorKind::WouldBlock && Instant::now() < deadline => {
                    std::thread::sleep(Duration::from_millis(5));
                }
                Err(error) => return Err(error.into()),
            }
        };
        stream.set_read_timeout(Some(Duration::from_secs(10)))?;
        stream.set_write_timeout(Some(Duration::from_secs(10)))?;
        Ok((child, stream))
    }
}

struct ChildProcess(Child);

impl ChildProcess {
    fn finish(mut self) -> Result {
        let deadline = Instant::now() + Duration::from_secs(10);
        loop {
            if let Some(status) = self.0.try_wait()? {
                assert!(status.success(), "child failed: {status}");
                return Ok(());
            }
            if Instant::now() >= deadline {
                return Err("lifecycle child did not finish".into());
            }
            std::thread::sleep(Duration::from_millis(5));
        }
    }
}

impl Drop for ChildProcess {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

#[test]
fn entry_in_another_process_excludes_publication_until_guard_drop() -> Result {
    let fleet = TestFleet::running()?;
    let before = fleet.registry.load_agent(&fleet.agent)?.lifecycle;
    let (child, mut stream) = fleet.child("hold")?;
    let mut signal = [0];
    stream.read_exact(&mut signal)?;
    assert_eq!(signal, *b"H");
    assert!(matches!(fleet.registry.compare_and_transition(&fleet.agent, /*expected_generation*/ 2, AgentLifecycle::Draining),
        Err(FleetRegistryError::LifecycleBusy { .. })));
    assert_eq!(fleet.registry.load_agent(&fleet.agent)?.lifecycle, before);
    stream.write_all(b"R")?;
    stream.read_exact(&mut signal)?;
    assert_eq!(signal, *b"D");
    child.finish()?;
    let after = fleet.registry.compare_and_transition(&fleet.agent, /*expected_generation*/ 2, AgentLifecycle::Draining)?;
    assert_eq!((after.generation, after.lifecycle), (3, AgentLifecycle::Draining));
    assert_eq!(std::fs::metadata(fleet.registry.layout().agent(&fleet.agent).run_root().join("lifecycle.lock"))?.len(), 0);
    Ok(())
}

#[test]
fn publication_before_another_process_entry_rejects_the_old_generation() -> Result {
    let fleet = TestFleet::running()?;
    let (child, mut stream) = fleet.child("late")?;
    let mut signal = [0];
    stream.read_exact(&mut signal)?;
    assert_eq!(signal, *b"W");
    let after = fleet.registry.compare_and_transition(&fleet.agent, /*expected_generation*/ 2, AgentLifecycle::Draining)?;
    stream.write_all(b"E")?;
    stream.read_exact(&mut signal)?;
    assert_eq!(signal, *b"S");
    child.finish()?;
    assert_eq!(fleet.registry.load_agent(&fleet.agent)?.lifecycle, after);
    Ok(())
}

// A separately executed test process, not a second handle in the parent.
#[test]
fn lifecycle_fence_child() -> Result {
    let Some(root) = std::env::var_os("HEPTA_LIFECYCLE_TEST_ROOT") else { return Ok(()); };
    let registry = FleetRegistry::open_existing(HeptaFleetRoot::parse(root)?)?;
    let agent = AgentId::parse(AGENT)?;
    let mut stream = TcpStream::connect(std::env::var("HEPTA_LIFECYCLE_TEST_PEER")?)?;
    stream.set_read_timeout(Some(Duration::from_secs(10)))?;
    let mut signal = [0];
    match std::env::var("HEPTA_LIFECYCLE_TEST_MODE")?.as_str() {
        "hold" => {
            let guard = registry.try_enter_generation(&agent, /*expected_generation*/ 2)?;
            stream.write_all(b"H")?;
            stream.read_exact(&mut signal)?;
            assert_eq!(signal, *b"R");
            drop(guard);
            stream.write_all(b"D")?;
        }
        "late" => {
            stream.write_all(b"W")?;
            stream.read_exact(&mut signal)?;
            assert_eq!(signal, *b"E");
            assert!(matches!(registry.try_enter_generation(&agent, /*expected_generation*/ 2),
                Err(FleetRegistryError::StaleGeneration { expected: 2, current: 3, .. })));
            stream.write_all(b"S")?;
        }
        mode => return Err(format!("unknown lifecycle child mode {mode}").into()),
    }
    Ok(())
}
