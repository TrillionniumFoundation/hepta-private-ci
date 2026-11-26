use super::*;
use crate::CognitiveAccess;
use crate::CognitiveRecoveryAnchor;
use crate::CognitiveRecoveryRequirement;
use crate::CognitiveScope;
use crate::ProductionAuthorityLease;
use crate::ProductionAuthorityToken;
use crate::ProductionWriterError;
use crate::cognitive_test_support::agent_id;
use crate::cognitive_test_support::source;
use codex_hepta_paths::HeptaFleetRoot;
use std::io;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::process::Command;
use std::time::Duration;
use std::time::Instant;

const CHILD: &str = "cognitive_store::database_init_tests::bootstrap_child";

fn layout(root: &Path) -> io::Result<HeptaAgentLayout> {
    let fleet = HeptaFleetRoot::parse(root.join("fleet")).map_err(io::Error::other)?;
    Ok(fleet.layout().agent(&agent_id(/*suffix*/ 249)))
}

fn bootstrap(root: &Path, mask: &str) -> io::Result<()> {
    // Prepare only the directory/lock before changing the CHILD's umask. This
    // isolates DB creation, including masks which remove every requested bit.
    let layout = layout(root)?;
    super::create_private_directory(layout.cognitive_root()).map_err(io::Error::other)?;
    drop(
        super::CognitiveStoreOpenGuard::acquire_shared(layout.cognitive_root())
            .map_err(io::Error::other)?,
    );
    let mut child = Command::new("sh")
        .arg("-c")
        .arg(format!("umask {mask}; exec \"$@\""))
        .arg("private-db-child")
        .arg(std::env::current_exe()?)
        .args(["--exact", CHILD, "--ignored", "--nocapture"])
        .env("HEPTA_PRIVATE_DB_CHILD_ROOT", root)
        .spawn()?;
    let deadline = Instant::now() + Duration::from_secs(/*secs*/ 30);
    loop {
        if let Some(status) = child.try_wait()? {
            assert!(status.success(), "bootstrap child failed: {status}");
            return Ok(());
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            panic!("cold bootstrap child exceeded its deadline");
        }
        // Process supervision only: recovery is never attempted before exit.
        std::thread::sleep(Duration::from_millis(/*millis*/ 10));
    }
}

#[tokio::test]
#[ignore = "child-only abrupt SQLite bootstrap"]
async fn bootstrap_child() {
    let root = PathBuf::from(std::env::var_os("HEPTA_PRIVATE_DB_CHILD_ROOT").expect("child root"));
    let store = CognitiveStore::open(&layout(&root).expect("fixture layout"))
        .await
        .expect("bootstrap");
    store
        .append_source(
            &CognitiveAccess::agent_private(agent_id(/*suffix*/ 249)),
            &source(
                CognitiveScope::AgentPrivate,
                "cold-source",
                "durable cold fact",
            ),
        )
        .await
        .expect("committed source");
    let anchor = store.recovery_anchor().await.expect("current cut");
    let mut witness = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(root.join("anchor.json"))
        .expect("new witness");
    witness
        .set_permissions(fs::Permissions::from_mode(/*mode*/ 0o600))
        .expect("private new witness");
    witness
        .write_all(&serde_json::to_vec(&anchor).expect("encode cut"))
        .expect("write cut");
    witness.sync_all().expect("durable witness");
    File::open(&root)
        .and_then(|directory| directory.sync_all())
        .expect("durable witness directory");
    // Deliberately skip Rust/SQLite cleanup: public recovery must accept a real
    // cold WAL bundle, not only a pool.close() fixture with sidecars removed.
    std::process::exit(/*code*/ 0);
}

fn authority() -> Result<ProductionAuthorityLease, ProductionWriterError> {
    ProductionAuthorityLease::from_verified_parts(
        agent_id(/*suffix*/ 249),
        Sha256Digest::for_bytes(b"private-bootstrap-grant"),
        /*authority_epoch*/ 7,
        /*owner_epoch*/ 11,
        u64::MAX,
        ProductionAuthorityToken::from_verified_bytes(b"private-bootstrap-fence".to_vec())?,
    )
}

