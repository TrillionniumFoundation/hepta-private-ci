//! Actual isolated Root→UID60001 filesystem/Registry checks. No kernel role,
//! writer authorization or native qualification is manufactured by this test.

use super::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use std::process::Command;

const ROOT_ENV: &str = "HEPTA_NATIVE_PERMISSION_TEST_ROOT";
const CHILD: &str = "native_cpu_entry::permissions::tests::native_permissions_child";

#[test]
#[ignore = "requires isolated actual Root and UID60001 child; no production state"]
fn native_permissions_keep_original_control_owner_for_real_host_uid() -> io::Result<()> {
    if unsafe { libc::geteuid() } != 0 {
        return Err(invalid("actual Root qualification required"));
    }
    let temp = tempfile::Builder::new()
        .prefix("hepta-native-permissions-")
        .tempdir_in("/run")?;
    std::fs::set_permissions(temp.path(), std::fs::Permissions::from_mode(0o711))?;
    let workspace = temp.path().join("workspace");
    platform::private_dir(&workspace, HOST, HOST, 0o700)?;
    let fleet_root = HeptaFleetRoot::parse(temp.path().join("fleet")).map_err(error)?;
    let fleet = FleetRegistry::initialize(fleet_root.clone()).map_err(error)?;
    let agent = AgentId::parse(AGENT).map_err(error)?;
    let record = fleet
        .register(
            AgentManifest::new(
                agent.clone(),
                WorkspaceBinding::new(workspace, &fleet_root).map_err(error)?,
                ResourceBudget::local_default(),
            )
            .map_err(error)?,
        )
        .map_err(error)?;
    let layout = record.layout;
    runtime()?.block_on(async {
        let store = CognitiveStore::open(&layout).await.map_err(error)?;
        let _actual_initial_cut = store.recovery_anchor().await.map_err(error)?;
        store.close().await;
        Ok::<_, io::Error>(())
    })?;
    handoff_fresh(fleet.layout(), &layout)?;
    let before = std::fs::read(layout.agent_config())?;
    // Start the original test image as Root; only that isolated helper drops
    // credentials. /run may be noexec, and no copied executable is needed.
    let output = Command::new(std::env::current_exe()?)
        .args([
            "--exact",
            CHILD,
            "--ignored",
            "--nocapture",
            "--test-threads=1",
        ])
        .env(ROOT_ENV, temp.path())
        .output()?;
    if !output.status.success() {
        return Err(invalid(format!(
            "actual UID60001 child failed: {} {}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        )));
    }
    assert_eq!(std::fs::read(layout.agent_config())?, before);
    let forged = layout
        .run_root()
        .join("lifecycle-00000000000000000001.json");
    assert_eq!(std::fs::metadata(&forged)?.uid(), HOST);
    assert!(
        fleet.load_agent(&agent).is_err(),
        "Root also rejects the Host-owned future generation"
    );
    std::fs::remove_file(forged)?;
    let actual = fleet.load_agent(&agent).map_err(error)?;
    assert_eq!(actual.lifecycle.generation, 0);
    let next = fleet
        .compare_and_transition(&agent, 0, AgentLifecycle::Starting)
        .map_err(error)?;
    assert_eq!(next.generation, 1);
    let published = std::fs::metadata(
        layout
            .run_root()
            .join("lifecycle-00000000000000000001.json"),
    )?;
    assert_eq!(
        (published.uid(), published.gid(), published.mode() & 0o777),
        (0, HOST, 0o640)
    );
    Ok(())
}

#[test]
#[ignore = "private isolated child of native_permissions_keep_original_control_owner_for_real_host_uid"]
fn native_permissions_child() -> io::Result<()> {
    let root = std::env::var_os(ROOT_ENV)
        .ok_or_else(|| invalid("isolated permission helper identity missing"))?;
    let root = std::path::PathBuf::from(root);
    let metadata = std::fs::symlink_metadata(&root)?;
    if !root.starts_with("/run")
        || !metadata.is_dir()
        || metadata.uid() != 0
        || metadata.mode() & 0o777 != 0o711
        || metadata.file_type().is_symlink()
    {
        return Err(invalid("isolated Root fixture differs"));
    }
    platform::drop_host_privileges()?;
    assert_eq!(
        (unsafe { libc::geteuid() }, unsafe { libc::getegid() }),
        (HOST, HOST)
    );
    let fleet =
        FleetRegistry::open_existing(HeptaFleetRoot::parse(root.join("fleet")).map_err(error)?)
            .map_err(error)?;
    let agent = AgentId::parse(AGENT).map_err(error)?;
    let record = fleet.load_agent(&agent).map_err(error)?;
    let layout = record.layout;
    runtime()?.block_on(async {
        let store = CognitiveStore::open(&layout).await.map_err(error)?;
        let _actual_cut = store.recovery_anchor().await.map_err(error)?;
        store.close().await;
        Ok::<_, io::Error>(())
    })?;
    // The Host can create its real private runtime files in the shared sticky
    // directory, while Root-owned control files remain inaccessible for write.
    let lock = std::fs::OpenOptions::new()
        .write(true)
        .read(true)
        .create_new(true)
        .open(layout.writer_lock())?;
    lock.try_lock().map_err(error)?;
    let socket = std::os::unix::net::UnixListener::bind(layout.agentd_control_socket())?;
    assert!(
        std::fs::OpenOptions::new()
            .write(true)
            .open(layout.agent_config())
            .is_err()
    );
    let initial = layout
        .run_root()
        .join("lifecycle-00000000000000000000.json");
    assert!(
        std::fs::OpenOptions::new()
            .write(true)
            .open(&initial)
            .is_err()
    );
    assert!(std::fs::remove_file(&initial).is_err());
    assert!(
        fleet
            .compare_and_transition(&agent, 0, AgentLifecycle::Starting)
            .is_err()
    );
    assert!(
        std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(
                layout
                    .releases_root()
                    .join("release-state-00000000000000000001.json")
            )
            .is_err()
    );
    let mut forged = record.lifecycle;
    forged.generation = 1;
    forged.lifecycle = AgentLifecycle::Starting;
    std::fs::write(
        layout
            .run_root()
            .join("lifecycle-00000000000000000001.json"),
        serde_json::to_vec(&forged).map_err(error)?,
    )?;
    assert!(
        fleet.load_agent(&agent).is_err(),
        "syntactically valid higher generation must fail its original owner check"
    );
    drop(socket);
    drop(lock);
    Ok(())
}
