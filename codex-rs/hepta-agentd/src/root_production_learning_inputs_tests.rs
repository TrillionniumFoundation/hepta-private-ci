//! Pure scope binding checks. Synthetic public values do not establish Root
//! provenance, a live writer lease, independent stage owners or publication.

use super::*;
use crate::HostAuthorityFiveLanePathsV1;
use crate::HostAuthorityLearningProfileV1;
use crate::HostAuthorityPublicBootstrapV1;
use crate::HostAuthorityPublicConsumerV1;
use crate::HostAuthorityPublicConsumersV1;
use crate::HostAuthorityPublicIssuerKeyV1;
use crate::HostAuthorityRegisteredIdentity;
use crate::HostAuthorityWriterRegistration;
use crate::learning_iteration_checkpoint::learning_test_support::fixture;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CognitiveCheckpointHead;
use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use codex_hepta_memory::CognitiveCheckpointPhase;
use codex_hepta_memory::CognitiveCheckpointWriterBinding;
use codex_hepta_memory::CognitiveRecoveryAnchor;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

fn bundles() -> anyhow::Result<(
    tempfile::TempDir,
    AgentdIdentity,
    HostAuthorityPublicBootstrapV1,
    HostAuthorityLearningBootstrapV1,
)> {
    let (directory, identity, coordinator) = fixture()?;
    let (trust, mut proof) = crate::root_writer_proof::tests::fixture();
    proof.claims.registered_agent_id = identity.agent_id.clone();
    proof.claims.spawn_generation = identity.spawn_generation;
    proof.claims.authority_lease.binding.principal_id = identity.agent_id.to_string();
    proof.claims.authority_lease_sha256 =
        Sha256Digest::for_bytes(&serde_json::to_vec(&proof.claims.authority_lease)?);
    proof.signature_hex = SigningKey::from_bytes(&[47; 32])
        .sign(&proof.claims.signing_bytes()?)
        .to_bytes()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    let digest = proof.sha256()?;
    let pin: Digest32 = digest.as_str().parse()?;
    let initial = coordinator.snapshot();
    let profile = HostAuthorityLearningProfileV1::new(
        &identity,
        pin.into_array(),
        initial.request.clone(),
        initial.owners.clone(),
    )?;
    let root = CognitiveCheckpointPeerLifetime {
        uid: 0,
        pid: 123,
        boot_id: "synthetic-binding-boot".into(),
        process_start_ticks: 1,
    };
    let consumer = CognitiveCheckpointPeerLifetime {
        uid: 60001,
        pid: 456,
        boot_id: root.boot_id.clone(),
        process_start_ticks: 2,
    };
    let registered = HostAuthorityRegisteredIdentity {
        agent_id: identity.agent_id.clone(),
        spawn_generation: identity.spawn_generation,
        fleet_root: identity.fleet_root.clone(),
        workspace: identity.workspace.clone(),
        resources: identity.resources.clone(),
    };
    let revocations = crate::root_writer_proof::tests::observation(&proof).revocations;
    let frontier = FinalUseFrontier::for_initial_head(&revocations)?;
    let claims = &proof.claims;
    let writer = HostAuthorityWriterRegistration {
        registered_agent_id: claims.registered_agent_id.clone(),
        spawn_generation: claims.spawn_generation,
        owner_epoch: claims.owner_epoch,
        local_lease_id: claims.local_lease_id.clone(),
        local_lease_generation: claims.local_lease_generation,
        authority_lease: claims.authority_lease.clone(),
    };
    let head = CognitiveCheckpointHead {
        schema_version: 1,
        owner_agent_id: identity.agent_id.clone(),
        publisher_epoch: 1,
        counter: 1,
        last_mutation_sequence: 0,
        writer_binding: CognitiveCheckpointWriterBinding {
            lease_id: writer.local_lease_id.clone(),
            generation: writer.local_lease_generation,
            authority_epoch: writer.authority_lease.authority_epoch,
            owner_epoch: writer.owner_epoch,
            authority_grant_digest: digest.clone(),
            fencing_token_digest: Sha256Digest::for_bytes(b"synthetic-token"),
            expires_at_unix_seconds: 30,
        },
        peer_lifetime: consumer.clone(),
        phase: CognitiveCheckpointPhase::Current,
        last_current: CognitiveRecoveryAnchor {
            profile: "synthetic-cognitive-scope".into(),
            owner_agent_id: identity.agent_id.clone(),
            schema_digest: Sha256Digest::for_bytes(b"synthetic-schema"),
            state_digest: Sha256Digest::for_bytes(b"synthetic-state"),
        },
        proposal: None,
        last_request: None,
    };
    let lanes = directory.path().join("synthetic-lanes");
    let original = HostAuthorityPublicBootstrapV1 {
        schema_version: 1,
        operation: crate::HOST_AUTHORITY_BOOTSTRAP_V1.into(),
        root: root.clone(),
        consumer: consumer.clone(),
        registered_identity: registered.clone(),
        issuer_key: HostAuthorityPublicIssuerKeyV1 {
            key_id: trust.issuer_id,
            verifying_key: trust.verifying_key,
            not_before_authority_epoch: 2,
            not_after_authority_epoch: 2,
        },
        revocations,
        writer,
        writer_proof: proof,
        checkpoint: head,
        consumers: HostAuthorityPublicConsumersV1 {
            device: HostAuthorityPublicConsumerV1 {
                local_state_dir: directory.path().join("device"),
                owner_id: "fixture-device".into(),
                frontier,
            },
            notes: HostAuthorityPublicConsumerV1 {
                local_state_dir: directory.path().join("notes"),
                owner_id: "fixture-notes".into(),
                frontier,
            },
        },
        sockets: HostAuthorityFiveLanePathsV1 {
            observation: lanes.join("observation.sock"),
            issuer: lanes.join("issuer.sock"),
            checkpoint: lanes.join("checkpoint.sock"),
            device_frontier: lanes.join("device.sock"),
            notes_frontier: lanes.join("notes.sock"),
        },
    };
    let learning = HostAuthorityLearningBootstrapV1 {
        schema_version: 1,
        operation: crate::HOST_AUTHORITY_LEARNING_BOOTSTRAP_V1.into(),
        root,
        consumer,
        registered_identity: registered,
        writer_proof_digest: digest.as_str().to_owned(),
        initial_snapshot: profile.encoded_initial().to_owned(),
        update_scope: None,
        socket_path: lanes.join("learning-checkpoint-v1.sock"),
    };
    Ok((directory, identity, original, learning))
}

