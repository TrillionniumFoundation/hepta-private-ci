//! Creation-time Linux DAC checks on the original controller's write path.
//! Every umask change occurs in a dedicated single-test subprocess. The Root
//! case executes an actual UID/GID60001 child at the pre-chmod boundary; this
//! qualifies host filesystem permissions, not a native kernel or writer role.

use super::*;
use pretty_assertions::assert_eq;
use std::cell::Cell;
use std::cell::RefCell;
use std::os::unix::process::CommandExt;
use std::path::PathBuf;
use std::process::Command;
use std::rc::Rc;

const WORKER: &str = "control_file::creation_tests::control_creation_isolated_worker";
const FOREIGN: &str = "control_file::creation_tests::control_creation_non_owner_child";
const KIND_ENV: &str = "HEPTA_CONTROL_CREATE_TEST_KIND";
const MASK_ENV: &str = "HEPTA_CONTROL_CREATE_TEST_UMASK";
const PATH_ENV: &str = "HEPTA_CONTROL_CREATE_TEST_PATH";
const EXPECT_ENV: &str = "HEPTA_CONTROL_CREATE_TEST_EXPECT";
const INSTALL_ENV: &str = "HEPTA_TEST_ROOT_OWNER_INSTALL_DESTINATION";
const HOST: u32 = 60001;

type CreationObserver = Box<dyn FnOnce(&File, &Path) -> Result<(), FleetRegistryError>>;

thread_local! {
    static CREATION_OBSERVER: RefCell<Option<CreationObserver>> = RefCell::new(None);
}

/// Test-only observation immediately after the actual O_EXCL open and before
/// any owner adjustment, chmod, write or publication. No production hook exists.
pub(super) fn observe_created(file: &File, path: &Path) -> Result<(), FleetRegistryError> {
    let observer = CREATION_OBSERVER.with(|slot| slot.borrow_mut().take());
    if let Some(observer) = observer {
        observer(file, path)?;
    }
    Ok(())
}

fn observe_once(observer: impl FnOnce(&File, &Path) -> Result<(), FleetRegistryError> + 'static) {
    CREATION_OBSERVER.with(|slot| {
        let mut slot = slot.borrow_mut();
        assert!(slot.is_none());
        *slot = Some(Box::new(observer));
    });
}

fn run_one(mut command: Command) -> Result<(), FleetRegistryError> {
    let output = command.output()?;
    if !output.status.success() {
        return Err(corrupt(format!(
            "isolated control-creation check failed: {}\n{}\n{}",
            output.status,
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr),
        )));
    }
    print!("{}", String::from_utf8_lossy(&output.stdout));
    Ok(())
}

fn exact_test(executable: &Path, selector: &str) -> Command {
    let mut command = Command::new(executable);
    command.args([
        "--exact",
        selector,
        "--ignored",
        "--nocapture",
        "--test-threads=1",
    ]);
    command
}

#[test]
fn control_creation_preserves_umask_without_shared_write_at_open() -> Result<(), FleetRegistryError>
{
    let executable = std::env::current_exe()?;
    for mask in ["000", "002", "022", "027", "077"] {
        let mut command = exact_test(&executable, WORKER);
        command.env(KIND_ENV, "ordinary").env(MASK_ENV, mask);
        run_one(command)?;
    }
    Ok(())
}

fn root_exec_parent() -> Result<PathBuf, FleetRegistryError> {
    let parent = PathBuf::from(
        std::env::var_os(INSTALL_ENV)
            .ok_or_else(|| corrupt("explicit Root0/0711 executable fixture parent is required"))?,
    );
    if !parent.is_absolute() || parent.canonicalize()? != parent {
        return Err(corrupt("Root executable fixture parent must be canonical"));
    }
    for path in parent.ancestors() {
        let metadata = std::fs::symlink_metadata(path)?;
        if !metadata.is_dir()
            || metadata.file_type().is_symlink()
            || metadata.uid() != 0
            || metadata.mode() & 0o022 != 0
            || metadata.mode() & 0o001 == 0
        {
            return Err(corrupt(
                "Root executable fixture ancestor is not protected and searchable",
            ));
        }
    }
    let metadata = std::fs::metadata(&parent)?;
    if metadata.gid() != 0 || metadata.mode() & 0o7777 != 0o711 {
        return Err(corrupt(
            "Root executable fixture parent must be exactly Root0:0/0711",
        ));
    }
    Ok(parent)
}

