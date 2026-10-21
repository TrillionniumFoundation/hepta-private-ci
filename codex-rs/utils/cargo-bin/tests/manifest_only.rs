use std::error::Error;
use std::ffi::OsStr;
use std::process::Command;

use codex_utils_cargo_bin::CargoBinError;
use codex_utils_cargo_bin::cargo_bin;

const CHILD_TEST: &str = "CODEX_CARGO_BIN_REGRESSION_CHILD";

fn assert_missing_bazel_binary(
    test_name: &str,
    binary: &str,
    extra_env: &[(&str, &str)],
) -> Result<(), Box<dyn Error>> {
    if std::env::var_os(CHILD_TEST).as_deref() == Some(OsStr::new(test_name)) {
        let result = cargo_bin(binary);
        assert!(
            matches!(&result, Err(CargoBinError::NotFound { name, .. }) if name == binary),
            "undeclared Bazel binary should return NotFound: {result:?}"
        );
        return Ok(());
    }

    // Keep environment changes in a child so Cargo and Bazel can run these
    // regressions concurrently with other tests.
    let mut command = Command::new(std::env::current_exe()?);
    command.args(["--exact", test_name, "--nocapture"]);
    for (key, _) in std::env::vars_os() {
        if key.to_string_lossy().starts_with("CARGO_BIN_EXE_") {
            command.env_remove(key);
        }
    }
    command
        .env(CHILD_TEST, test_name)
        .env("RUNFILES_MANIFEST_ONLY", "1")
        .envs(extra_env.iter().copied());
    let output = command.output()?;
    assert!(
        output.status.success(),
        "child exited with {}\nstdout:\n{}\nstderr:\n{}",
        output.status,
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    Ok(())
}

#[test]
fn undeclared_bazel_binary_returns_not_found() -> Result<(), Box<dyn Error>> {
    assert_missing_bazel_binary("undeclared_bazel_binary_returns_not_found", "codex", &[])
}

#[test]
fn unrelated_bazel_binary_does_not_enable_cargo_fallback() -> Result<(), Box<dyn Error>> {
    assert_missing_bazel_binary(
        "unrelated_bazel_binary_does_not_enable_cargo_fallback",
        "codex-code-mode-host",
        &[("CARGO_BIN_EXE_codex", "_main/codex-rs/cli/codex")],
    )
}
