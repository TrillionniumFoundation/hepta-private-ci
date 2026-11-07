use std::fs;

use codex_hepta_contracts::AgentId;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

use super::FleetRegistry;
use super::lifecycle_path;
use crate::AgentLifecycle;
use crate::AgentManifest;
use crate::ResourceBudget;
use crate::WorkspaceBinding;

fn fixture() -> (tempfile::TempDir, FleetRegistry, crate::AgentRecord) {
    let temp = tempfile::tempdir().expect("temporary root");
    let root = temp.path().canonicalize().expect("canonical root");
    let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
    let registry = FleetRegistry::initialize(fleet_root.clone()).expect("registry");
    let workspace = root.join("workspace");
    fs::create_dir(&workspace).expect("workspace");
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("id");
    let manifest = AgentManifest::new(
        agent_id,
        WorkspaceBinding::new(&workspace, &fleet_root).expect("binding"),
        ResourceBudget::local_default(),
    )
    .expect("manifest");
    let record = registry.register(manifest).expect("register");
    (temp, registry, record)
}

#[test]
fn local_read_ignores_corrupt_peers_but_global_audit_still_rejects_them() {
    let (_temp, registry, record) = fixture();
    // Each added peer is deliberately incomplete. A reader that accidentally
    // enumerates the fleet will fail, independently of filesystem timing.
    for number in 1..=128 {
        let peer = format!("019153a4-3088-7e03-a56a-{number:012x}");
        fs::create_dir(registry.layout().agents_root().join(peer)).expect("peer");
        assert_eq!(
            registry
                .load_agent(&record.manifest.agent_id)
                .expect("local read"),
            record
        );
    }
    assert!(registry.load().is_err());
}

#[test]
fn local_read_observes_a_new_generation_without_cached_authority() {
    let (_temp, registry, mut expected) = fixture();
    expected.lifecycle = registry
        .compare_and_transition(
            &expected.manifest.agent_id,
            /*expected_generation*/ 0,
            AgentLifecycle::Starting,
        )
        .expect("new generation");
    assert_eq!(
        registry
            .load_agent(&expected.manifest.agent_id)
            .expect("fresh read"),
        expected
    );
}

#[test]
fn local_read_still_rejects_its_own_corrupt_lifecycle_and_missing_manifest() {
    let (_temp, registry, record) = fixture();
    let path = lifecycle_path(record.layout.run_root(), /*generation*/ 0);
    let original = fs::read(&path).expect("original lifecycle");
    fs::write(&path, b"not-json").expect("corrupt local lifecycle");
    assert!(registry.load_agent(&record.manifest.agent_id).is_err());
    fs::write(path, original).expect("restore fixture lifecycle");
    fs::remove_file(record.layout.agent_config()).expect("remove own manifest");
    assert!(registry.load_agent(&record.manifest.agent_id).is_err());
}

#[cfg(unix)]
#[test]
fn local_read_rejects_a_symlinked_control_file() {
    let (_temp, registry, record) = fixture();
    let path = record.layout.agent_config();
    let target = path.with_extension("saved");
    fs::rename(path, &target).expect("move fixture manifest");
    std::os::unix::fs::symlink(target, path).expect("fixture symlink");
    assert!(registry.load_agent(&record.manifest.agent_id).is_err());
}

#[test]
fn local_control_writer_refuses_overflow_before_creating_a_file() {
    let root = tempfile::tempdir().expect("temporary root");
    let accepted = root.path().join("accepted");
    let rejected = root.path().join("rejected");
    let exact = vec![b'x'; super::MAX_CONTROL_FILE_BYTES as usize];
    super::write_new_file(&accepted, &exact).expect("exact bound is writable");
    assert_eq!(
        super::read_regular_file(&accepted)
            .expect("read exact bound")
            .as_bytes(),
        exact
    );
    let mut oversized = exact.clone();
    oversized.push(b'x');
    assert!(matches!(
        super::write_new_file(&rejected, &oversized),
        Err(crate::FleetRegistryError::Corrupt(_))
    ));
    assert!(!rejected.exists());
    assert_eq!(
        fs::read(&accepted).expect("accepted bytes unchanged"),
        exact
    );
    fs::write(&accepted, [0xff]).expect("invalid UTF-8 fixture");
    assert!(matches!(
        super::read_regular_file(&accepted),
        Err(crate::FleetRegistryError::Io(error)) if error.kind() == std::io::ErrorKind::InvalidData
    ));
}

