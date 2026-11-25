use super::*;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use std::fs::OpenOptions;
use std::io::BufRead;
use std::io::Read;
use std::io::Write;
use std::os::fd::FromRawFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::fs::symlink;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::sync::mpsc;
use std::time::Duration;

const LOCK: &str = ".cognitive-store.lock";
const CANDIDATE: &str = "cognitive_recovered_v1_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.sqlite3";
const POINTER: &str = ".cognitive-active-v1";
const OLD: &str = "cognitive_recovered_v1_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.sqlite3";

struct Fixture {
    root: PathBuf,
    source: SqliteConfig,
    destination: SqliteConfig,
}

fn config(path: PathBuf) -> SqliteConfig {
    SqliteConfig::from_sqlite_home(AbsolutePathBuf::try_from(path).unwrap())
}

fn private_file(path: &Path, bytes: &[u8], uid: u32) {
    let file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .unwrap();
    file.set_permissions(std::fs::Permissions::from_mode(0o600))
        .unwrap();
    (&file).write_all(bytes).unwrap();
    std::os::unix::fs::chown(path, Some(uid), /*gid*/ None).unwrap();
    file.sync_all().unwrap();
}

impl Fixture {
    fn root_owned() -> Self {
        assert_eq!(
            super::super::OwnerRule::CurrentUser.expected_uid().unwrap(),
            0
        );
        let protected = std::env::var_os("HEPTA_TEST_ROOT_MATERIAL_DESTINATION")
            .expect("actual Root fixture requires its protected destination");
        let name = crate::runtime::test_support::unique_temp_dir();
        let root = PathBuf::from(protected).join(name.file_name().unwrap());
        std::fs::create_dir(&root).unwrap();
        std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700)).unwrap();
        for child in ["source", "owner"] {
            std::fs::create_dir(root.join(child)).unwrap();
            std::fs::set_permissions(root.join(child), std::fs::Permissions::from_mode(0o700))
                .unwrap();
        }
        private_file(
            &root.join("source/cognitive_1.sqlite3"),
            b"retained physical bytes, not a Current proof",
            0,
        );
        private_file(&root.join("owner").join(LOCK), b"", 60001);
        private_file(
            &root.join("owner").join(POINTER),
            format!("{OLD}\n").as_bytes(),
            60001,
        );
        for suffix in ["", "-wal", "-shm", "-journal"] {
            private_file(
                &root.join("owner").join(format!("{OLD}{suffix}")),
                format!("dirty sentinel {suffix}").as_bytes(),
                60001,
            );
        }
        std::os::unix::fs::chown(root.join("owner"), Some(60001), /*gid*/ None).unwrap();
        Self {
            source: config(root.join("source")),
            destination: config(root.join("owner")),
            root,
        }
    }

    fn source(&self) -> ExistingSqliteRecoveryGuard {
        self.source
            .bind_existing_recovery_database(&self.source.home().join("cognitive_1.sqlite3"))
            .unwrap()
    }

    fn bind(&self) -> RootSqliteOwnerCopy {
        RootSqliteOwnerCopy::bind_registered(&self.destination, OsStr::new(LOCK)).unwrap()
    }

    fn assert_predecessor_unchanged(&self) {
        assert_eq!(
            std::fs::read(self.destination.home().join(POINTER)).unwrap(),
            format!("{OLD}\n").as_bytes()
        );
        for suffix in ["", "-wal", "-shm", "-journal"] {
            assert_eq!(
                std::fs::read(self.destination.home().join(format!("{OLD}{suffix}"))).unwrap(),
                format!("dirty sentinel {suffix}").as_bytes()
            );
        }
        assert_eq!(
            std::fs::read(self.source.home().join("cognitive_1.sqlite3")).unwrap(),
            b"retained physical bytes, not a Current proof"
        );
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

#[test]
fn owner_copy_refuses_non_root_before_creating_any_path() {
    if super::super::OwnerRule::CurrentUser.expected_uid().unwrap() == 0 {
        let status = child_command("deny").status().unwrap();
        assert!(status.success());
        return;
    }
    assert_non_root_refusal();
}

fn assert_non_root_refusal() {
    assert_ne!(
        super::super::OwnerRule::CurrentUser.expected_uid().unwrap(),
        0
    );
    let absent = crate::runtime::test_support::unique_temp_dir();
    assert!(!absent.exists());
    assert!(
        RootSqliteOwnerCopy::bind_registered(&config(absent.clone()), OsStr::new(LOCK)).is_err()
    );
    assert!(!absent.exists());
}

#[test]
#[ignore = "requires actual Root0 and a protected destination; never substitute the current UID"]
fn root_owner_copy_retains_real_lock_and_never_activates_candidate() {
    let fixture = Fixture::root_owned();
    let guard = fixture.source();
    let candidate = fixture
        .bind()
        .materialize_consolidated_candidate(&guard, OsStr::new(CANDIDATE))
        .unwrap();
    let metadata = std::fs::metadata(candidate.path()).unwrap();
    assert_eq!(
        (metadata.uid(), metadata.mode() & 0o7777, metadata.nlink()),
        (60001, 0o600, 1)
    );
    assert_eq!(
        std::fs::read(candidate.path()).unwrap(),
        std::fs::read(fixture.source.home().join("cognitive_1.sqlite3")).unwrap()
    );
    candidate.verify_unchanged().unwrap();
    fixture.assert_predecessor_unchanged();
    let other_lock = File::open(fixture.destination.home().join(LOCK)).unwrap();
    assert!(other_lock.try_lock().is_err());
    drop(candidate);
    other_lock.try_lock().unwrap();
    drop(other_lock);
    assert!(
        fixture
            .bind()
            .materialize_consolidated_candidate(&guard, OsStr::new(CANDIDATE))
            .is_err(),
        "an existing candidate must never be reused"
    );
    fixture.assert_predecessor_unchanged();
}

#[test]
#[ignore = "requires actual Root0 and a protected destination"]
fn root_owner_copy_refuses_actual_owner_lock_and_same_path_replacement() {
    let fixture = Fixture::root_owned();
    let mut child = child_command("lock");
    child.stdin(File::open(fixture.destination.home().join(LOCK)).unwrap());
    let mut child = start_child(child);
    assert_eq!(
        child.signals.recv_timeout(Duration::from_secs(5)).unwrap(),
        "locked"
    );
    assert!(RootSqliteOwnerCopy::bind_registered(&fixture.destination, OsStr::new(LOCK)).is_err());
    child.child.kill().unwrap();
    child.child.wait().unwrap();
    drop(child);
    let copy = fixture.bind();
    std::fs::rename(
        fixture.destination.home().join(LOCK),
        fixture.destination.home().join("retired-lock"),
    )
    .unwrap();
    private_file(
        &fixture.destination.home().join(LOCK),
        b"replacement",
        60001,
    );
    assert!(
        copy.materialize_consolidated_candidate(&fixture.source(), OsStr::new(CANDIDATE))
            .is_err()
    );
    assert!(!fixture.destination.home().join(CANDIDATE).exists());
    fixture.assert_predecessor_unchanged();
}

#[test]
#[ignore = "requires actual Root0 and a protected destination"]
fn root_owner_copy_rejects_source_drift_and_preserves_existing_sidecars() {
    for change in ["bytes", "inode", "source-sidecar", "candidate-sidecar"] {
        let fixture = Fixture::root_owned();
        let guard = fixture.source();
        let source = fixture.source.home().join("cognitive_1.sqlite3");
        match change {
            "bytes" => std::fs::write(&source, b"different bytes").unwrap(),
            "inode" => {
                std::fs::rename(&source, source.with_extension("old")).unwrap();
                private_file(&source, b"retained physical bytes, not a Current proof", 0);
            }
            "source-sidecar" => private_file(&source.with_extension("sqlite3-wal"), b"wal", 0),
            "candidate-sidecar" => private_file(
                &fixture.destination.home().join(format!("{CANDIDATE}-wal")),
                b"do not touch",
                60001,
            ),
            _ => unreachable!(),
        }
        assert!(
            fixture
                .bind()
                .materialize_consolidated_candidate(&guard, OsStr::new(CANDIDATE))
                .is_err(),
            "{change}"
        );
        assert!(!fixture.destination.home().join(CANDIDATE).exists());
        if change == "candidate-sidecar" {
            assert_eq!(
                std::fs::read(fixture.destination.home().join(format!("{CANDIDATE}-wal"))).unwrap(),
                b"do not touch"
            );
            fixture.assert_predecessor_unchanged();
        }
    }
}

#[test]
#[ignore = "requires actual Root0 and a protected destination"]
fn root_owner_copy_rejects_redirected_directory_and_unsafe_entries() {
    for change in [
        "parent-owner",
        "parent-writable",
        "leaf-mode",
        "lock-symlink",
        "lock-hardlink",
        "lock-fifo",
    ] {
        let fixture = Fixture::root_owned();
        let lock = fixture.destination.home().join(LOCK);
        match change {
            "parent-owner" => {
                std::os::unix::fs::chown(&fixture.root, Some(60001), /*gid*/ None).unwrap()
            }
            "parent-writable" => {
                std::fs::set_permissions(&fixture.root, std::fs::Permissions::from_mode(0o722))
                    .unwrap()
            }
            "leaf-mode" => std::fs::set_permissions(
                fixture.destination.home(),
                std::fs::Permissions::from_mode(0o750),
            )
            .unwrap(),
            "lock-symlink" => {
                std::fs::remove_file(&lock).unwrap();
                symlink("absent", &lock).unwrap();
            }
            "lock-hardlink" => {
                std::fs::hard_link(&lock, fixture.destination.home().join("alias")).unwrap()
            }
            "lock-fifo" => {
                std::fs::remove_file(&lock).unwrap();
                let name = std::ffi::CString::new(lock.as_os_str().as_encoded_bytes()).unwrap();
                // SAFETY: name is NUL-terminated and live for this syscall.
                assert_eq!(unsafe { libc::mkfifo(name.as_ptr(), 0o600) }, 0);
            }
            _ => unreachable!(),
        }
        assert!(
            RootSqliteOwnerCopy::bind_registered(&fixture.destination, OsStr::new(LOCK)).is_err(),
            "{change}"
        );
        assert!(!fixture.destination.home().join(CANDIDATE).exists());
    }
    let fixture = Fixture::root_owned();
    let copy = fixture.bind();
    std::fs::rename(
        fixture.destination.home(),
        fixture.root.join("original-owner"),
    )
    .unwrap();
    std::fs::create_dir(fixture.destination.home()).unwrap();
    std::fs::set_permissions(
        fixture.destination.home(),
        std::fs::Permissions::from_mode(0o700),
    )
    .unwrap();
    std::os::unix::fs::chown(fixture.destination.home(), Some(60001), /*gid*/ None).unwrap();
    assert!(
        copy.materialize_consolidated_candidate(&fixture.source(), OsStr::new(CANDIDATE))
            .is_err()
    );
    assert!(
        std::fs::read_dir(fixture.destination.home())
            .unwrap()
            .next()
            .is_none()
    );
    assert!(!fixture.root.join("original-owner").join(CANDIDATE).exists());
}

#[test]
#[ignore = "requires actual Root0, protected destination and actual child SIGKILL"]
fn root_owner_copy_killed_at_physical_stages_preserves_original_selection() {
    for stage in [
        "created",
        "written",
        "data-synced",
        "ownership-synced",
        "directory-synced",
    ] {
        let fixture = Fixture::root_owned();
        let mut command = child_command("copy");
        command
            .env("HEPTA_OWNER_COPY_ROOT", &fixture.root)
            .env("HEPTA_OWNER_COPY_STAGE", stage)
            .stdin(Stdio::piped());
        let mut child = start_child(command);
        assert_eq!(
            child.signals.recv_timeout(Duration::from_secs(5)).unwrap(),
            stage
        );
        child.child.kill().unwrap();
        assert!(!child.child.wait().unwrap().success());
        drop(child);
        assert!(fixture.destination.home().join(CANDIDATE).exists());
        fixture.assert_predecessor_unchanged();
        drop(fixture.bind());
    }
}

#[test]
#[ignore = "requires actual Root0 and a protected destination; the I/O error is explicitly injected"]
fn root_owner_copy_injected_sync_error_leaves_unactivated_orphan() {
    let fixture = Fixture::root_owned();
    let mut command = child_command("copy");
    command
        .env("HEPTA_OWNER_COPY_ROOT", &fixture.root)
        .env("HEPTA_OWNER_COPY_STAGE", "fail-directory-sync");
    let output = command.output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(fixture.destination.home().join(CANDIDATE).exists());
    fixture.assert_predecessor_unchanged();
    drop(fixture.bind());
}

#[test]
#[ignore = "requires actual Root0 and a protected destination"]
fn root_owner_copy_bounds_image_and_refuses_path_names_before_creation() {
    for length in [0, 128 * 1024 * 1024 + 1] {
        let fixture = Fixture::root_owned();
        OpenOptions::new()
            .write(true)
            .open(fixture.source.home().join("cognitive_1.sqlite3"))
            .unwrap()
            .set_len(length)
            .unwrap();
        let result = fixture
            .bind()
            .materialize_consolidated_candidate(&fixture.source(), OsStr::new(CANDIDATE));
        assert!(matches!(result, Err(SqliteRecoveryError::Unavailable)));
        assert!(!fixture.destination.home().join(CANDIDATE).exists());
    }
    let fixture = Fixture::root_owned();
    for name in [
        "../escaped.sqlite3",
        "/absolute.sqlite3",
        "nested/candidate.sqlite3",
        "foo.sqlite3/",
        ".cognitive-active-v1",
        "line\nbreak.sqlite3",
    ] {
        assert!(
            fixture
                .bind()
                .materialize_consolidated_candidate(&fixture.source(), OsStr::new(name))
                .is_err(),
            "{name:?}"
        );
    }
    assert!(!fixture.root.join("escaped.sqlite3").exists());
    fixture.assert_predecessor_unchanged();
}

#[test]
#[ignore = "requires actual Root0, a protected destination and controlled child barriers"]
fn root_owner_copy_replacement_during_write_never_targets_replacement_entries() {
    for replacement in ["candidate", "hardlink", "directory"] {
        let fixture = Fixture::root_owned();
        let mut command = child_command("copy-refuse");
        command
            .env("HEPTA_OWNER_COPY_ROOT", &fixture.root)
            .env("HEPTA_OWNER_COPY_STAGE", "created")
            .stdin(Stdio::piped());
        let mut child = start_child(command);
        assert_eq!(
            child.signals.recv_timeout(Duration::from_secs(5)).unwrap(),
            "created"
        );
        let candidate = fixture.destination.home().join(CANDIDATE);
        match replacement {
            "candidate" | "hardlink" => {
                std::fs::rename(&candidate, fixture.destination.home().join("held-orphan"))
                    .unwrap();
                if replacement == "candidate" {
                    private_file(&candidate, b"replacement must stay unchanged", 60001);
                } else {
                    std::fs::hard_link(fixture.destination.home().join(OLD), &candidate).unwrap();
                }
            }
            "directory" => {
                std::fs::rename(fixture.destination.home(), fixture.root.join("held-owner"))
                    .unwrap();
                std::fs::create_dir(fixture.destination.home()).unwrap();
                std::fs::set_permissions(
                    fixture.destination.home(),
                    std::fs::Permissions::from_mode(0o700),
                )
                .unwrap();
                std::os::unix::fs::chown(
                    fixture.destination.home(),
                    Some(60001),
                    /*gid*/ None,
                )
                .unwrap();
            }
            _ => unreachable!(),
        }
        child.child.stdin.as_mut().unwrap().write_all(&[1]).unwrap();
        assert_eq!(
            child.signals.recv_timeout(Duration::from_secs(5)).unwrap(),
            "rejected"
        );
        assert!(child.child.wait().unwrap().success());
        drop(child);
        if replacement == "directory" {
            assert!(
                std::fs::read_dir(fixture.destination.home())
                    .unwrap()
                    .next()
                    .is_none()
            );
            assert_eq!(
                std::fs::read(fixture.root.join("held-owner").join(POINTER)).unwrap(),
                format!("{OLD}\n").as_bytes()
            );
        } else {
            fixture.assert_predecessor_unchanged();
            let expected = if replacement == "candidate" {
                b"replacement must stay unchanged".as_slice()
            } else {
                b"dirty sentinel ".as_slice()
            };
            assert_eq!(std::fs::read(&candidate).unwrap(), expected);
        }
    }
}

// Private test-only barrier. Production exposes no callback or fault switch.
pub(super) fn checkpoint(stage: &str) -> Result<(), SqliteRecoveryError> {
    let Ok(requested) = std::env::var("HEPTA_OWNER_COPY_STAGE") else {
        return Ok(());
    };
    if requested == "fail-directory-sync" && stage == "before-directory-sync" {
        return Err(SqliteRecoveryError::Indeterminate);
    }
    if requested == stage {
        println!("ROOT_OWNER_COPY {stage}");
        std::io::stdout().flush().unwrap();
        std::io::stdin().read_exact(&mut [0_u8]).unwrap();
    }
    Ok(())
}

fn child_command(role: &str) -> Command {
    let suffix = module_path!().split_once("::").unwrap().1;
    let mut command = Command::new(std::env::current_exe().unwrap());
    command
        .args([
            "--exact",
            &format!("{suffix}::child_helper"),
            "--ignored",
            "--nocapture",
        ])
        .env("HEPTA_OWNER_COPY_CHILD", role);
    command
}

struct ControlledChild {
    child: Child,
    signals: mpsc::Receiver<String>,
    reader: Option<std::thread::JoinHandle<()>>,
}

impl Drop for ControlledChild {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
        if let Some(reader) = self.reader.take() {
            let _ = reader.join();
        }
    }
}

