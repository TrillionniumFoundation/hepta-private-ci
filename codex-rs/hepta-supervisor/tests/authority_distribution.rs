use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::H7ArtifactSigner;
use codex_hepta_memory::H7QualificationRuntime;
use codex_hepta_memory::H7SignedArtifactEnvelope;
use codex_hepta_memory::H7SignedArtifactTransition;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::FleetRegistryError;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_supervisor::H7H89ProductionGrantSigner;
use codex_hepta_supervisor::H7H89ProductionTransition;
use codex_hepta_supervisor::ProductionAuthorityBundle;
use codex_hepta_supervisor::ProductionAuthorityError;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

#[test]
fn pinned_bundle_rotation_rejects_predecessor_and_accepts_current_signer() {
    let envelope = h7_envelope();
    let agent = AgentId::parse(AGENT_ID).expect("fixed AgentId");
    let old_signer = H7H89ProductionGrantSigner::from_seed("release-policy", 3, [3; 32])
        .expect("old signer");
    let current_signer = H7H89ProductionGrantSigner::from_seed("release-policy", 4, [4; 32])
        .expect("current signer");
    let h7_signer = H7ArtifactSigner::from_seed("h7-policy", 9, [7; 32]).expect("H7 signer");
    let bundle = ProductionAuthorityBundle::new(
        current_signer.signer_id(),
        current_signer.signer_epoch(),
        current_signer.verifying_key(),
        "h7-policy",
        9,
        h7_signer.verifying_key(),
    )
    .expect("bundle");
    let dir = tempfile::tempdir().expect("temporary directory");
    let path = dir.path().join("authority-bundle.json");
    std::fs::write(&path, bundle.to_json_bytes().expect("bundle JSON")).expect("write bundle");
    let (_, verifier) = ProductionAuthorityBundle::load_pinned(&path, &bundle.bundle_sha256)
        .expect("load pinned bundle");

    let old_grant = grant(&old_signer, &envelope, &agent, 11);
    assert_eq!(
        verifier.verify(
            &old_grant,
            &envelope,
            &agent,
            "release-v1",
            "release-v2",
            5,
            7,
            11,
            150,
        ),
        Err(ProductionAuthorityError::SignerEpochMismatch)
    );

    let current_grant = grant(&current_signer, &envelope, &agent, 11);
    verifier
        .verify(
            &current_grant,
            &envelope,
            &agent,
            "release-v1",
            "release-v2",
            5,
            7,
            11,
            150,
        )
        .expect("current signer grant");
}

#[test]
fn wrong_signer_stale_grant_and_authority_epoch_rollover_fail_closed() {
    let envelope = h7_envelope();
    let agent = AgentId::parse(AGENT_ID).expect("fixed AgentId");
    let current_signer = H7H89ProductionGrantSigner::from_seed("release-policy", 4, [4; 32])
        .expect("current signer");
    let wrong_signer = H7H89ProductionGrantSigner::from_seed("other-policy", 4, [8; 32])
        .expect("wrong signer");
    let h7_signer = H7ArtifactSigner::from_seed("h7-policy", 9, [7; 32]).expect("H7 signer");
    let bundle = ProductionAuthorityBundle::new(
        current_signer.signer_id(),
        current_signer.signer_epoch(),
        current_signer.verifying_key(),
        "h7-policy",
        9,
        h7_signer.verifying_key(),
    )
    .expect("bundle");
    let verifier = bundle.verifier().expect("bundle verifier");

    let wrong_grant = grant(&wrong_signer, &envelope, &agent, 11);
    assert_eq!(
        verifier.verify(
            &wrong_grant,
            &envelope,
            &agent,
            "release-v1",
            "release-v2",
            5,
            7,
            11,
            150,
        ),
        Err(ProductionAuthorityError::SignerMismatch)
    );

    let stale_epoch = grant(&current_signer, &envelope, &agent, 10);
    assert_eq!(
        verifier.verify(
            &stale_epoch,
            &envelope,
            &agent,
            "release-v1",
            "release-v2",
            5,
            7,
            11,
            150,
        ),
        Err(ProductionAuthorityError::AuthorityEpochFence {
            expected: 11,
            actual: 10,
        })
    );

    let expired = current_signer
        .sign(
            &agent,
            "release-v1",
            "release-v2",
            H7H89ProductionTransition::Upgrade,
            &envelope,
            5,
            7,
            11,
            100,
            120,
        )
        .expect("expired grant shape");
    assert_eq!(
        verifier.verify(
            &expired,
            &envelope,
            &agent,
            "release-v1",
            "release-v2",
            5,
            7,
            11,
            150,
        ),
        Err(ProductionAuthorityError::Expired)
    );
}