#[test]
fn local_owner_reload_bounds_manifest_and_lifecycle_without_mutating_control_records() {
    let (_temp, registry, record) = fixture();
    for path in [
        record.layout.agent_config().to_path_buf(),
        lifecycle_path(record.layout.run_root(), /*generation*/ 0),
    ] {
        let original = fs::read(&path).expect("original control record");
        let mut padded = original.clone();
        padded.resize(super::MAX_CONTROL_FILE_BYTES as usize, b' ');
        fs::write(&path, &padded).expect("valid exact-bound whitespace");
        assert_eq!(
            registry
                .load_agent(&record.manifest.agent_id)
                .expect("exact bound reload"),
            record
        );
        padded.push(b' ');
        fs::write(&path, &padded).expect("oversized control record");
        assert!(matches!(
            registry.load_agent(&record.manifest.agent_id),
            Err(crate::FleetRegistryError::Corrupt(_))
        ));
        assert_eq!(
            fs::read(&path).expect("failed read leaves record unchanged"),
            padded
        );
        fs::write(&path, original).expect("restore actual owner record");
        assert_eq!(
            registry
                .load_agent(&record.manifest.agent_id)
                .expect("restored reload"),
            record
        );
    }
}

#[cfg(unix)]
#[test]
fn local_owner_reload_refuses_fifo_manifest_and_lifecycle_without_waiting_for_a_writer() {
    use std::os::unix::fs::OpenOptionsExt;
    use std::time::Duration;
    use std::time::Instant;

    let (temp, registry, record) = fixture();
    for (index, path) in [
        record.layout.agent_config().to_path_buf(),
        lifecycle_path(record.layout.run_root(), /*generation*/ 0),
    ]
    .into_iter()
    .enumerate()
    {
        // Keep the backup outside the owner's enumerated lifecycle directory.
        let backup = temp.path().join(format!("control-{index}.saved"));
        fs::rename(&path, &backup).expect("retain original control record");
        let status = std::process::Command::new("mkfifo")
            .args(["-m", "600"])
            .arg(&path)
            .status()
            .expect("create actual FIFO");
        assert!(status.success());
        let (done, observed) = std::sync::mpsc::channel();
        let rescue_path = path.clone();
        let rescue = std::thread::spawn(move || {
            if observed.recv_timeout(Duration::from_secs(1)).is_err() {
                // A blocking-open regression gets EOF and then fails the
                // original one-second assertion. Retry ENXIO until the reader
                // arrives; a one-shot writer could miss a delayed open.
                loop {
                    if matches!(
                        observed.try_recv(),
                        Ok(()) | Err(std::sync::mpsc::TryRecvError::Disconnected)
                    ) {
                        break;
                    }
                    match fs::OpenOptions::new()
                        .write(true)
                        .custom_flags(libc::O_NONBLOCK)
                        .open(&rescue_path)
                    {
                        Ok(_writer) => break,
                        Err(error) if error.raw_os_error() == Some(libc::ENXIO) => {
                            std::thread::sleep(Duration::from_millis(1));
                        }
                        Err(error) => {
                            panic!("FIFO rescue could not open the original fixture: {error}")
                        }
                    }
                }
            }
        });
        let started = Instant::now();
        let refused = registry.load_agent(&record.manifest.agent_id);
        let elapsed = started.elapsed();
        let _ = done.send(());
        rescue.join().expect("join FIFO rescue");
        assert!(matches!(
            refused,
            Err(crate::FleetRegistryError::Corrupt(_))
        ));
        assert!(elapsed < Duration::from_secs(1));
        fs::remove_file(&path).expect("remove only fixture FIFO");
        fs::rename(&backup, &path).expect("restore original control record");
        assert_eq!(
            registry
                .load_agent(&record.manifest.agent_id)
                .expect("restored owner"),
            record
        );
    }
}
