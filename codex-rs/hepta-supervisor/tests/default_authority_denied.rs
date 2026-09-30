#![cfg(all(unix, not(feature = "production-authority")))]

use std::fs::OpenOptions;
use std::io::Read;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_supervisor::H7H89ProductionGrantVerifier;
use codex_hepta_supervisor::ProductionAuthorityBundle;
use codex_hepta_supervisor::SupervisorError;
use ed25519_dalek::SigningKey;
use tokio_util::sync::CancellationToken;

// Public deterministic fixture material. Never install this as a trust anchor.
const TEST_SEED: [u8; 32] = [117; 32];

#[tokio::test]
async fn default_library_refuses_runtime_verifier_before_opening_fleet() -> Result<()> {
    // Integration tests link the non-cfg(test) library. Library unit tests alone
    // cannot prove this: their qualification seam intentionally enables authority.
    ensure!(!std::hint::black_box(
        codex_hepta_supervisor::PRODUCTION_AUTHORITY_FEATURE_ENABLED
    ));
    let temp = tempfile::tempdir()?;
    let absent = temp.path().canonicalize()?.join("fleet-must-not-exist");
    let root = HeptaFleetRoot::parse(absent.clone())?;
    let verifier = H7H89ProductionGrantVerifier::from_bytes(
        "default-denial-fixture",
        1,
        SigningKey::from_bytes(&TEST_SEED).verifying_key().to_bytes(),
    )?;
    let result = codex_hepta_supervisor::run_supervisord_with_grant_verifier(
        root,
        CancellationToken::new(),
        verifier,
    )
    .await;
    ensure!(matches!(
        result,
        Err(SupervisorError::ProductionAuthorityFeatureDisabled)
    ));
    ensure!(!absent.exists(), "denied call touched fleet state");
    Ok(())
}

#[test]
fn default_daemon_refuses_pinned_bundle_before_fleet_mutation() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    let fleet = root.join("fleet-must-not-exist");
    let key = SigningKey::from_bytes(&TEST_SEED);
    let h7_key = SigningKey::from_bytes(&[118; 32]);
    let bundle = ProductionAuthorityBundle::new(
        "default-denial-fixture",
        1,
        key.verifying_key(),
        "default-h7-fixture",
        1,
        h7_key.verifying_key(),
    )?;
    let bundle_path = root.join("authority-bundle.json");
    let bundle_bytes = bundle.to_json_bytes()?;
    std::fs::write(&bundle_path, &bundle_bytes)?;
    std::fs::set_permissions(&bundle_path, std::fs::Permissions::from_mode(0o600))?;

    // Use a regular diagnostic file rather than a pipe a child could retain.
    let diagnostic = root.join("stderr.log");
    let stderr = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&diagnostic)?;
    let mut child = ChildGuard(
        Command::new(env!("CARGO_BIN_EXE_hepta-supervisord"))
            .arg("--fleet-root")
            .arg(&fleet)
            .arg("--authority-bundle")
            .arg(&bundle_path)
            .arg("--authority-bundle-sha256")
            .arg(bundle.bundle_sha256.as_str())
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(stderr)
            .spawn()
            .context("start default product daemon")?,
    );
    let deadline = Instant::now() + Duration::from_secs(5);
    let status = loop {
        if let Some(status) = child.0.try_wait()? {
            break status;
        }
        ensure!(
            Instant::now() < deadline,
            "default daemon did not reject authority"
        );
        std::thread::sleep(Duration::from_millis(10));
    };
    ensure!(
        !status.success(),
        "default daemon accepted production authority"
    );
    let mut bytes = Vec::new();
    std::fs::File::open(&diagnostic)?
        .take(8193)
        .read_to_end(&mut bytes)?;
    ensure!(bytes.len() <= 8192, "unbounded default-denial diagnostics");
    let text = std::str::from_utf8(&bytes)?;
    let expected = SupervisorError::ProductionAuthorityFeatureDisabled.to_string();
    ensure!(
        text.contains(&expected),
        "daemon failed for an unrelated reason: {text}"
    );
    ensure!(!fleet.exists(), "default daemon touched fleet state");
    ensure!(
        std::fs::read(&bundle_path)? == bundle_bytes,
        "daemon changed verifier material"
    );
    Ok(())
}

struct ChildGuard(Child);

impl Drop for ChildGuard {
    fn drop(&mut self) {
        if self.0.try_wait().ok().flatten().is_none() {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
}
