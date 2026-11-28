//! Synthetic metadata controls; no original Root, consent or training is claimed.

use super::*;
use crate::learning_iteration_checkpoint::learning_test_support::fixture;
use pretty_assertions::assert_eq;

fn profile(identity: &AgentdIdentity) -> anyhow::Result<HostAuthorityPairedTrainingProfileV1> {
    let manifest = PairedTrainingMaterialManifestV1 {
        failure_sha256: Digest32::of_bytes(b"{\"v\":1}\n"),
        failure_bytes: 8,
        correction_sha256: Digest32::of_bytes(b"{\"v\":2}\n"),
        correction_bytes: 8,
    };
    Ok(HostAuthorityPairedTrainingProfileV1 {
        schema_version: 1,
        identity_digest: crate::neuron_generation_process_identity_digest_v1(identity)?.to_string(),
        writer_proof_digest: Digest32::of_bytes(b"synthetic original writer proof").to_string(),
        study: Digest32::of_bytes(b"synthetic study").to_string(),
        enrollment: Digest32::of_bytes(b"synthetic enrollment").to_string(),
        frozen_materials: manifest.commitment()?.to_string(),
        principal_id: "synthetic-human".into(),
        policy_generation: 1,
        operation: Digest32::of_bytes(b"synthetic fixed operation").to_string(),
        failure_sha256: manifest.failure_sha256.to_string(),
        failure_bytes: manifest.failure_bytes,
        correction_sha256: manifest.correction_sha256.to_string(),
        correction_bytes: manifest.correction_bytes,
        enrollment_revision: 1,
        effect_lifetime_ms: 500,
    })
}

#[test]
fn paired_profile_roundtrip_keeps_raw_commitment_and_original_writer_binding() -> anyhow::Result<()>
{
    let (_directory, identity, _coordinator) = fixture()?;
    let profile = profile(&identity)?;
    let original = profile.require_binding(&identity, &profile.writer_proof_digest)?;
    let restored: HostAuthorityPairedTrainingProfileV1 =
        serde_json::from_slice(&serde_json::to_vec(&profile)?)?;
    assert_eq!(
        restored.require_binding(&identity, &profile.writer_proof_digest)?,
        original
    );
    let mut changed_identity = identity.clone();
    changed_identity.spawn_generation += 1;
    assert!(
        restored
            .require_binding(&changed_identity, &profile.writer_proof_digest)
            .is_err()
    );
    assert!(
        restored
            .require_binding(&identity, &Digest32::of_bytes(b"other writer").to_string())
            .is_err()
    );
    // The canonical record commitment excludes this original file's newline.
    // Replacing one digest with the other must not preserve the frozen plan.
    let mut changed = restored;
    changed.failure_sha256 = Digest32::of_bytes(b"{\"v\":1}").to_string();
    assert!(changed.decode_plan().is_err());
    Ok(())
}

#[test]
fn paired_profile_refuses_fabricated_turn_and_noncanonical_or_mixed_metadata() -> anyhow::Result<()>
{
    let (_directory, identity, _coordinator) = fixture()?;
    let profile = profile(&identity)?;
    let mut raw = serde_json::to_value(&profile)?;
    raw["turn_id"] = serde_json::Value::String("fabricated-startup-turn".into());
    assert!(serde_json::from_value::<HostAuthorityPairedTrainingProfileV1>(raw).is_err());
    let mut raw = serde_json::to_value(&profile)?;
    raw["policy_generation"] = serde_json::Value::Bool(true);
    assert!(serde_json::from_value::<HostAuthorityPairedTrainingProfileV1>(raw).is_err());
    for case in 0..6 {
        let mut changed = profile.clone();
        match case {
            0 => changed.failure_sha256 = changed.failure_sha256.to_uppercase(),
            1 => changed.schema_version = 2,
            2 => changed.failure_bytes += 1,
            3 => changed.enrollment_revision = 0,
            4 => changed.policy_generation = 0,
            5 => changed.operation = Digest32::from_array([0; 32]).to_string(),
            _ => unreachable!(),
        }
        assert!(changed.decode_plan().is_err(), "case {case}");
    }
    Ok(())
}
