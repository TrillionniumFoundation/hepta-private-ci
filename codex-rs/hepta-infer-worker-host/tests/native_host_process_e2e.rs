use codex_utils_cargo_bin::cargo_bin;
use std::error::Error;
use std::process::Command;

#[test]
fn native_worker_help_executes_the_real_binary_without_state() -> Result<(), Box<dyn Error>> {
    let output = Command::new(cargo_bin("hepta-infer-worker")?)
        .arg("--help")
        .output()?;
    assert!(output.status.success(), "{output:?}");
    let stdout = std::str::from_utf8(&output.stdout)?;
    assert!(stdout.contains("--profile native-app-server"));
    assert!(stdout.contains("--resume"));
    assert!(output.stderr.is_empty(), "{output:?}");
    Ok(())
}

#[test]
fn native_worker_fails_closed_without_an_explicit_profile() -> Result<(), Box<dyn Error>> {
    let output = Command::new(cargo_bin("hepta-infer-worker")?).output()?;
    assert!(
        !output.status.success(),
        "worker unexpectedly accepted no profile"
    );
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("--profile native-app-server must be selected explicitly"),
        "unexpected stderr: {stderr}"
    );
    Ok(())
}