#[test]
fn learning_bundle_requires_same_original_writer_peer_identity_and_fixed_lane() -> anyhow::Result<()>
{
    let (_directory, identity, original, learning) = bundles()?;
    let root_pid = original.root.pid;
    assert_eq!(
        validate_binding(&learning, &original, &identity, root_pid)?,
        learning.decode_initial()?
    );
    for case in 0..13 {
        let mut changed = learning.clone();
        match case {
            0 => changed.root.pid += 1,
            1 => changed.root.uid = 60001,
            2 => changed.root.boot_id = "another-boot".into(),
            3 => changed.root.process_start_ticks += 1,
            4 => changed.consumer.uid += 1,
            5 => changed.consumer.pid += 1,
            6 => changed.consumer.boot_id = "another-boot".into(),
            7 => changed.consumer.process_start_ticks += 1,
            8 => changed.registered_identity.spawn_generation += 1,
            9 => changed.writer_proof_digest = Digest32::from_array([9; 32]).to_string(),
            10 => changed.socket_path = changed.socket_path.with_file_name("another-learning.sock"),
            11 => changed.operation = crate::HOST_AUTHORITY_BOOTSTRAP_V1.into(),
            12 => changed.schema_version = 2,
            _ => unreachable!(),
        }
        assert!(
            validate_binding(&changed, &original, &identity, root_pid).is_err(),
            "case {case}"
        );
    }
    assert!(validate_binding(&learning, &original, &identity, root_pid + 1).is_err());
    let mut changed = original;
    changed.registered_identity.spawn_generation += 1;
    assert!(validate_binding(&learning, &changed, &identity, root_pid).is_err());
    Ok(())
}

#[test]
fn learning_bundle_refuses_other_agent_initial_operation_and_profile_bytes() -> anyhow::Result<()> {
    let (_directory, identity, original, mut learning) = bundles()?;
    let initial = learning.decode_initial()?;
    let mut foreign = identity.clone();
    foreign.agent_id =
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13").map_err(anyhow::Error::msg)?;
    let mut request = initial.request;
    request.agent_id = StableId::new(foreign.agent_id.as_str())?;
    let pin: Digest32 = learning.writer_proof_digest.parse()?;
    let profile =
        HostAuthorityLearningProfileV1::new(&foreign, pin.into_array(), request, initial.owners)?;
    learning.initial_snapshot = profile.encoded_initial().to_owned();
    assert!(validate_binding(&learning, &original, &identity, original.root.pid).is_err());
    learning.initial_snapshot = "invalid-profile-bytes".into();
    assert!(validate_binding(&learning, &original, &identity, original.root.pid).is_err());
    Ok(())
}

#[test]
fn scoped_learning_handoff_requires_its_complete_original_profile() -> anyhow::Result<()> {
    let (_directory, identity, original, mut learning) = bundles()?;
    let initial = learning.decode_initial()?;
    let pin: Digest32 = learning.writer_proof_digest.parse()?;
    let profile = HostAuthorityLearningProfileV1::new_scoped_v2(
        &identity,
        pin.into_array(),
        initial.request.clone(),
        initial.owners.clone(),
        codex_hepta_learning_artifacts::LearningUpdateScopeV2::Cell,
        Digest32::of_bytes(b"rule"),
    )?;
    learning.schema_version = 2;
    learning.operation = crate::HOST_AUTHORITY_LEARNING_BOOTSTRAP_V2.into();
    learning.update_scope = profile.update_scope.clone();
    assert_eq!(
        validate_binding(&learning, &original, &identity, original.root.pid)?,
        initial
    );
    assert_eq!(
        learning.frozen_scope(&initial)?,
        profile.frozen_scope(&initial)?
    );
    for mutation in 0..5 {
        let mut changed = serde_json::to_value(&learning)?;
        match mutation {
            0 => changed["schema_version"] = serde_json::json!(1),
            1 => {
                changed["operation"] =
                    serde_json::json!(crate::HOST_AUTHORITY_LEARNING_BOOTSTRAP_V1)
            }
            2 => changed["update_scope"] = serde_json::Value::Null,
            3 => changed["update_scope"]["scope"] = serde_json::json!("organ"),
            4 => {
                changed["update_scope"]["update_rule"] =
                    serde_json::json!(Digest32::of_bytes(b"other-rule").to_string())
            }
            _ => unreachable!(),
        }
        let changed = serde_json::from_value(changed)?;
        assert!(
            validate_binding(&changed, &original, &identity, original.root.pid).is_err(),
            "mutation {mutation}"
        );
    }
    Ok(())
}
