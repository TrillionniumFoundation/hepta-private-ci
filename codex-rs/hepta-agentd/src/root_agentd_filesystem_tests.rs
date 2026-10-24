//! Actual UID/GID read/write boundaries around the original Registry and DB.
//! This component proof does not claim a live Root authority or native G2 run.

use super::*;
use crate::FreshHostCognitiveState;
use crate::HostAuthorityRegisteredIdentity;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistryError;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_memory::CognitiveStore;
use pretty_assertions::assert_eq;
use std::process::Command;

const CHILD: &str = "authority_host_runtime::session::filesystem::tests::original_registry_reader_child";
const AGENT: &str = "019a2a19-0000-7000-8000-000000000009";

struct OriginalFixture {
    _temporary: tempfile::TempDir,
    registry: FleetRegistry,
    identity: AgentdIdentity,
    authority: PathBuf,
}

async fn original_fixture() -> OriginalFixture {
    // SAFETY: geteuid reads the current actual process credential.
    assert_eq!(unsafe { libc::geteuid() }, 0);
    let parent = std::env::var_os("HEPTA_FILESYSTEM_TEST_ROOT")
        .expect("an explicit Root-owned traversable isolated parent is required");
    let temporary = tempfile::tempdir_in(parent).unwrap();
    std::fs::set_permissions(temporary.path(), std::fs::Permissions::from_mode(0o755)).unwrap();
    let fleet = HeptaFleetRoot::parse(temporary.path().join("fleet")).unwrap();
    let registry = FleetRegistry::initialize(fleet.clone()).unwrap();
    let workspace = temporary.path().join("workspace");
    std::fs::DirBuilder::new().mode(0o700).create(&workspace).unwrap();
    let agent = AgentId::parse(AGENT).unwrap();
    let record = registry.register(AgentManifest::new(agent.clone(),
        WorkspaceBinding::new(workspace.clone(), &fleet).unwrap(), ResourceBudget::local_default(),
    ).unwrap()).unwrap();
    let starting = registry.compare_and_transition(&agent, record.lifecycle.generation, AgentLifecycle::Starting).unwrap();
    let registered = HostAuthorityRegisteredIdentity {
        agent_id: agent, spawn_generation: starting.generation,
        fleet_root: fleet.as_path().to_path_buf(), workspace, resources: record.manifest.resources,
    };
    let fresh = FreshHostCognitiveState::prepare(&registered).await.unwrap();
    let identity = registered.identity().unwrap();
    drop(fresh);
    let authority = temporary.path().join("protected");
    std::fs::DirBuilder::new().mode(0o700).create(&authority).unwrap();
    std::fs::write(authority.join("custody-probe"), b"private test bytes, not an issuer key").unwrap();
    std::fs::write(identity.layout.home_root().join("write-probe"), b"original Agent data").unwrap();
    OriginalFixture { _temporary: temporary, registry, identity, authority }
}

#[tokio::test]
#[ignore = "explicit actual Root filesystem handoff and dedicated UID/GID child"]
async fn original_root_filesystem_preserves_registry_reads_and_denies_control_writes() {
    let fixture = original_fixture().await;
    let id = &fixture.identity;
    let initial = fixture.registry.load_agent(&id.agent_id).unwrap();
    let parent = handoff_fresh_filesystem(id, /*uid*/ 60001, /*gid*/ 60001, &fixture.authority).unwrap();
    assert_eq!(parent, id.layout.agent_root().join("final-use"));
    assert_eq!(fixture.registry.load_agent(&id.agent_id).unwrap(), initial);
    run_reader(&fixture, initial.lifecycle.generation, initial.release_state.generation);
    let running = fixture.registry.compare_and_transition(&id.agent_id,
        initial.lifecycle.generation, AgentLifecycle::Running).unwrap();
    let release = fixture.registry.compare_and_set_release_state(&id.agent_id,
        initial.release_state.generation, /*current*/ None, /*previous*/ None).unwrap();
    for path in [
        id.layout.run_root().join(format!("lifecycle-{:020}.json", running.generation)),
        id.layout.releases_root().join(format!("release-state-{:020}.json", release.generation)),
    ] {
        let metadata = std::fs::symlink_metadata(path).unwrap();
        assert_eq!((metadata.uid(), metadata.gid(), metadata.mode() & 0o7777), (0, 60001, 0o640));
    }
    run_reader(&fixture, running.generation, release.generation);
    assert_eq!(fixture.registry.load_agent(&id.agent_id).unwrap().lifecycle, running);
    println!("ROOT_FILESYSTEM_READONLY original_registry=true actual_uid=60001 actual_gid=60001 root_publish_readable=true peer_control_write_denied=true protected_state_private=true");
}

fn run_reader(fixture: &OriginalFixture, lifecycle: u64, release: u64) {
    let output = Command::new("/usr/bin/setpriv")
        .args(["--reuid=60001", "--regid=60001", "--clear-groups", "--no-new-privs",
            "--inh-caps=-all", "--ambient-caps=-all", "--bounding-set=-all"])
        .arg(std::env::current_exe().unwrap())
        .args(["--exact", CHILD, "--ignored", "--nocapture", "--test-threads=1"])
        .env_clear().env("PATH", "/usr/bin:/bin")
        .env("RUST_MIN_STACK", "8388608")
        .env("HEPTA_FILESYSTEM_READER_FLEET", &fixture.identity.fleet_root)
        .env("HEPTA_FILESYSTEM_READER_PROTECTED", &fixture.authority)
        .env("HEPTA_FILESYSTEM_READER_LIFECYCLE", lifecycle.to_string())
        .env("HEPTA_FILESYSTEM_READER_RELEASE", release.to_string())
        .current_dir("/").output().unwrap();
    assert!(output.status.success(), "actual peer child failed: stdout={} stderr={}",
        String::from_utf8_lossy(&output.stdout), String::from_utf8_lossy(&output.stderr));
    let stdout = String::from_utf8(output.stdout).unwrap();
    assert!(stdout.contains("ROOT_FILESYSTEM_READER actual_uid=60001 actual_gid=60001 control_write_denied=true"));
    assert!(stdout.contains("1 passed; 0 failed"));
    print!("{stdout}");
}