fn start_child(mut command: Command) -> ControlledChild {
    let mut child = command
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .unwrap();
    let stdout = child.stdout.take().unwrap();
    let (send, receive) = mpsc::channel();
    let reader = std::thread::spawn(move || {
        for line in std::io::BufReader::new(stdout).lines() {
            let line = line.unwrap();
            if let Some((_, value)) = line.split_once("ROOT_OWNER_COPY ") {
                let _ = send.send(value.to_string());
            }
        }
    });
    ControlledChild {
        child,
        signals: receive,
        reader: Some(reader),
    }
}

#[test]
#[ignore = "only the controlled parent launches this helper"]
fn child_helper() {
    match std::env::var("HEPTA_OWNER_COPY_CHILD").unwrap().as_str() {
        "deny" | "lock" => {
            // SAFETY: this dedicated child is still Root; drop supplementary
            // groups and all UID/GID privilege before exercising owner access.
            unsafe {
                assert_eq!(libc::setgroups(0, std::ptr::null()), 0);
                assert_eq!(libc::setgid(60001), 0);
                assert_eq!(libc::setuid(60001), 0);
            }
            if std::env::var("HEPTA_OWNER_COPY_CHILD").unwrap() == "deny" {
                assert_non_root_refusal();
                return;
            }
            assert_eq!(
                super::super::OwnerRule::CurrentUser.expected_uid().unwrap(),
                60001
            );
            // SAFETY: parent transferred its original opened lock as stdin.
            // This child has not constructed another owner of descriptor 0.
            let lock = unsafe { File::from_raw_fd(libc::STDIN_FILENO) };
            lock.try_lock_shared().unwrap();
            println!("ROOT_OWNER_COPY locked");
            std::io::stdout().flush().unwrap();
            loop {
                std::thread::park();
            }
        }
        "copy" | "copy-refuse" => {
            let root = PathBuf::from(std::env::var_os("HEPTA_OWNER_COPY_ROOT").unwrap());
            let source = config(root.join("source"));
            let guard = source
                .bind_existing_recovery_database(&source.home().join("cognitive_1.sqlite3"))
                .unwrap();
            let result =
                RootSqliteOwnerCopy::bind_registered(&config(root.join("owner")), OsStr::new(LOCK))
                    .unwrap()
                    .materialize_consolidated_candidate(&guard, OsStr::new(CANDIDATE));
            assert!(
                std::env::var("HEPTA_OWNER_COPY_STAGE").unwrap() == "fail-directory-sync"
                    || std::env::var("HEPTA_OWNER_COPY_CHILD").unwrap() == "copy-refuse"
            );
            assert!(result.is_err());
            println!("ROOT_OWNER_COPY rejected");
        }
        value => panic!("unexpected controlled child role: {value}"),
    }
}
