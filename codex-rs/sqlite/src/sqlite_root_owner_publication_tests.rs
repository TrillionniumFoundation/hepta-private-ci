use super::super::RootSqliteOwnerCopy;
use super::super::SqliteConfig;
use super::*;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use std::fs::OpenOptions;
use std::io::BufRead;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::sync::mpsc;
use std::time::Duration;

const POINTER: &str = ".cognitive-active-v1";
const LOCK: &str = ".cognitive-store.lock";
const CANDIDATE: &str = "cognitive_recovered_v1_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.sqlite3";
const OLD: &str = "cognitive_recovered_v1_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.sqlite3";
const TEMPORARY: &str = ".cognitive-active-v1.tmp-publication-fixture";

struct Fixture {
    root: PathBuf,
}
fn config(path: PathBuf) -> SqliteConfig {
    SqliteConfig::from_sqlite_home(AbsolutePathBuf::try_from(path).unwrap())
}
fn file(path: &Path, bytes: &[u8], uid: u32) {
    let file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path)
        .unwrap();
    file.set_permissions(std::fs::Permissions::from_mode(0o600))
        .unwrap();
    (&file).write_all(bytes).unwrap();
    std::os::unix::fs::chown(path, Some(uid), /*gid*/ None).unwrap();
    file.sync_all().unwrap();
}
impl Fixture {
    fn new() -> Self {
        directory::require_root().unwrap();
        let parent = std::env::var_os("HEPTA_TEST_ROOT_MATERIAL_DESTINATION")
            .expect("protected actual Root fixture destination");
        let name = crate::test_support::unique_temp_dir();
        let root = PathBuf::from(parent).join(name.file_name().unwrap());
        std::fs::create_dir(&root).unwrap();
        std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700)).unwrap();
        for name in ["source", "owner"] {
            std::fs::create_dir(root.join(name)).unwrap();
            std::fs::set_permissions(root.join(name), std::fs::Permissions::from_mode(0o700))
                .unwrap();
        }
        file(
            &root.join("source/cognitive_1.sqlite3"),
            b"physical image only; not an authenticated cut",
            0,
        );
        file(&root.join("owner").join(LOCK), b"", 60001);
        file(
            &root.join("owner").join(POINTER),
            format!("{OLD}\n").as_bytes(),
            60001,
        );
        for suffix in ["", "-wal", "-shm", "-journal"] {
            file(
                &root.join("owner").join(format!("{OLD}{suffix}")),
                b"original Dirty bytes",
                60001,
            );
        }
        std::os::unix::fs::chown(root.join("owner"), Some(60001), /*gid*/ None).unwrap();
        Self { root }
    }
    fn prepare(&self) -> RootSqliteOwnerPublication {
        prepare(&self.root).unwrap()
    }
    fn preserve_dirty(&self) {
        for suffix in ["", "-wal", "-shm", "-journal"] {
            assert_eq!(
                std::fs::read(self.root.join("owner").join(format!("{OLD}{suffix}"))).unwrap(),
                b"original Dirty bytes"
            );
        }
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}
fn prepare(root: &Path) -> Result<RootSqliteOwnerPublication, SqliteRecoveryError> {
    let source = config(root.join("source"));
    let source =
        source.bind_existing_recovery_database(&source.home().join("cognitive_1.sqlite3"))?;
    RootSqliteOwnerCopy::bind_registered(&config(root.join("owner")), OsStr::new(LOCK))?
        .materialize_consolidated_candidate(&source, OsStr::new(CANDIDATE))?
        .observe_active_pointer(OsStr::new(POINTER))
}

#[test]
#[ignore = "requires actual Root0 and its protected material test destination"]
fn root_publication_keeps_original_lock_and_publishes_only_bound_candidate() {
    let fixture = Fixture::new();
    let publication = fixture.prepare();
    assert_eq!(
        publication.previous_pointer_bytes(),
        Some(format!("{OLD}\n").as_bytes())
    );
    let published = publication.publish(OsStr::new(TEMPORARY)).unwrap();
    published.verify_unchanged().unwrap();
    assert_eq!(published.path(), fixture.root.join("owner").join(CANDIDATE));
    assert_eq!(
        std::fs::read(fixture.root.join("owner").join(POINTER)).unwrap(),
        format!("{CANDIDATE}\n").as_bytes()
    );
    let pointer = std::fs::metadata(fixture.root.join("owner").join(POINTER)).unwrap();
    assert_eq!(
        (pointer.uid(), pointer.mode() & 0o7777, pointer.nlink()),
        (60001, 0o600, 1)
    );
    let contender = File::open(fixture.root.join("owner").join(LOCK)).unwrap();
    assert!(contender.try_lock().is_err());
    drop(published);
    contender.try_lock().unwrap();
    fixture.preserve_dirty();
}

#[test]
#[ignore = "requires actual Root0 and its protected material test destination"]
fn root_publication_rejects_pointer_or_parent_replacement_without_touching_replacement() {
    for replace_parent in [false, true] {
        let fixture = Fixture::new();
        let publication = fixture.prepare();
        if replace_parent {
            std::fs::rename(
                fixture.root.join("owner"),
                fixture.root.join("retained-owner"),
            )
            .unwrap();
            std::fs::create_dir(fixture.root.join("owner")).unwrap();
            file(
                &fixture.root.join("owner").join(POINTER),
                b"replacement untouched",
                60001,
            );
        } else {
            std::fs::rename(
                fixture.root.join("owner").join(POINTER),
                fixture.root.join("owner/old-pointer"),
            )
            .unwrap();
            file(
                &fixture.root.join("owner").join(POINTER),
                b"replacement untouched",
                60001,
            );
        }
        assert!(publication.publish(OsStr::new(TEMPORARY)).is_err());
        assert_eq!(
            std::fs::read(fixture.root.join("owner").join(POINTER)).unwrap(),
            b"replacement untouched"
        );
    }
}

