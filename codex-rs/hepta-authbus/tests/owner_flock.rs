#![cfg(all(
    unix,
    not(any(target_os = "illumos", target_os = "solaris"))
))]

use std::fs::OpenOptions;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;

use codex_hepta_authbus::AuthBusAuthorityError;
use codex_hepta_authbus::AuthBusAuthorityHost;
use tempfile::TempDir;

struct Paths {
    _root: TempDir,
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
        _root: root,
    }
}

fn owner_lock_path(database: &Path) -> PathBuf {
    let mut name = database
        .file_name()
        .expect("database file name")
        .to_os_string();
    name.push(".authbus-owner-lock.sqlite");
    database
        .parent()
        .expect("database parent")
        .join(name)
}

fn run_owner_probe(paths: &Paths, owner_id: &str, marker_name: &str) -> String {
    let marker = paths._root.path().join(marker_name);
    let _ = std::fs::remove_file(&marker);
    let status = Command::new(std::env::current_exe().expect("current test executable"))
        .arg("cross_process_probe_reports_lock_state")
        .arg("--exact")
        .arg("--nocapture")
        .env("AUTHBUS_FLOCK_PROBE", "1")
        .env("AUTHBUS_OWNER_ID", owner_id)
        .env("AUTHBUS_OWNER_DATABASE", &paths.database)
        .env("AUTHBUS_OWNER_CHECKPOINT", &paths.checkpoint)
        .env("AUTHBUS_OWNER_MARKER", &marker)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .expect("run owner probe");
    assert!(status.success(), "owner probe child failed");
    std::fs::read_to_string(marker).expect("owner probe result")
}

#[tokio::test]
async fn closing_unrelated_descriptor_does_not_release_live_owner_fence() {
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
        run_owner_probe(&paths, owner_id, "probe-still-blocked"),
        "blocked"
    );
    drop(owner);
    assert_eq!(
        run_owner_probe(&paths, owner_id, "probe-after-release"),
        "acquired"
    );
}

#[tokio::test]
async fn cross_process_probe_reports_lock_state() {
    if std::env::var_os("AUTHBUS_FLOCK_PROBE").is_none() {
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
