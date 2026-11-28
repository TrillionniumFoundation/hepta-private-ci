//! Pure binding checks reuse the existing synthetic public-bootstrap fixture.
//! No Root capability, original human turn, material read or training is claimed.
use super::*;
use crate::HostAuthorityPairedTrainingProfileV1;
use crate::PairedTrainingMaterialManifestV1;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;

fn bundles() -> anyhow::Result<(
    tempfile::TempDir,
    AgentdIdentity,
    crate::HostAuthorityPublicBootstrapV1,
    HostAuthorityPairedTrainingBootstrapV1,
)> {
    let (directory, identity, original, _learning) =
        crate::root_production_learning_inputs::tests::bundles()?;
    let manifest = PairedTrainingMaterialManifestV1 {
        failure_sha256: Digest32::of_bytes(b"synthetic failure"),
        failure_bytes: 17,
        correction_sha256: Digest32::of_bytes(b"synthetic correction"),
        correction_bytes: 20,
    };
    let profile = HostAuthorityPairedTrainingProfileV1 {
        schema_version: 1,
        identity_digest: crate::neuron_generation_process_identity_digest_v1(&identity)?
            .to_string(),
        writer_proof_digest: original.writer_proof.sha256()?.as_str().to_owned(),
        study: Digest32::of_bytes(b"synthetic study").to_string(),
        enrollment: Digest32::of_bytes(b"synthetic enrollment").to_string(),
        frozen_materials: manifest.commitment()?.to_string(),
        principal_id: "synthetic-principal".into(),
        policy_generation: 1,
        operation: Digest32::of_bytes(b"synthetic operation").to_string(),
        failure_sha256: manifest.failure_sha256.to_string(),
        failure_bytes: manifest.failure_bytes,
        correction_sha256: manifest.correction_sha256.to_string(),
        correction_bytes: manifest.correction_bytes,
        enrollment_revision: 1,
        effect_lifetime_ms: 1_000,
    };
    let paired = HostAuthorityPairedTrainingBootstrapV1 {
        schema_version: 1,
        operation: HOST_AUTHORITY_PAIRED_TRAINING_BOOTSTRAP_V1.into(),
        root: original.root.clone(),
        consumer: original.consumer.clone(),
        registered_identity: original.registered_identity.clone(),
        writer_proof_digest: original.writer_proof.sha256()?.as_str().to_owned(),
        socket_path: original
            .sockets
            .observation
            .parent()
            .unwrap()
            .join("paired-training-v1.sock"),
        profile,
    };
    Ok((directory, identity, original, paired))
}

#[test]
fn paired_bundle_binds_original_root_consumer_identity_proof_and_fixed_lane() -> anyhow::Result<()>
{
    let (_directory, identity, original, paired) = bundles()?;
    let root_pid = original.root.pid;
    assert_eq!(
        validate_binding(&paired, &original, &identity, root_pid)?,
        paired.profile.decode_plan()?.training,
    );
    for case in 0..13 {
        let mut changed = paired.clone();
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
            9 => changed.writer_proof_digest = Digest32::of_bytes(b"other writer").to_string(),
            10 => changed.socket_path = changed.socket_path.with_file_name("other.sock"),
            11 => changed.operation = crate::HOST_AUTHORITY_BOOTSTRAP_V1.into(),
            12 => changed.schema_version = 2,
            _ => unreachable!(),
        }
        assert!(
            validate_binding(&changed, &original, &identity, root_pid).is_err(),
            "case {case}"
        );
    }
    assert!(validate_binding(&paired, &original, &identity, root_pid + 1).is_err());
    Ok(())
}

#[test]
fn paired_bundle_rejects_foreign_profile_writer_and_invalid_material_pins() -> anyhow::Result<()> {
    let (_directory, identity, original, paired) = bundles()?;
    for case in 0..6 {
        let mut changed = paired.clone();
        match case {
            0 => {
                changed.profile.identity_digest = Digest32::of_bytes(b"other identity").to_string()
            }
            1 => {
                changed.profile.writer_proof_digest =
                    Digest32::of_bytes(b"other writer").to_string()
            }
            2 => changed.profile.failure_sha256 = Digest32::of_bytes(b"other failure").to_string(),
            3 => changed.profile.operation = Digest32::ZERO.to_string(),
            4 => changed.profile.enrollment_revision = 0,
            5 => changed.profile.policy_generation = 0,
            _ => unreachable!(),
        }
        assert!(
            validate_binding(&changed, &original, &identity, original.root.pid).is_err(),
            "case {case}"
        );
    }
    let mut other_original = original;
    other_original.registered_identity.spawn_generation += 1;
    assert!(validate_binding(&paired, &other_original, &identity, paired.root.pid).is_err());
    Ok(())
}
