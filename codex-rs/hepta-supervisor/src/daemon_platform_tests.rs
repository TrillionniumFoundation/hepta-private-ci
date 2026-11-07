use std::io::ErrorKind;

use anyhow::Result;
use codex_hepta_paths::HeptaFleetRoot;
use ed25519_dalek::SigningKey;
use tokio_util::sync::CancellationToken;

use crate::H7H89ProductionGrantVerifier;
use crate::SupervisorError;
use crate::run_supervisord;
use crate::run_supervisord_with_grant_verifier;

// This input is deliberately unusable. The platform boundary must reject
// before reading a trust service or any uninitialized Fleet directory.
fn inactive_release_trust(root: &std::path::Path) -> codex_hepta_fleet::FleetReleaseTrustConfig {
    let endpoint = codex_hepta_contracts::authority_trust_unix::UnixPqTrustEndpointConfig {
        socket_path: root.join("unavailable.sock"),
        peer_uid: 0,
        service_id: "unavailable".into(),
        key_generation: 1,
        public_key_id: [0; 32],
        public_key_spki: Vec::new(),
        timeout_ms: 2000,
    };
    codex_hepta_fleet::FleetReleaseTrustConfig {
        schema_version: 1,
        profile: "hepta.fleet.release-trust.pq.v1".into(),
        owner_id: "hepta.fleet.release.unavailable".into(),
        initial_root_sha256: [0; 32],
        network_id: [0; 32],
        platform_sha256: [0; 32],
        clock: endpoint.clone(),
        frontier: endpoint,
    }
}

#[tokio::test]
async fn unsupported_host_rejects_daemon_before_accessing_fleet_state() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().join("uninitialized-fleet");
    let cancellation = CancellationToken::new();
    let result = run_supervisord(
        HeptaFleetRoot::parse(root.clone())?,
        inactive_release_trust(&root),
        cancellation.clone(),
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
        inactive_release_trust(&root),
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
