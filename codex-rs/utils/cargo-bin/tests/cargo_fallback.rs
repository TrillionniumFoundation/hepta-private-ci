use std::error::Error;
use std::ffi::OsStr;
use std::path::PathBuf;
use std::process::Command;

use codex_utils_cargo_bin::CargoBinError;
use codex_utils_cargo_bin::cargo_bin;
use pretty_assertions::assert_eq;

const CHILD_TEST: &str = "CODEX_CARGO_FALLBACK_REGRESSION_CHILD";
const EXPECTED_SIBLING: &str = "CODEX_CARGO_FALLBACK_EXPECTED_SIBLING";
const SIBLING_NAME: &str = "codex-cargo-fallback-sibling";
const TEST_NAME: &str = "cargo_fallback_resolves_siblings_and_reports_missing_optional_binaries";

#[test]
fn cargo_fallback_resolves_siblings_and_reports_missing_optional_binaries()
-> Result<(), Box<dyn Error>> {
    if std::env::var_os(CHILD_TEST).as_deref() == Some(OsStr::new(TEST_NAME)) {
        let expected = PathBuf::from(std::env::var_os(EXPECTED_SIBLING).expect("expected sibling"));
        let actual = cargo_bin(SIBLING_NAME)?;
        assert!(actual.is_absolute());
        assert_eq!(actual.canonicalize()?, expected.canonicalize()?);

        let missing_name = "codex-no-such-optional-cargo-binary";
        let missing = cargo_bin(missing_name);
        assert!(
            matches!(&missing, Err(CargoBinError::NotFound { name, .. }) if name == missing_name),
            "an optional Cargo binary must return NotFound: {missing:?}"
        );
        return Ok(());
    }

    // Exercise a real relocated test executable in Cargo's debug/deps layout.
    // Child-only environment changes also let Bazel run this Cargo regression.
    let temp = tempfile::tempdir()?;
    let profile = temp.path().join("debug");
    let deps = profile.join("deps");
    std::fs::create_dir_all(&deps)?;
    let suffix = std::env::consts::EXE_SUFFIX;
    let child = deps.join(format!("cargo-fallback-probe{suffix}"));
    let sibling = profile.join(format!("{SIBLING_NAME}{suffix}"));
    let current_exe = std::env::current_exe()?;
    std::fs::copy(&current_exe, &child)?;
    std::fs::copy(&current_exe, &sibling)?;
    let mut command = Command::new(child);
    command.args(["--exact", TEST_NAME, "--nocapture"]);
    for (key, _) in std::env::vars_os() {
        if key.to_string_lossy().starts_with("CARGO_BIN_EXE_") {
            command.env_remove(key);
        }
    }
    let output = command
        .env_remove("RUNFILES_MANIFEST_ONLY")
        .env_remove("RUNFILES_MANIFEST_FILE")
        .env(CHILD_TEST, TEST_NAME)
        .env(EXPECTED_SIBLING, sibling)
        .output()?;
    assert!(
        output.status.success(),
        "child exited with {}\nstdout:\n{}\nstderr:\n{}",
        output.status,
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    Ok(())
}
