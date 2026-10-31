//! Actual supported argv reaches the explicit host-v2 decoder. No model is
//! admitted by these negative filesystem/dispatch controls.
#![cfg(target_os = "linux")]

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::process::CommandExt;
use std::process::Child;
use std::process::Command;
use std::process::Output;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;

struct OwnedChild(Option<Child>);
impl Drop for OwnedChild {
    fn drop(&mut self) {
        if let Some(child) = &mut self.0 {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

fn cli(args: &[String]) -> Output {
    let mut command =
        Command::new(codex_utils_cargo_bin::cargo_bin("hepta-neural-agentd").unwrap());
    command.args(args);
    run_command(command)
}

fn run_command(mut command: Command) -> Output {
    let child = command
        .env_remove("HEPTA_FLEET_ROOT")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    let mut owner = OwnedChild(Some(child));
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        if owner.0.as_mut().unwrap().try_wait().unwrap().is_some() {
            return owner.0.take().unwrap().wait_with_output().unwrap();
        }
        assert!(Instant::now() < deadline, "neural CLI child deadline");
        std::thread::sleep(Duration::from_millis(5));
    }
}

#[test]
fn actual_cell_daemon_rejects_anonymous_image_before_aliases_but_keeps_old_dispatch() {
    let directory = tempfile::tempdir().unwrap();
    let original = codex_utils_cargo_bin::cargo_bin("hepta-neural-agentd").unwrap();
    // SAFETY: a static NUL-terminated name and valid Linux flags create a new FD.
    let fd = unsafe {
        libc::memfd_create(
            c"hepta-cell-cli-fixture".as_ptr(),
            libc::MFD_CLOEXEC | libc::MFD_ALLOW_SEALING,
        )
    };
    assert!(fd >= 0, "native sealed-image fixture creation failed");
    // SAFETY: fd is a new successful memfd, transferred exactly once to File.
    let mut sealed = unsafe { File::from_raw_fd(fd) };
    std::io::copy(&mut File::open(&original).unwrap(), &mut sealed).unwrap();
    sealed
        .set_permissions(std::fs::Permissions::from_mode(0o700))
        .unwrap();
    let seals = libc::F_SEAL_SEAL | libc::F_SEAL_WRITE | libc::F_SEAL_GROW | libc::F_SEAL_SHRINK;
    // SAFETY: the live FD is owned above, and F_ADD_SEALS takes the integer mask.
    assert_eq!(
        unsafe { libc::fcntl(sealed.as_raw_fd(), libc::F_ADD_SEALS, seals) },
        0
    );
    let fd_path = format!("/proc/self/fd/{}", sealed.as_raw_fd());
    let message = "Cell-v2 requires a reopenable native image";
    for (name, args) in [
        ("help", vec!["--host-format", "cell-v2", "--help"]),
        (
            "cold",
            vec![
                "--host-format",
                "cell-v2",
                "--host-config",
                "/absent-controlled-host",
                "--host-config-sha256",
                "0101010101010101010101010101010101010101010101010101010101010101",
            ],
        ),
    ] {
        let home = directory.path().join(name);
        let mut command = Command::new(&fd_path);
        command.args(args).env("CODEX_HOME", &home);
        let rejected = run_command(command);
        assert!(!rejected.status.success());
        assert!(String::from_utf8_lossy(&rejected.stderr).contains(message));
        assert!(rejected.stdout.is_empty());
        assert!(!home.exists(), "Cell image rejection must precede aliases");
    }
    let mut named = Command::new(original);
    named
        .args(["--host-format", "cell-v2", "--help"])
        .env("CODEX_HOME", directory.path().join("named"));
    let named = run_command(named);
    assert!(named.status.success());
    assert!(String::from_utf8_lossy(&named.stdout).contains("--host-format owner-v1|cell-v2"));

    let mut legacy = Command::new(&fd_path);
    legacy
        .args(["--host-format", "owner-v1", "--help"])
        .env("CODEX_HOME", directory.path().join("legacy"));
    assert!(
        run_command(legacy).status.success(),
        "the explicit Cell gate must not redefine owner-v1"
    );

    let helper_home = directory.path().join("helper");
    let mut helper = Command::new(&fd_path);
    helper
        .arg0("apply_patch")
        .args(["--host-format", "cell-v2"])
        .env("CODEX_HOME", &helper_home);
    let helper = run_command(helper);
    assert_eq!(helper.status.code(), Some(2));
    assert!(
        String::from_utf8_lossy(&helper.stderr)
            .contains("apply_patch accepts exactly one argument")
    );
    assert!(!String::from_utf8_lossy(&helper.stderr).contains(message));
    assert!(
        !helper_home.exists(),
        "original helper dispatch must precede daemon preflight"
    );
}

#[test]
fn actual_argv_selects_v2_strict_decoder_before_any_fleet_or_model_owner() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().canonicalize().unwrap().join("host.json");
    let raw = br#"{"schema":"hepta-smollm-cognitive-cell-host-v2"}"#;
    OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&path)
        .unwrap()
        .write_all(raw)
        .unwrap();
    let mut args = vec![
        "--host-config".to_owned(),
        path.display().to_string(),
        "--host-config-sha256".to_owned(),
        Digest32::of_bytes(raw).to_string(),
    ];
    let legacy = cli(&args);
    assert!(!legacy.status.success());
    assert!(String::from_utf8_lossy(&legacy.stderr).contains("missing field `descriptor`"));
    args.extend(["--host-format".to_owned(), "cell-v2".to_owned()]);
    let cell = cli(&args);
    assert!(!cell.status.success());
    assert!(String::from_utf8_lossy(&cell.stderr).contains("missing field `owner`"));
    assert_eq!(
        (legacy.stdout, cell.stdout),
        (Vec::<u8>::new(), Vec::<u8>::new())
    );
    assert_eq!(std::fs::read_dir(directory.path()).unwrap().count(), 1);
}

#[test]
fn actual_argv_rejects_unknown_and_duplicate_formats_without_fallback() {
    let base = vec![
        "--host-config".to_owned(),
        "/absent-controlled-host".to_owned(),
        "--host-config-sha256".to_owned(),
        Digest32::from_array([1; 32]).to_string(),
    ];
    let mut args = base.clone();
    args.extend(["--host-format".to_owned(), "cell-v999".to_owned()]);
    let unknown = cli(&args);
    assert!(!unknown.status.success());
    assert!(String::from_utf8_lossy(&unknown.stderr).contains("unsupported neural host format"));
    args = base;
    args.extend([
        "--host-format".to_owned(),
        "cell-v2".to_owned(),
        "--host-format".to_owned(),
        "owner-v1".to_owned(),
    ]);
    let duplicate = cli(&args);
    assert!(!duplicate.status.success());
    assert!(
        String::from_utf8_lossy(&duplicate.stderr)
            .contains("unknown or duplicate neural host flag")
    );
    assert_eq!(
        (unknown.stdout, duplicate.stdout),
        (Vec::<u8>::new(), Vec::<u8>::new())
    );
}