fn read_anchor(root: &Path) -> io::Result<CognitiveRecoveryAnchor> {
    Ok(serde_json::from_reader(File::open(
        root.join("anchor.json"),
    )?)?)
}

async fn recover(
    layout: &HeptaAgentLayout,
    anchor: &CognitiveRecoveryAnchor,
    authority: &ProductionAuthorityLease,
) -> Result<CognitiveStore, crate::CognitiveRecoveryError> {
    CognitiveStore::open_with_recovery(
        layout,
        CognitiveRecoveryRequirement::ExactCurrentCut(anchor),
        authority,
        &|lease: &ProductionAuthorityLease, owner: &AgentId| {
            if &lease.agent_id == owner {
                Ok(())
            } else {
                Err("fixture owner mismatch".into())
            }
        },
    )
    .await
}

#[tokio::test]
async fn abrupt_child_keeps_private_sidecars_and_public_exact_cut_recovery() {
    for mask in ["022", "077", "777"] {
        let temp = tempfile::tempdir().expect("fixture");
        let root = temp.path().canonicalize().expect("canonical fixture");
        bootstrap(&root, mask).expect("cold bootstrap child");
        for name in [
            "cognitive_1.sqlite3",
            "cognitive_1.sqlite3-wal",
            "cognitive_1.sqlite3-shm",
        ] {
            let metadata = fs::symlink_metadata(
                layout(&root)
                    .expect("fixture layout")
                    .cognitive_root()
                    .join(name),
            )
            .expect("retained cold bundle");
            assert_eq!(metadata.mode() & 0o7777, 0o600, "mask {mask}, {name}");
            assert_eq!(metadata.nlink(), 1);
        }
        let expected = read_anchor(&root).expect("decode cut");
        let recovered = recover(
            &layout(&root).expect("fixture layout"),
            &expected,
            &authority().expect("fixture authority"),
        )
        .await
        .expect("public cold recovery");
        assert_eq!(
            recovered.recovery_anchor().await.expect("recovered cut"),
            expected
        );
        recovered.pool.close().await;
    }
}

#[tokio::test]
async fn recovery_does_not_repair_an_unsafe_existing_sidecar() {
    let temp = tempfile::tempdir().expect("fixture");
    let root = temp.path().canonicalize().expect("canonical fixture");
    bootstrap(&root, "022").expect("cold bootstrap child");
    let wal = layout(&root)
        .expect("fixture layout")
        .cognitive_root()
        .join("cognitive_1.sqlite3-wal");
    fs::set_permissions(&wal, fs::Permissions::from_mode(/*mode*/ 0o644))
        .expect("unsafe fixture mode");
    let before = fs::read(&wal).expect("retain WAL bytes");
    assert!(matches!(
        recover(
            &layout(&root).expect("fixture layout"),
            &read_anchor(&root).expect("decode cut"),
            &authority().expect("fixture authority"),
        )
        .await,
        Err(crate::CognitiveRecoveryError::Indeterminate(_))
    ));
    assert_eq!(fs::metadata(&wal).expect("WAL mode").mode() & 0o7777, 0o644);
    assert_eq!(fs::read(&wal).expect("unchanged WAL"), before);
}

#[test]
fn existing_private_bytes_are_neither_truncated_nor_rewritten() {
    let temp = canonical_database_test_directory();
    let root = create_private_directory(temp.path()).expect("private canonical fixture root");
    let home = AbsolutePathBuf::try_from(root.clone()).expect("absolute fixture root");
    let config = SqliteConfig::from_sqlite_home(home);
    let path = root.join("existing");
    fs::write(&path, b"retained bytes").expect("seed");
    fs::set_permissions(&path, fs::Permissions::from_mode(/*mode*/ 0o600)).expect("private mode");
    let before = fs::metadata(&path).expect("metadata");
    config
        .prepare_private_bootstrap_database(&path)
        .expect("existing private file");
    let after = fs::metadata(&path).expect("metadata");
    assert_eq!(
        (before.dev(), before.ino(), before.mode()),
        (after.dev(), after.ino(), after.mode())
    );
    assert_eq!(fs::read(&path).expect("retained"), b"retained bytes");
}

