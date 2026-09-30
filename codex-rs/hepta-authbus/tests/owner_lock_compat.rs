#![cfg(target_os = "linux")]

use std::fs::OpenOptions;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_authbus::AuthBusAuthorityError;
use codex_hepta_authbus::AuthBusAuthorityHost;
use tempfile::TempDir;

const CHILD_TIMEOUT: Duration = Duration::from_secs(10);

struct Paths {
    root: TempDir,
    database: PathBuf,
    checkpoint: PathBuf,
}

fn private_paths() -> Paths {
    let root = TempDir::new().expect("temporary root");
    let database_root = root.path().join("database");
    let checkpoint_root = root.path().join("checkpoint");
    std::fs::create_dir_all(&database_root).expect("database root");
    std::fs::create_dir_all(&checkpoint_root).expect("checkpoint root");
    std::fs::set_permissions(&database_root, std::fs::Permissions::from_mode(0o700))
        .expect("database permissions");
    std::fs::set_permissions(&checkpoint_root, std::fs::Permissions::from_mode(0o700))
        .expect("checkpoint permissions");
    Paths {
        database: database_root.join("authority.sqlite"),
        checkpoint: checkpoint_root.join("authority-checkpoint.json"),
        root,
    }
}

fn owner_lock_path(database: &Path) -> PathBuf {
    let mut name = database
        .file_name()
        .expect("database file name")
        .to_os_string();
    name.push(".authbus-owner-lock.sqlite");
    database.parent().expect("database parent").join(name)
}

fn test_command(test_name: &str) -> Command {
    let mut command = Command::new(std::env::current_exe().expect("current test executable"));
    command
        .arg(test_name)
        .arg("--exact")
        .arg("--nocapture")
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    command
}

fn wait_for_path(path: &Path) {
    let deadline = Instant::now() + CHILD_TIMEOUT;
    while !path.exists() {
        assert!(
            Instant::now() < deadline,
            "timed out waiting for child marker {}",
            path.display()
        );
        std::thread::sleep(Duration::from_millis(10));
    }
}

fn wait_for_child(mut child: Child, context: &str) {
    let deadline = Instant::now() + CHILD_TIMEOUT;
    loop {
        match child.try_wait().expect("query child status") {
            Some(status) => {
                assert!(status.success(), "{context} failed: {status}");
                return;
            }
            None if Instant::now() < deadline => {
                std::thread::sleep(Duration::from_millis(10));
            }
            None => {
                let _ = child.kill();
                let _ = child.wait();
                panic!("{context} timed out");
            }
        }
    }
}

fn run_host_probe(paths: &Paths, owner_id: &str, marker_name: &str) -> String {
    let marker = paths.root.path().join(marker_name);
    let _ = std::fs::remove_file(&marker);
    let mut command = test_command("owner_host_probe_process");
    command
        .env("AUTHBUS_OWNER_HOST_PROBE", "1")
        .env("AUTHBUS_OWNER_ID", owner_id)
        .env("AUTHBUS_OWNER_DATABASE", &paths.database)
        .env("AUTHBUS_OWNER_CHECKPOINT", &paths.checkpoint)
        .env("AUTHBUS_OWNER_MARKER", &marker);
    let child = command.spawn().expect("spawn owner host probe");
    wait_for_child(child, "owner host probe");
    std::fs::read_to_string(marker).expect("owner host probe result")
}

fn run_legacy_probe(paths: &Paths, marker_name: &str) -> String {
    let marker = paths.root.path().join(marker_name);
    let _ = std::fs::remove_file(&marker);
    let mut command = test_command("legacy_posix_probe_process");
    command
        .env("AUTHBUS_LEGACY_POSIX_PROBE", "1")
        .env("AUTHBUS_OWNER_LOCK", owner_lock_path(&paths.database))
        .env("AUTHBUS_OWNER_MARKER", &marker);
    let child = command.spawn().expect("spawn legacy POSIX probe");
    wait_for_child(child, "legacy POSIX probe");
    std::fs::read_to_string(marker).expect("legacy POSIX probe result")
}

#[tokio::test]
async fn ofd_owner_survives_unrelated_close_and_blocks_new_and_legacy_owners() {
    let paths = private_paths();
    let owner_id = "descriptor-lifetime-owner";
    let owner =
        AuthBusAuthorityHost::bootstrap(&paths.database, paths.checkpoint.clone(), owner_id)
            .await
            .expect("bootstrap owner");

    let unrelated = OpenOptions::new()
        .read(true)
        .write(true)
        .open(owner_lock_path(&paths.database))
        .expect("open unrelated descriptor for live lock inode");
    drop(unrelated);

    assert_eq!(
        run_host_probe(&paths, owner_id, "new-owner-still-blocked"),
        "blocked"
    );
    assert_eq!(
        run_legacy_probe(&paths, "legacy-owner-still-blocked"),
        "blocked"
    );

    drop(owner);
    assert_eq!(
        run_host_probe(&paths, owner_id, "new-owner-after-release"),
        "acquired"
    );
    assert_eq!(
        run_legacy_probe(&paths, "legacy-owner-after-release"),
        "acquired"
    );
}

