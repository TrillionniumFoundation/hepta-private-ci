//! Actual supported argv reaches the explicit host-v2 decoder. No model is
//! admitted by these negative filesystem/dispatch controls.
#![cfg(target_os = "linux")]

use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
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
    let child = Command::new(codex_utils_cargo_bin::cargo_bin("hepta-neural-agentd").unwrap())
        .args(args)
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
