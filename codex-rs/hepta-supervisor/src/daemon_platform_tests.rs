use std::io::ErrorKind;

use anyhow::Result;
use codex_hepta_paths::HeptaFleetRoot;
use ed25519_dalek::SigningKey;
use tokio_util::sync::CancellationToken;

use crate::H7H89ProductionGrantVerifier;
use crate::SupervisorError;
use crate::run_supervisord;
use crate::run_supervisord_with_grant_verifier;

#[tokio::test]
async fn unsupported_host_rejects_daemon_before_accessing_fleet_state() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("uninitialized-fleet");
    let cancellation = CancellationToken::new();
    let result = run_supervisord(HeptaFleetRoot::parse(root.clone())?, cancellation.clone()).await;
    assert!(matches!(
        result,
        Err(SupervisorError::Io(error)) if error.kind() == ErrorKind::Unsupported
    ));
    assert!(!root.exists());
    assert!(!cancellation.is_cancelled());
    Ok(())
}

#[tokio::test]
async fn pinned_verifier_cannot_enable_daemon_on_unsupported_host() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("uninitialized-fleet");
    let cancellation = CancellationToken::new();
    let verifier = H7H89ProductionGrantVerifier::new(
        "unsupported-host-test",
        /*signer_epoch*/ 1,
        SigningKey::from_bytes(&[7; 32]).verifying_key(),
    )?;
    let result = run_supervisord_with_grant_verifier(
        HeptaFleetRoot::parse(root.clone())?,
        cancellation.clone(),
        verifier,
    )
    .await;
    assert!(matches!(
        result,
        Err(SupervisorError::Io(error)) if error.kind() == ErrorKind::Unsupported
    ));
    assert!(!root.exists());
    assert!(!cancellation.is_cancelled());
    Ok(())
}