#[tokio::test]
#[ignore = "only the explicit Root filesystem test launches this exact dedicated-UID child"]
async fn original_registry_reader_child() {
    let fleet = std::env::var_os("HEPTA_FILESYSTEM_READER_FLEET").expect("explicit reader child inputs required");
    // SAFETY: these calls only read actual kernel credentials.
    assert_eq!(unsafe { (libc::getuid(), libc::geteuid(), libc::getgid(), libc::getegid()) },
        (60001, 60001, 60001, 60001));
    crate::authority_host_runtime::verify_process_credentials(std::process::id(), /*uid*/ 60001, /*gid*/ 60001).unwrap();
    let registry = FleetRegistry::open_existing(HeptaFleetRoot::parse(PathBuf::from(fleet)).unwrap()).unwrap();
    let agent = AgentId::parse(AGENT).unwrap();
    let record = registry.load_agent(&agent).unwrap();
    assert_eq!(record.lifecycle.generation,
        std::env::var("HEPTA_FILESYSTEM_READER_LIFECYCLE").unwrap().parse::<u64>().unwrap());
    assert_eq!(record.release_state.generation,
        std::env::var("HEPTA_FILESYSTEM_READER_RELEASE").unwrap().parse::<u64>().unwrap());
    let next = match record.lifecycle.lifecycle {
        AgentLifecycle::Starting => AgentLifecycle::Running,
        AgentLifecycle::Running => AgentLifecycle::Draining,
        other => panic!("unexpected original lifecycle {other:?}"),
    };
    assert!(matches!(registry.compare_and_transition(&agent, record.lifecycle.generation, next),
        Err(FleetRegistryError::Io(error)) if error.kind() == io::ErrorKind::PermissionDenied));
    assert!(matches!(registry.compare_and_set_release_state(&agent,
        record.release_state.generation, /*current*/ None, /*previous*/ None),
        Err(FleetRegistryError::Io(error)) if error.kind() == io::ErrorKind::PermissionDenied));
    for path in [record.layout.agent_config().to_path_buf(), record.layout.writer_lock().to_path_buf()] {
        assert_eq!(OpenOptions::new().write(true).open(path).unwrap_err().kind(), io::ErrorKind::PermissionDenied);
    }
    assert_eq!(std::fs::remove_file(record.layout.agent_config()).unwrap_err().kind(), io::ErrorKind::PermissionDenied);
    assert_eq!(std::fs::write(record.layout.run_root().join("peer-mutation"), b"refused").unwrap_err().kind(), io::ErrorKind::PermissionDenied);
    assert_eq!(File::open(record.layout.writer_lock()).unwrap_err().kind(), io::ErrorKind::PermissionDenied);
    let protected = PathBuf::from(std::env::var_os("HEPTA_FILESYSTEM_READER_PROTECTED").unwrap());
    assert_eq!(File::open(protected.join("custody-probe")).unwrap_err().kind(), io::ErrorKind::PermissionDenied);
    OpenOptions::new().read(true).write(true).open(record.layout.home_root().join("write-probe")).unwrap();
    std::fs::write(record.layout.agent_root().join("final-use/peer-data-probe"), b"private local data").unwrap();
    let store = CognitiveStore::open(&record.layout).await.unwrap();
    assert_eq!(store.recovery_anchor().await.unwrap().owner_agent_id, agent);
    store.close().await;
    assert_eq!(registry.load_agent(&record.manifest.agent_id).unwrap(), record);
    println!("ROOT_FILESYSTEM_READER actual_uid=60001 actual_gid=60001 control_write_denied=true original_db_opened=true");
}

#[tokio::test]
#[ignore = "explicit actual Root scope-refusal test, no Agent runtime is started"]
async fn original_root_filesystem_rejects_aliases_and_existing_workspace_before_ownership_change() {
    for failure in ["symlink", "hardlink", "workspace", "authority-overlap"] {
        let fixture = original_fixture().await;
        let id = &fixture.identity;
        let outside = fixture.authority.join("custody-probe");
        match failure {
            "symlink" => std::os::unix::fs::symlink(&outside, id.layout.home_root().join("alias")).unwrap(),
            "hardlink" => std::fs::hard_link(&outside, id.layout.home_root().join("alias")).unwrap(),
            "workspace" => std::fs::write(id.workspace.join("existing-work"), b"must not recursively chown").unwrap(),
            "authority-overlap" => {}
            _ => unreachable!(),
        }
        let protected = if failure == "authority-overlap" { id.layout.home_root() } else { &fixture.authority };
        let error = handoff_fresh_filesystem(id, /*uid*/ 60001, /*gid*/ 60001, protected).unwrap_err();
        assert!(error.to_string().contains("original Root filesystem handoff"), "{error}");
        for path in [id.layout.agent_root(), id.layout.home_root(), id.layout.cognitive_root(), &id.workspace] {
            assert_eq!(std::fs::symlink_metadata(path).unwrap().uid(), 0, "{failure}: {}", path.display());
        }
        assert!(!id.layout.agent_root().join("final-use").exists());
    }
}