#[tokio::test]
async fn legacy_posix_owner_blocks_new_ofd_owner_during_rolling_replacement() {
    let paths = private_paths();
    let ready = paths.root.path().join("legacy-holder-ready");
    let release = paths.root.path().join("legacy-holder-release");
    let mut command = test_command("legacy_posix_holder_process");
    command
        .env("AUTHBUS_LEGACY_POSIX_HOLDER", "1")
        .env("AUTHBUS_OWNER_LOCK", owner_lock_path(&paths.database))
        .env("AUTHBUS_OWNER_READY", &ready)
        .env("AUTHBUS_OWNER_RELEASE", &release);
    let child = command.spawn().expect("spawn legacy POSIX holder");
    wait_for_path(&ready);

    let blocked =
        AuthBusAuthorityHost::bootstrap(&paths.database, paths.checkpoint.clone(), "new-ofd-owner")
            .await;
    std::fs::write(&release, b"release").expect("release legacy POSIX holder");
    wait_for_child(child, "legacy POSIX holder");
    assert!(matches!(
        blocked,
        Err(AuthBusAuthorityError::OwnerAlreadyActive)
    ));

    AuthBusAuthorityHost::bootstrap(&paths.database, paths.checkpoint.clone(), "new-ofd-owner")
        .await
        .expect("new OFD owner after legacy release");
}

#[tokio::test]
async fn owner_host_probe_process() {
    if std::env::var_os("AUTHBUS_OWNER_HOST_PROBE").is_none() {
        return;
    }
    let owner_id = std::env::var("AUTHBUS_OWNER_ID").expect("child owner id");
    let database =
        PathBuf::from(std::env::var_os("AUTHBUS_OWNER_DATABASE").expect("child database path"));
    let checkpoint =
        PathBuf::from(std::env::var_os("AUTHBUS_OWNER_CHECKPOINT").expect("child checkpoint path"));
    let marker =
        PathBuf::from(std::env::var_os("AUTHBUS_OWNER_MARKER").expect("child marker path"));
    let state = match AuthBusAuthorityHost::open(&database, checkpoint, &owner_id).await {
        Ok(_host) => "acquired",
        Err(AuthBusAuthorityError::OwnerAlreadyActive) => "blocked",
        Err(error) => panic!("unexpected owner probe result: {error}"),
    };
    std::fs::write(marker, state).expect("write owner probe result");
}

#[test]
fn legacy_posix_probe_process() {
    if std::env::var_os("AUTHBUS_LEGACY_POSIX_PROBE").is_none() {
        return;
    }
    let lock_path = PathBuf::from(std::env::var_os("AUTHBUS_OWNER_LOCK").expect("child lock path"));
    let marker =
        PathBuf::from(std::env::var_os("AUTHBUS_OWNER_MARKER").expect("child marker path"));
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .open(lock_path)
        .expect("open owner lock");
    let state =
        match rustix::fs::fcntl_lock(&file, rustix::fs::FlockOperation::NonBlockingLockExclusive) {
            Ok(()) => "acquired",
            Err(error)
                if error == rustix::io::Errno::AGAIN || error == rustix::io::Errno::ACCESS =>
            {
                "blocked"
            }
            Err(error) => panic!("unexpected legacy POSIX probe result: {error}"),
        };
    std::fs::write(marker, state).expect("write legacy POSIX probe result");
}

#[test]
fn legacy_posix_holder_process() {
    if std::env::var_os("AUTHBUS_LEGACY_POSIX_HOLDER").is_none() {
        return;
    }
    let lock_path = PathBuf::from(std::env::var_os("AUTHBUS_OWNER_LOCK").expect("child lock path"));
    let ready = PathBuf::from(std::env::var_os("AUTHBUS_OWNER_READY").expect("child ready path"));
    let release =
        PathBuf::from(std::env::var_os("AUTHBUS_OWNER_RELEASE").expect("child release path"));
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .open(lock_path)
        .expect("open owner lock");
    rustix::fs::fcntl_lock(&file, rustix::fs::FlockOperation::NonBlockingLockExclusive)
        .expect("acquire legacy POSIX owner lock");
    std::fs::write(&ready, b"ready").expect("write legacy holder ready marker");
    wait_for_path(&release);
    rustix::fs::fcntl_lock(&file, rustix::fs::FlockOperation::Unlock)
        .expect("release legacy POSIX owner lock");
}