#[test]
#[ignore = "isolated actual Root, UID60001 and explicit protected executable fixture parent"]
fn control_creation_refuses_actual_non_owner_write_before_chmod() -> Result<(), FleetRegistryError>
{
    if rustix::process::geteuid().as_raw() != 0 {
        return Err(corrupt("actual Root qualification is required"));
    }
    let install = tempfile::Builder::new()
        .prefix("hepta-fleet-control-create-")
        .tempdir_in(root_exec_parent()?)?;
    std::fs::set_permissions(install.path(), std::fs::Permissions::from_mode(0o711))?;
    let executable = install.path().join("original-fleet-libtest");
    std::fs::copy(std::env::current_exe()?, &executable)?;
    std::fs::set_permissions(&executable, std::fs::Permissions::from_mode(0o555))?;
    File::open(&executable)?.sync_all()?;
    for mask in ["000", "002", "077"] {
        let mut command = exact_test(&executable, WORKER);
        command.env(KIND_ENV, "root-native").env(MASK_ENV, mask);
        run_one(command)?;
    }
    Ok(())
}

fn foreign_probe(path: &Path, expect_open: bool) -> Result<(), FleetRegistryError> {
    let mut command = exact_test(&std::env::current_exe()?, FOREIGN);
    command
        .uid(HOST)
        .gid(HOST)
        .env(PATH_ENV, path)
        .env(EXPECT_ENV, if expect_open { "opened" } else { "denied" });
    run_one(command)
}

struct RestoreUmask(Mode);
impl Drop for RestoreUmask {
    fn drop(&mut self) {
        rustix::process::umask(self.0);
    }
}

#[test]
#[ignore = "private single-test subprocess; never changes a parallel test runner's umask"]
fn control_creation_isolated_worker() -> Result<(), FleetRegistryError> {
    let arguments: Vec<String> = std::env::args().collect();
    if !arguments.iter().any(|arg| arg == WORKER)
        || !arguments.iter().any(|arg| arg == "--exact")
        || !arguments.iter().any(|arg| arg == "--test-threads=1")
    {
        return Err(corrupt(
            "umask check requires its dedicated exact single-test process",
        ));
    }
    let kind = std::env::var(KIND_ENV).map_err(|_| corrupt("missing isolated test kind"))?;
    let mask_text = std::env::var(MASK_ENV).map_err(|_| corrupt("missing isolated test umask"))?;
    let mask = u32::from_str_radix(&mask_text, 8).map_err(|_| corrupt("invalid test umask"))?;
    if ![0, 0o002, 0o022, 0o027, 0o077].contains(&mask) {
        return Err(corrupt("test umask is outside the finite fixture"));
    }
    let _restore = RestoreUmask(rustix::process::umask(Mode::from_bits_truncate(mask)));
    match kind.as_str() {
        "ordinary" => ordinary_case(mask),
        "root-native" => root_case(mask),
        _ => Err(corrupt("unknown isolated test kind")),
    }
}

fn ordinary_case(mask: u32) -> Result<(), FleetRegistryError> {
    let temp = tempfile::tempdir()?;
    std::fs::set_permissions(temp.path(), std::fs::Permissions::from_mode(0o700))?;
    let owner = ControlOwner::at(temp.path())?;
    let path = temp.path().join("new-control.json");
    let observed = Rc::new(Cell::new(false));
    let captured = observed.clone();
    observe_once(move |file, _| {
        let mode = file.metadata()?.mode() & 0o777;
        assert_eq!(mode, 0o644 & !mask);
        assert_eq!(mode & 0o022, 0);
        captured.set(true);
        Ok(())
    });
    owner.write_new(&path, b"original controller bytes\n")?;
    assert!(
        observed.get(),
        "the actual creation boundary was not reached"
    );
    assert_eq!(std::fs::metadata(&path)?.mode() & 0o777, 0o644 & !mask);
    assert_eq!(owner.read_text(&path)?, "original controller bytes\n");
    println!("control-create ordinary umask={mask:03o} actual pre-chmod and final mode verified");
    Ok(())
}