#[test]
fn existing_links_and_restrictive_permissions_are_rejected_without_repair() {
    let temp = canonical_database_test_directory();
    let root = create_private_directory(temp.path()).expect("private canonical fixture root");
    let home = AbsolutePathBuf::try_from(root.clone()).expect("absolute fixture root");
    let config = SqliteConfig::from_sqlite_home(home);
    let original = root.join("original");
    fs::write(&original, b"unchanged").expect("seed");
    fs::set_permissions(&original, fs::Permissions::from_mode(/*mode*/ 0o600))
        .expect("private mode");
    let symlink = root.join("symlink");
    std::os::unix::fs::symlink(&original, &symlink).expect("symlink");
    assert!(config.prepare_private_bootstrap_database(&symlink).is_err());
    let hardlink = root.join("hardlink");
    fs::hard_link(&original, &hardlink).expect("hardlink");
    assert!(
        config
            .prepare_private_bootstrap_database(&hardlink)
            .is_err()
    );
    assert_eq!(fs::read(&original).expect("unchanged target"), b"unchanged");
    let restricted = root.join("restricted");
    fs::write(&restricted, b"private").expect("seed");
    fs::set_permissions(&restricted, fs::Permissions::from_mode(/*mode*/ 0o000))
        .expect("restricted fixture");
    assert!(
        config
            .prepare_private_bootstrap_database(&restricted)
            .is_err()
    );
    assert_eq!(
        fs::metadata(&restricted).expect("unchanged mode").mode() & 0o7777,
        0o000
    );
}

#[test]
fn existing_fifo_is_rejected_without_waiting_for_a_peer() {
    use std::os::unix::fs::FileTypeExt;
    let temp = canonical_database_test_directory();
    let root = create_private_directory(temp.path()).expect("private canonical fixture root");
    let home = AbsolutePathBuf::try_from(root.clone()).expect("absolute fixture root");
    let config = SqliteConfig::from_sqlite_home(home);
    let path = root.join("fifo");
    assert!(
        Command::new("mkfifo")
            .arg(&path)
            .status()
            .expect("create fixture FIFO")
            .success()
    );
    assert!(config.prepare_private_bootstrap_database(&path).is_err());
    assert!(
        fs::symlink_metadata(&path)
            .expect("retained FIFO")
            .file_type()
            .is_fifo()
    );
}

#[tokio::test]
async fn open_rejects_existing_nonprivate_main_without_repair() {
    let temp = tempfile::tempdir().expect("fixture");
    let root = temp.path().canonicalize().expect("canonical fixture");
    let store = CognitiveStore::open(&layout(&root).expect("fixture layout"))
        .await
        .expect("valid private store");
    store.pool.close().await;
    drop(store);
    let path = layout(&root)
        .expect("fixture layout")
        .cognitive_root()
        .join("cognitive_1.sqlite3");
    fs::set_permissions(&path, fs::Permissions::from_mode(/*mode*/ 0o644))
        .expect("nonprivate existing fixture");
    let before = fs::read(&path).expect("valid database bytes");
    assert!(matches!(
        CognitiveStore::open(&layout(&root).expect("fixture layout")).await,
        Err(CognitiveStoreError::Unavailable(_))
    ));
    assert_eq!(
        fs::metadata(&path).expect("unchanged mode").mode() & 0o7777,
        0o644
    );
    assert_eq!(fs::read(&path).expect("unchanged bytes"), before);
}

#[path = "cognitive_database_crash_tests.rs"]
mod crash_tests;

#[path = "cognitive_database_lock_tests.rs"]
mod lock_tests;
