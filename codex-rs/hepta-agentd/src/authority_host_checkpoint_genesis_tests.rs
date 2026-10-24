//! Existing original owners with actual Root stores and verified physical data.
//! These tests do not claim a native kernel boot or an authorized CPU effect.

use super::*;
use pretty_assertions::assert_eq;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::OpenOptionsExt;

fn unused(f: &Fixture) -> (Arc<RootAuthorityDirectory>, DeploymentFinalUseIssuer) {
    let path = f._temp.path().join("genesis-checkpoint");
    std::fs::DirBuilder::new()
        .mode(0o700)
        .create(&path)
        .unwrap();
    let root = RootAuthorityDirectory::open(&path).unwrap();
    let issuer = DeploymentFinalUseIssuer::create_protected(
        &f._temp.path().join("genesis-issuer"),
        "genesis-original-root".into(),
        vec![crate::DeploymentGrantPolicy {
            subject_id: f.previous.head.owner_agent_id.to_string(),
            destination_id: codex_hepta_memory::HOS2_DESTINATION_V1.into(),
            scope_sha256: [11; 32],
            lifetime_ms: 5_000,
        }],
        f.clock.clone(),
        f.registry.verifier(),
        "reentry-root-lease".into(),
        1,
    )
    .unwrap();
    (root, issuer)
}

#[tokio::test]
#[ignore = "actual Root original unused issuer, protected physical genesis and reopen"]
async fn root_original_genesis_retains_the_same_physical_cut_without_publishing_current() {
    let f = Fixture::new().await;
    let (directory, issuer) = unused(&f);
    let genesis = crate::HostCognitiveCheckpoint::prepare_original_genesis_for_root(
        directory.clone(),
        &issuer,
        &f.clock,
        &f.material,
    )
    .unwrap();
    assert_eq!(genesis.cut(), f.material.anchor());
    assert_eq!(
        genesis.verifying_key(),
        issuer.trust_key().unwrap().verifying_key
    );
    let first = genesis.sha256();
    let retained = crate::HostCognitiveCheckpoint::retained_original_genesis_for_root(
        directory.clone(),
        &f.previous.head.owner_agent_id,
        &f.clock,
    )
    .unwrap();
    assert_eq!(retained.sha256(), first);
    retained.require_material(&f.material).unwrap();
    retained
        .with_no_checkpoint(&f.material, || {
            issuer.with_original_unused_genesis_for_root(|signer, key, policies| {
                retained
                    .require_issuer(signer, key)
                    .map_err(io::Error::other)?;
                assert_eq!(policies, retained.initial_policies());
                Ok(())
            })
        })
        .unwrap()
        .unwrap();
    assert!(crate::HostCognitiveCheckpoint::retained_head_for_root(directory).is_err());
    assert_eq!(f.actual_head(), f.previous.head);
}

#[tokio::test]
#[ignore = "actual Root used issuer and an already installed checkpoint cannot become genesis"]
async fn root_original_genesis_refuses_used_issuer_and_existing_original_head() {
    let f = Fixture::new().await;
    let (directory, issuer) = unused(&f);
    assert!(
        crate::HostCognitiveCheckpoint::prepare_original_genesis_for_root(
            directory,
            &f.issuer,
            &f.clock,
            &f.material,
        )
        .is_err()
    );
    assert!(
        crate::HostCognitiveCheckpoint::prepare_original_genesis_for_root(
            f.directory.clone(),
            &issuer,
            &f.clock,
            &f.material,
        )
        .is_err()
    );
    assert_eq!(f.actual_head(), f.previous.head);
    assert_eq!(
        f.issuer
            .retained_writer_state_for_root()
            .unwrap()
            .registration,
        f.failed_writer
    );
}

#[tokio::test]
#[ignore = "actual Root incomplete first-head candidate and wrong original key are retained refusals"]
async fn root_original_genesis_keeps_partial_head_and_wrong_identity_failures_visible() {
    let f = Fixture::new().await;
    let (directory, issuer) = unused(&f);
    let genesis = crate::HostCognitiveCheckpoint::prepare_original_genesis_for_root(
        directory,
        &issuer,
        &f.clock,
        &f.material,
    )
    .unwrap();
    let mut wrong = genesis.verifying_key();
    wrong[0] ^= 1;
    assert!(genesis.require_issuer(genesis.issuer_id(), wrong).is_err());
    use sha2::Digest;
    let name = format!(
        "frontier-v1-{:x}.json.next",
        sha2::Sha256::digest(b"root-cognitive-checkpoint-v1")
    );
    let path = f._temp.path().join("genesis-checkpoint").join(name);
    let file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&path)
        .unwrap();
    file.sync_all().unwrap();
    assert!(genesis.with_no_checkpoint(&f.material, || ()).is_err());
    assert_eq!(path.metadata().unwrap().len(), 0);
    assert_eq!(f.actual_head(), f.previous.head);
}
