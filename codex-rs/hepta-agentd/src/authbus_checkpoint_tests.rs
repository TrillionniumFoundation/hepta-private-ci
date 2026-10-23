use std::fs;
use std::os::unix::fs::PermissionsExt;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_paths::HeptaFleetRoot;

use super::*;

fn make_fifo(path: &Path) {
    assert!(
        std::process::Command::new("mkfifo")
            .args(["-m", "600"])
            .arg(path)
            .status()
            .expect("POSIX mkfifo")
            .success()
    );
}

fn expect_bounded_fifo_rejection(fifo: &Path, operation: impl FnOnce() -> bool + Send + 'static) {
    use std::os::unix::fs::OpenOptionsExt;
    use std::sync::mpsc;
    use std::time::Duration;

    let (sender, receiver) = mpsc::channel();
    let worker =
        std::thread::spawn(move || sender.send(operation()).expect("open result receiver"));
    let observed = receiver.recv_timeout(Duration::from_secs(/*secs*/ 2));
    // Rescue a regressed blocking read-open before joining, so the failing
    // test remains finite and leaves no blocked worker behind.
    if observed.is_err() {
        let rescue = OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
            .open(fifo)
            .expect("release blocking FIFO open");
        receiver
            .recv_timeout(Duration::from_secs(/*secs*/ 2))
            .expect("FIFO opener finishes after cleanup");
        drop(rescue);
    }
    worker.join().expect("open worker");
    assert!(observed.expect("checkpoint open must not wait for a FIFO writer"));
}

struct Fixture {
    _temp: tempfile::TempDir,
    path: PathBuf,
    witness: ReplayCheckpointFile,
    initial: ReplayCheckpoint,
}

impl Fixture {
    fn new() -> Self {
        let temp = tempfile::tempdir().expect("temporary owner root");
        let root = temp.path().canonicalize().expect("canonical root");
        let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent id");
        let fleet = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
        let layout = fleet.layout().agent(&agent_id);
        fs::create_dir_all(layout.home_root()).expect("owner home");
        fs::set_permissions(layout.home_root(), fs::Permissions::from_mode(0o700))
            .expect("private home");
        let identity = AgentdIdentity {
            agent_id,
            spawn_generation: 1,
            fleet_root: fleet.as_path().to_path_buf(),
            workspace: root.join("workspace"),
            resources: ResourceBudget::local_default(),
            home_root: layout.home_root().to_path_buf(),
            run_root: layout.run_root().to_path_buf(),
            control_socket: layout.agentd_control_socket().to_path_buf(),
            app_server_socket: layout.app_server_socket().to_path_buf(),
            layout,
        };
        let parent = root.join("witness");
        fs::create_dir(&parent).expect("external witness directory");
        fs::set_permissions(&parent, fs::Permissions::from_mode(0o700))
            .expect("private witness directory");
        let path = parent.join("checkpoint.json");
        let initial = ReplayCheckpoint {
            generation: 1,
            digest: Digest32::of_bytes(b"initial replay frontier"),
        };
        let document = CheckpointDocument {
            schema_version: CHECKPOINT_SCHEMA_VERSION,
            agent_id: identity.agent_id.to_string(),
            generation: initial.generation,
            digest: initial.digest.to_string(),
        };
        fs::write(
            &path,
            serde_json::to_vec(&document).expect("checkpoint encoding"),
        )
        .expect("installed checkpoint");
        fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).expect("private checkpoint");
        let (witness, recovered) =
            ReplayCheckpointFile::open(path.clone(), &identity).expect("open witness");
        assert_eq!(recovered, initial);
        Self {
            _temp: temp,
            path,
            witness,
            initial,
        }
    }

    fn next(&self) -> ReplayCheckpoint {
        ReplayCheckpoint {
            generation: self.initial.generation + 1,
            digest: Digest32::of_bytes(b"advanced replay frontier"),
        }
    }
}