#[test]
#[ignore = "requires actual Root0 and its protected material test destination"]
fn root_publication_accepts_absence_but_never_reuses_temporary_or_follows_pointer_link() {
    let fixture = Fixture::new();
    std::fs::remove_file(fixture.root.join("owner").join(POINTER)).unwrap();
    let publication = fixture.prepare();
    assert_eq!(publication.previous_pointer_bytes(), None);
    file(
        &fixture.root.join("owner").join(TEMPORARY),
        b"previous incomplete publication",
        60001,
    );
    assert!(publication.publish(OsStr::new(TEMPORARY)).is_err());
    assert!(!fixture.root.join("owner").join(POINTER).exists());
    assert_eq!(
        std::fs::read(fixture.root.join("owner").join(TEMPORARY)).unwrap(),
        b"previous incomplete publication"
    );
    let redirected = Fixture::new();
    std::fs::remove_file(redirected.root.join("owner").join(POINTER)).unwrap();
    std::os::unix::fs::symlink(
        redirected.root.join("source/cognitive_1.sqlite3"),
        redirected.root.join("owner").join(POINTER),
    )
    .unwrap();
    assert!(prepare(&redirected.root).is_err());
    redirected.preserve_dirty();
}

struct ControlledChild {
    child: Child,
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
fn child_command(root: &Path, phase: &str, mode: &str) -> Command {
    let name = format!(
        "{}::publication_child",
        module_path!().split_once("::").unwrap().1
    );
    let mut command = Command::new(std::env::current_exe().unwrap());
    command
        .args(["--exact", &name, "--ignored", "--nocapture"])
        .env("HEPTA_TEST_OWNER_PUBLICATION_ROOT", root)
        .env("HEPTA_TEST_OWNER_PUBLICATION_PHASE", phase)
        .env("HEPTA_TEST_OWNER_PUBLICATION_MODE", mode)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit());
    command
}

#[test]
#[ignore = "requires actual Root0; executes five real SIGKILL publication boundaries"]
fn root_publication_crash_preserves_old_files_and_never_returns_a_receipt() {
    for phase in [
        "pointer-created",
        "pointer-synced",
        "pointer-renamed",
        "before-pointer-directory-sync",
        "pointer-directory-synced",
    ] {
        let fixture = Fixture::new();
        let mut child = child_command(&fixture.root, phase, "pause")
            .spawn()
            .unwrap();
        let output = child.stdout.take().unwrap();
        let (sender, receiver) = mpsc::channel();
        let reader = std::thread::spawn(move || {
            for line in std::io::BufReader::new(output)
                .lines()
                .map_while(Result::ok)
            {
                if line == "publication-paused" {
                    let _ = sender.send(());
                    break;
                }
            }
        });
        let mut controlled = ControlledChild {
            child,
            reader: Some(reader),
        };
        receiver
            .recv_timeout(Duration::from_secs(5))
            .expect("bounded actual publication phase");
        controlled.child.kill().unwrap();
        assert!(!controlled.child.wait().unwrap().success());
        drop(controlled);
        fixture.preserve_dirty();
        let selected = std::fs::read(fixture.root.join("owner").join(POINTER)).unwrap();
        let expected = if matches!(phase, "pointer-created" | "pointer-synced") {
            OLD
        } else {
            CANDIDATE
        };
        assert_eq!(selected, format!("{expected}\n").as_bytes());
        let lock = File::open(fixture.root.join("owner").join(LOCK)).unwrap();
        lock.try_lock().unwrap();
    }
}

#[test]
#[ignore = "requires actual Root0; injected sync-boundary error is not a kernel power-loss test"]
fn root_publication_uncertain_directory_sync_never_returns_success_or_reuses_candidate() {
    let fixture = Fixture::new();
    let output = child_command(&fixture.root, "before-pointer-directory-sync", "fail")
        .output()
        .unwrap();
    assert!(output.status.success(), "{output:?}");
    assert_eq!(
        std::fs::read(fixture.root.join("owner").join(POINTER)).unwrap(),
        format!("{CANDIDATE}\n").as_bytes()
    );
    fixture.preserve_dirty();
    assert!(prepare(&fixture.root).is_err());
}

pub(super) fn checkpoint(phase: &str) -> Result<(), SqliteRecoveryError> {
    if std::env::var("HEPTA_TEST_OWNER_PUBLICATION_PHASE").as_deref() != Ok(phase) {
        return Ok(());
    }
    match std::env::var("HEPTA_TEST_OWNER_PUBLICATION_MODE").as_deref() {
        Ok("fail") => Err(SqliteRecoveryError::Indeterminate),
        Ok("pause") => {
            println!("publication-paused");
            std::io::stdout().flush().unwrap();
            let mut byte = [0];
            std::io::stdin().read_exact(&mut byte).unwrap();
            Ok(())
        }
        _ => panic!("invalid private publication fixture mode"),
    }
}

#[test]
#[ignore = "controlled child only; parent supplies actual Root context"]
fn publication_child() {
    let root =
        std::env::var_os("HEPTA_TEST_OWNER_PUBLICATION_ROOT").expect("controlled child root");
    let result = prepare(Path::new(&root))
        .unwrap()
        .publish(OsStr::new(TEMPORARY));
    if std::env::var("HEPTA_TEST_OWNER_PUBLICATION_MODE").as_deref() == Ok("fail") {
        assert!(matches!(result, Err(SqliteRecoveryError::Indeterminate)));
    } else {
        result.unwrap();
    }
}
