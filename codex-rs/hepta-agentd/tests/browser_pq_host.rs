#![cfg(unix)]

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::process::Command;
use std::process::Stdio;

use ed25519_dalek::SigningKey;
use serde_json::json;
use sha2::Digest;
use sha2::Sha256;

#[test]
fn ordinary_browser_binary_rejects_legacy_before_owner_or_child_creation() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    fs::set_permissions(&root, fs::Permissions::from_mode(0o700))?;
    let marker = root.join("unexpected-child");
    let node = root.join("node-fixture");
    fs::write(
        &node,
        format!("#!/bin/sh\nprintf invoked > '{}'\n", marker.display()),
    )?;
    fs::set_permissions(&node, fs::Permissions::from_mode(0o700))?;
    let artifact = root.join("artifact-fixture");
    fs::write(&artifact, b"qualification artifact")?;
    let digest = format!("{:x}", Sha256::digest(b"qualification artifact"));
    let call = root.join("call.json");
    fs::write(
        &call,
        serde_json::to_vec(
            &json!({"method":"observe_page","input":{"profileId":"profile.1"},
        "signed_grant":null,"binding":null}),
        )?,
    )?;
    for case in 0..3 {
        let owner = root.join(format!("authority-{case}"));
        let key = SigningKey::from_bytes(&[7; 32]);
        // Case zero is the complete legacy configuration accepted by the old
        // ordinary binary, including valid Ed25519 trust and pinned artifacts.
        let mut config = json!({"signer_id":"legacy-browser", "verifying_key":key.verifying_key().to_bytes(),
            "authority_state_dir":owner, "authority_epoch":9, "revocation_revision":1, "revoked_grant_ids":[],
            "node_path":node, "service_path":artifact, "service_sha256":digest,
            "worker_path":artifact, "worker_sha256":digest, "profile_root":root.join("profile"),
            "journal_path":root.join("journal"), "bwrap_path":"/bin/true", "driver_timeout_ms":2000});
        if case != 0 {
            config["schema_version"] = json!(2);
        }
        if case == 1 {
            config["authentication_profile"] = json!("classical_v1");
        }
        let path = root.join(format!("config-{case}.json"));
        fs::write(&path, serde_json::to_vec(&config)?)?;
        fs::set_permissions(&path, fs::Permissions::from_mode(0o600))?;
        let output = Command::new(codex_utils_cargo_bin::cargo_bin("hepta-agentd-browser")?)
            .arg(&path)
            .stdin(Stdio::from(fs::File::open(&call)?))
            .output()?;
        assert!(!output.status.success());
        assert!(
            String::from_utf8(output.stderr)?
                .contains("ordinary Browser effects require schema 2 and explicit ml_dsa65_v2")
        );
        assert!(!owner.exists());
        assert!(!marker.exists());
    }
    Ok(())
}
