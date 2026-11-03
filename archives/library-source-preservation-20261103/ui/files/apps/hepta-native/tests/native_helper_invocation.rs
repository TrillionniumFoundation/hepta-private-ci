//! These probes use only the no-effect protocol-check path, never a dialog or effect.
use std::io::Write as _;
use std::process::Command;
use std::process::Stdio;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

fn binary() -> std::path::PathBuf {
    codex_utils_cargo_bin::cargo_bin("hepta-native").unwrap()
}

#[test]
fn direct_helper_cli_without_private_channel_is_denied_before_desktop_entry() {
    let output = Command::new(binary())
        .args(["--native-platform-helper", "protocol-check"])
        .env_remove("HEPTA_NATIVE_HELPER_NONCE")
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(77));
    assert!(String::from_utf8_lossy(&output.stderr).contains("private inherited channel"));
}

#[test]
fn forged_ticket_from_a_foreign_parent_image_is_rejected() {
    let nonce = "a".repeat(64);
    let ticket = serde_json::json!({"schema":1,"mode":"protocol-check","parent":std::process::id(),
        "created_ms":SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis() as u64,"nonce":nonce});
    let (reader, mut writer) = std::io::pipe().unwrap();
    writer
        .write_all(&serde_json::to_vec(&ticket).unwrap())
        .unwrap();
    drop(writer);
    let status = Command::new(binary())
        .args(["--native-platform-helper", "protocol-check"])
        .env("HEPTA_NATIVE_HELPER_NONCE", "a".repeat(64))
        .stderr(Stdio::from(reader))
        .status()
        .unwrap();
    assert_eq!(status.code(), Some(77));
}

#[test]
fn actual_native_parent_completes_no_effect_helper_handshake() {
    let output = Command::new(binary()).arg("--self-test").output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let report: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(report["schema"], "hepta.native-self-test.v1");
}