#[test]
fn inspected_checkpoint_fifo_replacement_is_rejected_without_waiting_for_a_writer() {
    let fixture = Fixture::new();
    let inspected = InspectedCheckpointFile::inspect(&fixture.path, fixture.witness.owner_uid)
        .expect("regular checkpoint preflight");
    let retained = fixture.path.with_extension("retained");
    fs::rename(&fixture.path, &retained).expect("retain preflight inode");
    let original = fs::read(&retained).expect("original witness bytes");
    make_fifo(&fixture.path);
    expect_bounded_fifo_rejection(&fixture.path, move || inspected.read().is_err());
    assert_eq!(
        fs::read(retained).expect("unchanged original witness"),
        original
    );
}

#[test]
fn inspected_checkpoint_symlink_to_fifo_is_rejected_at_open_without_following_it() {
    let fixture = Fixture::new();
    let inspected = InspectedCheckpointFile::inspect(&fixture.path, fixture.witness.owner_uid)
        .expect("regular checkpoint preflight");
    let retained = fixture.path.with_extension("retained");
    fs::rename(&fixture.path, &retained).expect("retain preflight inode");
    let original = fs::read(&retained).expect("original witness bytes");
    let fifo = fixture.path.with_extension("fifo");
    make_fifo(&fifo);
    std::os::unix::fs::symlink(&fifo, &fixture.path).expect("replacement final-component symlink");
    expect_bounded_fifo_rejection(
        &fifo,
        move || matches!(inspected.read(), Err(AgentdError::Io(error)) if error.raw_os_error() == Some(libc::ELOOP)),
    );
    assert_eq!(
        fs::read(retained).expect("unchanged original witness"),
        original
    );
}

#[test]
fn checkpoint_directory_sync_rejects_fifo_parent_without_waiting_for_a_writer() {
    let temp = tempfile::tempdir().expect("tempdir");
    let parent = temp.path().join("parent");
    fs::create_dir(&parent).expect("directory before replacement");
    fs::rename(&parent, temp.path().join("retained-parent")).expect("retain parent inode");
    make_fifo(&parent);
    let replaced_parent = parent.clone();
    expect_bounded_fifo_rejection(&parent, move || {
        sync_parent_directory(&replaced_parent).is_err()
    });
}

#[test]
fn permission_drift_rejects_read_and_publication_without_replacing_witness() {
    let fixture = Fixture::new();
    let original = fs::read(&fixture.path).expect("original witness");
    fs::set_permissions(&fixture.path, fs::Permissions::from_mode(0o666))
        .expect("simulate loss of private protection");
    assert!(fixture.witness.read().is_err());
    assert!(
        fixture
            .witness
            .replace(fixture.initial, fixture.next())
            .is_err()
    );
    assert_eq!(fs::read(&fixture.path).expect("retained witness"), original);
}

#[test]
fn directory_permission_drift_rejects_read_and_publication() {
    let fixture = Fixture::new();
    fs::set_permissions(
        fixture.path.parent().expect("witness directory"),
        fs::Permissions::from_mode(0o755),
    )
    .expect("simulate directory protection drift");
    assert!(fixture.witness.read().is_err());
    assert!(
        fixture
            .witness
            .replace(fixture.initial, fixture.next())
            .is_err()
    );
}

#[test]
fn writable_nonsticky_ancestor_rejects_open_read_and_publication() {
    let fixture = Fixture::new();
    let original = fs::read(&fixture.path).expect("original witness");
    fs::set_permissions(fixture._temp.path(), fs::Permissions::from_mode(0o777))
        .expect("introduce writable ancestor above private witness parent");
    assert!(ReplayCheckpointFile::open(fixture.path.clone(), &fixture.witness.identity).is_err());
    assert!(fixture.witness.read().is_err());
    assert!(
        fixture
            .witness
            .replace(fixture.initial, fixture.next())
            .is_err()
    );
    assert_eq!(fs::read(&fixture.path).expect("retained witness"), original);
}