fn root_case(mask: u32) -> Result<(), FleetRegistryError> {
    if rustix::process::geteuid().as_raw() != 0 {
        return Err(corrupt("native permission worker must be actual Root"));
    }
    let executable = std::env::current_exe()?;
    let temp = tempfile::Builder::new()
        .prefix("controller-fixture-")
        .tempdir_in(
            executable
                .parent()
                .ok_or_else(|| corrupt("missing fixture parent"))?,
        )?;
    std::fs::set_permissions(temp.path(), std::fs::Permissions::from_mode(0o711))?;
    let agent = temp.path().join("agent");
    std::fs::create_dir(&agent)?;
    std::os::unix::fs::chown(&agent, Some(0), Some(HOST))?;
    std::fs::set_permissions(&agent, std::fs::Permissions::from_mode(0o750))?;
    let run = agent.join("run");
    std::fs::create_dir(&run)?;
    std::os::unix::fs::chown(&run, Some(0), Some(HOST))?;
    std::fs::set_permissions(&run, std::fs::Permissions::from_mode(0o3770))?;

    // Controlled old-mode negative. Only this disposable inode uses 0666;
    // the production writer has no mode selector or fault override.
    let old_path = run.join("old-mode-negative.json");
    let old_file: File = rustix::fs::open(
        &old_path,
        OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL | OFlags::NOFOLLOW | OFlags::CLOEXEC,
        Mode::from_bits_truncate(0o666),
    )
    .map_err(std::io::Error::from)?
    .into();
    assert_eq!(old_file.metadata()?.mode() & 0o777, 0o666 & !mask);
    foreign_probe(&old_path, mask & 0o020 == 0)?;
    old_file.set_permissions(std::fs::Permissions::from_mode(0o640))?;
    drop(old_file);

    let owner = ControlOwner::at(&agent)?;
    let path = run.join("actual-controller.json");
    let observed = Rc::new(Cell::new(false));
    let captured = observed.clone();
    observe_once(move |file, path| {
        let metadata = file.metadata()?;
        assert_eq!(
            (metadata.uid(), metadata.gid(), metadata.mode() & 0o777),
            (0, HOST, 0o644 & !mask)
        );
        // This executes before write_new can chown/chmod/write/publish. The
        // real other UID must fail its actual O_WRONLY open with EACCES.
        foreign_probe(path, false)?;
        captured.set(true);
        Ok(())
    });
    owner.write_new(&path, b"original controller bytes\n")?;
    assert!(
        observed.get(),
        "the actual creation boundary was not reached"
    );
    let published = std::fs::metadata(&path)?;
    assert_eq!(
        (published.uid(), published.gid(), published.mode() & 0o777),
        (0, HOST, 0o640)
    );
    assert_eq!(owner.read_text(&path)?, "original controller bytes\n");
    println!(
        "control-create Root/UID60001 umask={mask:03o} old-mode negative and actual write_new verified"
    );
    Ok(())
}

#[test]
#[ignore = "private actual non-owner child; executed after CommandExt uid/gid drop"]
fn control_creation_non_owner_child() -> Result<(), FleetRegistryError> {
    assert_eq!(
        (
            rustix::process::geteuid().as_raw(),
            rustix::process::getegid().as_raw()
        ),
        (HOST, HOST)
    );
    let path = PathBuf::from(
        std::env::var_os(PATH_ENV).ok_or_else(|| corrupt("missing original fixture file"))?,
    );
    let expected =
        std::env::var(EXPECT_ENV).map_err(|_| corrupt("missing original expected observation"))?;
    let metadata = std::fs::symlink_metadata(&path)?;
    assert!(metadata.is_file() && !metadata.file_type().is_symlink());
    assert_eq!((metadata.uid(), metadata.gid()), (0, HOST));
    let result = std::fs::OpenOptions::new().write(true).open(&path);
    match (expected.as_str(), result) {
        ("opened", Ok(mut file)) => {
            file.write_all(b"actual non-owner writable descriptor\n")?;
            file.sync_all()?;
            println!("control-create actual UID60001 acquired and wrote the old-mode descriptor");
        }
        ("denied", Err(error)) if error.raw_os_error() == Some(13) => {
            println!("control-create actual UID60001 O_WRONLY refused with EACCES");
        }
        (_, result) => {
            return Err(corrupt(format!(
                "actual foreign write differed from {expected}: {result:?}"
            )));
        }
    }
    Ok(())
}
