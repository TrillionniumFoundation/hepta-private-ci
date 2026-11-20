use std::process::Command;

#[test]
fn native_worker_help_executes_the_real_binary_without_state() {
    let worker = codex_utils_cargo_bin::cargo_bin("hepta-infer-worker")
        .expect("resolve native worker binary");
    let output = Command::new(worker)
        .arg("--help")
        .output()
        .expect("execute native worker help");
    assert!(output.status.success(), "{output:?}");
    let stdout = std::str::from_utf8(&output.stdout).expect("UTF-8 help output");
    assert!(stdout.contains("--profile native-app-server"));
    assert!(stdout.contains("--resume"));
    assert!(output.stderr.is_empty(), "{output:?}");
}

#[test]
fn native_worker_fails_closed_without_an_explicit_profile() {
    let worker = codex_utils_cargo_bin::cargo_bin("hepta-infer-worker")
        .expect("resolve native worker binary");
    let output = Command::new(worker)
        .output()
        .expect("execute native worker without profile");
    assert!(
        !output.status.success(),
        "worker unexpectedly accepted no profile"
    );
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("--profile native-app-server must be selected explicitly"),
        "unexpected stderr: {stderr}"
    );
}