#[test]
fn fleet_revocation_is_observed_from_the_current_policy_owner() {
    let temp = tempfile::tempdir().expect("temporary directory");
    let root = HeptaFleetRoot::parse(temp.path().join("fleet")).expect("fleet root");
    let registry = FleetRegistry::initialize(root.clone()).expect("registry");
    let agent = AgentId::parse(AGENT_ID).expect("fixed AgentId");
    let workspace = temp.path().join("workspace");
    std::fs::create_dir(&workspace).expect("workspace");
    registry
        .register(
            AgentManifest::new(
                agent.clone(),
                WorkspaceBinding::new(workspace.canonicalize().expect("canonical workspace"), &root)
                    .expect("workspace binding"),
                ResourceBudget::local_default(),
            )
            .expect("manifest"),
        )
        .expect("register Agent");
    let source = temp.path().join("agentd");
    std::fs::write(&source, b"#!/bin/sh\nexit 0\n").expect("program bytes");
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&source, std::fs::Permissions::from_mode(0o700))
            .expect("program permissions");
    }
    let release = ReleaseId::parse("release-v2").expect("release id");
    registry
        .install_release(release.clone(), &source, Vec::new())
        .expect("install release");
    registry
        .allow_release(&agent, &release)
        .expect("allow release");
    registry
        .resolve_release(&agent, &release)
        .expect("resolve allowed release");
    registry
        .revoke_release(&agent, &release)
        .expect("revoke release");
    assert!(matches!(
        registry.resolve_release(&agent, &release),
        Err(FleetRegistryError::ReleaseRevoked { .. })
    ));
}

fn grant(
    signer: &H7H89ProductionGrantSigner,
    envelope: &H7SignedArtifactEnvelope,
    agent: &AgentId,
    authority_epoch: u64,
) -> codex_hepta_supervisor::H7H89ProductionGrant {
    signer
        .sign(
            agent,
            "release-v1",
            "release-v2",
            H7H89ProductionTransition::Upgrade,
            envelope,
            5,
            7,
            authority_epoch,
            110,
            190,
        )
        .expect("grant")
}

fn h7_envelope() -> H7SignedArtifactEnvelope {
    let mut runtime = H7QualificationRuntime::new();
    let event = codex_hepta_memory::H7TrajectoryEvent::new(
        "authority-distribution-trajectory",
        1,
        "reload",
        100,
        true,
        1,
        1,
        1,
        Sha256Digest::for_bytes(b"authority-distribution-fence"),
    )
    .expect("trajectory event");
    runtime.append_trajectory_event(event).expect("append event");
    runtime
        .evaluate_trajectory("authority-distribution-trajectory")
        .expect("evaluate trajectory");
    let artifact = runtime
        .propose_artifact(
            "authority-distribution-artifact",
            "authority-distribution-trajectory",
            1,
        )
        .expect("artifact");
    H7ArtifactSigner::from_seed("h7-policy", 9, [7; 32])
        .expect("H7 signer")
        .sign(
            &artifact,
            None,
            H7SignedArtifactTransition::Reload,
            0,
            None,
            100,
            200,
        )
        .expect("H7 envelope")
}