#[test]
fn trusted_sticky_ancestor_preserves_private_witness_recovery_and_publication() {
    let fixture = Fixture::new();
    fs::set_permissions(fixture._temp.path(), fs::Permissions::from_mode(0o1777))
        .expect("trusted sticky ancestor above private witness parent");
    assert_eq!(
        fixture.witness.read().expect("recover witness"),
        fixture.initial
    );
    let next = fixture.next();
    fixture
        .witness
        .replace(fixture.initial, next)
        .expect("publish witness");
    assert_eq!(fixture.witness.read().expect("advanced witness"), next);
}

#[test]
fn hard_link_created_after_open_rejects_read_and_publication() {
    let fixture = Fixture::new();
    fs::hard_link(&fixture.path, fixture.path.with_extension("linked"))
        .expect("simulate linked witness");
    assert!(fixture.witness.read().is_err());
    assert!(
        fixture
            .witness
            .replace(fixture.initial, fixture.next())
            .is_err()
    );
}

#[test]
fn symlink_replacement_is_rejected_without_touching_its_target() {
    let fixture = Fixture::new();
    let target = fixture.path.with_extension("retained");
    fs::rename(&fixture.path, &target).expect("retain original file");
    let original = fs::read(&target).expect("original witness");
    std::os::unix::fs::symlink(&target, &fixture.path).expect("simulate linked path");
    assert!(fixture.witness.read().is_err());
    assert!(
        fixture
            .witness
            .replace(fixture.initial, fixture.next())
            .is_err()
    );
    assert_eq!(fs::read(target).expect("untouched target"), original);
}

#[test]
fn directory_replacement_is_rejected_before_open_or_publication() {
    let fixture = Fixture::new();
    fs::remove_file(&fixture.path).expect("remove original file");
    fs::create_dir(&fixture.path).expect("simulate non-file witness");
    assert!(fixture.witness.read().is_err());
    assert!(
        fixture
            .witness
            .replace(fixture.initial, fixture.next())
            .is_err()
    );
    assert!(fixture.path.is_dir());
}

#[test]
fn publication_preserves_exact_predecessor_and_idempotent_private_replacement() {
    let fixture = Fixture::new();
    let wrong = ReplayCheckpoint {
        generation: fixture.initial.generation,
        digest: Digest32::of_bytes(b"different predecessor"),
    };
    assert!(fixture.witness.replace(wrong, fixture.next()).is_err());
    assert_eq!(
        fixture.witness.read().expect("unchanged checkpoint"),
        fixture.initial
    );
    let next = fixture.next();
    fixture
        .witness
        .replace(fixture.initial, next)
        .expect("publish next witness");
    fixture
        .witness
        .replace(fixture.initial, next)
        .expect("idempotent lost-reply retry");
    assert_eq!(fixture.witness.read().expect("new checkpoint"), next);
    assert_eq!(
        fs::metadata(&fixture.path)
            .expect("new file")
            .permissions()
            .mode()
            & 0o777,
        0o600
    );
}

#[test]
fn temporary_creation_conflict_does_not_delete_another_publication_file() {
    let fixture = Fixture::new();
    let name = fixture
        .path
        .file_name()
        .expect("checkpoint filename")
        .to_str()
        .expect("UTF-8 filename");
    let temporary = fixture
        .path
        .parent()
        .expect("witness directory")
        .join(format!(
            ".{name}.{}.{}.tmp",
            std::process::id(),
            fixture.next().generation,
        ));
    let competing_bytes = b"another publication owns this temporary file";
    fs::write(&temporary, competing_bytes).expect("simulate a concurrent publisher");
    assert!(
        fixture
            .witness
            .replace(fixture.initial, fixture.next())
            .is_err()
    );
    assert_eq!(
        fs::read(&temporary).expect("retained competing file"),
        competing_bytes
    );
    assert_eq!(
        fixture.witness.read().expect("unchanged predecessor"),
        fixture.initial
    );
}
